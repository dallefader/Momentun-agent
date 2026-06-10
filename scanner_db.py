"""
scanner_db.py - Lager-lag (SQLite) for trading-scanneren.

FASE 1: afkobler BEREGNING fra VISNING (scan_results + scan_meta).
FASE 2: tilfojer prices (OHLCV-historik), universe og ticker_state, sa
        baggrunds-workeren kan hente inkrementelt og styre tiering.

Designprincipper:
* Ingen Streamlit-afhaengighed. Importeres bade af UI'et og workeren.
* Kolonne-agnostisk snapshot: hver ticker gemmes som en raekke med hele sin
  data-dict som JSON, sa algoritmen kan aendre felter uden skema-migrering.
* WAL-mode: samtidig laeser (UI) + skriver (worker) uden at blokere.
"""

from __future__ import annotations

import os
import json
import math
import sqlite3
from datetime import datetime

import pandas as pd

_DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scanner.db")
SCHEMA_VERSION = 2


def db_path(path=None):
    return path or _DEFAULT_DB


# ---------------------------------------------------------------------------
# JSON-hjaelpere - numpy-skalarer, NaN/NA mm.
# ---------------------------------------------------------------------------
def _json_default(o):
    if hasattr(o, "item"):
        try:
            return o.item()
        except Exception:
            pass
    if isinstance(o, (datetime,)):
        return o.isoformat()
    return str(o)


def _clean_value(v):
    if v is None:
        return None
    try:
        if isinstance(v, float) and math.isnan(v):
            return None
    except Exception:
        pass
    try:
        if v is pd.NA or (not isinstance(v, (list, dict, str)) and pd.isna(v)):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(v, "item"):
        try:
            return v.item()
        except Exception:
            return v
    return v


