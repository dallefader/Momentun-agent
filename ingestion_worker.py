"""
ingestion_worker.py - FASE 2: baggrunds-daemon der holder databasen frisk.

Ansvar:
* Inkrementel hentning: fuld backfill EN gang pr. ticker, derefter kun de
  seneste bars (period='5d'), flettet ind i prices-tabellen.
* Rolling chunks med rate-limit-venlig rytme (delay + jitter, Stooq-failover).
* Tiered frekvens: Tier A (positioner+watchlist+aktive BUY) opdateres hyppigt,
  Tier B (resten) sjaeldnere, Tier C (kronisk fejlende) sjaeldnest.
* Efter hver cyklus: beregn signaler via scanner_core.compute_scan og skriv
  snapshot via scanner_db - PRAECIS samme algoritme som UI'et.

Koeres som launchd-daemon paa Mac mini'en (se com.db.scanner.worker.plist).
Fetcheren er injicerbar, saa logikken kan testes uden netvaerk.

  python ingestion_worker.py --seed        # seed universe-tabel fra core.UNIVERSE
  python ingestion_worker.py --backfill     # tving fuld hentning af alt, eet gennemloeb
  python ingestion_worker.py --once         # eet normalt gennemloeb og afslut
  python ingestion_worker.py                # uendelig daemon-loop
"""
from __future__ import annotations

import os
import sys
import json
import time
import random
import logging
import argparse
from datetime import datetime, timedelta

import pandas as pd

import scanner_core as core
import scanner_db as sdb

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(HERE, "worker_config.json")
LOG_FILE = os.path.join(HERE, "worker.log")

DEFAULTS = {
    "cadence_seconds": {"A": 600, "B": 1800, "C": 86400},
    "loop_sleep_seconds": 90,
    "chunk_size": 50,
    "chunk_delay_seconds": 1.5,
    "chunk_jitter_seconds": 1.0,
    "backfill_period": "1y",
    "incremental_period": "5d",
    "catchup_period": "1mo",
    "stale_days_for_catchup": 5,
    "max_fail_before_tier_c": 5,
    "use_stooq_failover": True,
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout),
              logging.FileHandler(LOG_FILE, encoding="utf-8")],
)
LOG = logging.getLogger("worker")


def load_config():
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_FILE):
        try:
            cfg.update(json.load(open(CONFIG_FILE, encoding="utf-8")))
        except Exception as e:
            LOG.warning(f"Kunne ikke laese {CONFIG_FILE}: {e}")
    return cfg


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


# ---------------------------------------------------------------------------
# Standard-fetcher (yfinance + Stooq). Injicerbar for tests.
# ---------------------------------------------------------------------------
def _normalize_yf_df(df):
    if df is None or df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        for level in range(df.columns.nlevels):
            vals = df.columns.get_level_values(level)
            if "Close" in vals or "close" in vals:
                df = df.copy(); df.columns = vals
                break
        else:
            df = df.copy(); df.columns = df.columns.get_level_values(0)
    if "Close" not in df.columns and "close" in df.columns:
        df = df.rename(columns={"close": "Close", "open": "Open", "high": "High",
                                "low": "Low", "volume": "Volume"})
    return df


def make_yf_fetch_chunk(yf_module, retries=3, backoff=2.0):
    def fetch_chunk(chunk, period):
        out = {}
        for attempt in range(retries):
            try:
                raw = yf_module.download(chunk, period=period, interval="1d",
                                         group_by="ticker", auto_adjust=True,
                                         progress=False, threads=True)
                for t in chunk:
                    try:
                        df = raw[t] if len(chunk) > 1 else raw
                        df = _normalize_yf_df(df)
                        if df is None or "Close" not in df.columns:
                            continue
                        df = df.dropna()
                        if len(df) >= 1:
                            out[t] = df[["Open", "High", "Low", "Close", "Volume"]]
                    except Exception:
                        pass
                if out:
                    return out
            except Exception as e:
                LOG.warning(f"yf retry {attempt+1}/{retries}: {e}")
            time.sleep(backoff ** attempt)
        return out
    return fetch_chunk


