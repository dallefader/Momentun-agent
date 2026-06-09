"""
fmp_fetcher.py – Financial Modeling Prep data fetcher
Erstatter yfinance i scan_runner.py med stabil FMP API
"""

import os
import time
import logging
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

LOG = logging.getLogger('fmp_fetcher')

# Læs API-nøgle fra fil
def get_api_key():
    # 1) Miljøvariabel (Streamlit Cloud secrets eller shell export)
    key = os.environ.get('FMP_API_KEY', '').strip()
    if key:
        return key
    # 2) Lokal fil (udvikling)
    key_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fmp_key.txt')
    try:
        with open(key_file) as f:
            return f.read().strip()
    except:
        raise Exception("FMP API-nøgle ikke fundet — sæt FMP_API_KEY miljøvariabel eller fmp_key.txt")

FMP_BASE = "https://financialmodelingprep.com/stable"
REQUEST_DELAY = 0.2  # sekunder mellem requests


def fmp_get(endpoint, params=None):
    """Lav et GET-kald til FMP API."""
    api_key = get_api_key()
    url = f"{FMP_BASE}/{endpoint}"
    p = {"apikey": api_key}
    if params:
        p.update(params)
    try:
        r = requests.get(url, params=p, timeout=15)
        if r.status_code == 200:
            return r.json()
        else:
            LOG.warning(f"FMP {endpoint}: {r.status_code} – {r.text[:100]}")
            return None
    except Exception as e:
        LOG.error(f"FMP request fejl: {e}")
        return None


def fetch_historical(symbol, days=400):
    """
    Hent historiske OHLCV-data for en aktie.
    Returnerer DataFrame med kolonner: Open, High, Low, Close, Volume
    og DatetimeIndex – samme format som yfinance.
    """
    data = fmp_get(f"historical-price-eod/full", {"symbol": symbol})
    time.sleep(REQUEST_DELAY)

    if not data or not isinstance(data, list) or len(data) == 0:
        return pd.DataFrame()

    df = pd.DataFrame(data)
    if 'date' not in df.columns or 'close' not in df.columns:
        return pd.DataFrame()

    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)

    # Filtrer til ønskede dage
    cutoff = datetime.now() - timedelta(days=days)
    df = df[df['date'] >= cutoff]

    if len(df) < 50:
        return pd.DataFrame()

    # Omdøb kolonner til yfinance-format
    df = df.rename(columns={
        'open': 'Open',
        'high': 'High',
        'low': 'Low',
        'close': 'Close',
        'volume': 'Volume'
    })

    df = df.set_index('date')
    df.index.name = 'Date'

    # Behold kun relevante kolonner
    cols = [c for c in ['Open', 'High', 'Low', 'Close', 'Volume'] if c in df.columns]
    return df[cols].dropna()


# Europæiske og ikke-US suffixer der skal bruge yfinance
YFINANCE_SUFFIXES = [
    '.CO', '.ST', '.OL', '.DE', '.PA', '.AS', '.SW',
    '.MI', '.MC', '.L', '.HE', '.AX', '.SI', '.T',
    '.HK', '.KS', '.TW', '.NS', '.BR', '.MU', '.VI'
]

def is_us_ticker(symbol):
    """Returnerer True hvis aktien er en US-ticker der virker med FMP Starter."""
    return not any(symbol.endswith(s) for s in YFINANCE_SUFFIXES)


def fetch_yfinance(symbol, days=420, timeout=30):
    """Hent data via yfinance for ikke-US aktier. Timeout per forsøg: 30s."""
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
    import yfinance as yf

    period = '14mo' if days <= 420 else '2y'
    df = pd.DataFrame()

    for attempt in range(2):
        try:
            with ThreadPoolExecutor(max_workers=1) as ex:
                future = ex.submit(
                    yf.download, symbol,
                    period=period, interval='1d',
                    auto_adjust=True, progress=False
                )
                df = future.result(timeout=timeout)
        except FuturesTimeout:
            LOG.warning(f"yfinance timeout ({timeout}s) for {symbol} — forsøg {attempt+1}")
            df = pd.DataFrame()
        except Exception as e:
            LOG.warning(f"yfinance fejl for {symbol}: {e}")
            df = pd.DataFrame()

        if df is not None and not df.empty:
            break

    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        for level in range(df.columns.nlevels):
            vals = df.columns.get_level_values(level)
            if 'Close' in vals:
                df.columns = vals
                break
    df = df.dropna()
    return df if len(df) >= 50 else pd.DataFrame()