# ---------------------------------------------------------------------------
# Skema
# ---------------------------------------------------------------------------
def _connect(path=None):
    conn = sqlite3.connect(db_path(path), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def init_db(path=None):
    conn = _connect(path)
    try:
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);")
        cur.execute("SELECT version FROM schema_version LIMIT 1;")
        if cur.fetchone() is None:
            cur.execute("INSERT INTO schema_version(version) VALUES (?);", (SCHEMA_VERSION,))

        cur.execute(
            "CREATE TABLE IF NOT EXISTS scan_results ("
            "ticker TEXT PRIMARY KEY, score REAL, buy TEXT, sell TEXT, "
            "stn INTEGER, rs_rank INTEGER, sector TEXT, region TEXT, "
            "data TEXT NOT NULL, updated TEXT NOT NULL);")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_scan_score ON scan_results(score DESC);")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_scan_buy ON scan_results(buy);")

        cur.execute(
            "CREATE TABLE IF NOT EXISTS scan_meta ("
            "id INTEGER PRIMARY KEY CHECK (id = 1), ts TEXT, regime TEXT, "
            "n_rows INTEGER, source TEXT, columns TEXT);")

        cur.execute(
            "CREATE TABLE IF NOT EXISTS universe ("
            "ticker TEXT PRIMARY KEY, name TEXT, sector TEXT, region TEXT, "
            "currency TEXT, tier TEXT, active INTEGER DEFAULT 1, last_seen TEXT);")

        cur.execute(
            "CREATE TABLE IF NOT EXISTS prices ("
            "ticker TEXT NOT NULL, date TEXT NOT NULL, open REAL, high REAL, "
            "low REAL, close REAL, volume REAL, PRIMARY KEY (ticker, date));")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_prices_ticker ON prices(ticker);")

        cur.execute(
            "CREATE TABLE IF NOT EXISTS ticker_state ("
            "ticker TEXT PRIMARY KEY, tier TEXT DEFAULT 'B', last_success TEXT, "
            "last_attempt TEXT, fail_count INTEGER DEFAULT 0, last_source TEXT, "
            "n_bars INTEGER DEFAULT 0);")
        cur.execute(
            "CREATE TABLE IF NOT EXISTS diagnostics ("
            "id INTEGER PRIMARY KEY CHECK (id=1), ts TEXT, payload TEXT);")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS signal_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                date        TEXT NOT NULL,
                ticker      TEXT NOT NULL,
                name        TEXT,
                signal      TEXT,
                setup       TEXT,
                score       REAL,
                ts_score    REAL,
                ss_score    REAL,
                rp_score    REAL,
                price       REAL,
                sma20       REAL,
                sma60       REAL,
                sma200      REAL,
                dist_sma200 REAL,
                dist_sma20  REAL,
                rsi         REAL,
                rsi_t       TEXT,
                atr20       REAL,
                atr_pct     REAL,
                volr        REAL,
                rvol50      REAL,
                rs_rank     REAL,
                rs_t        TEXT,
                squeeze     INTEGER,
                higher_low  INTEGER,
                ifs         REAL,
                dist_h20    REAL,
                sector      TEXT,
                region      TEXT,
                regime      TEXT,
                stage       TEXT,
                stn         INTEGER,
                stop        REAL,
                dolvol_usd_m REAL,
                forward_5d  REAL,
                forward_20d REAL,
                forward_60d REAL,
                forward_120d REAL,
                UNIQUE(date, ticker)
            );""")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_siglog_date   ON signal_log(date);")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_siglog_ticker ON signal_log(ticker);")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_siglog_signal ON signal_log(signal);")
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Signal log — backtest data collection
# ---------------------------------------------------------------------------
def log_signals(df, regime="NEUTRAL", path=None):
    """Log alle BUY-signaler fra et scan med fulde features til signal_log.
    Kør én gang per fuld scan. UNIQUE(date, ticker) forhindrer dubletter."""
    if df is None or df.empty:
        return 0
    init_db(path)
    log_signals_set = {'BUY NOW', 'BUY BREAKOUT', 'BUILD POSITION', 'STARTER BUY',
                       'EXTENDED — WAIT', 'EXIT'}
    today = datetime.now().strftime('%Y-%m-%d')
    conn = _connect(path)
    inserted = 0
    try:
        cur = conn.cursor()
        mask = df['buy'].isin(log_signals_set) | df['sell'].isin(log_signals_set)
        for _, r in df[mask].iterrows():
            signal = r.get('buy') if r.get('buy') in log_signals_set else r.get('sell')
            p  = _clean_value(r.get('price'))
            s2 = _clean_value(r.get('sma200'))
            s20= _clean_value(r.get('sma20'))
            dist_sma200 = round((s2 - p) / s2 * 100, 2) if s2 and p and s2 > 0 else None
            dist_sma20  = round((p - s20) / s20 * 100, 2) if s20 and p and s20 > 0 else None
            try:
                cur.execute("""
                    INSERT OR IGNORE INTO signal_log
                    (date, ticker, name, signal, setup, score, ts_score, ss_score, rp_score,
                     price, sma20, sma60, sma200, dist_sma200, dist_sma20,
                     rsi, rsi_t, atr20, atr_pct, volr, rvol50,
                     rs_rank, rs_t, squeeze, higher_low, ifs, dist_h20,
                     sector, region, regime, stage, stn, stop, dolvol_usd_m)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    today,
                    r.get('ticker'), r.get('name'),
                    signal, _clean_value(r.get('setup')),
                    _clean_value(r.get('score')),
                    _clean_value(r.get('ts')), _clean_value(r.get('ss')), _clean_value(r.get('rp')),
                    p,
                    s20, _clean_value(r.get('sma60')), s2,
                    dist_sma200, dist_sma20,
                    _clean_value(r.get('rsi')), _clean_value(r.get('rsi_t')),
                    _clean_value(r.get('atr20')), _clean_value(r.get('atr_pct')),
                    _clean_value(r.get('volr')), _clean_value(r.get('rvol50')),
                    _clean_value(r.get('rs_rank')), _clean_value(r.get('rs_t')),
                    int(bool(_clean_value(r.get('sqz')))),
                    int(bool(_clean_value(r.get('hl')))),
                    _clean_value(r.get('ifs')), _clean_value(r.get('dh20')),
                    r.get('sector'), r.get('region'), regime,
                    _clean_value(r.get('stage')), _clean_value(r.get('stn')),
                    _clean_value(r.get('stop')), _clean_value(r.get('dolvol_usd_m')),
                ))
                inserted += cur.rowcount
            except Exception:
                pass
        conn.commit()
    finally:
        conn.close()
    return inserted