def make_stooq_single():
    try:
        import pandas_datareader.data as pdr
    except Exception:
        return None
    suffix_map = {"": ".US", ".L": ".UK", ".DE": ".DE", ".PA": ".FR", ".AS": ".NL",
                  ".SW": ".CH", ".MC": ".ES", ".MI": ".IT", ".HE": ".FI"}

    def stooq_single(ticker):
        base, suffix = ticker, ""
        if "." in ticker:
            parts = ticker.rsplit(".", 1)
            base, suffix = parts[0], "." + parts[1]
        sx = suffix_map.get(suffix)
        if sx is None:
            return None
        sticker = (base + sx).lower()
        try:
            end = datetime.now(); start = end - timedelta(days=400)
            df = pdr.DataReader(sticker, "stooq", start, end).sort_index()
            df = _normalize_yf_df(df)
            if df is not None and "Close" in df.columns and len(df) >= 1:
                return df[["Open", "High", "Low", "Close", "Volume"]]
        except Exception:
            pass
        return None
    return stooq_single


# ---------------------------------------------------------------------------
# Tiering
# ---------------------------------------------------------------------------
def _load_list(fname):
    p = os.path.join(HERE, fname)
    if not os.path.exists(p):
        return []
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return []


def assign_tiers(universe, cfg, db_path=None):
    """Tier A = positioner + watchlist + aktive BUY-kandidater. Tier C =
    kronisk fejlende. Resten = Tier B."""
    positions = _load_list("positions.json")
    watchlist = _load_list("watchlist.json")
    pos_tickers = {p.get("ticker") if isinstance(p, dict) else p for p in positions}
    wl_tickers = set(watchlist)

    scan = sdb.read_scan_results(db_path)
    buy_tickers = set()
    if not scan.empty and "buy" in scan.columns:
        buy_tickers = set(scan.loc[scan["buy"].isin(
            ["BUY NOW", "BUY BREAKOUT", "STARTER BUY", "BUILD POSITION"]), "ticker"])

    tier_a = pos_tickers | wl_tickers | buy_tickers
    states = sdb.get_ticker_states(db_path)
    maxfail = cfg["max_fail_before_tier_c"]
    for u in universe:
        t = u[0]
        fc = states.get(t, {}).get("fail_count", 0) or 0
        if t in tier_a:
            tier = "A"
        elif fc >= maxfail:
            tier = "C"
        else:
            tier = "B"
        sdb.set_tier(t, tier, db_path)
    return {"A": sum(1 for u in universe if u[0] in tier_a)}


def select_due(universe, cfg, now=None, db_path=None):
    """Returnerer de tickere hvis sidste succes er aeldre end deres tier-kadence
    (eller som aldrig er hentet)."""
    now = now or datetime.now()
    cadence = cfg["cadence_seconds"]
    states = sdb.get_ticker_states(db_path)
    due = []
    for u in universe:
        t = u[0]
        st = states.get(t, {})
        tier = st.get("tier") or "B"
        last = st.get("last_success")
        if not last:
            due.append(t); continue
        try:
            age = (now - datetime.fromisoformat(last)).total_seconds()
        except Exception:
            due.append(t); continue
        if age >= cadence.get(tier, cadence["B"]):
            due.append(t)
    return due


def decide_period(ticker, cfg, now=None, db_path=None):
    """backfill hvis ingen historik; catchup hvis stale; ellers inkrementel."""
    now = now or datetime.now()
    last = sdb.get_last_price_date(ticker, db_path)
    if not last:
        return cfg["backfill_period"]
    try:
        age_days = (now - datetime.fromisoformat(last)).days
    except Exception:
        age_days = 999
    if age_days >= cfg["stale_days_for_catchup"]:
        return cfg["catchup_period"]
    return cfg["incremental_period"]


# ---------------------------------------------------------------------------
# Hentning + lagring
# ---------------------------------------------------------------------------
def fetch_and_store(tickers, cfg, fetch_chunk, stooq_single=None,
                    now=None, db_path=None):
    now = now or datetime.now()
    # Grupper efter noedvendig periode, saa en batch deler periode
    by_period = {}
    for t in tickers:
        per = decide_period(t, cfg, now, db_path)
        by_period.setdefault(per, []).append(t)

    stats = {"ok": 0, "stooq": 0, "failed": 0, "bars": 0}
    for period, group in by_period.items():
        for chunk in _chunks(group, cfg["chunk_size"]):
            got = fetch_chunk(chunk, period) or {}
            for t in chunk:
                df = got.get(t)
                src = "yfinance"
                if (df is None or getattr(df, "empty", True)) and stooq_single and cfg["use_stooq_failover"]:
                    df = stooq_single(t); src = "stooq"
                if df is not None and not df.empty:
                    n = sdb.upsert_prices(t, df, db_path)
                    total = len(sdb.read_prices(t, db_path))
                    sdb.record_fetch(t, True, source=src, n_bars=total, path=db_path)
                    stats["ok"] += 1; stats["bars"] += n
                    if src == "stooq":
                        stats["stooq"] += 1
                else:
                    sdb.record_fetch(t, False, path=db_path)
                    stats["failed"] += 1
            time.sleep(cfg["chunk_delay_seconds"] + random.uniform(0, cfg["chunk_jitter_seconds"]))
    return stats