def fetch_batch(symbols, days=400):
    """
    Hent historiske data for en liste af symboler.
    FMP → US-aktier | yfinance → europæiske/asiatiske aktier
    Returnerer dict {symbol: DataFrame}
    """
    results = {}
    total = len(symbols)
    fmp_count = 0
    yf_count = 0

    for i, symbol in enumerate(symbols):
        if i % 50 == 0:
            LOG.info(f"Batch: {i}/{total} | FMP: {fmp_count} | yfinance: {yf_count}")

        if is_us_ticker(symbol):
            df = fetch_historical(symbol, days)
            if not df.empty:
                fmp_count += 1
                results[symbol] = df
        else:
            df = fetch_yfinance(symbol, days)
            if not df.empty:
                yf_count += 1
                results[symbol] = df

    LOG.info(f"Batch færdig: {len(results)}/{total} | FMP: {fmp_count} | yfinance: {yf_count}")
    return results


def fetch_quote(symbol):
    """Hent seneste pris og daglig ændring."""
    data = fmp_get(f"quote/{symbol}")
    time.sleep(REQUEST_DELAY)
    if not data or not isinstance(data, list) or len(data) == 0:
        return None
    return data[0]


def fetch_fx_rates():
    """
    Hent FX-kurser mod USD.
    Returnerer dict {'USD': 1.0, 'EUR': 1.08, 'DKK': 0.145, ...}
    """
    rates = {'USD': 1.0}

    currencies = [
        'EUR', 'DKK', 'SEK', 'NOK', 'GBP', 'CHF',
        'JPY', 'HKD', 'KRW', 'TWD', 'INR', 'CAD',
        'AUD', 'BRL', 'ILS'
    ]

    for cur in currencies:
        data = fmp_get(f"quote/{cur}USD")
        time.sleep(0.1)
        if data and isinstance(data, list) and len(data) > 0:
            price = data[0].get('price')
            if price:
                rates[cur] = float(price)

    # Fallback defaults
    defaults = {
        'DKK': 0.145, 'EUR': 1.08, 'SEK': 0.095, 'NOK': 0.092,
        'GBP': 1.27, 'CHF': 1.12, 'JPY': 0.0066, 'HKD': 0.128,
        'KRW': 0.00074, 'TWD': 0.031, 'INR': 0.012, 'CAD': 0.73,
        'AUD': 0.66, 'BRL': 0.20, 'ILS': 0.27
    }
    for cur, val in defaults.items():
        rates.setdefault(cur, val)

    return rates


def fetch_market_data_fmp(tickers_with_names):
    """
    Hent markedsdata til Market Pulse i dashboardet.
    Erstatter fetch_market_data() i scanner_v7.py
    """
    rows = {}
    symbols = [t for t, _ in tickers_with_names]

    for symbol in symbols:
        data = fmp_get(f"historical-price-eod/full", {"symbol": symbol})
        time.sleep(REQUEST_DELAY)

        if not data or not isinstance(data, list) or len(data) < 5:
            continue

        df = pd.DataFrame(data)
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').reset_index(drop=True)

        c = df['close'].values
        if len(c) < 5:
            continue

        p = float(c[-1])
        prev = float(c[-2])
        d5 = float(c[-6]) if len(c) > 5 else prev
        d30 = float(c[-31]) if len(c) > 30 else prev

        pct1 = round((p / prev - 1) * 100, 1) if prev > 0 else 0
        pct5 = round((p / d5 - 1) * 100, 1) if d5 > 0 else 0
        pct30 = round((p / d30 - 1) * 100, 1) if d30 > 0 else 0

        s20 = float(np.mean(c[-20:])) if len(c) >= 20 else p
        s60 = float(np.mean(c[-60:])) if len(c) >= 60 else p
        trend = 'UP' if p > s20 > s60 else ('DOWN' if p < s20 < s60 else 'MIX')

        rows[symbol] = {
            'price': round(p, 2),
            'pct1': pct1,
            'pct5': pct5,
            'pct30': pct30,
            'trend': trend,
            'closes': c[-60:].tolist()
        }

    return rows


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Tester FMP connection...")
    df = fetch_historical("AAPL", days=400)
    if not df.empty:
        print(f"✅ AAPL: {len(df)} dage hentet")
        print(f"   Seneste pris: {df['Close'].iloc[-1]}")
        print(f"   Dato: {df.index[-1].date()}")
    else:
        print("❌ Ingen data")