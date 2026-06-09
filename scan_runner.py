"""
scan_runner.py – Køres af worker.py som subprocess.
Bruger FMP (Financial Modeling Prep) i stedet for yfinance
for stabil og pålidelig datahentning.

Brug:
  python scan_runner.py full   → scanner alle aktier
  python scan_runner.py buy    → scanner kun BUY-kandidater
"""

import sys
import os
import logging
import pandas as pd
import numpy as np

os.environ['STREAMLIT_SERVER_HEADLESS'] = 'true'

import scanner_db as sdb
import fmp_fetcher as fmp

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
LOG = logging.getLogger('scan_runner')

BUY_SIGNALS = {'BUY NOW', 'BUY BREAKOUT', 'BUILD POSITION', 'STARTER BUY'}


def patch_streamlit_cache():
    import streamlit as st
    import functools
    def noop_cache(func=None, **kwargs):
        if func is not None:
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                return func(*args, **kwargs)
            return wrapper
        def decorator(f):
            @functools.wraps(f)
            def wrapper(*args, **kwargs):
                return f(*args, **kwargs)
            return wrapper
        return decorator
    st.cache_data = noop_cache
    st.cache_resource = noop_cache


def build_all_raw_fmp(universe):
    """
    Henter historiske data for hele universet via FMP.
    Returnerer dict {ticker: DataFrame} – samme format som yfinance.
    """
    symbols = [t[0] for t in universe]
    LOG.info(f"Henter data fra FMP for {len(symbols)} aktier...")
    return fmp.fetch_batch(symbols, days=420)


def run_full(universe):
    """Fuld scan af alle aktier via FMP + compute_scan (ingen monkey-patch)."""
    LOG.info(f"FULD SCAN – {len(universe)} aktier via FMP")

    patch_streamlit_cache()
    from scanner_v7 import fetch_market_data, derive_regime
    from scanner_core import compute_scan

    # Hent FX-rater via FMP
    LOG.info("Henter FX-rater...")
    fx_rates = fmp.fetch_fx_rates()
    LOG.info(f"FX-rater hentet: {len(fx_rates)} valutaer")

    # Hent all_raw data via FMP/yfinance
    all_raw = build_all_raw_fmp(universe)
    LOG.info(f"Data hentet for {len(all_raw)} aktier")

    try:
        mkt = fetch_market_data()
        regime = derive_regime(mkt, pd.DataFrame())

        # Brug compute_scan direkte — den tager all_raw som input
        # og behøver ingen monkey-patch af yfinance
        LOG.info(f"Beregner signaler for {len(all_raw)} aktier...")
        df_out, dropped = compute_scan(all_raw, universe, fx_rates, regime)
        LOG.info(f"compute_scan færdig: {len(df_out)} aktier med data, {len(dropped)} droppet")

        scan = df_out if df_out is not None and not df_out.empty else pd.DataFrame()
        regime = derive_regime(mkt, scan)

        # ── UNIVERSE-PADDING ──────────────────────────────────────────────
        # Aktier der blev droppet af scanner (for kort historik, manglende
        # data, osv.) tilføjes som stub-rækker med minimale værdier, så
        # dashboardet altid viser hele universet.
        info_map = {t[0]: t for t in universe}
        scanned_tickers = set(scan['ticker'].tolist()) if not scan.empty else set()
        stubs = []
        for ticker, df in all_raw.items():
            if ticker in scanned_tickers:
                continue
            info = info_map.get(ticker, (ticker, ticker, 'Unknown', 'US', 'CORE'))
            try:
                price = float(df['Close'].iloc[-1]) if df is not None and 'Close' in df.columns and len(df) > 0 else 0.0
            except Exception:
                price = 0.0
            stubs.append({
                'ticker': info[0],
                'name': info[1] if len(info) > 1 else ticker,
                'sector': info[2] if len(info) > 2 else 'Unknown',
                'region': info[3] if len(info) > 3 else 'US',
                'tier': info[4] if len(info) > 4 else 'CORE',
                'price': round(price, 2),
                'score': 0, 'dpct': 0.0, 'rsi': None, 'rsi_t': None,
                'sma20': None, 'sma60': None, 'sma200': None,
                'trend': None, 'trend200': None,
                'high20': None, 'low5': None, 'dh20': None,
                'volr': None, 'rvol50': None, 'avgvol': None, 'dolvol_m': None,
                'liq': '❌', 'lp': False,
                'atr20': None, 'atr_pct': 0.0,
                'sqz': '—', 'sqz_b': False,
                'rs_t': None, 'hl': '—', 'ia': '—', 'cap': '—',
                'ifs': None, 'ls': None, 'stn': 0, 'stage': None, 'rs_rank': 0,
                'w52h': None, 'w52l': None, 'dist52': None,
                'ts': 0, 'ss': 0, 'rp': 0,
                'setup': 'NO_DATA', 'buy': 'NO DATA', 'sell': 'HOLD', 'stop': None,
                'dolvol_usd_m': None, 'currency': 'USD', 'spark': [],
            })

        # Tilføj stubs der ikke allerede er i universe (ingen data i all_raw)
        raw_tickers = set(all_raw.keys())
        for ticker, info in info_map.items():
            if ticker in scanned_tickers or ticker in raw_tickers:
                continue
            stubs.append({
                'ticker': info[0],
                'name': info[1] if len(info) > 1 else ticker,
                'sector': info[2] if len(info) > 2 else 'Unknown',
                'region': info[3] if len(info) > 3 else 'US',
                'tier': info[4] if len(info) > 4 else 'CORE',
                'price': 0.0, 'score': 0, 'dpct': 0.0,
                'rsi': None, 'rsi_t': None, 'sma20': None, 'sma60': None, 'sma200': None,
                'trend': None, 'trend200': None, 'high20': None, 'low5': None, 'dh20': None,
                'volr': None, 'rvol50': None, 'avgvol': None, 'dolvol_m': None,
                'liq': '❌', 'lp': False, 'atr20': None, 'atr_pct': 0.0,
                'sqz': '—', 'sqz_b': False, 'rs_t': None, 'hl': '—', 'ia': '—', 'cap': '—',
                'ifs': None, 'ls': None, 'stn': 0, 'stage': None, 'rs_rank': 0,
                'w52h': None, 'w52l': None, 'dist52': None,
                'ts': 0, 'ss': 0, 'rp': 0,
                'setup': 'NO_DATA', 'buy': 'NO DATA', 'sell': 'HOLD', 'stop': None,
                'dolvol_usd_m': None, 'currency': 'USD', 'spark': [],
            })

        if stubs:
            stub_df = pd.DataFrame(stubs)
            scan = pd.concat([scan, stub_df], ignore_index=True)
            LOG.info(f"Universe-padding: {len(stubs)} stub-rækker tilføjet")

        n = sdb.write_scan_results(scan, regime, source='worker-fmp-full')
        LOG.info(f"FULD SCAN færdig – {n} aktier gemt ({len(scanned_tickers)} med data, {len(stubs)} stubs) | regime={regime}")
    except Exception as e:
        LOG.error(f"run_full fejlede: {e}", exc_info=True)