def compute_and_store_snapshot(universe, yf_module=None, db_path=None):
    """Beregn signaler over al lagret historik og skriv snapshot. Replikerer
    UI'ets to-pas regime: regime1 (kun marked) -> compute_scan -> regime_final."""
    uni_tickers = [u[0] for u in universe]
    all_raw = sdb.build_all_raw(tickers=uni_tickers, min_bars=1, path=db_path)
    fx = core.fetch_fx_rates_live(yf_module)
    mkt = core.fetch_market_data_live(yf_module)
    regime1 = core.derive_regime(mkt, pd.DataFrame())
    df, dropped = core.compute_scan(all_raw, universe, fx, regime1)
    regime_final = core.derive_regime(mkt, df)
    n = sdb.write_scan_results(df, regime_final, source="worker", path=db_path)
    sdb.write_diagnostics({
        "ts": datetime.now().isoformat(),
        "universe": len(universe),
        "with_history": len(all_raw),
        "in_snapshot": n,
        "dropped": len(dropped),
        "dropped_sample": [{"ticker": t, "reason": r} for t, r in dropped[:40]],
        "regime": regime_final,
    }, path=db_path)
    return {"snapshot_rows": n, "with_history": len(all_raw),
            "dropped": len(dropped), "regime": regime_final}


def ensure_universe(db_path=None):
    """Returnerer universet fra DB; seeder fra core.UNIVERSE hvis tomt."""
    uni = sdb.read_universe(path=db_path)
    if not uni:
        sdb.seed_universe(core.UNIVERSE, path=db_path)
        uni = sdb.read_universe(path=db_path)
    return uni


def run_cycle(cfg, fetch_chunk, stooq_single=None, yf_module=None,
              force_all=False, now=None, db_path=None):
    now = now or datetime.now()
    universe = ensure_universe(db_path)
    assign_tiers(universe, cfg, db_path)
    if force_all:
        due = [u[0] for u in universe]
    else:
        due = select_due(universe, cfg, now, db_path)
    LOG.info(f"Cyklus: {len(due)}/{len(universe)} tickere due for hentning")
    fetch_stats = {"ok": 0, "stooq": 0, "failed": 0, "bars": 0}
    if due:
        fetch_stats = fetch_and_store(due, cfg, fetch_chunk, stooq_single, now, db_path)
    snap = compute_and_store_snapshot(universe, yf_module, db_path)
    LOG.info(f"Hentning: {fetch_stats} | Snapshot: {snap}")
    return {"due": len(due), "fetch": fetch_stats, "snapshot": snap}


def main_loop(cfg, fetch_chunk, stooq_single, yf_module):
    LOG.info("Worker startet - daemon-loop")
    while True:
        try:
            run_cycle(cfg, fetch_chunk, stooq_single, yf_module)
        except Exception as e:
            LOG.exception(f"Cyklus fejlede: {e}")
        time.sleep(cfg["loop_sleep_seconds"])


def get_yf():
    try:
        import yfinance as yf
        return yf
    except Exception:
        LOG.error("yfinance ikke installeret - kan ikke hente data")
        return None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", action="store_true", help="Seed universe-tabel og afslut")
    ap.add_argument("--once", action="store_true", help="Eet gennemloeb og afslut")
    ap.add_argument("--backfill", action="store_true", help="Tving fuld hentning, eet gennemloeb")
    args = ap.parse_args(argv)

    cfg = load_config()
    sdb.init_db()

    if args.seed:
        n = sdb.seed_universe(core.UNIVERSE)
        LOG.info(f"Universe seeded: {n} tickere")
        return

    yf = get_yf()
    fetch_chunk = make_yf_fetch_chunk(yf) if yf else (lambda c, p: {})
    stooq_single = make_stooq_single() if cfg["use_stooq_failover"] else None

    if args.once or args.backfill:
        run_cycle(cfg, fetch_chunk, stooq_single, yf, force_all=args.backfill)
        return

    main_loop(cfg, fetch_chunk, stooq_single, yf)


if __name__ == "__main__":
    main()