def update_forward_returns(current_prices: dict, path=None):
    """Opdater forward returns for historiske signaler baseret på aktuelle priser.
    current_prices = {ticker: price}. Kør efter hvert scan."""
    if not current_prices:
        return 0
    conn = _connect(path)
    updated = 0
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, date, ticker, price
            FROM signal_log
            WHERE price > 0
              AND (forward_5d IS NULL OR forward_20d IS NULL
                   OR forward_60d IS NULL OR forward_120d IS NULL)
        """)
        rows = cur.fetchall()
        today = datetime.now().date()
        for row_id, date_str, ticker, entry_price in rows:
            cp = current_prices.get(ticker)
            if not cp or not entry_price:
                continue
            try:
                signal_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except Exception:
                continue
            days = (today - signal_date).days
            ret = round((cp / entry_price - 1) * 100, 2)
            updates = {}
            if days >= 5:   updates['forward_5d']   = ret
            if days >= 20:  updates['forward_20d']  = ret
            if days >= 60:  updates['forward_60d']  = ret
            if days >= 120: updates['forward_120d'] = ret
            if updates:
                set_clause = ', '.join(f"{k} = ?" for k in updates)
                cur.execute(
                    f"UPDATE signal_log SET {set_clause} WHERE id = ?",
                    (*updates.values(), row_id)
                )
                updated += cur.rowcount
        conn.commit()
    finally:
        conn.close()
    return updated


def get_signal_log(path=None) -> pd.DataFrame:
    """Hent hele signal_log som DataFrame."""
    conn = _connect(path)
    try:
        return pd.read_sql_query(
            "SELECT * FROM signal_log ORDER BY date DESC, score DESC", conn)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Snapshot - skrivning
# ---------------------------------------------------------------------------
def write_scan_results(df, regime="NEUTRAL", source="ui", path=None):
    """Erstatter HELE snapshottet atomisk. Tom df springes over."""
    if df is None or df.empty:
        return 0
    init_db(path)
    records = df.to_dict(orient="records")
    columns = list(df.columns)
    now = datetime.now().isoformat()
    rows = []
    for rec in records:
        clean = {k: _clean_value(v) for k, v in rec.items()}
        ticker = clean.get("ticker")
        if not ticker:
            continue
        rows.append((
            ticker, _clean_value(clean.get("score")), clean.get("buy"),
            clean.get("sell"), _clean_value(clean.get("stn")),
            _clean_value(clean.get("rs_rank")), clean.get("sector"),
            clean.get("region"), json.dumps(clean, default=_json_default), now))
    conn = _connect(path)
    try:
        cur = conn.cursor()
        cur.execute("BEGIN;")
        cur.execute("DELETE FROM scan_results;")
        cur.executemany(
            "INSERT INTO scan_results (ticker, score, buy, sell, stn, rs_rank, "
            "sector, region, data, updated) VALUES (?,?,?,?,?,?,?,?,?,?);", rows)
        cur.execute("DELETE FROM scan_meta;")
        cur.execute(
            "INSERT INTO scan_meta (id, ts, regime, n_rows, source, columns) "
            "VALUES (1, ?, ?, ?, ?, ?);",
            (now, regime, len(rows), source, json.dumps(columns)))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return len(rows)


# ---------------------------------------------------------------------------
# Snapshot - laesning
# ---------------------------------------------------------------------------
def read_scan_results(path=None):
    p = db_path(path)
    if not os.path.exists(p):
        return pd.DataFrame()
    init_db(path)
    conn = _connect(path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT columns FROM scan_meta WHERE id = 1;")
        meta_row = cur.fetchone()
        columns = json.loads(meta_row[0]) if meta_row and meta_row[0] else None
        cur.execute("SELECT data FROM scan_results;")
        data_rows = cur.fetchall()
    finally:
        conn.close()
    if not data_rows:
        return pd.DataFrame()
    records = [json.loads(r[0]) for r in data_rows]
    df = pd.DataFrame.from_records(records)
    if columns:
        ordered = [c for c in columns if c in df.columns]
        extra = [c for c in df.columns if c not in ordered]
        df = df[ordered + extra]
    if "score" in df.columns and not df.empty:
        df = df.sort_values("score", ascending=False).reset_index(drop=True)
    return df


def get_scan_meta(path=None):
    p = db_path(path)
    if not os.path.exists(p):
        return None
    init_db(path)
    conn = _connect(path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT ts, regime, n_rows, source FROM scan_meta WHERE id = 1;")
        row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return {"ts": row[0], "regime": row[1], "n_rows": row[2], "source": row[3]}


# ---------------------------------------------------------------------------
# FASE 2: PRIS-HISTORIK (OHLCV)
# ---------------------------------------------------------------------------
def upsert_prices(ticker, df, path=None):
    """Indsaetter/opdaterer OHLCV-bars. Idempotent (INSERT OR REPLACE)."""
    if df is None or df.empty:
        return 0
    init_db(path)
    d = df.copy()
    idx = pd.to_datetime(d["Date"]) if "Date" in d.columns else pd.to_datetime(d.index)
    rows = []
    for i, (_, r) in enumerate(d.iterrows()):
        date = pd.Timestamp(idx[i]).strftime("%Y-%m-%d")
        def g(col):
            v = _clean_value(r.get(col) if hasattr(r, "get") else None)
            return float(v) if v is not None else None
        rows.append((ticker, date, g("Open"), g("High"), g("Low"), g("Close"), g("Volume")))
    conn = _connect(path)
    try:
        conn.executemany(
            "INSERT OR REPLACE INTO prices (ticker, date, open, high, low, close, volume) "
            "VALUES (?,?,?,?,?,?,?);", rows)
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def get_last_price_date(ticker, path=None):
    p = db_path(path)
    if not os.path.exists(p):
        return None
    conn = _connect(path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT MAX(date) FROM prices WHERE ticker = ?;", (ticker,))
        row = cur.fetchone()
    finally:
        conn.close()
    return row[0] if row and row[0] else None


def read_prices(ticker, path=None):
    """Hele OHLCV-historikken som DataFrame med DatetimeIndex + OHLCV-kolonner."""
    p = db_path(path)
    if not os.path.exists(p):
        return pd.DataFrame()
    conn = _connect(path)
    try:
        df = pd.read_sql_query(
            "SELECT date, open, high, low, close, volume FROM prices "
            "WHERE ticker = ? ORDER BY date ASC;", conn, params=(ticker,))
    finally:
        conn.close()
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    df.columns = ["Open", "High", "Low", "Close", "Volume"]
    return df


def build_all_raw(tickers=None, min_bars=1, path=None):
    """{ticker: OHLCV-DataFrame} fra prices - formatet compute_scan forventer."""
    p = db_path(path)
    if not os.path.exists(p):
        return {}
    conn = _connect(path)
    try:
        if tickers is None:
            tickers = [r[0] for r in conn.execute("SELECT DISTINCT ticker FROM prices;").fetchall()]
    finally:
        conn.close()
    out = {}
    for t in tickers:
        df = read_prices(t, path)
        if not df.empty and len(df) >= min_bars:
            out[t] = df
    return out


# ---------------------------------------------------------------------------
# FASE 2: UNIVERSE-TABEL
# ---------------------------------------------------------------------------
def seed_universe(entries, path=None):
    """entries = liste af tuples (ticker,name,sector,region,tier)."""
    init_db(path)
    now = datetime.now().isoformat()
    rows = []
    for e in entries:
        ticker = e[0]
        name = e[1] if len(e) > 1 else ticker
        sector = e[2] if len(e) > 2 else "Unknown"
        region = e[3] if len(e) > 3 else "US"
        tier = e[4] if len(e) > 4 else "CORE"
        rows.append((ticker, name, sector, region, tier, now))
    conn = _connect(path)
    try:
        conn.executemany(
            "INSERT INTO universe (ticker, name, sector, region, tier, active, last_seen) "
            "VALUES (?,?,?,?,?,1,?) "
            "ON CONFLICT(ticker) DO UPDATE SET name=excluded.name, "
            "sector=excluded.sector, region=excluded.region, tier=excluded.tier;", rows)
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def read_universe(active_only=True, path=None):
    """Universet som liste af tuples (ticker,name,sector,region,tier)."""
    p = db_path(path)
    if not os.path.exists(p):
        return []
    conn = _connect(path)
    try:
        q = ("SELECT ticker,name,sector,region,tier FROM universe"
             + (" WHERE active=1" if active_only else "") + ";")
        rows = conn.execute(q).fetchall()
    finally:
        conn.close()
    return [tuple(r) for r in rows]


# ---------------------------------------------------------------------------
# FASE 2: TICKER-STATE
# ---------------------------------------------------------------------------
def record_fetch(ticker, ok, source=None, n_bars=None, path=None):
    init_db(path)
    now = datetime.now().isoformat()
    conn = _connect(path)
    try:
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO ticker_state (ticker) VALUES (?);", (ticker,))
        if ok:
            cur.execute(
                "UPDATE ticker_state SET last_attempt=?, last_success=?, fail_count=0, "
                "last_source=COALESCE(?,last_source), n_bars=COALESCE(?,n_bars) "
                "WHERE ticker=?;", (now, now, source, n_bars, ticker))
        else:
            cur.execute(
                "UPDATE ticker_state SET last_attempt=?, fail_count=fail_count+1 "
                "WHERE ticker=?;", (now, ticker))
        conn.commit()
    finally:
        conn.close()


def set_tier(ticker, tier, path=None):
    init_db(path)
    conn = _connect(path)
    try:
        conn.execute("INSERT OR IGNORE INTO ticker_state (ticker) VALUES (?);", (ticker,))
        conn.execute("UPDATE ticker_state SET tier=? WHERE ticker=?;", (tier, ticker))
        conn.commit()
    finally:
        conn.close()


def get_ticker_states(path=None):
    p = db_path(path)
    if not os.path.exists(p):
        return {}
    conn = _connect(path)
    try:
        rows = conn.execute(
            "SELECT ticker,tier,last_success,last_attempt,fail_count,last_source,n_bars "
            "FROM ticker_state;").fetchall()
    finally:
        conn.close()
    return {r[0]: {"tier": r[1], "last_success": r[2], "last_attempt": r[3],
                   "fail_count": r[4], "last_source": r[5], "n_bars": r[6]} for r in rows}


def write_diagnostics(diag, path=None):
    init_db(path)
    conn = _connect(path)
    try:
        conn.execute("DELETE FROM diagnostics;")
        conn.execute("INSERT INTO diagnostics (id, ts, payload) VALUES (1, ?, ?);",
                     (datetime.now().isoformat(), json.dumps(diag, default=_json_default)))
        conn.commit()
    finally:
        conn.close()


def read_diagnostics(path=None):
    p = db_path(path)
    if not os.path.exists(p):
        return None
    conn = _connect(path)
    try:
        row = conn.execute("SELECT ts, payload FROM diagnostics WHERE id=1;").fetchone()
    finally:
        conn.close()
    if not row:
        return None
    out = json.loads(row[1]) if row[1] else {}
    out["ts"] = row[0]
    return out


if __name__ == "__main__":
    init_db()
    meta = get_scan_meta()
    if meta is None:
        print("Databasen er tom - intet snapshot endnu.")
    else:
        print("Snapshot:", meta["n_rows"], "aktier | regime=", meta["regime"],
              "| kilde=", meta["source"], "|", meta["ts"])
    states = get_ticker_states()
    print("ticker_state:", len(states), "tickere | universe:",
          len(read_universe(active_only=False)))