def run_buy(universe):
    """Genscanner kun aktuelle BUY-kandidater."""
    current = sdb.read_scan_results()
    if current.empty:
        LOG.info("BUY SCAN: ingen eksisterende data")
        return

    buy_tickers = set(
        current[current['buy'].isin(BUY_SIGNALS)]['ticker'].tolist()
    )
    if not buy_tickers:
        LOG.info("BUY SCAN: ingen aktuelle BUY-kandidater")
        return

    LOG.info(f"BUY SCAN – {len(buy_tickers)} kandidater via FMP")

    uni_map = {t[0]: t for t in universe}
    buy_universe = [uni_map[t] for t in buy_tickers if t in uni_map]

    if not buy_universe:
        return

    # Kør fuld scan på kun BUY-aktier
    patch_streamlit_cache()
    from scanner_v7 import fetch_scanner_data, fetch_market_data, derive_regime
    import yfinance as yf

    all_raw = build_all_raw_fmp(buy_universe)
    fx_rates = fmp.fetch_fx_rates()

    original_download = yf.download

    def fmp_patch(tickers, **kwargs):
        if isinstance(tickers, str):
            tickers = [tickers]
        if len(tickers) == 1:
            return all_raw.get(tickers[0], pd.DataFrame())
        result = {}
        for t in tickers:
            if t in all_raw:
                result[t] = all_raw[t]
        if not result:
            return pd.DataFrame()
        dfs = []
        for k, df in result.items():
            d = df.copy()
            d.columns = pd.MultiIndex.from_tuples([(col, k) for col in d.columns])
            dfs.append(d)
        return pd.concat(dfs, axis=1) if dfs else pd.DataFrame()

    yf.download = fmp_patch

    import scanner_v7 as sv7
    original_fx = sv7.fetch_fx_rates
    sv7.fetch_fx_rates = lambda: fx_rates

    try:
        mkt = fetch_market_data()
        regime = derive_regime(mkt, current)
        new_scan = fetch_scanner_data(tuple(buy_universe), regime)

        if new_scan.empty:
            return

        updated = current[~current['ticker'].isin(buy_tickers)].copy()
        updated = pd.concat([updated, new_scan], ignore_index=True)
        updated = updated.sort_values('score', ascending=False).reset_index(drop=True)

        n = sdb.write_scan_results(updated, regime, source='worker-fmp-buy')
        LOG.info(f"BUY SCAN færdig – {len(buy_tickers)} kandidater opdateret")
    finally:
        yf.download = original_download
        sv7.fetch_fx_rates = original_fx


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'full'

    patch_streamlit_cache()
    from scanner_v7 import UNIVERSE, load_custom_universe

    custom = load_custom_universe()
    existing = {t[0] for t in UNIVERSE}
    universe = UNIVERSE + [e for e in custom if e[0] not in existing]

    sdb.init_db()

    LOG.info(f"Univers: {len(universe)} aktier | Mode: {mode}")

    if mode == 'full':
        run_full(universe)
    elif mode == 'buy':
        run_buy(universe)
    else:
        LOG.error(f"Ukendt mode: {mode}")
        sys.exit(1)


if __name__ == '__main__':
    main()