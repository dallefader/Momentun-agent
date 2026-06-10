"""
Trading Scanner Pro v5.0
========================
ALGORITMEN ER UÆNDRET I FORHOLD TIL v4 BORTSET FRA ÉN AFTALT TILFØJELSE:
  * Stage 2 (Weinstein) er hard filter for BUY/BREAKOUT/BUILD/STARTER-signaler.
    Aktier udenfor Stage 2 kan ikke producere aggressive long-signaler.

ØVRIGE ÆNDRINGER ER REN INFRASTRUKTUR (rører ikke signal-logikken):
  - FX-korrektion: dollar_volume konverteres til USD via daglige FX-rates,
    så alle markeder behandles ligeværdigt i likviditetsgaten.
  - GBp-håndtering for .L tickere (pence → GBP → USD).
  - Yfinance retries med exponential backoff + Stooq failover via
    pandas-datareader, så færre tickere falder ud af scannet stille.
  - Vektoriseret SMA200-serie i stedet for O(N²) per-ticker loop
    (kun performance, samme resultat).
  - Variabel-rename: 'st' fra derive_states-kald til 'sigres' så det
    ikke skygger Streamlit's 'st'-modul.
  - Diagnostik-tab: viser hvor mange tickere yfinance gav data på,
    hvor mange via Stooq-failover, og hvilke der fejlede.
  - Backtest-tab: gemmer dagligt snapshot af BUY-signaler i JSON og
    beregner forward returns (1-19/20-59/60-119/120+ dage) med hit-rate
    og gennemsnitlig return, så algoritmens edge dokumenteres over tid.

UNDER MOTORHJELMEN (UÆNDRET FRA v4)
  - 500+ aktier, makro/sektor-ETF'er, Bloomberg-style Streamlit UI
  - Positions / watchlist / custom universe persisteres i JSON
  - RSI / ATR / IBD RS / score-vægte / setup-detektorer / stops: alt 1:1 v4
"""

import yfinance as yf
import pandas as pd
import numpy as np
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, time, timedelta
import pytz
import json
import os
import time as time_module
import logging

# pandas-datareader er optional (stooq failover)
try:
    import pandas_datareader.data as pdr
    HAS_PDR = True
except ImportError:
    HAS_PDR = False

# Diagnostic-logging
logging.basicConfig(level=logging.WARNING, format='%(asctime)s [%(levelname)s] %(message)s')
LOG = logging.getLogger('scanner_v5')

st.set_page_config(page_title="Trading Terminal Pro v5.0", page_icon="🟢",
                   layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600;700&family=Orbitron:wght@700;900&display=swap');

  /* ── BASE ── */
  .stApp,.main{background:#0a0a0a;color:#e0e0e0;font-family:'IBM Plex Mono',monospace;}
  section[data-testid="stSidebar"]{display:none!important;}
  [data-testid="collapsedControl"]{display:none!important;}
  .block-container{padding-top:0.3rem!important;padding-bottom:0!important;max-width:100%!important;}

  /* Hide Streamlit chrome */
  #MainMenu{visibility:hidden;}
  header[data-testid="stHeader"]{background:#000;height:0;min-height:0;padding:0;overflow:hidden;}
  footer{visibility:hidden;}
  .stDeployButton{display:none;}
  [data-testid="stToolbar"]{display:none;}
  .block-container{padding-top:0.5rem!important;padding-bottom:0!important;}
  div[data-testid="stDecoration"]{display:none;}
  h1{color:#ffffff!important;font-family:'Orbitron',monospace!important;font-size:1.1rem!important;letter-spacing:3px;margin:0!important;}
  h2,h3{color:#888!important;font-family:'IBM Plex Mono',monospace!important;font-size:0.72rem!important;letter-spacing:2px;margin:3px 0!important;text-transform:uppercase;}
  p,li,label,.stMarkdown{color:#aaa!important;font-family:'IBM Plex Mono',monospace!important;font-size:0.78rem!important;}

  /* ── METRICS ── */
  [data-testid="metric-container"]{background:#111;border:1px solid #222;padding:6px 10px;}
  [data-testid="metric-container"] label{color:#555!important;font-family:'IBM Plex Mono',monospace!important;font-size:0.58rem!important;text-transform:uppercase;letter-spacing:2px;}
  [data-testid="stMetricValue"]{color:#fff!important;font-family:'Orbitron',monospace!important;font-size:1.1rem!important;font-weight:700!important;}

  /* ── BUTTONS ── */
  .stButton button{background:#111;color:#00ff88;border:1px solid #333;font-family:'IBM Plex Mono',monospace;font-size:0.72rem;text-transform:uppercase;padding:4px 12px;}
  .stButton button:hover{background:#00ff88;color:#000;border-color:#00ff88;}

  /* ── TABS ── */
  .stTabs [data-baseweb="tab-list"]{background:#000;border-bottom:1px solid #222;gap:0;}
  .stTabs [data-baseweb="tab"]{background:#000;color:#444;border:1px solid #1a1a1a;font-family:'IBM Plex Mono',monospace;font-size:0.68rem;letter-spacing:1px;text-transform:uppercase;padding:5px 14px;}
  .stTabs [aria-selected="true"]{background:#00ff88!important;color:#000!important;font-weight:700!important;}

  /* ── INPUTS ── */
  .stSelectbox>div>div,.stMultiSelect>div>div,.stTextInput>div>div{background:#0d0d0d;border:1px solid #222;color:#ddd;font-family:'IBM Plex Mono',monospace;}
  hr{border-color:#1a1a1a;margin:6px 0;}
  ::-webkit-scrollbar{width:3px;height:3px;}
  ::-webkit-scrollbar-thumb{background:#333;}
  ::-webkit-scrollbar-track{background:#000;}
  .stDataFrame{border:1px solid #1e1e1e;}

  /* ── BLOOMBERG COMPONENTS ── */

  /* Header bar */
  .bb-header{background:#000;border-bottom:2px solid #00ff88;padding:6px 12px;display:flex;align-items:center;gap:16px;}
  .bb-title{color:#fff;font-family:'Orbitron',monospace;font-size:0.95rem;font-weight:900;letter-spacing:3px;}
  .bb-regime-on {color:#00ff88;font-family:'Orbitron',monospace;font-weight:700;font-size:0.8rem;border:1px solid #00ff88;padding:2px 10px;}
  .bb-regime-off{color:#ff3333;font-family:'Orbitron',monospace;font-weight:700;font-size:0.8rem;border:1px solid #ff3333;padding:2px 10px;}
  .bb-regime-neu{color:#ffaa00;font-family:'Orbitron',monospace;font-weight:700;font-size:0.8rem;border:1px solid #ffaa00;padding:2px 10px;}

  /* KPI strip */
  .kpi-strip{display:flex;gap:0;border-bottom:1px solid #1a1a1a;margin-bottom:8px;}
  .kpi-cell{flex:1;padding:5px 10px;border-right:1px solid #1a1a1a;background:#0d0d0d;}
  .kpi-cell:last-child{border-right:none;}
  .kpi-label{color:#555;font-size:0.58rem;text-transform:uppercase;letter-spacing:2px;font-family:'IBM Plex Mono',monospace;}
  .kpi-value{color:#fff;font-size:1.1rem;font-family:'Orbitron',monospace;font-weight:700;line-height:1.2;}
  .kpi-up{color:#00ff88;}
  .kpi-dn{color:#ff3333;}
  .kpi-neu{color:#ffaa00;}

  /* Panel */
  .bb-panel{background:#0d0d0d;border:1px solid #1e1e1e;margin-bottom:6px;}
  .bb-panel-hdr{background:#111;border-bottom:1px solid #1e1e1e;padding:3px 10px;font-family:'IBM Plex Mono',monospace;font-size:0.62rem;color:#555;text-transform:uppercase;letter-spacing:2px;display:flex;justify-content:space-between;}
  .bb-panel-hdr span{color:#00ff88;}

  /* Market row */
  .mkt-row{display:grid;grid-template-columns:72px 1fr 80px 70px 60px;gap:0;padding:2px 8px;border-bottom:1px solid #111;font-family:'IBM Plex Mono',monospace;font-size:0.74rem;align-items:center;}
  .mkt-row:hover{background:#141414;}
  .mkt-t{color:#fff;font-weight:600;}
  .mkt-n{color:#444;overflow:hidden;white-space:nowrap;font-size:0.68rem;}
  .mkt-p{color:#ccc;text-align:right;}
  .mkt-up{color:#00ff88;text-align:right;font-weight:600;}
  .mkt-dn{color:#ff3333;text-align:right;font-weight:600;}
  .mkt-neu{color:#666;text-align:right;}
  .mkt-grp{padding:2px 8px;background:#0a0a0a;font-family:'IBM Plex Mono',monospace;font-size:0.58rem;color:#333;text-transform:uppercase;letter-spacing:2px;border-bottom:1px solid #111;}

  /* Signal blocks – Bloomberg style farveblokke */
  .sig-block{display:inline-block;padding:2px 8px;font-family:'IBM Plex Mono',monospace;font-size:0.68rem;font-weight:700;text-transform:uppercase;letter-spacing:1px;}
  .sig-buynow  {background:#00ff88;color:#000;}
  .sig-breakout{background:#00cc66;color:#000;}
  .sig-build   {background:#0066cc;color:#fff;}
  .sig-starter {background:#004499;color:#aad4ff;}
  .sig-extended{background:#cc8800;color:#000;}
  .sig-reduce  {background:#cc4400;color:#fff;}
  .sig-exit    {background:#cc0000;color:#fff;}
  .sig-watch   {background:#1a1a1a;color:#444;}

  /* Candidate row – Bloomberg style */
  .cand-row{display:grid;grid-template-columns:80px 130px 80px 55px 40px auto;gap:4px;padding:4px 8px;border-bottom:1px solid #111;font-family:'IBM Plex Mono',monospace;font-size:0.74rem;align-items:center;}
  .cand-row:hover{background:#141414;}
  .cand-t{color:#fff;font-weight:700;}
  .cand-n{color:#444;overflow:hidden;white-space:nowrap;font-size:0.67rem;}
  .cand-p{color:#ccc;text-align:right;}
  .cand-s{color:#fff;font-family:'Orbitron',monospace;font-size:0.7rem;text-align:right;font-weight:700;}

  /* Position row */
  .pos-row{display:grid;grid-template-columns:70px 110px 65px 65px 70px auto;gap:4px;padding:4px 8px;border-bottom:1px solid #111;font-family:'IBM Plex Mono',monospace;font-size:0.74rem;align-items:center;}
  .pos-row:hover{background:#141414;}

  /* Mover row */
  .mov-row{display:grid;grid-template-columns:72px 90px 75px auto auto;gap:4px;padding:3px 8px;border-bottom:1px solid #111;font-family:'IBM Plex Mono',monospace;font-size:0.72rem;align-items:center;}
  .mov-row:hover{background:#141414;}
  .mov-t-up{color:#00ff88;font-weight:700;}
  .mov-t-dn{color:#ff3333;font-weight:700;}
  .mov-sec{color:#333;font-size:0.64rem;}
  .mov-p{color:#999;text-align:right;}

  /* Sektor heatmap blokke */
  .sek-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:2px;margin-top:4px;}
  .sek-cell{padding:6px 8px;text-align:center;font-family:'IBM Plex Mono',monospace;}
  .sek-name{font-size:0.62rem;color:#999;text-transform:uppercase;letter-spacing:1px;}
  .sek-pct{font-size:0.9rem;font-weight:700;font-family:'Orbitron',monospace;margin-top:2px;}

  /* Trend badges */
  .tr-up {background:#003322;color:#00ff88;font-size:0.6rem;padding:1px 5px;font-family:'IBM Plex Mono',monospace;}
  .tr-dn {background:#220000;color:#ff3333;font-size:0.6rem;padding:1px 5px;font-family:'IBM Plex Mono',monospace;}
  .tr-mix{background:#1a1500;color:#ffaa00;font-size:0.6rem;padding:1px 5px;font-family:'IBM Plex Mono',monospace;}

  /* Sidebar */
  .sb-exch{display:flex;align-items:center;gap:6px;padding:2px 0;font-family:'IBM Plex Mono',monospace;font-size:0.7rem;border-bottom:1px solid #111;}
  .sb-open  {color:#00ff88;}
  .sb-closed{color:#ff3333;}
  .sb-pre   {color:#ffaa00;}

  /* Scanner table */
  .scan-row{display:grid;grid-template-columns:75px 120px 80px 55px 50px 50px 40px 50px 45px auto;gap:2px;padding:3px 6px;border-bottom:1px solid #0f0f0f;font-family:'IBM Plex Mono',monospace;font-size:0.71rem;align-items:center;}
  .scan-row:hover{background:#111;}
  .scan-hdr{background:#0a0a0a;color:#444;font-size:0.6rem;text-transform:uppercase;letter-spacing:1px;}
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════
# ── CONFIG (uændret algoritmisk fra v4; kun infrastruktur-felter tilføjet) ─
import scanner_db as sdb   # FASE 1: SQLite lager-lag (afkobler beregning fra visning)

CONFIG = {
    'rsi_period': 14, 'sma_fast': 20, 'sma_mid': 60, 'sma_long': 200,
    'atr_fast': 5, 'atr_slow': 20, 'breakout_distance': 0.06,
    'squeeze_factor': 0.78, 'min_avg_vol': 200_000,
    'min_dollar_vol': 8_000_000,                       # nu USD-normaliseret via FX
    'max_retries': 3,
    'retry_backoff_base': 2.0,                         # sek for exponential backoff
    'forward_return_horizons': [20, 60, 120],          # backtest forward returns
    'min_history_days': 210,
}
POSITIONS_FILE        = 'positions.json'
WATCHLIST_FILE        = 'watchlist.json'
CUSTOM_UNIVERSE_FILE  = 'custom_universe.json'
SIGNALS_HISTORY_FILE  = 'signals_history.json'        # backtest snapshots
DIAGNOSTICS_FILE      = 'scanner_diagnostics.json'    # download success/failure log

# ── FX & CURRENCY ──────────────────────────────────────────────────────
# Bemærk: .L (UK) tickere er normalt i pence (GBp). Vi multiplicerer prisen
# med 0.01 INDEN konvertering til USD. Andre særtilfælde kan tilføjes her.
CURRENCY_BY_REGION = {
    'US':'USD','Denmark':'DKK','Sweden':'SEK','Norway':'NOK','Finland':'EUR',
    'Germany':'EUR','UK':'GBP','France':'EUR','Netherlands':'EUR',
    'Switzerland':'CHF','Spain':'EUR','Italy':'EUR','Japan':'JPY',
    'HongKong':'HKD','SouthKorea':'KRW','Taiwan':'TWD','India':'INR',
    'Canada':'CAD','Australia':'AUD','Brazil':'BRL','Israel':'ILS',
    'Global':'USD','Europe':'EUR','Commodities':'USD','Crypto':'USD',
    'Unknown':'USD',
}

def ticker_is_gbp_pence(ticker: str) -> bool:
    """LSE-aktier (.L) handles typisk i pence — yfinance returnerer rå pris i GBp."""
    return ticker.endswith('.L')

EXCHANGES = {
    'NYSE':       {'tz':'America/New_York',  'open':time(9,30),'close':time(16,0), 'pre':time(4,0),  'flag':'🇺🇸'},
    'Copenhagen': {'tz':'Europe/Copenhagen', 'open':time(9,0), 'close':time(17,0), 'pre':time(8,30),'flag':'🇩🇰'},
    'Oslo':       {'tz':'Europe/Oslo',       'open':time(9,0), 'close':time(16,30),'pre':time(8,30),'flag':'🇳🇴'},
    'Stockholm':  {'tz':'Europe/Stockholm',  'open':time(9,0), 'close':time(17,30),'pre':time(8,30),'flag':'🇸🇪'},
    'Amsterdam':  {'tz':'Europe/Amsterdam',  'open':time(9,0), 'close':time(17,30),'pre':time(8,0), 'flag':'🇳🇱'},
    'Frankfurt':  {'tz':'Europe/Berlin',     'open':time(9,0), 'close':time(17,30),'pre':time(8,0), 'flag':'🇩🇪'},
    'London':     {'tz':'Europe/London',     'open':time(8,0), 'close':time(16,30),'pre':time(7,0), 'flag':'🇬🇧'},
    'Paris':      {'tz':'Europe/Paris',      'open':time(9,0), 'close':time(17,30),'pre':time(8,0), 'flag':'🇫🇷'},
    'Tokyo':      {'tz':'Asia/Tokyo',        'open':time(9,0), 'close':time(15,30),'pre':time(8,0), 'flag':'🇯🇵'},
    'HongKong':   {'tz':'Asia/Hong_Kong',    'open':time(9,30),'close':time(16,0), 'pre':time(9,0), 'flag':'🇭🇰'},
}

def get_exchange_status(info):
    tz=pytz.timezone(info['tz']); now=datetime.now(tz); t=now.time()
    if now.weekday()>=5: return 'LUKKET'
    if info['open']<=t<info['close']: return 'ÅBEN'
    if info['pre']<=t<info['open']:   return 'PRE'
    return 'LUKKET'

# ══════════════════════════════════════════════════════════════
# MARKET TICKERS
# ══════════════════════════════════════════════════════════════
MARKET_GROUPS = {
    '🇺🇸 US INDICES': [
        ('SPY',  'S&P 500'),
        ('QQQ',  'Nasdaq 100'),
        ('IWM',  'Russell 2000'),
        ('DIA',  'Dow Jones'),
        ('^VIX', 'VIX Fear'),
    ],
    '🌍 EUROPA INDICES': [
        ('^OMXC25', 'C25 København'),
        ('^GDAXI',  'DAX (Tyskland)'),
        ('^FCHI',   'CAC 40 (Frankrig)'),
        ('^FTSE',   'FTSE 100 (UK)'),
        ('^AEX',    'AEX (Holland)'),
        ('^OMXS30', 'OMX30 (Sverige)'),
        ('^OSEBX',  'OBX (Norge)'),
    ],
    '🌏 ASIA & EM': [
        ('EEM',   'Emerg. Markets'),
        ('EWJ',   'Japan'),
        ('MCHI',  'China'),
        ('EWY',   'South Korea'),
        ('EWT',   'Taiwan'),
    ],
    '🛢️ ENERGI': [
        ('CL=F',  'WTI Olie'),
        ('BZ=F',  'Brent Olie'),
        ('NG=F',  'Naturgas'),
        ('RB=F',  'Benzin'),
        ('HO=F',  'Fyringsolie'),
    ],
    '🥇 METALLER': [
        ('GLD',   'Guld ETF'),
        ('GC=F',  'Guld Futures'),
        ('SLV',   'Sølv ETF'),
        ('HG=F',  'Kobber'),
        ('PL=F',  'Platin'),
    ],
    '🌾 RÅVARER': [
        ('ZW=F',  'Hvede'),
        ('ZC=F',  'Majs'),
        ('ZS=F',  'Soja'),
        ('CC=F',  'Kakao'),
        ('KC=F',  'Kaffe'),
    ],
    '💱 MAKRO': [
        ('UUP',   'US Dollar'),
        ('^TNX',  '10Y Rente'),
        ('^TYX',  '30Y Rente'),
        ('TIP',   'TIPS Inflation'),
        ('BITO',  'Bitcoin ETF'),
    ],
}

MACRO_TICKERS = [t for grp in MARKET_GROUPS.values() for t,_ in grp]
MACRO_NAMES   = {t: n for grp in MARKET_GROUPS.values() for t,n in grp}

# ══════════════════════════════════════════════════════════════
# SEKTOR ETFS TIL HEATMAP
# ══════════════════════════════════════════════════════════════
SECTOR_ETFS = [
    ('XLK',  'Tech'),
    ('XLF',  'Financials'),
    ('XLE',  'Energy'),
    ('XLV',  'Healthcare'),
    ('XLI',  'Industrials'),
    ('XLB',  'Materials'),
    ('XLY',  'Consumer Disc'),
    ('XLP',  'Consumer Staples'),
    ('XLU',  'Utilities'),
    ('XLRE', 'Real Estate'),
    ('XLC',  'Comm. Services'),
    ('SOXX', 'Semiconductors'),
    ('IBB',  'Biotech'),
    ('ITA',  'Defense'),
    ('ICLN', 'Clean Energy'),
]

# ══════════════════════════════════════════════════════════════
# FULDT UNIVERS – 500+ AKTIER
# ══════════════════════════════════════════════════════════════
from scanner_core import UNIVERSE

# ══════════════════════════════════════════════════════════════
# INDIKATORER (vektoriserede via pandas — O(N) overalt)
# ══════════════════════════════════════════════════════════════
def sma(arr, n):
    if arr is None or len(arr)<n: return None
    return float(np.mean(arr[-n:]))

def rolling_sma(closes, n):
    """Vektoriseret SMA-serie — bruges til stage og chart."""
    return pd.Series(closes).rolling(n).mean().values

def calc_rsi(closes, period=14):
    # UÆNDRET fra v4 — simpel sum-baseret RSI
    if closes is None or len(closes)<period+1: return None
    gains=losses=0.0
    for i in range(len(closes)-period,len(closes)):
        d=closes[i]-closes[i-1]
        if d>=0: gains+=d
        else: losses+=abs(d)
    ag=gains/period; al=losses/period
    if al==0 and ag==0: return 50.0
    if al==0: return 100.0
    return 100.0-(100.0/(1.0+ag/al))

def calc_atr(highs,lows,closes,period=20):
    # UÆNDRET fra v4
    if highs is None or len(highs)<period+1: return None
    trs=[max(highs[i]-lows[i],abs(highs[i]-closes[i-1]),abs(lows[i]-closes[i-1])) for i in range(1,len(highs))]
    if len(trs)<period: return None
    return float(np.mean(trs[-period:]))

def calc_ibd_rs_raw(c):
    """IBD-style vægtet relative-strength på 252-handelsdages basis.
    Vægte: 40/20/20/20 for seneste til ældste kvartal (standard IBD)."""
    n = len(c)
    if n < 200: return None
    try:
        q4 = c[-1]   / c[-64]  - 1 if n >= 64  else 0
        q3 = c[-64]  / c[-127] - 1 if n >= 127 else 0
        q2 = c[-127] / c[-189] - 1 if n >= 189 else 0
        q1 = c[-189] / c[-min(252,n)] - 1 if n >= 190 else 0
        return q4*0.40 + q3*0.20 + q2*0.20 + q1*0.20
    except Exception:
        return None

def weinstein_stage(c, s200_series):
    """Stage klassifikation:
       1=accumulation base, 2=advancing (pris>SMA200, SMA200 stigende),
       3=distribution, 4=declining. Position-tradere køber primært i Stage 2."""
    if len(c) < 210: return 0, '?'
    p = float(c[-1])
    s = s200_series[-1] if not pd.isna(s200_series[-1]) else None
    s_4w = s200_series[-20] if len(s200_series) >= 20 and not pd.isna(s200_series[-20]) else s
    if s is None or s_4w is None: return 0, '?'
    rising = s > s_4w
    if p > s and rising:     return 2, 'S2✅'
    if p > s and not rising: return 3, 'S3⚠️'
    if p < s and not rising: return 4, 'S4❌'
    return 1, 'S1🔄'

# ══════════════════════════════════════════════════════════════
# SIGNALLOGIK – v5
# Algoritmen er UÆNDRET fra v4 bortset fra ÉN aftalt ændring:
#   * Stage 2 (Weinstein) er hard filter for accum/ib/br/ma.
#     Aktier udenfor Stage 2 kan ikke producere BUY/BREAKOUT/BUILD/STARTER.
# Alle øvrige vægte, tærskler og stop-multiplikatorer matcher v4 1:1.
# ══════════════════════════════════════════════════════════════
def derive_states(price,sma20,sma60,sma200,rsi,rsi_trend,low5,dist_h20,
                  vol_ratio,liq_pass,atr20,squeeze,rs_trend,higher_low,
                  inst_accum,cap_risk,trend,trend200,market_regime,
                  ifs,ls,stage_num,rs_rank):
    ts=0
    if price>sma200: ts+=24
    if sma20>sma60:  ts+=18
    if price>sma20:  ts+=10
    if rs_trend=='UP': ts+=12
    if higher_low: ts+=8
    ts+=min(10,int((ifs or 0)/10))

    tight=(atr20/price)<=0.045 if(atr20 and price>0) else False
    accum=(trend=='BUY' and trend200=='LONG TREND' and rsi is not None
           and 38<=rsi<=64 and vol_ratio is not None and vol_ratio>=0.90
           and abs((price-sma20)/sma20)<=0.06 and rs_trend in('UP','FLAT',''))
    ib=accum and(inst_accum or(ifs or 0)>=65)
    br=(trend=='BUY' and trend200=='LONG TREND' and rs_trend in('UP','FLAT','')
        and dist_h20 is not None and 0<=dist_h20<=CONFIG['breakout_distance']
        and vol_ratio is not None and 0.95<=vol_ratio<=3.0
        and rsi is not None and 44<=rsi<=78
        and(squeeze or(dist_h20 is not None and dist_h20<=0.03)))
    ma=(br and vol_ratio is not None and vol_ratio>=1.10
        and rsi is not None and 50<=rsi<=80 and liq_pass and market_regime!='RISK_OFF')
    ext=(rsi is not None and rsi>84) or price>sma20*1.14
    w1=price<sma20; w2=sma20<sma60; w3=price<sma200; w4=rs_trend=='DOWN'
    wc=sum([w1,w2,w3,w4])
    wk=wc>=2 or(price<sma20 and rs_trend=='DOWN')
    fs=wc>=3 and((rsi is not None and rsi<42) or price<low5)

    # ── ENESTE AFTALTE NYHED: Stage 2 hard filter ──
    if stage_num != 2:
        accum = ib = br = ma = False

    ss=0
    if accum: ss+=20
    if tight: ss+=6
    if ib:    ss+=18
    if br:    ss+=22
    if ma:    ss+=16
    if squeeze: ss+=6
    if rsi is not None and 46<=rsi<=72: ss+=6
    if dist_h20 is not None and dist_h20<=0.07: ss+=6
    if vol_ratio is not None and vol_ratio>=0.95: ss+=6
    ss+=min(10,int((ls or 0)/10))

    rp=0
    if not liq_pass: rp+=14
    if market_regime=='RISK_OFF': rp+=10
    if rs_trend=='DOWN': rp+=6
    if ext: rp+=8
    if cap_risk: rp+=6
    if wk: rp+=8
    if fs: rp+=14

    pri=max(0,min(100,ts+ss-rp))

    if fs:   st_='FAILED_SETUP'
    elif ext: st_='EXTENDED'
    elif ma:  st_='MOMENTUM_ACTIVE'
    elif br:  st_='BREAKOUT_READY'
    elif ib:  st_='INSTITUTIONAL_BUILD'
    elif accum: st_='ACCUMULATION'
    elif wk:  st_='WEAKENING'
    else:     st_='NO_SETUP'

    am={'ACCUMULATION':'STARTER','INSTITUTIONAL_BUILD':'BUILD',
        'BREAKOUT_READY':'BREAKOUT_ENTRY','MOMENTUM_ACTIVE':'MOMENTUM_ENTRY',
        'EXTENDED':'EXTENDED','WEAKENING':'REDUCE','FAILED_SETUP':'EXIT'}
    ac=am.get(st_,'WATCHLIST')
    if market_regime=='RISK_OFF' and ac in('BUILD','BREAKOUT_ENTRY','MOMENTUM_ENTRY'): ac='STARTER'

    bm={'STARTER':'STARTER BUY','BUILD':'BUILD POSITION',
        'BREAKOUT_ENTRY':'BUY BREAKOUT','MOMENTUM_ENTRY':'BUY NOW','EXTENDED':'EXTENDED — WAIT'}
    buy=bm.get(ac,'WATCHLIST')
    sell='EXIT' if ac=='EXIT' else('REDUCE' if ac=='REDUCE' else 'HOLD')

    stop=round(sma20,2)
    if st_=='MOMENTUM_ACTIVE' and atr20: stop=round(max(low5,price-1.5*atr20),2)
    elif st_=='INSTITUTIONAL_BUILD' and atr20: stop=round(max(low5,sma20-0.5*atr20),2)

    return {'ts':ts,'ss':ss,'rp':rp,'score':pri,'setup':st_,'action':ac,
            'buy':buy,'sell':sell,'stop':stop}

# ══════════════════════════════════════════════════════════════
# LOKALE REFERENCE INDEKS PR. REGION
# ══════════════════════════════════════════════════════════════
REGION_INDEX = {
    'US':          'SPY',
    'Denmark':     '^OMXC25',
    'Sweden':      '^OMXS30',
    'Norway':      '^OSEBX',
    'Finland':     '^OMXH25',
    'Germany':     '^GDAXI',
    'UK':          '^FTSE',
    'France':      '^FCHI',
    'Netherlands': '^AEX',
    'Switzerland': '^SSMI',
    'Spain':       '^IBEX',
    'Italy':       'FTSEMIB.MI',
    'Japan':       '^N225',
    'HongKong':    '^HSI',
    'SouthKorea':  '^KS11',
    'Taiwan':      '^TWII',
    'India':       '^BSESN',
    'Canada':      '^GSPTSE',
    'Australia':   '^AXJO',
    'Brazil':      '^BVSP',
    'Israel':      '^TA125.TA',
    'Global':      'SPY',
    'Europe':      'VGK',
    'Commodities': 'GLD',
    'Crypto':      'BITO',
}

# ══════════════════════════════════════════════════════════════
# FX RATES — daglige spot-kurser til USD-normaliseret dollar_volume
# ══════════════════════════════════════════════════════════════
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_fx_rates():
    """Hent spot-kurser fra yfinance for alle ikke-USD valutaer.
    Returnerer dict: {'USD': 1.0, 'DKK': 0.143, 'EUR': 1.085, ...}
    Værdien er kurs til USD (multiplicer lokal pris med kursen for at få USD)."""
    currencies = sorted({c for c in CURRENCY_BY_REGION.values() if c != 'USD'})
    fx_tickers = [f"{c}USD=X" for c in currencies]
    rates = {'USD': 1.0}
    try:
        raw = yf.download(fx_tickers, period='5d', interval='1d',
                          group_by='ticker', auto_adjust=True, progress=False, threads=True)
        for c in currencies:
            tk = f"{c}USD=X"
            try:
                df = raw[tk] if len(fx_tickers) > 1 else raw
                series = df['Close'].dropna()
                if len(series) > 0:
                    rates[c] = float(series.iloc[-1])
            except Exception as e:
                LOG.warning(f"FX lookup failed for {c}: {e}")
    except Exception as e:
        LOG.error(f"FX batch fetch failed: {e}")
    # Fallback: hvis kritiske valutaer mangler, brug rimelige defaults
    defaults = {'DKK':0.145,'EUR':1.08,'SEK':0.095,'NOK':0.092,'GBP':1.27,
                'CHF':1.12,'JPY':0.0066,'HKD':0.128,'KRW':0.00074,'TWD':0.031,
                'INR':0.012,'CAD':0.73,'AUD':0.66,'BRL':0.20,'ILS':0.27,'TRY':0.030}
    for c, d in defaults.items():
        rates.setdefault(c, d)
    return rates

def to_usd(price_local, region, ticker, fx_rates):
    """Konvertér lokalpris til USD. GBp behandles som rå lokal valuta uden konvertering."""
    if price_local is None or price_local <= 0:
        return 0.0
    cur = CURRENCY_BY_REGION.get(region, 'USD')
    rate = fx_rates.get(cur, 1.0)
    return price_local * rate

@st.cache_data(ttl=900, show_spinner=False)
def fetch_reference_indices():
    """Hent alle lokale reference indeks til RS Trend beregning"""
    unique_indices = list(set(REGION_INDEX.values()))
    closes = {}
    # Hent i én batch – de er få nok
    try:
        raw = yf.download(unique_indices, period='3mo', interval='1d',
                         group_by='ticker', auto_adjust=True, progress=False, threads=True)
        for idx in unique_indices:
            try:
                df = (raw[idx] if len(unique_indices)>1 else raw).dropna()
                if len(df) >= 25:
                    closes[idx] = df['Close'].squeeze().values
            except: pass
    except: pass
    return closes

@st.cache_data(ttl=600, show_spinner=False)
def fetch_market_data():
    all_tickers=list(set(MACRO_TICKERS+[t for t,_ in SECTOR_ETFS]))
    rows={}
    try:
        raw=yf.download(all_tickers,period='6mo',interval='1d',
                        group_by='ticker',auto_adjust=True,progress=False)
        for t in all_tickers:
            try:
                df=(raw[t] if len(all_tickers)>1 else raw).dropna()
                if len(df)<5: continue
                c=df['Close'].squeeze().values
                p=float(c[-1]); prev=float(c[-2])
                d5=float(c[-6]) if len(c)>5 else prev
                d30=float(c[-31]) if len(c)>30 else prev
                pct1=round((p/prev-1)*100,1) if prev>0 else 0
                pct5=round((p/d5-1)*100,1) if d5>0 else 0
                pct30=round((p/d30-1)*100,1) if d30>0 else 0
                s20=float(np.mean(c[-20:])) if len(c)>=20 else p
                s60=float(np.mean(c[-60:])) if len(c)>=60 else p
                trend='UP' if p>s20>s60 else('DOWN' if p<s20<s60 else 'MIX')
                rows[t]={'price':round(p,2),'pct1':pct1,'pct5':pct5,'pct30':pct30,'trend':trend,
                         'closes': c[-60:].tolist()}  # gem til sparklines
            except: pass
    except: pass
    return rows

# ══════════════════════════════════════════════════════════════
# DOWNLOAD HELPERS — retries + Stooq failover + diagnostics
# ══════════════════════════════════════════════════════════════
def _normalize_yf_df(df):
    """Flatter MultiIndex-kolonner som yfinance nu returnerer i mange tilfælde.
    Sikrer at vi altid har simple kolonnenavne som 'Close', 'High' osv."""
    if df is None or df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        # Find det niveau som indeholder 'Close', 'High' etc. og brug det
        for level in range(df.columns.nlevels):
            vals = df.columns.get_level_values(level)
            if 'Close' in vals or 'close' in vals:
                df = df.copy()
                df.columns = vals
                break
        else:
            # Fallback: brug øverste niveau
            df = df.copy()
            df.columns = df.columns.get_level_values(0)
    # Sikr at 'Close' kolonne findes (yfinance kan have lowercase i visse tilfælde)
    if 'Close' not in df.columns and 'close' in df.columns:
        df = df.rename(columns={'close':'Close','open':'Open','high':'High',
                                'low':'Low','volume':'Volume'})
    return df

def _yf_chunk_with_retries(chunk, period='1y'):
    """Download en chunk fra yfinance med exponential backoff.
    Returnerer dict {ticker: DataFrame} for de succesfulde tickere."""
    out = {}
    attempts = CONFIG['max_retries']
    for attempt in range(attempts):
        try:
            raw = yf.download(chunk, period=period, interval='1d',
                              group_by='ticker', auto_adjust=True,
                              progress=False, threads=True)
            for t in chunk:
                try:
                    # Slice ticker-data ud — virker både for batch og single
                    if len(chunk) > 1:
                        try:
                            df = raw[t]
                        except (KeyError, TypeError):
                            continue
                    else:
                        df = raw
                    df = _normalize_yf_df(df)
                    if df is None or 'Close' not in df.columns:
                        continue
                    df = df.dropna()
                    if len(df) >= CONFIG['min_history_days']:
                        out[t] = df
                except Exception:
                    pass
            if out:                       # vi fik mindst noget — stop retries
                return out
        except Exception as e:
            LOG.warning(f"yf.download retry {attempt+1}/{attempts} failed: {e}")
        time_module.sleep(CONFIG['retry_backoff_base'] ** attempt)
    return out

def _stooq_single(ticker):
    """Stooq failover for én ticker. Mapper yfinance-suffix til stooq-konvention.
    Returnerer DataFrame eller None. Bemærk: Stooq's globale dækning er ujævn.
    Bedst på US-tickere; nordisk dækning er begrænset."""
    if not HAS_PDR: return None
    # Yfinance → Stooq mapping
    suffix_map = {
        '': '.US',     # US uden suffix
        '.L': '.UK',   # London
        '.DE': '.DE',
        '.PA': '.FR',
        '.AS': '.NL',
        '.SW': '.CH',
        '.MC': '.ES',
        '.MI': '.IT',
        '.HE': '.FI',
    }
    base = ticker
    suffix = ''
    if '.' in ticker:
        parts = ticker.rsplit('.', 1)
        base, suffix = parts[0], '.' + parts[1]
    stooq_suffix = suffix_map.get(suffix)
    if stooq_suffix is None:
        return None
    stooq_ticker = (base + stooq_suffix).lower()
    try:
        end = datetime.now()
        start = end - timedelta(days=400)
        df = pdr.DataReader(stooq_ticker, 'stooq', start, end).sort_index()
        df = _normalize_yf_df(df)
        if df is not None and 'Close' in df.columns and len(df) >= CONFIG['min_history_days']:
            return df
    except Exception as e:
        LOG.debug(f"Stooq failed for {ticker} ({stooq_ticker}): {e}")
    return None

@st.cache_data(ttl=60, show_spinner=False)
def fetch_scanner_data(universe_tuple, market_regime='NEUTRAL'):
    universe = list(universe_tuple)
    tickers = [t[0] for t in universe]
    info_map = {t[0]: t for t in universe}
    results = []
    all_raw = {}
    diagnostics = {'requested': len(tickers), 'yf_ok': 0, 'stooq_ok': 0, 'failed': []}

    # 1) Yfinance batch-download med retries
    for i in range(0, len(tickers), 50):
        chunk = tickers[i:i+50]
        got = _yf_chunk_with_retries(chunk, period='1y')
        all_raw.update(got)
        diagnostics['yf_ok'] += len(got)

    # 2) Stooq failover for de tickere yfinance ikke gav data på
    missing = [t for t in tickers if t not in all_raw]
    if missing and HAS_PDR:
        for t in missing[:50]:            # cap antal stooq-calls for hastighed
            df = _stooq_single(t)
            if df is not None:
                all_raw[t] = df
                diagnostics['stooq_ok'] += 1
    diagnostics['failed'] = [t for t in tickers if t not in all_raw]

    # Gem foreløbig diagnostik (uden dropped_reasons — den fyldes nedenfor)
    diagnostics['dropped_after_yf'] = []   # vil blive fyldt af per-ticker loopet

    # 3) FX-rates — bruges til USD-normaliseret dollar volume
    fx_rates = fetch_fx_rates()

    # 4) Sikkerhedsfilter: drop alle DataFrames der mangler 'Close' eller har for kort historik
    all_raw = {t: df for t, df in all_raw.items()
               if df is not None and 'Close' in df.columns
               and len(df) >= CONFIG['min_history_days']}

    # 5) IBD RS raw + percentile rank på tværs af hele universet
    rs_raws = {t: calc_ibd_rs_raw(df['Close'].squeeze().values) for t, df in all_raw.items()}
    valid_rs={k:v for k,v in rs_raws.items() if v is not None}
    rs_ranks=pd.Series(valid_rs).rank(pct=True).multiply(99).round(0).astype(int) if valid_rs else pd.Series()

    # Track hvorfor tickere bliver droppet i per-ticker indikator-loopet
    dropped_reasons = []   # liste af (ticker, årsag)

    for ticker,df in all_raw.items():
        try:
            info=info_map.get(ticker,(ticker,ticker,'Unknown','Unknown','CORE'))
            # Sikkerhedscheck — disse skulle aldrig fejle her, men hvis de gør, log årsagen
            if 'Close' not in df.columns:
                dropped_reasons.append((ticker, "mangler 'Close' kolonne efter normalisering"))
                continue
            c=df['Close'].squeeze().values; h=df['High'].squeeze().values
            l=df['Low'].squeeze().values;   v=df['Volume'].squeeze().values
            n=len(c)
            if n<210:
                dropped_reasons.append((ticker, f"kun {n} dages historik (kræver 210+)"))
                continue
            price=float(c[-1])
            if price<=0 or price>1_000_000:
                dropped_reasons.append((ticker, f"pris uden for range: {price}"))
                continue
            prev=float(c[-2])
            dpct=(price/prev-1)*100 if prev>0 else 0
            if abs(dpct)>50: dpct=0

            sma20v=sma(c,20); sma60v=sma(c,60); sma200v=sma(c,200)
            if any(x is None for x in [sma20v,sma60v,sma200v]):
                dropped_reasons.append((ticker, "SMA-beregning returnerede None (NaN i data?)"))
                continue
            # NaN-check på de kritiske værdier — Yahoo's danske data er ofte NaN-spækket
            if any(pd.isna(x) for x in [sma20v,sma60v,sma200v,price,prev]):
                dropped_reasons.append((ticker, "NaN i SMA eller pris (Yahoo data-kvalitet)"))
                continue
            rsiv=calc_rsi(c,14)
            atr5v=calc_atr(h,l,c,5); atr20v=calc_atr(h,l,c,20)
            high20=float(np.max(c[-20:]))
            low5v=float(np.min(l[-5:])); low20v=float(np.min(l[-20:]))
            avg_v20=float(np.mean(v[-20:])); avg_v50=float(np.mean(v[-50:])) if n>=50 else avg_v20
            last_vol=float(v[-1])
            volr=last_vol/avg_v20 if avg_v20>0 else None
            rvol50=last_vol/avg_v50 if avg_v50>0 else None

            region = info[3] if len(info)>3 else 'US'
            dolvol = avg_v20 * price
            dist_h20=(high20-price)/high20 if high20>0 else None
            hl=low5v>low20v
            lp=avg_v20>=CONFIG['min_avg_vol'] and dolvol>=CONFIG['min_dollar_vol']
            cap_r=dolvol<25_000_000
            sqz=bool(atr5v and atr20v and atr5v<atr20v*CONFIG['squeeze_factor'])
            rsi_prev5=calc_rsi(c[:-5],14) if n>19 else rsiv
            rsi_t='UP' if(rsiv and rsi_prev5 and rsiv>rsi_prev5) else('DOWN' if(rsiv and rsi_prev5 and rsiv<rsi_prev5) else 'FLAT')

            # ── RS TREND MOD LOKALT INDEKS ──
            local_idx = REGION_INDEX.get(region, 'SPY')
            # Brug lokalt indeks hvis det er i all_raw, ellers SPY, ellers FLAT
            # Eksplicit None-check — 'DataFrame or X' kaster ValueError
            ref_df = all_raw.get(local_idx)
            if ref_df is None:
                ref_df = all_raw.get('SPY')
            if ref_df is not None:
                ref_closes = ref_df['Close'].squeeze().values
                if len(ref_closes)>=21 and n>=21:
                    ref_now  = float(ref_closes[-1])
                    ref_past = float(ref_closes[-21])
                    if ref_now>0 and ref_past>0:
                        rs_now  = price / ref_now
                        rs_past = float(c[-21]) / ref_past
                        rs_t = 'UP' if rs_now>rs_past else('DOWN' if rs_now<rs_past else 'FLAT')
                    else: rs_t='FLAT'
                else: rs_t='FLAT'
            else: rs_t='FLAT'

            trend='BUY' if sma20v>sma60v else('SELL' if sma20v<sma60v else 'HOLD')
            trend200='LONG TREND' if price>sma200v else 'WEAK LONG TREND'

            ia=(trend=='BUY' and trend200=='LONG TREND' and rsiv is not None
                and 40<=rsiv<=64 and rs_t in('UP','FLAT') and rsi_t in('UP','FLAT')
                and volr is not None and volr>=0.95 and hl and dist_h20 is not None and dist_h20<=0.10)

            ifs=0
            if volr and volr>1.15: ifs+=20
            if hl: ifs+=20
            if rs_t=='UP': ifs+=20
            if price>sma20v: ifs+=20
            if rsiv and 42<=rsiv<=68: ifs+=20
            if trend200=='LONG TREND': ifs+=10
            if ia: ifs+=10
            ifs=min(ifs,100)

            ls=0
            if avg_v20>=5_000_000: ls+=40
            elif avg_v20>=1_000_000: ls+=25
            elif avg_v20>=200_000: ls+=12
            if dolvol>=100_000_000: ls+=30
            elif dolvol>=30_000_000: ls+=20
            elif dolvol>=8_000_000: ls+=10
            if volr and volr>=1.0: ls+=20
            if not cap_r: ls+=10
            ls=min(ls,100)

            # Vektoriseret SMA200-serie — O(N), ikke O(N²) som i v4
            s200arr = rolling_sma(c, 200)
            stn,stl=weinstein_stage(c,s200arr)
            rs_rank=int(rs_ranks.get(ticker,0)) if ticker in rs_ranks.index else 0
            w52h=float(np.max(c[-252:])) if n>=252 else float(np.max(c))
            w52l=float(np.min(c[-252:])) if n>=252 else float(np.min(c))
            atr_pct=atr20v/price*100 if(atr20v and price>0) else 0

            # v5: stn og rs_rank sendes ind for Stage 2 hard filter + RS-bonus
            sigres=derive_states(price,sma20v,sma60v,sma200v,rsiv,rsi_t,low5v,dist_h20,
                             volr,lp,atr20v,sqz,rs_t,hl,ia,cap_r,trend,trend200,
                             market_regime,ifs,ls,stn,rs_rank)
            results.append({
                'ticker':ticker,'name':info[1],'sector':info[2],'region':info[3],'tier':info[4] if len(info)>4 else 'CORE',
                'price':round(price,2),'dpct':round(dpct,1),
                'rsi':round(rsiv,1) if rsiv else None,'rsi_t':rsi_t,
                'sma20':round(sma20v,2),'sma60':round(sma60v,2),'sma200':round(sma200v,2),
                'trend':trend,'trend200':trend200,
                'high20':round(high20,2),'low5':round(low5v,2),
                'dh20':round(dist_h20*100,1) if dist_h20 is not None else None,
                'volr':round(volr,2) if volr else None,'rvol50':round(rvol50,2) if rvol50 else None,
                'avgvol':round(avg_v20,0),'dolvol_m':round(dolvol/1e6,1),
                'liq':'✅' if lp else '❌','lp':lp,
                'atr20':round(atr20v,2) if atr20v else None,'atr_pct':round(atr_pct,1),
                'sqz':'⚡' if sqz else '—','sqz_b':sqz,
                'rs_t':rs_t,'hl':'✅' if hl else '—','ia':'✅' if ia else '—','cap':'⚠️' if cap_r else '—',
                'ifs':ifs,'ls':ls,'stn':stn,'stage':stl,'rs_rank':rs_rank,
                'w52h':round(w52h,2),'w52l':round(w52l,2),
                'dist52':round((w52h-price)/w52h*100,1) if w52h>0 else 0,
                'ts':sigres['ts'],'ss':sigres['ss'],'rp':sigres['rp'],'score':sigres['score'],
                'setup':sigres['setup'],'buy':sigres['buy'],'sell':sigres['sell'],'stop':sigres['stop'],
                'dolvol_usd_m':round(dolvol/1e6,1),'currency':CURRENCY_BY_REGION.get(region,'USD'),
                'spark':[round(float(x),2) for x in c[-40:]],   # mini-chart data til forsiden
            })
        except Exception as e:
            # Log den faktiske exception så vi kan se hvilke tickere fejler hvorfor
            dropped_reasons.append((ticker, f"{type(e).__name__}: {str(e)[:120]}"))
            continue

    df_out=pd.DataFrame(results)
    if not df_out.empty:
        df_out=df_out.sort_values('score',ascending=False).reset_index(drop=True)

    # Gem fuld diagnostik til UI nu hvor vi har dropped_reasons
    try:
        with open(DIAGNOSTICS_FILE, 'w') as f:
            json.dump({
                'ts': datetime.now().isoformat(),
                'requested': diagnostics['requested'],
                'yf_ok': diagnostics['yf_ok'],
                'stooq_ok': diagnostics['stooq_ok'],
                'final_in_scan': len(df_out),
                'failed_count': len(diagnostics['failed']),
                'failed_tickers': diagnostics['failed'][:50],
                'dropped_after_download_count': len(dropped_reasons),
                'dropped_after_download': [
                    {'ticker': t, 'reason': r} for t, r in dropped_reasons[:80]
                ],
            }, f, indent=2)
    except Exception as e:
        LOG.warning(f"Diagnostics save failed: {e}")

    return df_out

def derive_regime(mkt,scan):
    """
    Forbedret regime-beregning:
    - Bruger BÅDE 6M trend OG daglig bevægelse
    - VIX niveau + VIX retning (faldende VIX = bullish)
    - Breadth fra scanneren
    - Kortsigtede momentum signaler
    """
    score=0
    if mkt:
        # Index trend (6M) – men vægter lavere nu
        for t,pts in [('SPY',1),('QQQ',1),('IWM',1)]:
            if t in mkt:
                tr=mkt[t]['trend']
                score+=pts if tr=='UP' else(-pts if tr=='DOWN' else 0)

        # Daglig bevægelse – er markedet grønt I DAG?
        for t,pts in [('SPY',2),('QQQ',1),('IWM',1)]:
            if t in mkt:
                pct=mkt[t].get('pct1',0) or 0
                score+=pts if pct>0.5 else(-pts if pct<-0.5 else 0)

        # 5-dages momentum
        for t,pts in [('SPY',1),('QQQ',1)]:
            if t in mkt:
                pct5=mkt[t].get('pct5',0) or 0
                score+=pts if pct5>1.0 else(-pts if pct5<-2.0 else 0)

        # VIX niveau
        if '^VIX' in mkt:
            v=mkt['^VIX']['price']
            score+=-3 if v>35 else(-2 if v>28 else(-1 if v>22 else(1 if v<18 else(2 if v<15 else 0))))

        # VIX retning – faldende VIX er bullish
        if '^VIX' in mkt:
            vix_pct=mkt['^VIX'].get('pct1',0) or 0
            score+=2 if vix_pct<-5 else(1 if vix_pct<-2 else(-1 if vix_pct>5 else 0))

    if not scan.empty:
        total=max(len(scan),1)
        a20=(scan['price']>scan['sma20']).sum()/total
        a200=(scan['price']>scan['sma200']).sum()/total
        score+=2 if a20>=0.55 else(-2 if a20<0.40 else 0)
        score+=2 if a200>=0.50 else(-2 if a200<0.35 else 0)
        buys=scan['buy'].isin(['BUY NOW','BUY BREAKOUT','STARTER BUY','BUILD POSITION']).sum()
        score+=1 if buys>=5 else(-1 if buys==0 else 0)

    if score>=6: return 'RISK_ON'
    if score<=0: return 'RISK_OFF'
    return 'NEUTRAL'

# ══════════════════════════════════════════════════════════════
# POSITIONER
# ══════════════════════════════════════════════════════════════
def load_json(f):
    try:
        return json.load(open(f)) if os.path.exists(f) else []
    except Exception:
        return []

def save_json(f, d):
    # Beskyt signals_history.json mod at blive overskrevet med tom data
    if f == SIGNALS_HISTORY_FILE and not d:
        existing = load_json(f)
        if existing:
            return  # Bevar eksisterende data — skriv aldrig tom liste til signals_history
    json.dump(d, open(f,'w'), indent=2, default=str)

def load_custom_universe():
    raw = load_json(CUSTOM_UNIVERSE_FILE)
    return [tuple(r) for r in raw]

def save_custom_universe(entries):
    save_json(CUSTOM_UNIVERSE_FILE, [list(e) for e in entries])

# ══════════════════════════════════════════════════════════════
# BACKTEST — forward-return tracker for live evidens
# ══════════════════════════════════════════════════════════════
def save_daily_signal_snapshot(scan_df):
    if scan_df is None or scan_df.empty:
        return 0
    today = datetime.now().strftime('%Y-%m-%d')
    history = load_json(SIGNALS_HISTORY_FILE)
    existing_dates = {h.get('date') for h in history}
    if today in existing_dates:
        return 0

    # Find tickers logget inden for de seneste 3 dage
    from datetime import datetime as dt, timedelta
    recent_tickers = set()
    for h in history:
        try:
            snap_date = dt.strptime(h.get('date',''), '%Y-%m-%d').date()
            days_ago = (dt.now().date() - snap_date).days
            if days_ago <= 3:
                for s in h.get('signals', []):
                    recent_tickers.add(s.get('ticker',''))
        except:
            pass
    buy_mask = scan_df['buy'].isin(
        ['BUY NOW','BUY BREAKOUT','BUILD POSITION','STARTER BUY']
    )
    buys = scan_df[buy_mask & (scan_df['sector'] != 'REF')]

    # Fjern tickers der allerede er logget inden for 3 dage
    buys = buys[~buys['ticker'].isin(recent_tickers)]
    if buys.empty:
        return 0
    snapshot = {
        'date': today,
        'signals': [
            {'ticker': r['ticker'], 'name': r['name'], 'signal': r['buy'],
             'entry_price': float(r['price']),
             'score': int(r['score']),
             'stage_num': int(r.get('stn', 0)),
             'rs_rank': int(r.get('rs_rank', 0)),
             'region': r.get('region', 'US'),
             'sector': r.get('sector', 'Unknown')}
            for _, r in buys.iterrows()
        ]
    }
    history.append(snapshot)
    save_json(SIGNALS_HISTORY_FILE, history)
    return len(snapshot['signals'])

def compute_forward_returns(scan_df):
    """For hvert historisk BUY-signal beregnes forward return ved
    20/60/120 dage (hvis så meget tid er gået). Returns ny DataFrame."""
    history = load_json(SIGNALS_HISTORY_FILE)
    if not history or scan_df is None or scan_df.empty:
        return pd.DataFrame()
    current_prices = dict(zip(scan_df['ticker'], scan_df['price']))
    today = datetime.now().date()
    rows = []
    for snap in history:
        try:
            snap_date = datetime.strptime(snap['date'], '%Y-%m-%d').date()
        except Exception:
            continue
        days_held = (today - snap_date).days
        for sig in snap.get('signals', []):
            t = sig.get('ticker')
            cp = current_prices.get(t)
            if not cp:  # None or 0 fra scan-DB — prøv live fetch
                cp = _live_price(t)
            if not cp or sig.get('entry_price', 0) <= 0:
                continue
            ep = sig['entry_price']
            ret = (cp / ep - 1) * 100
            rows.append({
                'date': snap['date'],
                'days_held': days_held,
                'ticker': t,
                'name': sig.get('name', t),
                'signal': sig.get('signal'),
                'sector': sig.get('sector', 'Unknown'),
                'entry': round(sig['entry_price'], 2),
                'current': round(cp, 2),
                'return_pct': round(ret, 2),
                'score_at_entry': sig.get('score', 0),
            })
    df_out = pd.DataFrame(rows)
    if not df_out.empty:
        df_out = df_out.sort_values('date').drop_duplicates(subset='ticker', keep='first')
        df_out = df_out.sort_values('days_held', ascending=False).reset_index(drop=True)
    return df_out

def backtest_summary(fwd_df):
    """Aggregér forward-returns til hit-rate + gennemsnit pr. horisont og signal."""
    if fwd_df.empty:
        return pd.DataFrame()
    # Behold kun første entry per ticker
    if not fwd_df.empty:
        fwd_df = fwd_df.sort_values('date').drop_duplicates(subset='ticker', keep='first')
    bins = {'1-19d':(0,19),'20-59d':(20,59),'60-119d':(60,119),'120d+':(120,99999)}
    rows = []
    for sig_name, grp in fwd_df.groupby('signal'):
        for label, (lo, hi) in bins.items():
            seg = grp[(grp['days_held'] >= lo) & (grp['days_held'] <= hi)]
            if seg.empty: continue
            rows.append({
                'Signal': sig_name,
                'Horisont': label,
                'N': len(seg),
                'Hit-rate %': round((seg['return_pct'] > 0).mean() * 100, 1),
                'Avg return %': round(seg['return_pct'].mean(), 2),
                'Median %': round(seg['return_pct'].median(), 2),
                'Best %': round(seg['return_pct'].max(), 2),
                'Worst %': round(seg['return_pct'].min(), 2),
            })
    return pd.DataFrame(rows)

@st.cache_data(ttl=300, show_spinner=False)
def _live_price(ticker):
    """Hent seneste lukkekurs via yfinance — fallback når scan-DB har price=0."""
    try:
        df = yf.download(ticker, period='5d', interval='1d', progress=False, auto_adjust=True)
        if df is None or df.empty:
            return None
        close = df['Close']
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        p = float(close.dropna().iloc[-1])
        return p if p > 0 else None
    except Exception:
        return None


@st.cache_data(ttl=60, show_spinner=False)
def lookup_ticker(ticker):
    try:
        tk = yf.Ticker(ticker)
        info = tk.info
        name   = info.get('longName') or info.get('shortName') or ticker
        sector = info.get('sector') or 'Unknown'
        country = info.get('country') or 'Unknown'
        country_map = {
            'United States':'US','Denmark':'Denmark','Sweden':'Sweden',
            'Norway':'Norway','Finland':'Finland','Germany':'Germany',
            'United Kingdom':'UK','France':'France','Netherlands':'Netherlands',
            'Switzerland':'Switzerland','Spain':'Spain','Italy':'Italy',
            'Japan':'Japan','Hong Kong':'HongKong','South Korea':'SouthKorea',
            'Taiwan':'Taiwan','Canada':'Canada','Israel':'Israel',
        }
        region = country_map.get(country, country)
        return (ticker.upper(), name, sector, region, 'EXTENDED'), None
    except Exception as e:
        return None, str(e)

def enrich_positions(positions,scan):
    if not positions: return pd.DataFrame()
    rows=[]
    for p in positions:
        t=p['ticker']; m=scan[scan['ticker']==t] if not scan.empty else pd.DataFrame()
        cp=float(m.iloc[0]['price']) if not m.empty else None
        if not cp:  # None eller 0 — prøv live fetch
            cp = _live_price(t)
        if not cp:
            cp = p['entry_price']  # sæt entry som sidst kendte pris
        rows.append({'TICKER':t,'NAVN':p.get('name',t),'ENTRY':p['entry_price'],'NU':round(cp,2),
                     'PnL%':round((cp/p['entry_price']-1)*100,2),
                     'PnLkr':round((cp-p['entry_price'])*p['shares'],2),
                     'AKTIER':p['shares'],
                     'STOP':m.iloc[0]['stop'] if not m.empty else '—',
                     'SIGNAL':m.iloc[0]['buy'] if not m.empty else '—',
                     'RS':m.iloc[0]['rs_rank'] if not m.empty else '—',
                     'SCORE':m.iloc[0]['score'] if not m.empty else '—',
                     'DATO':p.get('date','—')})
    df=pd.DataFrame(rows)
    return df.sort_values('PnL%',ascending=False) if not df.empty else df

# ══════════════════════════════════════════════════════════════
# CHART
# ══════════════════════════════════════════════════════════════
@st.cache_data(ttl=900, show_spinner=False)
def get_chart_data(ticker):
    return yf.download(ticker,period='1y',interval='1d',auto_adjust=True,progress=False).dropna()

def make_sparkline(values, color='#00ff88', height=40):
    """Mini sparkline chart til market pulse"""
    if values is None or len(values) < 2: return None
    v = list(values[-30:])  # seneste 30 dage
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        y=v, mode='lines',
        line=dict(color=color, width=1.5),
        fill='tozeroy',
        fillcolor=f'rgba({int(color[1:3],16)},{int(color[3:5],16)},{int(color[5:7],16)},0.08)',
        hoverinfo='skip'
    ))
    fig.update_layout(
        height=height, margin=dict(l=0,r=0,t=0,b=0),
        plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        showlegend=False
    )
    return fig

def make_vix_gauge(vix_val):
    """VIX Fear/Greed gauge"""
    if vix_val is None: vix_val = 20
    color = '#ff3333' if vix_val>28 else ('#ffaa00' if vix_val>20 else '#00ff88')
    label = 'EKSTREM FRYGT' if vix_val>35 else ('FRYGT' if vix_val>25 else ('NEUTRAL' if vix_val>18 else ('GRÅDIGHED' if vix_val>15 else 'EKSTREM GRÅDIGHED')))
    fig = go.Figure(go.Indicator(
        mode='gauge+number',
        value=vix_val,
        number={'font':{'color':color,'family':'Orbitron','size':22},'suffix':''},
        gauge={
            'axis':{'range':[10,50],'tickcolor':'#333','tickfont':{'color':'#333','size':8},'tickvals':[15,20,25,30,40]},
            'bar':{'color':color,'thickness':0.6},
            'bgcolor':'#0d0d0d','bordercolor':'#1a1a1a','borderwidth':1,
            'steps':[
                {'range':[10,18],'color':'#002210'},
                {'range':[18,25],'color':'#111'},
                {'range':[25,35],'color':'#1a0a00'},
                {'range':[35,50],'color':'#1a0000'},
            ],
            'threshold':{'line':{'color':color,'width':2},'thickness':0.8,'value':vix_val}
        },
        title={'text':f'VIX FEAR/GREED<br><span style="font-size:0.65rem;color:#555">{label}</span>',
               'font':{'color':'#555','family':'IBM Plex Mono','size':9}},
    ))
    fig.update_layout(
        plot_bgcolor='#0d0d0d', paper_bgcolor='#0d0d0d',
        height=150, margin=dict(l=10,r=10,t=35,b=5),
        font=dict(color='#aaa')
    )
    return fig

def make_breadth_chart(scan_df):
    """Markedsbreadth donut – fordeling af signaler"""
    if scan_df.empty: return None
    clean = scan_df[scan_df['sector']!='REF']
    counts = {
        'BUY NOW':    (clean['buy']=='BUY NOW').sum(),
        'BREAKOUT':   (clean['buy']=='BUY BREAKOUT').sum(),
        'BUILD':      clean['buy'].isin(['BUILD POSITION','STARTER BUY']).sum(),
        'WATCHLIST':  (clean['buy']=='WATCHLIST').sum(),
        'REDUCE':     (clean['sell']=='REDUCE').sum(),
        'EXIT':       (clean['sell']=='EXIT').sum(),
    }
    labels = list(counts.keys())
    values = list(counts.values())
    colors = ['#00ff88','#00cc66','#0066cc','#222','#cc4400','#cc0000']
    fig = go.Figure(go.Pie(
        labels=labels, values=values,
        hole=0.65,
        marker=dict(colors=colors, line=dict(color='#0d0d0d',width=1)),
        textfont=dict(size=9, family='IBM Plex Mono', color='#888'),
        textposition='outside',
        hovertemplate='<b>%{label}</b>: %{value}<extra></extra>',
    ))
    total = sum(values)
    buy_total = counts['BUY NOW']+counts['BREAKOUT']+counts['BUILD']
    fig.add_annotation(
        text=f'<b style="font-size:16px">{buy_total}</b><br><span style="font-size:8px;color:#555">BUY</span>',
        x=0.5, y=0.5, showarrow=False,
        font=dict(color='#00ff88', family='Orbitron', size=14)
    )
    fig.update_layout(
        plot_bgcolor='#0d0d0d', paper_bgcolor='#0d0d0d',
        height=160, margin=dict(l=10,r=10,t=10,b=10),
        showlegend=False, font=dict(color='#aaa')
    )
    return fig

def make_score_histogram(scan_df):
    """Score distribution histogram"""
    if scan_df.empty: return None
    clean = scan_df[scan_df['sector']!='REF']['score'].dropna()
    fig = go.Figure(go.Histogram(
        x=clean, nbinsx=20,
        marker=dict(
            color=clean,
            colorscale=[[0,'#cc0000'],[0.5,'#ffaa00'],[1,'#00ff88']],
            line=dict(color='#0d0d0d',width=0.5)
        ),
    ))
    fig.update_layout(
        plot_bgcolor='#0d0d0d', paper_bgcolor='#0d0d0d',
        height=100, margin=dict(l=5,r=5,t=5,b=20),
        xaxis=dict(gridcolor='#111',color='#333',tickfont=dict(color='#333',size=8),title=''),
        yaxis=dict(gridcolor='#111',color='#333',tickfont=dict(color='#333',size=8)),
        bargap=0.1, font=dict(color='#aaa'),
        showlegend=False
    )
    return fig

def plot_chart(ticker,df,signal=''):
    if df.empty: return go.Figure()
    c=df['Close'].squeeze().values; h=df['High'].squeeze().values
    l=df['Low'].squeeze().values;   o=df['Open'].squeeze().values
    v=df['Volume'].squeeze().values; idx=df.index
    s20=pd.Series(c).rolling(20).mean().values
    s60=pd.Series(c).rolling(60).mean().values
    s200=pd.Series(c).rolling(200).mean().values
    d=pd.Series(c).diff(); g=d.clip(lower=0).rolling(14).mean(); ls_=(-d.clip(upper=0)).rolling(14).mean()
    rsi=(100-100/(1+g/ls_.replace(0,np.nan))).values
    fig=make_subplots(rows=3,cols=1,row_heights=[0.55,0.2,0.25],shared_xaxes=True,vertical_spacing=0.02)
    fig.add_trace(go.Candlestick(x=idx,open=o,high=h,low=l,close=c,name=ticker,
        increasing_line_color='#00ff41',decreasing_line_color='#ff3333',
        increasing_fillcolor='rgba(0,255,65,0.15)',decreasing_fillcolor='rgba(255,51,51,0.15)'),row=1,col=1)
    for arr,n,col,w in [(s20,'SMA20','#ffaa00',1.5),(s60,'SMA60','#0088ff',1.5),(s200,'SMA200','#cc44ff',2)]:
        fig.add_trace(go.Scatter(x=idx,y=arr,name=n,line=dict(color=col,width=w)),row=1,col=1)
    vc=['rgba(0,255,65,0.5)' if c[i]>=o[i] else 'rgba(255,51,51,0.5)' for i in range(len(c))]
    fig.add_trace(go.Bar(x=idx,y=v,marker_color=vc,showlegend=False),row=2,col=1)
    fig.add_trace(go.Scatter(x=idx,y=rsi,line=dict(color='#ffaa00',width=2),name='RSI'),row=3,col=1)
    fig.add_hline(y=70,line_dash='dash',line_color='rgba(255,51,51,0.5)',row=3,col=1)
    fig.add_hline(y=30,line_dash='dash',line_color='rgba(0,255,65,0.5)',row=3,col=1)
    fig.add_hline(y=50,line_dash='dot',line_color='rgba(255,255,255,0.15)',row=3,col=1)
    ax=dict(gridcolor='rgba(0,255,65,0.08)',zerolinecolor='rgba(0,255,65,0.08)',color='#008f23',tickfont=dict(color='#008f23'))
    fig.update_layout(plot_bgcolor='#000000',paper_bgcolor='#000a00',
        font=dict(color='#00ff41',family='Share Tech Mono',size=11),
        legend=dict(bgcolor='#000a00',bordercolor='rgba(0,255,65,0.2)',orientation='h',y=1.02,font=dict(size=9)),
        height=600,margin=dict(l=55,r=15,t=25,b=15),xaxis_rangeslider_visible=False,
        title=dict(text=f'[ {ticker} ] {signal}',font=dict(color='#00ff41',family='Orbitron',size=11)),
        xaxis=ax,xaxis2=ax,xaxis3=ax,yaxis=ax,yaxis2=ax,yaxis3={**ax,'range':[0,100]})
    return fig

def plot_sector_etf_chart(mkt):
    if not mkt: return go.Figure()
    sectors=[]; scores=[]; colors_=[]
    for etf,name in SECTOR_ETFS:
        if etf in mkt:
            d=mkt[etf]; pct=d['pct1']
            sectors.append(name); scores.append(pct)
            colors_.append('#00ff41' if pct>0 else '#ff3333')
    if not sectors: return go.Figure()
    order=sorted(range(len(scores)),key=lambda i:scores[i])
    fig=go.Figure(go.Bar(
        x=[scores[i] for i in order],
        y=[sectors[i] for i in order],
        orientation='h',
        marker_color=[colors_[i] for i in order],
        text=[f"{scores[i]:+.1f}%" for i in order],
        textposition='outside',textfont=dict(color='#00ff41',family='Share Tech Mono',size=10),
    ))
    fig.update_layout(plot_bgcolor='#000000',paper_bgcolor='#000a00',
        font=dict(color='#00ff41',family='Share Tech Mono',size=10),
        xaxis=dict(gridcolor='rgba(0,255,65,0.1)',zerolinecolor='rgba(0,255,65,0.3)',title='1D %'),
        yaxis=dict(gridcolor='rgba(0,255,65,0.08)'),
        height=max(350,len(sectors)*28),margin=dict(l=130,r=60,t=20,b=30),
        title=dict(text='SEKTOR PERFORMANCE 1D',font=dict(color='#00ff41',family='Orbitron',size=11)))
    return fig

# ══════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════
def pct_html(v, large=False):
    sz = '0.95rem' if large else '0.74rem'
    fw = '700' if large else '600'
    if v is None: return f'<span style="color:#444;font-size:{sz}">—</span>'
    if v>0: return f'<span style="color:#00ff88;font-size:{sz};font-weight:{fw};font-family:IBM Plex Mono,monospace">+{v:.1f}%</span>'
    if v<0: return f'<span style="color:#ff3333;font-size:{sz};font-weight:{fw};font-family:IBM Plex Mono,monospace">{v:.1f}%</span>'
    return f'<span style="color:#666;font-size:{sz};font-family:IBM Plex Mono,monospace">{v:.1f}%</span>'

def trend_badge(t):
    if t=='UP':   return '<span class="tr-up">▲UP</span>'
    if t=='DOWN': return '<span class="tr-dn">▼DN</span>'
    return '<span class="tr-mix">◆</span>'

def sig_block(val):
    """Bloomberg-style farveblok for signal"""
    m = {
        'BUY NOW':         'sig-buynow',
        'BUY BREAKOUT':    'sig-breakout',
        'BUILD POSITION':  'sig-build',
        'STARTER BUY':     'sig-starter',
        'EXTENDED — WAIT': 'sig-extended',
        'REDUCE':          'sig-reduce',
        'EXIT':            'sig-exit',
        'HOLD':            'sig-watch',
        'WATCHLIST':       'sig-watch',
    }
    cls = m.get(val,'sig-watch')
    short = {
        'BUY NOW':'BUY NOW','BUY BREAKOUT':'BREAKOUT',
        'BUILD POSITION':'BUILD','STARTER BUY':'STARTER',
        'EXTENDED — WAIT':'EXTENDED','REDUCE':'REDUCE',
        'EXIT':'EXIT','HOLD':'HOLD','WATCHLIST':'WATCH',
    }.get(val, val[:8])
    return f'<span class="sig-block {cls}">{short}</span>'

def sig_style(val):
    """For dataframe styling"""
    return {
        'BUY NOW':         'background:#00ff88;color:#000;font-weight:700',
        'BUY BREAKOUT':    'background:#00cc66;color:#000;font-weight:700',
        'BUILD POSITION':  'background:#0066cc;color:#fff',
        'STARTER BUY':     'background:#004499;color:#aad4ff',
        'EXTENDED — WAIT': 'background:#cc8800;color:#000',
        'REDUCE':          'background:#cc4400;color:#fff;font-weight:600',
        'EXIT':            'background:#cc0000;color:#fff;font-weight:700',
        'HOLD':            'background:#1a1a1a;color:#444',
        'WATCHLIST':       'background:#111;color:#333',
    }.get(val,'')

def pnl_style(val):
    if isinstance(val,(int,float)):
        return 'color:#00ff88;font-weight:700' if val>0 else('color:#ff3333;font-weight:700' if val<0 else '')
    return ''

def regime_html(r):
    cls={'RISK_ON':'bb-regime-on','RISK_OFF':'bb-regime-off','NEUTRAL':'bb-regime-neu'}.get(r,'bb-regime-neu')
    txt={'RISK_ON':'▲ RISK ON','RISK_OFF':'▼ RISK OFF','NEUTRAL':'◆ NEUTRAL'}.get(r,r)
    return f'<span class="{cls}">{txt}</span>'

def sek_color(pct):
    """Sektor heatmap bagfarve baseret på %"""
    if pct is None: return '#111','#444'
    if pct >= 2.0:  return '#003322','#00ff88'
    if pct >= 1.0:  return '#002218','#00cc66'
    if pct >= 0.3:  return '#001510','#009944'
    if pct >= 0.0:  return '#0d0d0d','#446644'
    if pct >= -0.3: return '#150a0a','#884444'
    if pct >= -1.0: return '#1a0000','#cc3333'
    if pct >= -2.0: return '#220000','#ff3333'
    return '#2a0000','#ff0000'

# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════
# v6 FORSIDE-HELPERS — treemap, market internals, earnings
# ══════════════════════════════════════════════════════════════
def make_market_treemap(scan_df, top_n=120):
    """Finviz/Bloomberg-style heatmap: sektor -> aktie, størrelse=dollar volume,
    farve=dagsbevægelse. Kun de mest likvide navne vises for at undgå rod."""
    if scan_df is None or scan_df.empty:
        return None
    clean = scan_df[scan_df['sector'] != 'REF'].copy()
    if clean.empty:
        return None
    volcol = 'dolvol_usd_m' if 'dolvol_usd_m' in clean.columns else 'dolvol_m'
    clean[volcol] = pd.to_numeric(clean[volcol], errors='coerce').fillna(0.0)
    clean = clean.nlargest(top_n, volcol)
    sectors = sorted(clean['sector'].unique().tolist())
    labels   = list(sectors) + clean['ticker'].tolist()
    parents  = [''] * len(sectors) + clean['sector'].tolist()
    # Sektor-bokse får værdi 0 (Plotly summerer børnene); aktier får deres volumen
    values   = [0] * len(sectors) + [max(v, 0.1) for v in clean[volcol].tolist()]
    # Farve efter dagsbevægelse; sektorer får neutral
    sec_color = [0.0] * len(sectors)
    stock_color = clean['dpct'].clip(-5, 5).tolist()
    colors   = sec_color + stock_color
    # Custom tekst på aktie-bokse
    sec_text = [''] * len(sectors)
    stock_text = [f"{r['dpct']:+.1f}%" for _, r in clean.iterrows()]
    text = sec_text + stock_text
    fig = go.Figure(go.Treemap(
        labels=labels, parents=parents, values=values,
        text=text, texttemplate="<b>%{label}</b><br>%{text}",
        textfont=dict(family='IBM Plex Mono', size=11),
        marker=dict(
            colors=colors,
            colorscale=[[0,'#cc0000'],[0.5,'#0d0d0d'],[1,'#00ff88']],
            cmid=0, cmin=-5, cmax=5,
            line=dict(color='#000', width=1),
        ),
        tiling=dict(packing='squarify'),
        hovertemplate='<b>%{label}</b><br>%{text}<extra></extra>',
        branchvalues='remainder',
    ))
    fig.update_layout(
        plot_bgcolor='#0a0a0a', paper_bgcolor='#0a0a0a',
        height=420, margin=dict(l=2, r=2, t=2, b=2),
        font=dict(color='#ddd'),
    )
    return fig

def compute_market_internals(scan_df):
    """Beregn markedets indre tilstand fra scan-data."""
    if scan_df is None or scan_df.empty:
        return None
    c = scan_df[scan_df['sector'] != 'REF']
    total = max(len(c), 1)
    adv = int((c['dpct'] > 0).sum())
    dec = int((c['dpct'] < 0).sum())
    unch = total - adv - dec
    new_high = int((c['dist52'] <= 2).sum()) if 'dist52' in c else 0
    # nye lows: tæt på 52-ugers low (inden for 3%)
    if {'w52l','price'}.issubset(c.columns):
        new_low = int((((c['price'] - c['w52l']) / c['w52l'] * 100) <= 3).sum())
    else:
        new_low = 0
    c20 = c[['price','sma20']].dropna()
    over20  = int((c20['price'] > c20['sma20']).sum())
    c200 = c[['price','sma200']].dropna()
    over200 = int((c200['price'] > c200['sma200']).sum())
    stage2  = int((c['stn'] == 2).sum())
    rsi_hot = int((c['rsi'] > 70).sum()) if 'rsi' in c else 0
    rsi_cold = int((c['rsi'] < 30).sum()) if 'rsi' in c else 0
    return {
        'total': total, 'adv': adv, 'dec': dec, 'unch': unch,
        'ad_ratio': round(adv / max(dec, 1), 2),
        'new_high': new_high, 'new_low': new_low,
        'over20_pct': round(over20 / total * 100),
        'over200_pct': round(over200 / total * 100),
        'stage2_pct': round(stage2 / total * 100),
        'rsi_hot': rsi_hot, 'rsi_cold': rsi_cold,
    }

def make_advance_decline_bar(internals):
    """Vandret stablet bar: advancere vs declinere."""
    if not internals:
        return None
    adv, dec, unch = internals['adv'], internals['dec'], internals['unch']
    fig = go.Figure()
    fig.add_trace(go.Bar(y=['A/D'], x=[adv], orientation='h', name='Adv',
                         marker_color='#00ff88', text=f"{adv}", textposition='inside',
                         textfont=dict(color='#000', family='IBM Plex Mono', size=12)))
    fig.add_trace(go.Bar(y=['A/D'], x=[unch], orientation='h', name='Flat',
                         marker_color='#333', text=f"{unch}" if unch else '',
                         textposition='inside', textfont=dict(color='#aaa', size=10)))
    fig.add_trace(go.Bar(y=['A/D'], x=[dec], orientation='h', name='Dec',
                         marker_color='#ff3333', text=f"{dec}", textposition='inside',
                         textfont=dict(color='#fff', family='IBM Plex Mono', size=12)))
    fig.update_layout(
        barmode='stack', height=70, margin=dict(l=4, r=4, t=4, b=4),
        plot_bgcolor='#0a0a0a', paper_bgcolor='#0a0a0a', showlegend=False,
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        font=dict(color='#aaa'),
    )
    return fig

@st.cache_data(ttl=21600, show_spinner=False)
def fetch_earnings_calendar(tickers_tuple):
    """Best-effort earnings-datoer fra yfinance for en lille ticker-liste.
    Cached 6 timer. yfinance er ustabil her, så alt er pakket i try/except."""
    out = []
    today = datetime.now().date()
    for t in list(tickers_tuple)[:25]:
        try:
            cal = yf.Ticker(t).calendar
            ed = None
            if isinstance(cal, dict):
                vals = cal.get('Earnings Date')
                if vals:
                    ed = vals[0] if isinstance(vals, list) else vals
            if ed is not None:
                ed_date = ed.date() if hasattr(ed, 'date') else ed
                days = (ed_date - today).days
                if -5 <= days <= 90:
                    out.append({'ticker': t, 'date': str(ed_date), 'days': days})
        except Exception:
            pass
    return sorted(out, key=lambda x: x['days'])


def refresh_scan_to_db():
    """Rydder Streamlit-cachen og genindlæser seneste snapshot fra DB.
    Worker (scan_runner.py) er ansvarlig for selve datahentning via FMP.
    OPDATER-knappen opdaterer kun visningen — ikke datakilden."""
    st.cache_data.clear()
    _scan = sdb.read_scan_results()
    return _scan

def main():
    positions=load_json(POSITIONS_FILE)
    watchlist=load_json(WATCHLIST_FILE)
    custom_entries = load_custom_universe()
    existing_tickers = {t[0] for t in UNIVERSE}
    full_universe = UNIVERSE + [e for e in custom_entries if e[0] not in existing_tickers]
    show_wl = False
    only_s2 = False

    # ── FASE 1: DB-FIRST DATALAESNING ──
    # Beregning er afkoblet fra visning. UI'et laeser det seneste snapshot
    # fra SQLite (ojeblikkeligt). Vi beregner KUN hvis databasen er kold
    # (intet snapshot endnu) eller hvis brugeren trykker OPDATER.
    sdb.init_db()
    mkt=fetch_market_data()
    scan=sdb.read_scan_results()
    scan_meta=sdb.get_scan_meta()
    if scan.empty:
        prog=st.progress(0,text="`[ INIT ] Kold database — beregner forste snapshot...`")
        regime=derive_regime(mkt,pd.DataFrame())
        prog.progress(22,text="`[ SCAN ] Scanner univers...`")
        scan=fetch_scanner_data(tuple(full_universe),regime)
        regime=derive_regime(mkt,scan)
        sdb.write_scan_results(scan,regime,source='ui-cold')
        scan_meta=sdb.get_scan_meta()
        prog.progress(100,text="`[ OK ] Klar`")
        prog.empty()
    else:
        # Varm laesning: brug gemt regime, undga genberegning.
        regime=(scan_meta or {}).get('regime') or derive_regime(mkt,scan)

    # Opdater sidebar filtre - ikke længere nødvendige her
    pass

    vix_price=mkt.get('^VIX',{}).get('price',None)
    vix_pct=mkt.get('^VIX',{}).get('pct1',None)

    # ── HEADER BAR ──
    if not scan.empty:
        buy_now  = (scan['buy']=='BUY NOW').sum()
        buy_br   = (scan['buy']=='BUY BREAKOUT').sum()
        build    = scan['buy'].isin(['STARTER BUY','BUILD POSITION']).sum()
        exits    = (scan['sell']=='EXIT').sum()
        s2       = (scan['stn']==2).sum()
        rs80     = (scan['rs_rank']>=80).sum()
        sqzn     = scan['sqz_b'].sum()
        ian      = (scan['ia']=='✅').sum()
    else:
        buy_now=buy_br=build=exits=s2=rs80=sqzn=ian=0

    spy_d  = mkt.get('SPY',{})
    qqq_d  = mkt.get('QQQ',{})
    vix_str = f"{vix_price:.1f}" if vix_price else "—"
    vix_col = '#ff3333' if vix_price and vix_price>28 else ('#ffaa00' if vix_price and vix_price>20 else '#00ff88')

    # Børsstatus som kompakt strip
    exch_html = ''
    for name, info in EXCHANGES.items():
        s  = get_exchange_status(info)
        tz = pytz.timezone(info['tz'])
        lt = datetime.now(tz).strftime('%H:%M')
        col = '#00ff88' if s=='ÅBEN' else ('#ffaa00' if s=='PRE' else '#333')
        dot = '●' if s=='ÅBEN' else ('◑' if s=='PRE' else '○')
        exch_html += f'<span style="color:{col};font-size:0.65rem;font-family:IBM Plex Mono,monospace;margin-right:12px">{info["flag"]} {dot} {name} {lt}</span>'

    kpi_cells = [
        ("REGIME",   regime_html(regime), ''),
        ("VIX",      f'<span style="color:{vix_col};font-family:Orbitron,monospace;font-weight:700;font-size:1rem">{vix_str}</span>', pct_html(vix_pct)),
        ("S&P 500",  f'<span style="color:#fff;font-family:Orbitron,monospace;font-size:0.9rem">{spy_d.get("price","—")}</span>', pct_html(spy_d.get('pct1'))),
        ("NASDAQ",   f'<span style="color:#fff;font-family:Orbitron,monospace;font-size:0.9rem">{qqq_d.get("price","—")}</span>', pct_html(qqq_d.get('pct1'))),
        ("AKTIER",   f'<span style="color:#fff;font-family:Orbitron,monospace;font-weight:700;font-size:1rem">{len(scan) if not scan.empty else 0}</span>', ''),
        ("BUY NOW",  f'<span style="color:#00ff88;font-family:Orbitron,monospace;font-weight:700;font-size:1.1rem">{buy_now}</span>', ''),
        ("BREAKOUT", f'<span style="color:#00cc66;font-family:Orbitron,monospace;font-weight:700;font-size:1.1rem">{buy_br}</span>', ''),
        ("BUILD",    f'<span style="color:#4488ff;font-family:Orbitron,monospace;font-weight:700;font-size:1.1rem">{build}</span>', ''),
        ("EXIT",     f'<span style="color:#ff3333;font-family:Orbitron,monospace;font-weight:700;font-size:1.1rem">{exits}</span>', ''),
        ("STAGE 2",  f'<span style="color:#aaa;font-family:Orbitron,monospace;font-size:1rem">{s2}</span>', ''),
        ("SQUEEZE⚡", f'<span style="color:#aaa;font-family:Orbitron,monospace;font-size:1rem">{sqzn}</span>', ''),
        ("RS>80",    f'<span style="color:#aaa;font-family:Orbitron,monospace;font-size:1rem">{rs80}</span>', ''),
    ]
    cells_html = ''.join([
        f'<div class="kpi-cell"><div class="kpi-label">{lbl}</div><div class="kpi-value">{val} {sub}</div></div>'
        for lbl,val,sub in kpi_cells
    ])

    _c1, _c2 = st.columns([11, 1])
    with _c1:
        if scan_meta and scan_meta.get('ts'):
            _ts=str(scan_meta['ts'])[:19].replace('T',' ')
            _src=scan_meta.get('source','—')
            st.markdown(
                f'<span style="font-family:IBM Plex Mono,monospace;font-size:0.7rem;color:#666">'
                f'◷ Snapshot: {_ts} · {scan_meta.get("n_rows",len(scan))} aktier · kilde: {_src} '
                f'· tryk OPDATER for at genberegne</span>',
                unsafe_allow_html=True)
    with _c2:
        if st.button("⟳ OPDATER", use_container_width=True):
            with st.spinner("Genberegner og gemmer snapshot..."):
                refresh_scan_to_db()
            st.rerun()

    st.markdown(
        f'<div style="background:#000;border-bottom:2px solid #00ff88;margin-bottom:4px">'
        f'<div style="display:flex;justify-content:space-between;align-items:center;padding:4px 12px;border-bottom:1px solid #0d0d0d">'
        f'<span style="font-family:Orbitron,monospace;font-size:0.85rem;color:#fff;font-weight:900;letter-spacing:3px">▸ TRADING TERMINAL PRO</span>'
        f'<span>{exch_html}</span>'
        f'</div>'
        f'<div class="kpi-strip">{cells_html}</div>'
        f'</div>',
        unsafe_allow_html=True
    )

    # v5: Gem dagens signaler til backtest-historikken (idempotent, max 1/dag)
    try:
        n_saved = save_daily_signal_snapshot(scan)
        if n_saved > 0:
            LOG.info(f"Backtest snapshot saved with {n_saved} signals")
    except Exception as e:
        LOG.warning(f"Snapshot save failed: {e}")

    # TABS
    tabs=st.tabs(["▸ FORSIDE","▸ SCANNER","▸ BENCHMARK","▸ POSITIONER","▸ WATCHLIST","▸ S1 PIPELINE","▸ CHARTS","▸ RS ANALYSE","▸ BACKTEST","▸ SIGNAL LOG","▸ DIAGNOSTIK","▸ PLAYBOOK"])
    tab1,tab2,tab3,tab4,tab5,tab_s1,tab6,tab7,tab_bt,tab_siglog,tab_diag,tab8=tabs

    # ═══════════════════════════════════════════
    # TAB 1: FORSIDE – BLOOMBERG STYLE
    # ═══════════════════════════════════════════
    with tab1:
        # ── SVG sparkline helper (hurtig, tæt, Bloomberg-stil) ──
        def _svg_spark(vals, w=120, h=30):
            if not vals or len(vals) < 2:
                return ''
            lo, hi = min(vals), max(vals)
            rng = (hi - lo) or 1
            n = len(vals)
            pts = []
            for i, v in enumerate(vals):
                x = i / (n - 1) * (w - 2) + 1
                y = h - 2 - (v - lo) / rng * (h - 4)
                pts.append(f"{x:.1f},{y:.1f}")
            up = vals[-1] >= vals[0]
            col = '#00ff88' if up else '#ff3333'
            fill = 'rgba(0,255,136,0.10)' if up else 'rgba(255,51,51,0.10)'
            poly = ' '.join(pts)
            area = f"1,{h-1} " + poly + f" {w-1},{h-1}"
            return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" style="display:block">'
                    f'<polygon points="{area}" fill="{fill}" stroke="none"/>'
                    f'<polyline points="{poly}" fill="none" stroke="{col}" stroke-width="1.4"/>'
                    f'</svg>')

        if scan.empty:
            st.warning("Ingen scan-data tilgængelig. Tryk ⟳ OPDATER eller tjek DIAGNOSTIK-tabben.")
        else:
            clean = scan[scan['sector'] != 'REF']
            internals = compute_market_internals(scan)

            # ═══ RÆKKE 1: MARKET INTERNALS STRIP ═══
            if internals:
                ad = internals['ad_ratio']
                ad_col = '#00ff88' if ad >= 1.5 else ('#ff3333' if ad <= 0.67 else '#ffaa00')
                nh, nl = internals['new_high'], internals['new_low']
                nh_col = '#00ff88' if nh >= nl else '#ff3333'
                o20, o200 = internals['over20_pct'], internals['over200_pct']
                o20_col = '#00ff88' if o20 >= 55 else ('#ff3333' if o20 <= 40 else '#ffaa00')
                o200_col = '#00ff88' if o200 >= 50 else ('#ff3333' if o200 <= 35 else '#ffaa00')
                s2 = internals['stage2_pct']
                cells = [
                    ("A/D RATIO", f'<span style="color:{ad_col}">{ad:.2f}</span>',
                     f'<span style="color:#00ff88">{internals["adv"]}</span> / <span style="color:#ff3333">{internals["dec"]}</span>'),
                    ("NEW HIGH / LOW", f'<span style="color:{nh_col}">{nh}</span> / <span style="color:#ff3333">{nl}</span>', '52w'),
                    ("OVER SMA20", f'<span style="color:{o20_col}">{o20}%</span>', f'{internals["total"]} aktier'),
                    ("OVER SMA200", f'<span style="color:{o200_col}">{o200}%</span>', 'langsigtet'),
                    ("STAGE 2", f'<span style="color:#00ff88">{s2}%</span>', 'i uptrend'),
                    ("RSI >70 / <30", f'<span style="color:#ffaa00">{internals["rsi_hot"]}</span> / <span style="color:#4488ff">{internals["rsi_cold"]}</span>', 'overbought/sold'),
                ]
                strip = '<div style="display:flex;gap:0;border:1px solid #1a1a1a;margin-bottom:6px">'
                for lbl, val, sub in cells:
                    strip += (f'<div style="flex:1;padding:5px 10px;border-right:1px solid #1a1a1a;background:#0d0d0d">'
                              f'<div style="color:#555;font-size:0.56rem;text-transform:uppercase;letter-spacing:1px;font-family:IBM Plex Mono,monospace">{lbl}</div>'
                              f'<div style="font-size:1.05rem;font-family:Orbitron,monospace;font-weight:700">{val}</div>'
                              f'<div style="color:#444;font-size:0.55rem;font-family:IBM Plex Mono,monospace">{sub}</div>'
                              f'</div>')
                strip += '</div>'
                st.markdown(strip, unsafe_allow_html=True)
                fig_ad = make_advance_decline_bar(internals)
                if fig_ad:
                    st.plotly_chart(fig_ad, use_container_width=True, config={'displayModeBar': False})

            # ═══ RÆKKE 2: TOP SETUPS (mini-charts) | POSITIONER + MOVERS ═══
            col_setups, col_side = st.columns([2, 1])

            with col_setups:
                cands = clean[clean['buy'].isin(['BUY NOW','BUY BREAKOUT','BUILD POSITION','STARTER BUY'])].head(14)
                st.markdown(f'<div class="bb-panel-hdr">TOP SETUPS <span>{len(cands)} SIGNALER</span></div>', unsafe_allow_html=True)
                if cands.empty:
                    st.markdown('<div style="padding:14px 8px;color:#888;font-family:IBM Plex Mono,monospace;font-size:0.8rem">⚠ INGEN AKTIVE BUY-SIGNALER — markedet er i RISK_OFF eller ingen Stage 2-setups.</div>', unsafe_allow_html=True)
                else:
                    rows = ('<div style="display:grid;grid-template-columns:64px 1fr 70px 56px 44px 38px 130px 96px;'
                            'gap:4px;padding:3px 8px;background:#0a0a0a;border-bottom:1px solid #222;'
                            'font-family:IBM Plex Mono,monospace;font-size:0.56rem;color:#555;text-transform:uppercase;letter-spacing:1px">'
                            '<span>Ticker</span><span>Navn</span><span style="text-align:right">Pris</span>'
                            '<span style="text-align:right">1D</span><span style="text-align:right">RS</span>'
                            '<span style="text-align:right">STG</span><span style="text-align:center">40D</span>'
                            '<span style="text-align:center">Signal</span></div>')
                    for _, r in cands.iterrows():
                        pct = r['dpct']
                        pcol = '#00ff88' if pct > 0 else ('#ff3333' if pct < 0 else '#666')
                        spark = _svg_spark(r.get('spark') or [])
                        rscol = '#00ff88' if r['rs_rank'] >= 80 else ('#ffaa00' if r['rs_rank'] >= 60 else '#666')
                        rows += (
                            f'<div style="display:grid;grid-template-columns:64px 1fr 70px 56px 44px 38px 130px 96px;gap:4px;'
                            f'padding:4px 8px;border-bottom:1px solid #111;align-items:center;font-family:IBM Plex Mono,monospace;font-size:0.74rem">'
                            f'<span style="color:#fff;font-weight:700">{r["ticker"]}</span>'
                            f'<span style="color:#555;overflow:hidden;white-space:nowrap;font-size:0.67rem">{r["name"]}</span>'
                            f'<span style="color:#ccc;text-align:right">{r["price"]:.2f}</span>'
                            f'<span style="color:{pcol};text-align:right;font-weight:600">{pct:+.1f}%</span>'
                            f'<span style="color:{rscol};text-align:right;font-weight:700">{int(r["rs_rank"])}</span>'
                            f'<span style="color:#888;text-align:right;font-size:0.62rem">{r["stage"]}</span>'
                            f'<span style="display:flex;justify-content:center">{spark}</span>'
                            f'<span style="display:flex;justify-content:flex-end">{sig_block(r["buy"])}</span>'
                            f'</div>'
                        )
                    st.markdown(rows, unsafe_allow_html=True)

            with col_side:
                pos_df_home = enrich_positions(positions, scan)
                if not pos_df_home.empty:
                    st.markdown(f'<div class="bb-panel-hdr">MINE POSITIONER <span>{len(pos_df_home)}</span></div>', unsafe_allow_html=True)
                    ph = ''
                    for _, r in pos_df_home.iterrows():
                        pnl = r['PnL%']
                        pcol = '#00ff88' if pnl > 0 else '#ff3333'
                        ph += (f'<div class="pos-row">'
                               f'<span style="color:#fff;font-weight:700;font-family:IBM Plex Mono,monospace">{r["TICKER"]}</span>'
                               f'<span style="color:#444;font-size:0.65rem;font-family:IBM Plex Mono,monospace;overflow:hidden;white-space:nowrap">{r["NAVN"]}</span>'
                               f'<span style="color:#999;text-align:right;font-family:IBM Plex Mono,monospace">{r["NU"]:.2f}</span>'
                               f'<span style="color:{pcol};text-align:right;font-family:IBM Plex Mono,monospace;font-weight:700">{pnl:+.1f}%</span>'
                               f'{sig_block(str(r["SIGNAL"]))}</div>')
                    st.markdown(ph, unsafe_allow_html=True)

                st.markdown('<div class="bb-panel-hdr" style="margin-top:6px">TOP MOVERS <span>1D</span></div>', unsafe_allow_html=True)
                mh = ''
                for _, r in clean.nlargest(6, 'dpct').iterrows():
                    mh += (f'<div class="mov-row">'
                           f'<span class="mov-t-up">{r["ticker"]}</span>'
                           f'<span class="mov-sec">{r["sector"]}</span>'
                           f'<span class="mov-p">{r["price"]:.2f}</span>'
                           f'<span class="mkt-up">{r["dpct"]:+.1f}%</span></div>')
                mh += '<div style="border-top:1px solid #1a1a1a;margin:2px 0"></div>'
                for _, r in clean.nsmallest(6, 'dpct').iterrows():
                    mh += (f'<div class="mov-row">'
                           f'<span class="mov-t-dn">{r["ticker"]}</span>'
                           f'<span class="mov-sec">{r["sector"]}</span>'
                           f'<span class="mov-p">{r["price"]:.2f}</span>'
                           f'<span class="mkt-dn">{r["dpct"]:+.1f}%</span></div>')
                st.markdown(mh, unsafe_allow_html=True)

            # ═══ RÆKKE 3: SEKTOR-ROTATION TREEMAP ═══
            st.markdown('<div class="bb-panel-hdr" style="margin-top:8px">SEKTOR-ROTATION <span>STØRRELSE=LIKVIDITET · FARVE=1D%</span></div>', unsafe_allow_html=True)
            fig_tree = make_market_treemap(scan)
            if fig_tree:
                st.plotly_chart(fig_tree, use_container_width=True, config={'displayModeBar': False})

            # ═══ RÆKKE 4: VIX · SIGNAL FORDELING · SCORE · EARNINGS ═══
            b1, b2, b3, b4 = st.columns([1, 1, 1, 1])
            with b1:
                st.markdown('<div class="bb-panel-hdr">VIX FEAR/GREED</div>', unsafe_allow_html=True)
                st.plotly_chart(make_vix_gauge(vix_price), use_container_width=True, config={'displayModeBar': False})
            with b2:
                st.markdown('<div class="bb-panel-hdr">SIGNAL FORDELING</div>', unsafe_allow_html=True)
                fd = make_breadth_chart(scan)
                if fd:
                    st.plotly_chart(fd, use_container_width=True, config={'displayModeBar': False})
            with b3:
                st.markdown('<div class="bb-panel-hdr">SCORE DISTRIBUTION</div>', unsafe_allow_html=True)
                fh = make_score_histogram(scan)
                if fh:
                    st.plotly_chart(fh, use_container_width=True, config={'displayModeBar': False})
            with b4:
                st.markdown('<div class="bb-panel-hdr">KOMMENDE EARNINGS <span>BEST-EFFORT</span></div>', unsafe_allow_html=True)
                watch_tickers = list(pos_df_home['TICKER']) if not pos_df_home.empty else []
                watch_tickers += clean[clean['buy'].isin(['BUY NOW','BUY BREAKOUT','BUILD POSITION','STARTER BUY'])]['ticker'].head(15).tolist()
                seen = set(); uniq = [t for t in watch_tickers if not (t in seen or seen.add(t))]
                ev = fetch_earnings_calendar(tuple(uniq))
                if ev:
                    eh = '<div style="font-family:IBM Plex Mono,monospace;font-size:0.72rem">'
                    for e in ev[:12]:
                        dcol = '#ff3333' if e['days'] <= 7 else ('#ffaa00' if e['days'] <= 21 else '#888')
                        eh += (f'<div style="display:flex;justify-content:space-between;padding:2px 4px;border-bottom:1px solid #111">'
                               f'<span style="color:#fff;font-weight:700">{e["ticker"]}</span>'
                               f'<span style="color:#666">{e["date"]}</span>'
                               f'<span style="color:{dcol};font-weight:700">{e["days"]}d</span></div>')
                    eh += '</div>'
                    st.markdown(eh, unsafe_allow_html=True)
                else:
                    st.markdown('<div style="color:#555;font-size:0.7rem;font-family:IBM Plex Mono,monospace;padding:6px 4px">Ingen earnings-data tilgængelig (yfinance-begrænsning).</div>', unsafe_allow_html=True)


    # ═══════════════════════════════════════════
    # TAB 2: SCANNER
    # ═══════════════════════════════════════════
    with tab2:
        # ── TILFØJ AKTIE ──
        with st.expander("➕ TILFØJ AKTIE TIL SCANNER", expanded=True):
            a1,a2,a3 = st.columns([2,1,1])
            with a1: new_ticker = st.text_input("TICKER","",placeholder="f.eks. IDR.MC",key='add_ticker').upper().strip()
            with a2:
                st.markdown("<br>",unsafe_allow_html=True)
                lookup_btn = st.button("🔍 SLÅ OP",use_container_width=True)
            with a3:
                st.markdown("<br>",unsafe_allow_html=True)
                add_btn = st.button("✚ TILFØJ",use_container_width=True)
            if lookup_btn and new_ticker:
                with st.spinner(f"Henter {new_ticker}..."):
                    result,err = lookup_ticker(new_ticker)
                if result:
                    st.session_state['lookup_result']=result
                    st.success(f"✓ **{result[1]}** | {result[2]} | {result[3]}")
                else:
                    st.error(f"Fejl: {err}")
                    st.session_state['lookup_result']=None
            if add_btn and new_ticker:
                result = st.session_state.get('lookup_result')
                if result and result[0]==new_ticker:
                    existing = load_custom_universe()
                    if any(e[0]==new_ticker for e in existing):
                        st.warning(f"{new_ticker} findes allerede")
                    elif new_ticker in {t[0] for t in UNIVERSE}:
                        st.warning(f"{new_ticker} er i standard universet")
                    else:
                        existing.append(result)
                        save_custom_universe(existing)
                        st.success(f"✓ {result[1]} tilføjet!")
                        with st.spinner("Opdaterer snapshot med ny ticker..."):
                            refresh_scan_to_db()
                        st.rerun()
                else:
                    st.warning("Tryk først 🔍 SLÅ OP")
            custom_now = load_custom_universe()
            if custom_now:
                st.markdown(f"**Tilføjede aktier ({len(custom_now)}):**")
                for i,e in enumerate(custom_now):
                    c1,c2 = st.columns([5,1])
                    with c1: st.markdown(f"`{e[0]}` — {e[1]} | {e[2]} | {e[3]}")
                    with c2:
                        if st.button("×",key=f"rm_{i}"):
                            custom_now.pop(i); save_custom_universe(custom_now)
                            with st.spinner("Opdaterer snapshot..."):
                                refresh_scan_to_db()
                            st.rerun()
        if not scan.empty:
            # ── Søge og filter række ──
            c1,c2,c3,c4,c5 = st.columns([2,1,1,1,1])
            with c1:
                search = st.text_input("🔍 SØG ticker / navn","",
                    placeholder="f.eks. AAPL eller Apple...")
            with c2:
                sf2 = st.selectbox("SEKTOR",["ALLE"]+sorted(scan['sector'].unique().tolist()))
            with c3:
                rf2 = st.selectbox("REGION",["ALLE"]+sorted(scan['region'].unique().tolist()))
            with c4:
                sig2 = st.selectbox("SIGNAL",["ALLE"]+sorted(scan['buy'].unique().tolist()))
            with c5:
                only_s2b = st.checkbox("KUN STAGE 2",False,key='scanner_s2')

            # ── Filtrering ──
            flt = scan.copy()
            flt = flt[flt['sector'] != 'REF']  # skjul reference indeks
            if search:
                s = search.upper()
                flt = flt[flt['ticker'].str.upper().str.contains(s) |
                          flt['name'].str.upper().str.contains(s)]
            if sf2 != "ALLE":  flt = flt[flt['sector']==sf2]
            if rf2 != "ALLE":  flt = flt[flt['region']==rf2]
            if sig2 != "ALLE": flt = flt[flt['buy']==sig2]
            if only_s2b:       flt = flt[flt['stn']==2]

            st.caption(f"`[ {len(flt)} / {len(scan)} AKTIER ]`")

            # Kolonner i EKSAKT samme rækkefølge som Sheets v5.1
            cols={
                'ticker':'Ticker','name':'Name','sector':'Sector','region':'Region','tier':'Tier',
                'price':'Price','dpct':'Daily%','rsi':'RSI','rsi_t':'RSI Trend',
                'sma20':'SMA20','sma60':'SMA60','sma200':'SMA200',
                'trend':'Trend','trend200':'Trend200',
                'high20':'High20','low5':'Low5','dh20':'DistHigh20%',
                'volr':'VolRatio','rvol50':'RVOL50','avgvol':'AvgVol20','dolvol_m':'DollarVol20',
                'liq':'LiquidityPass',
                'atr20':'ATR20','sqz':'Squeeze',
                'rs_t':'RS Trend','hl':'HigherLow','ia':'InstAccum','cap':'CapRisk',
                'ifs':'InstFlowScore','ls':'LiquidityScore',
                'ts':'TrendScore','ss':'SetupScore','rp':'RiskPenalty','score':'PriorityScore',
                'setup':'SetupState','buy':'BuySignal','sell':'SellSignal','stop':'Stop',
                'rs_rank':'RS Rank','stage':'Stage',
            }
            flt_d = flt[[c for c in cols.keys() if c in flt.columns]].rename(columns=cols)
            flt_d = flt_d.set_index(['Ticker','Name'])
            st.dataframe(
                flt_d.style
                .map(sig_style,subset=['BuySignal','SellSignal'])
                .format({
                    'Price':'{:.2f}','Daily%':'{:+.1f}%','RSI':'{:.1f}',
                    'SMA20':'{:.2f}','SMA60':'{:.2f}','SMA200':'{:.2f}',
                    'High20':'{:.2f}','Low5':'{:.2f}',
                    'DistHigh20%':'{:.1f}%','VolRatio':'{:.2f}','RVOL50':'{:.2f}',
                    'DollarVol20':'{:.1f}M','ATR20':'{:.2f}',
                    'InstFlowScore':'{:.0f}','LiquidityScore':'{:.0f}',
                    'TrendScore':'{:.0f}','SetupScore':'{:.0f}','RiskPenalty':'{:.0f}',
                    'PriorityScore':'{:.0f}','RS Rank':'{:.0f}',
                }, na_rep='—'),
                use_container_width=True,height=750)
            csv = flt.to_csv(index=False).encode('utf-8')
            st.download_button("⬇ EKSPORT CSV",csv,'scanner.csv','text/csv')

    # ═══════════════════════════════════════════
    # TAB 3: BENCHMARK
    # ═══════════════════════════════════════════
    with tab3:
        st.markdown("### `BENCHMARK & MARKEDSANALYSE`")
        if mkt:
            # Sektor performance chart
            st.plotly_chart(plot_sector_etf_chart(mkt),use_container_width=True)
            st.markdown("---")

            # Detaljeret markedsoversigt per gruppe
            for grp_name,tickers in MARKET_GROUPS.items():
                st.markdown(f"### `{grp_name}`")
                rows=[]
                for ticker,name in tickers:
                    d=mkt.get(ticker,{})
                    if d:
                        rows.append({'Ticker':ticker,'Navn':name,
                                     'Pris':d.get('price','—'),
                                     '1D%':d.get('pct1','—'),
                                     '5D%':d.get('pct5','—'),
                                     '30D%':d.get('pct30','—'),
                                     'Trend':d.get('trend','—')})
                if rows:
                    df_b=pd.DataFrame(rows)
                    def cp(v):
                        if isinstance(v,(int,float)): return f'color:{"#00ff41" if v>0 else "#ff3333" if v<0 else "#008f23"}'
                        return 'color:#008f23'
                    st.dataframe(df_b.style.map(cp,subset=['1D%','5D%','30D%'])
                                 .format({'Pris':'{:.2f}','1D%':'{:+.1f}%','5D%':'{:+.1f}%','30D%':'{:+.1f}%'}, na_rep='—'),
                                 use_container_width=True,hide_index=True)

            # Breadth
            if not scan.empty:
                st.markdown("---")
                st.markdown("### `MARKET BREADTH`")
                total=max(len(scan),1)
                _price=pd.to_numeric(scan['price'],errors='coerce')
                _sma200=pd.to_numeric(scan['sma200'],errors='coerce')
                _sma20=pd.to_numeric(scan['sma20'],errors='coerce')
                _rsi=pd.to_numeric(scan['rsi'],errors='coerce')
                a200=round((_price>_sma200).sum()/total*100,1)
                a20=round((_price>_sma20).sum()/total*100,1)
                r60=round((_rsi>60).sum()/total*100,1)
                r40=round((_rsi<40).sum()/total*100,1)
                s2pct=round((scan['stn']==2).sum()/total*100,1)
                c1,c2,c3,c4,c5=st.columns(5)
                c1.metric("Over SMA200",f"{a200}%")
                c2.metric("Over SMA20",f"{a20}%")
                c3.metric("RSI > 60",f"{r60}%")
                c4.metric("RSI < 40",f"{r40}%")
                c5.metric("Stage 2",f"{s2pct}%")

    # ═══════════════════════════════════════════
    # TAB 4: POSITIONER
    # ═══════════════════════════════════════════
    with tab4:
        st.markdown("### `MINE POSITIONER`")
        pos_df=enrich_positions(positions,scan)
        if not pos_df.empty:
            tp=pos_df['PnLkr'].sum(); ap=pos_df['PnL%'].mean(); wn=(pos_df['PnL%']>0).sum()
            c1,c2,c3,c4=st.columns(4)
            c1.metric("POSITIONER",len(pos_df)); c2.metric("TOTAL PnL",f"{tp:+.0f} kr")
            c3.metric("GNS PnL%",f"{ap:+.1f}%"); c4.metric("WINNERS",f"{wn}/{len(pos_df)}")
            st.dataframe(pos_df.style.map(pnl_style,subset=['PnL%','PnLkr'])
                         .map(sig_style,subset=['SIGNAL'])
                         .format({'ENTRY':'{:.2f}','NU':'{:.2f}','PnL%':'{:+.2f}%','PnLkr':'{:+.0f}'}, na_rep='—'),
                         use_container_width=True,hide_index=True)
        else:
            st.info("Ingen aktive positioner.")
        st.markdown("---")
        c1,c2,c3,c4,c5=st.columns(5)
        with c1: nt=st.text_input("TICKER").upper().strip()
        with c2: ne=st.number_input("ENTRY",min_value=0.0,step=0.01,format="%.2f")
        with c3: ns=st.number_input("AKTIER",min_value=1,step=1)
        with c4: nn=st.text_input("NAVN")
        with c5:
            st.markdown("<br>",unsafe_allow_html=True)
            if st.button("+ TILFØJ",use_container_width=True):
                if nt and ne>0:
                    positions.append({'ticker':nt,'name':nn or nt,'entry_price':ne,'shares':ns,'date':datetime.now().strftime('%Y-%m-%d')})
                    save_json(POSITIONS_FILE,positions); st.success(f"✓ {nt}"); st.rerun()
                else: st.error("Udfyld ticker og pris")
        if positions:
            c1,c2=st.columns([3,1])
            with c1: rm=st.selectbox("FJERN",[p['ticker'] for p in positions])
            with c2:
                st.markdown("<br>",unsafe_allow_html=True)
                if st.button("× FJERN",use_container_width=True):
                    positions=[p for p in positions if p['ticker']!=rm]
                    save_json(POSITIONS_FILE,positions); st.rerun()

    # ═══════════════════════════════════════════
    # TAB 5: WATCHLIST
    # ═══════════════════════════════════════════
    with tab5:
        st.markdown("### `PERSONLIG WATCHLIST`")
        if watchlist and not scan.empty:
            wl_df=scan[scan['ticker'].isin(watchlist)]
            if not wl_df.empty:
                st.dataframe(wl_df[['ticker','name','sector','price','dpct','rsi','rs_rank','stage','score','buy','stop']]
                             .rename(columns={'ticker':'TICKER','name':'NAVN','sector':'SEKTOR','price':'PRIS',
                                              'dpct':'1D%','rsi':'RSI','rs_rank':'RS','stage':'STG','score':'SCORE','buy':'SIGNAL','stop':'STOP'})
                             .style.map(sig_style,subset=['SIGNAL'])
                             .format({'PRIS':'{:.2f}','1D%':'{:+.1f}%','RSI':'{:.1f}','SCORE':'{:.0f}'}, na_rep='—'),
                             use_container_width=True,hide_index=True)
        else:
            st.info("Watchlist er tom.")
        st.markdown("---")
        c1,c2=st.columns([3,1])
        with c1: wt=st.text_input("TILFØJ TICKER").upper().strip()
        with c2:
            st.markdown("<br>",unsafe_allow_html=True)
            if st.button("+ TILFØJ",use_container_width=True,key='wl_a'):
                if wt and wt not in watchlist:
                    watchlist.append(wt); save_json(WATCHLIST_FILE,watchlist); st.rerun()
        if watchlist:
            c1,c2=st.columns([3,1])
            with c1: wr=st.selectbox("FJERN",watchlist)
            with c2:
                st.markdown("<br>",unsafe_allow_html=True)
                if st.button("× FJERN",use_container_width=True,key='wl_r'):
                    watchlist=[w for w in watchlist if w!=wr]
                    save_json(WATCHLIST_FILE,watchlist); st.rerun()

    # ═══════════════════════════════════════════
    # TAB S1: S1 PIPELINE
    # ═══════════════════════════════════════════
    with tab_s1:
        st.markdown("### `S1 PIPELINE — Stage 1 Breakout Kandidater`")
        st.caption("`Aktier i Stage 1 (pris < SMA200, SMA200 stiger) der nærmer sig Stage 2-bruddet. Ingen aktiv position — pipeline til fremtidige BUY-signaler.`")

        if scan.empty:
            st.info("Ingen scan-data tilgængelig.")
        else:
            s1 = scan[scan['stn'] == 1].copy()

            # Beregn afstand til SMA200 (positiv = pris under SMA200)
            _p   = pd.to_numeric(s1['price'],  errors='coerce')
            _s2  = pd.to_numeric(s1['sma200'], errors='coerce')
            _s20 = pd.to_numeric(s1['sma20'],  errors='coerce')
            _s60 = pd.to_numeric(s1['sma60'],  errors='coerce')
            s1['dist_sma200'] = ((_s2 - _p) / _s2 * 100).round(1)

            # Filtre
            c1, c2, c3 = st.columns(3)
            with c1: max_dist = st.slider("Maks. afstand til SMA200 (%)", 1, 25, 12)
            with c2: min_rs   = st.slider("Minimum RS Rank", 0, 90, 50)
            with c3: only_pos_trend = st.checkbox("Kun SMA20 > SMA60", value=True)

            s1 = s1[s1['dist_sma200'] <= max_dist]
            s1 = s1[pd.to_numeric(s1['rs_rank'], errors='coerce') >= min_rs]
            if only_pos_trend:
                s1 = s1[_s20.reindex(s1.index) > _s60.reindex(s1.index)]
            s1 = s1[s1['sector'] != 'REF']
            s1 = s1.sort_values('dist_sma200')

            # Metrics
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("KANDIDATER", len(s1))
            m2.metric("GNS. AFSTAND TIL SMA200",
                      f"{s1['dist_sma200'].mean():.1f}%" if not s1.empty else "—")
            m3.metric("GNS. RS RANK",
                      f"{pd.to_numeric(s1['rs_rank'], errors='coerce').mean():.0f}" if not s1.empty else "—")
            m4.metric("TOTAL S1 I UNIVERSET", len(scan[scan['stn'] == 1]))

            st.markdown("---")

            if s1.empty:
                st.info("Ingen S1-kandidater matcher kriterierne.")
            else:
                disp = s1[['ticker','name','sector','region','price','dist_sma200',
                            'sma20','sma60','sma200','rsi','rs_rank','dolvol_usd_m',
                            'stage','score']].copy()
                disp = disp.rename(columns={
                    'ticker':'TICKER','name':'NAVN','sector':'SEKTOR','region':'REGION',
                    'price':'PRIS','dist_sma200':'% U. SMA200',
                    'sma20':'SMA20','sma60':'SMA60','sma200':'SMA200',
                    'rsi':'RSI','rs_rank':'RS RANK','dolvol_usd_m':'VOL USD M',
                    'stage':'STAGE','score':'SCORE',
                })
                disp = disp.set_index(['TICKER','NAVN'])
                st.dataframe(
                    disp.style
                    .format({
                        'PRIS':'{:.2f}','% U. SMA200':'{:.1f}%',
                        'SMA20':'{:.2f}','SMA60':'{:.2f}','SMA200':'{:.2f}',
                        'RSI':'{:.1f}','RS RANK':'{:.0f}',
                        'VOL USD M':'{:.1f}M','SCORE':'{:.0f}',
                    }, na_rep='—'),
                    use_container_width=True, height=600)

                csv_s1 = s1.to_csv(index=False).encode('utf-8')
                st.download_button("⬇ EKSPORT S1 CSV", csv_s1, 's1_pipeline.csv', 'text/csv')

    # ═══════════════════════════════════════════
    # TAB 6: CHARTS
    # ═══════════════════════════════════════════
    with tab6:
        st.markdown("### `TERMINAL CHART`")
        if not scan.empty:
            tl=scan['ticker'].tolist()
            sel=st.selectbox("VÆLG AKTIE",tl,
                format_func=lambda t: f"{t} — {scan[scan['ticker']==t].iloc[0]['name']}" if not scan[scan['ticker']==t].empty else t)
            if sel:
                row=scan[scan['ticker']==sel].iloc[0]
                c1,c2,c3,c4,c5,c6,c7=st.columns(7)
                c1.metric("PRIS",f"{row['price']:.2f}"); c2.metric("1D%",f"{row['dpct']:+.1f}%")
                c3.metric("RSI",f"{row['rsi']:.1f}" if row['rsi'] else "—")
                c4.metric("RS RANK",f"{row['rs_rank']}/99"); c5.metric("SCORE",f"{int(row['score'])}")
                c6.metric("STAGE",row['stage']); c7.metric("ATR%",f"{row['atr_pct']:.1f}%")
                c1,c2,c3,c4=st.columns(4)
                c1.info(f"**SIGNAL:** {row['buy']}"); c2.info(f"**SETUP:** {row['setup']}")
                c3.info(f"**STOP:** {row['stop']}");  c4.info(f"**SQZ:** {row['sqz']}")
                with st.spinner("HENTER CHART..."):
                    cdf=get_chart_data(sel)
                    st.plotly_chart(plot_chart(sel,cdf,row['buy']),use_container_width=True)

    # ═══════════════════════════════════════════
    # TAB 7: RS ANALYSE
    # ═══════════════════════════════════════════
    with tab7:
        st.markdown("### `IBD RS RANK ANALYSE`")
        st.caption("`RS Rank påvirker IKKE PriorityScore`")
        if not scan.empty:
            color_map={'BUY NOW':'#00ff41','BUY BREAKOUT':'#00cc33','BUILD POSITION':'#0088ff',
                       'STARTER BUY':'#00aaff','EXTENDED — WAIT':'#ffaa00',
                       'REDUCE':'#ff6600','EXIT':'#ff3333','WATCHLIST':'#225522'}
            fig=go.Figure()
            for sig,grp in scan.groupby('buy'):
                fig.add_trace(go.Scatter(x=grp['rs_rank'],y=grp['score'],mode='markers+text',name=sig,
                    text=grp['ticker'],textposition='top center',
                    textfont=dict(size=8,color='#008f23',family='Share Tech Mono'),
                    marker=dict(size=8,color=color_map.get(sig,'#225522'),opacity=0.9,
                                line=dict(width=1,color='rgba(0,255,65,0.2)')),
                    hovertemplate='<b>%{text}</b><br>RS:%{x} | Score:%{y}<extra></extra>'))
            fig.add_vline(x=70,line_dash='dash',line_color='rgba(0,255,65,0.4)')
            fig.add_hline(y=60,line_dash='dash',line_color='rgba(255,170,0,0.4)')
            fig.update_layout(plot_bgcolor='#000000',paper_bgcolor='#000a00',
                font=dict(color='#00ff41',family='Share Tech Mono'),
                xaxis=dict(title='IBD RS RANK',range=[0,100],gridcolor='rgba(0,255,65,0.1)'),
                yaxis=dict(title='PRIORITY SCORE',range=[0,100],gridcolor='rgba(0,255,65,0.1)'),
                legend=dict(bgcolor='#000a00',bordercolor='rgba(0,255,65,0.2)',font=dict(size=9)),
                height=480,margin=dict(l=60,r=20,t=20,b=60))
            st.plotly_chart(fig,use_container_width=True)
            st.markdown("### `TOP 25 RS`")
            top25=scan.nlargest(25,'rs_rank')[['ticker','name','sector','region','price','dpct','rsi','rs_rank','stage','score','buy']]
            st.dataframe(top25.rename(columns={'ticker':'TICKER','name':'NAVN','sector':'SEKTOR','region':'REGION',
                'price':'PRIS','dpct':'1D%','rsi':'RSI','rs_rank':'RS','stage':'STG','score':'SCORE','buy':'SIGNAL'})
                .style.map(sig_style,subset=['SIGNAL'])
                .format({'PRIS':'{:.2f}','1D%':'{:+.1f}%','RSI':'{:.1f}','SCORE':'{:.0f}'}, na_rep='—'),
                use_container_width=True,hide_index=True)

    # ═══════════════════════════════════════════
    # TAB BACKTEST – forward returns paa historiske BUY-signaler
    # ═══════════════════════════════════════════
    with tab_bt:
        st.markdown("### `BACKTEST – LIVE FORWARD RETURN TRACKER`")
        st.caption("Bygger evidens for algoritmens edge ved at foelge BUY-signaler over tid. Snapshot tages automatisk en gang pr. dag.")

        history = load_json(SIGNALS_HISTORY_FILE)
        st.markdown(f"**Snapshots:** `{len(history)}` dage  -  **Total signaler logget:** `{sum(len(h.get('signals',[])) for h in history)}`")

        fwd_df = compute_forward_returns(scan)
        if fwd_df.empty:
            st.info("Ingen historiske signaler endnu - foerste snapshot tages efter denne scan. Kom tilbage om nogle dage / uger for at se forward-returns.")
        else:
            st.markdown("#### `SUMMARY - HIT-RATE & GENNEMSNITLIG RETURN PR. HORISONT`")
            summary = backtest_summary(fwd_df)
            if not summary.empty:
                def color_hit(v):
                    if isinstance(v,(int,float)):
                        return ('color:#00ff88;font-weight:700' if v>=55
                                else ('color:#ff3333;font-weight:700' if v<=45 else 'color:#ffaa00'))
                    return ''
                def color_ret(v):
                    if isinstance(v,(int,float)):
                        return ('color:#00ff88;font-weight:700' if v>0
                                else ('color:#ff3333;font-weight:700' if v<0 else ''))
                    return ''
                st.dataframe(
                    summary.style
                        .map(color_hit, subset=['Hit-rate %'])
                        .map(color_ret, subset=['Avg return %','Median %'])
                        .format({'Hit-rate %':'{:.1f}','Avg return %':'{:+.2f}',
                                 'Median %':'{:+.2f}','Best %':'{:+.2f}','Worst %':'{:+.2f}'}, na_rep='—'),
                    use_container_width=True, hide_index=True)
            st.markdown("---")
            st.markdown("#### `ALLE LOGGEDE SIGNALER`")
            show_df = fwd_df.sort_values('days_held', ascending=False)
            st.dataframe(
                show_df.style
                    .map(lambda v: 'color:#00ff88;font-weight:700' if isinstance(v,(int,float)) and v>0
                                   else ('color:#ff3333;font-weight:700' if isinstance(v,(int,float)) and v<0 else ''),
                         subset=['return_pct'])
                    .format({'entry':'{:.2f}','current':'{:.2f}','return_pct':'{:+.2f}%'}, na_rep='—'),
                use_container_width=True, hide_index=True, height=420)
            st.download_button("EKSPORT FORWARD RETURNS CSV",
                               fwd_df.to_csv(index=False).encode('utf-8'),
                               'forward_returns.csv','text/csv')

    # ═══════════════════════════════════════════
    # TAB SIGNAL LOG — backtest data til ML
    # ═══════════════════════════════════════════
    with tab_siglog:
        st.markdown("### `SIGNAL LOG — Historiske BUY-signaler med features`")
        st.caption("`Alle BUY-signaler logget med fulde tekniske features. Forward returns udfyldes automatisk efter 5/20/60/120 dage. Download CSV til ML-analyse.`")

        log_df = sdb.get_signal_log()

        if log_df.empty:
            st.info("Ingen signaler logget endnu. Kør et fuldt scan for at starte logningen.")
        else:
            # ── Metrics ─────────────────────────────────────────────
            total    = len(log_df)
            with_20d = log_df['forward_20d'].notna().sum()
            with_60d = log_df['forward_60d'].notna().sum()
            avg_20d  = log_df['forward_20d'].mean()
            hit_20d  = (log_df['forward_20d'] > 0).sum() / with_20d * 100 if with_20d > 0 else 0

            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("LOGGEDE SIGNALER", total)
            m2.metric("MED 20D RETURN", with_20d)
            m3.metric("MED 60D RETURN", with_60d)
            m4.metric("AVG 20D RETURN", f"{avg_20d:.1f}%" if with_20d else "—")
            m5.metric("HIT-RATE 20D", f"{hit_20d:.0f}%" if with_20d else "—")

            st.markdown("---")

            # ── Filtre ───────────────────────────────────────────────
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                sig_filter = st.multiselect("Signal", sorted(log_df['signal'].dropna().unique()),
                                            default=sorted(log_df['signal'].dropna().unique()))
            with c2:
                sec_filter = st.multiselect("Sektor", sorted(log_df['sector'].dropna().unique()),
                                            default=sorted(log_df['sector'].dropna().unique()))
            with c3:
                reg_filter = st.multiselect("Regime", sorted(log_df['regime'].dropna().unique()),
                                            default=sorted(log_df['regime'].dropna().unique()))
            with c4:
                only_returns = st.checkbox("Kun med 20d return", value=False)

            filtered = log_df[
                log_df['signal'].isin(sig_filter) &
                log_df['sector'].isin(sec_filter) &
                log_df['regime'].isin(reg_filter)
            ]
            if only_returns:
                filtered = filtered[filtered['forward_20d'].notna()]

            # ── Tabel ────────────────────────────────────────────────
            display_cols = ['date','ticker','name','signal','score','price',
                            'rsi','atr_pct','volr','rs_rank','squeeze',
                            'dist_sma200','dist_sma20','sector','regime','stage',
                            'forward_5d','forward_20d','forward_60d','forward_120d']
            show = filtered[[c for c in display_cols if c in filtered.columns]].copy()

            st.dataframe(
                show.style.format({
                    'score':'{:.0f}', 'price':'{:.2f}',
                    'rsi':'{:.1f}', 'atr_pct':'{:.1f}%',
                    'volr':'{:.2f}', 'rs_rank':'{:.0f}',
                    'dist_sma200':'{:.1f}%', 'dist_sma20':'{:.1f}%',
                    'forward_5d':'{:.1f}%', 'forward_20d':'{:.1f}%',
                    'forward_60d':'{:.1f}%', 'forward_120d':'{:.1f}%',
                }, na_rep='—'),
                use_container_width=True, height=500
            )

            st.markdown("---")

            # ── Performance summary ──────────────────────────────────
            if with_20d >= 5:
                st.markdown("#### Performance pr. signal (20d return)")
                perf = filtered[filtered['forward_20d'].notna()].groupby('signal').agg(
                    N=('forward_20d','count'),
                    Avg=('forward_20d','mean'),
                    Median=('forward_20d','median'),
                    Best=('forward_20d','max'),
                    Worst=('forward_20d','min'),
                ).round(1)
                perf['Hit%'] = (
                    filtered[filtered['forward_20d'].notna()]
                    .groupby('signal')['forward_20d']
                    .apply(lambda x: (x > 0).mean() * 100).round(1)
                )
                st.dataframe(perf, use_container_width=True)

            # ── CSV eksport ──────────────────────────────────────────
            csv = filtered.to_csv(index=False).encode('utf-8')
            st.download_button(
                "⬇ DOWNLOAD CSV TIL ML-ANALYSE",
                csv, 'signal_log.csv', 'text/csv',
                help="Indeholder alle features på signal-tidspunktet + forward returns. Klar til Excel eller Python/sklearn."
            )

    # ═══════════════════════════════════════════
    # TAB DIAGNOSTIK – download success/failure
    # ═══════════════════════════════════════════
    with tab_diag:
        st.markdown("### `DIAGNOSTIK - DATAKVALITET`")
        if os.path.exists(DIAGNOSTICS_FILE):
            try:
                diag = json.load(open(DIAGNOSTICS_FILE))
                c1,c2,c3,c4,c5 = st.columns(5)
                c1.metric("ANMODET",        diag.get('requested',0))
                c2.metric("YF OK",          diag.get('yf_ok',0))
                c3.metric("STOOQ FAILOVER", diag.get('stooq_ok',0))
                c4.metric("DROPPET EFTER DL", diag.get('dropped_after_download_count',0))
                c5.metric("I SCANNER",      diag.get('final_in_scan',0))
                st.caption(f"Seneste scan: `{diag.get('ts','-')}`")

                if diag.get('failed_tickers'):
                    st.markdown("**Tickere helt uden data fra yfinance (max 50 vist):**")
                    st.code(', '.join(diag['failed_tickers']))

                if diag.get('dropped_after_download'):
                    st.markdown("---")
                    st.markdown("**Tickere droppet i indikator-beregningen (max 80 vist):**")
                    st.caption("Disse blev hentet ok fra yfinance, men kunne ikke bearbejdes — typisk NaN i data, manglende kolonner, eller uventede exceptions.")
                    drop_df = pd.DataFrame(diag['dropped_after_download'])
                    st.dataframe(drop_df, use_container_width=True, hide_index=True, height=300)
            except Exception as e:
                st.error(f"Kunne ikke laese diagnostik: {e}")
        else:
            st.info("Ingen diagnostik endnu. Koer en scan.")

        st.markdown("---")
        st.markdown("### `FX-RATES (USD)`")
        try:
            fx = fetch_fx_rates()
            fx_df = pd.DataFrame([{'Valuta':k, 'Kurs til USD':round(v,5)} for k,v in sorted(fx.items())])
            st.dataframe(fx_df, use_container_width=True, hide_index=True)
        except Exception as e:
            st.error(f"FX-fetch fejlede: {e}")

    # ═══════════════════════════════════════════
    # TAB 8: PLAYBOOK / BOG
    # ═══════════════════════════════════════════
    with tab8:
        st.markdown("# `▸ TRADING TERMINAL – PLAYBOOK`")
        st.markdown("<div style='color:#005f12;font-family:Share Tech Mono;font-size:0.8rem'>Alt du behøver at vide om algoritmen, signalerne og hvordan du bruger terminalen</div>",unsafe_allow_html=True)
        st.markdown("---")

        sections = st.tabs(["📊 ALGORITMEN","🎯 SIGNALER","📈 SETUP STATES","⚠️ RISK","🌍 MARKED REGIME","💡 SÅDAN BRUGER DU DEN","📚 ORDLISTE"])
        s1,s2,s3,s4,s5,s6,s7 = sections

        with s1:
            st.markdown("## `ALGORITMEN – PRIORITY SCORE`")
            st.markdown("""
<div style='font-family:Share Tech Mono;font-size:0.82rem;color:#00cc33;line-height:1.8'>

<span style='color:#00ff41;font-size:0.9rem'>◆ HVAD ER PRIORITY SCORE?</span><br>
Priority Score er en samlet vurdering fra 0-100 der fortæller dig hvor interessant en aktie er som momentum-kandidat.
Den er bygget op af tre komponenter:

<br><br>
<span style='color:#00ff41'>PriorityScore = TrendScore + SetupScore − RiskPenalty</span>
<br><br>

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<span style='color:#ffaa00'>[ TRENDSCORE – max 72 point ]</span>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Måler styrken af den overordnede trend:

  +24  →  Pris over SMA200 (langsigtet uptrend)
  +18  →  SMA20 over SMA60 (mellemsigtet trend op)
  +10  →  Pris over SMA20 (kortsigtet styrke)
  +12  →  RS Trend = UP (outperformer lokalt indeks)
  + 8  →  Higher Low (lavere bunde stiger = akkumulation)
  +10  →  InstFlowScore / 10 (institutionel strøm, max 10p)
  ───
  MAX: 82 → begrænset til 72 i praksis

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<span style='color:#0088ff'>[ SETUPSCORE – max 100 point ]</span>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Måler kvaliteten af det tekniske setup:

  +20  →  Accumulation (RSI 38-64, tæt på SMA20, volumen OK)
  + 6  →  Tight Action (ATR20/pris ≤ 4.5% – lav volatilitet)
  +18  →  Institutional Build (akkumulation + institutionel flow)
  +22  →  Breakout Ready (tæt på 20-dages high, volumen, RSI 44-78)
  +16  →  Momentum Active (breakout + volumen + RSI 50-80)
  + 6  →  Squeeze (ATR5 < ATR20 × 0.78 – energi bygger op)
  + 6  →  RSI 46-72 (hverken overkøbt eller oversolgt)
  + 6  →  DistHigh20 ≤ 7% (tæt på modstand)
  + 6  →  VolRatio ≥ 0.95 (volumen mindst normalt)
  +10  →  LiquidityScore / 10 (likviditetskvalitet, max 10p)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<span style='color:#ff3333'>[ RISKPENALTY – trækkes fra ]</span>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Straffer aktier med høj risiko:

  −14  →  Ingen likviditet (AvgVol < 200k eller DollarVol < 8M)
  −10  →  RISK_OFF marked
  − 6  →  RS Trend = DOWN (underperformer lokalt indeks)
  − 8  →  Extended (RSI > 84 eller pris > SMA20 × 1.14)
  − 6  →  CapRisk (dollarvolumen < 25M)
  − 8  →  Weakening (2+ svaghedstegn)
  −14  →  Failed Setup (3+ svaghedstegn + RSI < 42)

</div>
""", unsafe_allow_html=True)

        with s2:
            st.markdown("## `SIGNALER – HVAD BETYDER DE?`")
            signals = [
                ("BUY NOW", "#00ff41", "003300",
                 "Momentum er aktivt. Volumen bekræfter. Breakout sker nu.",
                 "Bedst i RISK_ON marked. Brug tæt stop under Low5 eller 1.5×ATR20 fra pris.",
                 "RSI falder under 50. Pris lukker under Low5."),
                ("BUY BREAKOUT", "#00cc33", "002200",
                 "Aktien er tæt på eller bryder igennem 20-dages modstand med volumen.",
                 "Køb ved breakout med volumenbekræftelse. Stop under SMA20.",
                 "Falsk breakout – pris vender tilbage under modstand."),
                ("BUILD POSITION", "#0088ff", "001133",
                 "Institutionel akkumulation er i gang. Setup er klar men breakout ikke sket endnu.",
                 "Start med lille position. Tilføj ved breakout-bekræftelse.",
                 "Pris lukker under max(Low5, SMA20 − 0.5×ATR20)."),
                ("STARTER BUY", "#00aaff", "001122",
                 "Tidlig akkumulation. Trend er op men setup ikke fuldt modnet.",
                 "Brug lille startposition. Vent på bedre setup inden du tilføjer.",
                 "Pris lukker under SMA20."),
                ("EXTENDED — WAIT", "#ffaa00", "221100",
                 "Aktien er strakt for langt fra SMA20. RSI > 84 eller pris > SMA20 × 1.14.",
                 "Tilføj IKKE ny position. Hold eksisterende. Vent på reset til SMA20.",
                 "—"),
                ("REDUCE", "#ff6600", "221100",
                 "Setup svækkes. 2+ negative faktorer er til stede.",
                 "Reducer position. Skrap de svageste dele.",
                 "Yderligere svaghed bekræfter EXIT."),
                ("EXIT", "#ff3333", "330000",
                 "Setup er brudt ned. 3+ negative faktorer. RSI < 42 eller pris under Low5.",
                 "Luk position. Rationalisér ikke.",
                 "—"),
                ("WATCHLIST", "#336633", "050505",
                 "Aktien er interessant men ikke klar endnu. Ingen aktiv setup.",
                 "Overvåg. Sæt alarm hvis score stiger over 65.",
                 "—"),
            ]
            for sig,col,bg,meaning,action,invalidation in signals:
                st.markdown(f"""
<div style='background:#{bg};border:1px solid {col};border-left:4px solid {col};padding:12px 16px;margin:8px 0;font-family:Share Tech Mono'>
<span style='color:{col};font-size:0.9rem;font-weight:700'>{sig}</span><br>
<span style='color:#00cc33;font-size:0.78rem'>▸ Hvad:       </span><span style='color:#aaa;font-size:0.78rem'>{meaning}</span><br>
<span style='color:#00cc33;font-size:0.78rem'>▸ Hvad gør du:</span><span style='color:#00ff41;font-size:0.78rem'> {action}</span><br>
{"<span style='color:#00cc33;font-size:0.78rem'>▸ Invalideret: </span><span style='color:#ff6600;font-size:0.78rem'>" + invalidation + "</span>" if invalidation != "—" else ""}
</div>""", unsafe_allow_html=True)

        with s3:
            st.markdown("## `SETUP STATES – AKTIENS TILSTAND`")
            st.markdown("""
<div style='font-family:Share Tech Mono;font-size:0.82rem;color:#00cc33;line-height:2'>

Setup State er det tekniske stadie aktien befinder sig i – forskelligt fra Buy Signal.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

<span style='color:#00ff41'>MOMENTUM_ACTIVE</span>
Alle faktorer er grønne. Volumen bekræfter. Breakout sker nu.
→ Signal: BUY NOW (eller STARTER BUY i RISK_OFF)

<span style='color:#00cc33'>BREAKOUT_READY</span>
Aktien er tæt på 20-dages high. Setup er klar. Afventer volumen.
→ Signal: BUY BREAKOUT

<span style='color:#0088ff'>INSTITUTIONAL_BUILD</span>
Institutionel akkumulation i gang. Higher lows. Volumen stiger stille.
→ Signal: BUILD POSITION

<span style='color:#00aaff'>ACCUMULATION</span>
Tidlig fase. RSI 38-64. Pris konsoliderer tæt på SMA20.
→ Signal: STARTER BUY

<span style='color:#ffaa00'>EXTENDED</span>
Pris er for langt fra SMA20 (>14%) eller RSI over 84.
→ Signal: EXTENDED — WAIT (tilføj ikke)

<span style='color:#ff6600'>WEAKENING</span>
2+ svaghedstegn: pris under SMA20, SMA20 under SMA60, RS DOWN.
→ Signal: REDUCE

<span style='color:#ff3333'>FAILED_SETUP</span>
Setup er brudt. 3+ svaghedstegn + lav RSI eller pris under Low5.
→ Signal: EXIT

<span style='color:#336633'>NO_SETUP</span>
Ingen aktiv teknisk setup. Aktien er på hold.
→ Signal: WATCHLIST

</div>
""", unsafe_allow_html=True)

        with s4:
            st.markdown("## `RISK MANAGEMENT`")
            st.markdown("""
<div style='font-family:Share Tech Mono;font-size:0.82rem;color:#00cc33;line-height:1.9'>

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<span style='color:#ff3333'>STOP LEVELS – AUTOMATISK BEREGNET</span>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Hvert signal har sit eget stop-niveau:

  MOMENTUM_ACTIVE:      Stop = max(Low5, Pris − 1.5 × ATR20)
  INSTITUTIONAL_BUILD:  Stop = max(Low5, SMA20 − 0.5 × ATR20)
  BREAKOUT_READY:       Stop = SMA20
  ACCUMULATION:         Stop = SMA20
  Andre:                Stop = SMA20

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<span style='color:#ffaa00'>NØGLEPARAMETRE DU SKAL KENDE</span>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ATR20:     Average True Range 20 dage – måler daglig volatilitet
             Jo højere ATR%, jo større stop skal du have
             
  VolRatio:  Dagens volumen / 20-dages gennemsnit
             > 1.5 = høj institutionel interesse
             < 0.8 = svag interesse
             
  RVOL50:    Volumen vs 50-dages gennemsnit
             Bekræfter langsigtet volumenmønster
             
  DistHigh20: Afstand til 20-dages høj i %
             < 3% = breakout-zone
             > 7% = for langt fra modstand
             
  Squeeze ⚡: ATR5 < ATR20 × 0.78
             Energi bygger op. Breakout nært forestående.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<span style='color:#00ff41'>POSITION SIZING – TOMMELFINGERREGEL</span>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  STARTER BUY:     0.5–1% af portefølje
  BUILD POSITION:  1–2% af portefølje
  BUY BREAKOUT:    2–3% af portefølje
  BUY NOW:         2–4% af portefølje (kun RISK_ON)
  
  Max enkelt position: 5–8% af portefølje
  Max sektor eksponering: 20–25%

</div>
""", unsafe_allow_html=True)

        with s5:
            st.markdown("## `MARKED REGIME`")
            st.markdown("""
<div style='font-family:Share Tech Mono;font-size:0.82rem;color:#00cc33;line-height:1.9'>

Marked Regime er terminalens makro-filter. Det bestemmer om vi er i et godt eller dårligt
miljø for momentum-trading. Det påvirker:
  1. RiskPenalty (+10 i RISK_OFF)
  2. Signal downgrade (BUILD/BREAKOUT → STARTER i RISK_OFF)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<span style='color:#00ff41'>▲ RISK_ON  (score ≥ 6)</span>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Alle signaler aktive. BUY NOW og BUY BREAKOUT er fuldt aktive.
Momentum-strategier virker bedst i dette miljø.

Typiske tegn:
  • SPY/QQQ/IWM stiger dagligt
  • VIX under 18 og faldende
  • Mere end 55% af aktier over SMA20
  • Mange buy-signaler i scanneren

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<span style='color:#ffaa00'>◆ NEUTRAL  (score 1-5)</span>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Mixed marked. Vær selektiv. Fokus på de stærkeste kandidater.
Reducer positionsstørrelser med 25-50%.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<span style='color:#ff3333'>▼ RISK_OFF  (score ≤ 0)</span>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Defensivt marked. BUILD og BREAKOUT downgraders til STARTER.
Reducer eksponering. Fokus på kapitalbevarelse.

Typiske tegn:
  • SPY/QQQ i downtrend
  • VIX over 28
  • Under 40% af aktier over SMA20
  • Primært WATCHLIST/EXIT signaler

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<span style='color:#00cc33'>REGIME SCORING (hvordan den beregnes)</span>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  SPY/QQQ/IWM 6M trend:  +/-1 hver
  SPY/QQQ daglig >0.5%:  +2/+1
  VIX niveau:            +2 (<15) til -3 (>35)
  VIX retning faldende:  +2 (>5% fald i dag)
  % aktier over SMA20:   +2 (≥55%) eller -2 (<40%)
  % aktier over SMA200:  +2 (≥50%) eller -2 (<35%)
  Antal buy-signaler:    +1 (≥5) eller -1 (=0)

</div>
""", unsafe_allow_html=True)

        with s6:
            st.markdown("## `SÅDAN BRUGER DU TERMINALEN`")
            st.markdown("""
<div style='font-family:Share Tech Mono;font-size:0.82rem;color:#00cc33;line-height:1.9'>

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<span style='color:#00ff41'>DAGLIG RUTINE (5-10 minutter)</span>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. Åbn FORSIDE
     → Tjek Marked Regime (RISK_ON/NEUTRAL/RISK_OFF)
     → Se VIX – stiger eller falder det?
     → Scan Top Kandidater – hvilke sektorer er stærke?
  
  2. Tjek TOP 10 OP/NED
     → Er der mønster? (fx alle energi-aktier stiger)
     → Er der aktier du følger?
  
  3. Åbn SCANNER
     → Sorter på PriorityScore
     → Filtrér på BUY BREAKOUT eller BUY NOW
     → Tjek Stage 2 filter for Weinstein
  
  4. Tjek POSITIONER
     → Er nogen aktier ved stop?
     → Er der REDUCE eller EXIT signaler?
  
  5. CHARTS for specifikke kandidater
     → Bekræft visuelt hvad scanneren ser

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<span style='color:#ffaa00'>HVAD GØR DU I RISK_OFF?</span>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  • Reducer positioner der viser REDUCE signal
  • Luk positioner der viser EXIT signal
  • Tilføj IKKE nye store positioner
  • Brug STARTER BUY med halv normal størrelse
  • Hold mere cash end normalt (30-50%)
  • Fokus på defensive sektorer (Utilities, Healthcare)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<span style='color:#00ff41'>HVAD GØR DU I RISK_ON?</span>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  • Følg BUY NOW og BUY BREAKOUT signaler aktivt
  • Byg positioner gradvist (STARTER → BUILD → FULL)
  • Brug trailing stop (SMA20 som guide)
  • Tilføj til vindere der holder over SMA20
  • Fokus på høj InstFlowScore (≥70) og RS Trend UP

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<span style='color:#0088ff'>SÅDAN LÆSER DU SCANNER KOLONNER</span>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  PriorityScore:  Den vigtigste kolonne. Jo højere jo bedre.
  RS Trend:       UP = outperformer lokalt indeks (C25, DAX osv.)
  IFS:            InstFlowScore – institutionel interesse (>70 = godt)
  LS:             LiquidityScore – kan du handle den? (>60 = godt)
  TS/SS/RP:       TrendScore / SetupScore / RiskPenalty
  Stage:          Weinstein stage. S2 = uptrend, S4 = downtrend
  Squeeze ⚡:      Energi bygger op – breakout nært

</div>
""", unsafe_allow_html=True)

        with s7:
            st.markdown("## `ORDLISTE`")
            terms = [
                ("SMA20", "Simple Moving Average 20 dage", "Gennemsnitspris de seneste 20 handelsdage. Vigtig kortsigtede støtte/modstand."),
                ("SMA60", "Simple Moving Average 60 dage", "Mellemsigtet trend. SMA20 > SMA60 = uptrend."),
                ("SMA200", "Simple Moving Average 200 dage", "Langsigtet trend. Pris over SMA200 = LONG TREND."),
                ("RSI", "Relative Strength Index (14)", "Momentum-oscillator 0-100. Over 70 = overkøbt, under 30 = oversolgt. Optimal zone: 46-72."),
                ("ATR20", "Average True Range 20 dage", "Gennemsnitlig daglig prisrange. Bruges til stop-beregning."),
                ("VolRatio", "Volume Ratio", "Dagens volumen divideret med 20-dages gennemsnit. >1.5 = høj institutionel interesse."),
                ("RVOL50", "Relative Volume 50", "Dagens volumen vs 50-dages gennemsnit. Bekræfter langsigtet volumenmønster."),
                ("RS Trend", "Relative Strength Trend", "Sammenligner aktiens pris mod lokalt indeks (C25 for DK, DAX for DE osv.). UP = outperformer."),
                ("DistHigh20", "Distance to 20-day High", "Afstand fra aktuel pris til 20-dages høj i %. < 3% = breakout-zone."),
                ("Higher Low", "Higher Low", "Aktiens bunde (Low5) er højere end 20-dages lave bunde. Tegn på akkumulation."),
                ("Squeeze ⚡", "Volatility Squeeze", "ATR5 < ATR20 × 0.78. Lav volatilitet bygger op til stor bevægelse."),
                ("InstFlowScore", "Institutional Flow Score 0-100", "Sammenvejning af volumen, RS, RSI og prisstyrke. Måler institutionel interesse."),
                ("LiquidityScore", "Liquidity Score 0-100", "Kombinerer AvgVol20, DollarVol og VolRatio. Sikrer at aktien er handelbar."),
                ("IBD RS Rank", "Investor's Business Daily RS Rank 1-99", "Relativ 12-måneders performance vægtet: 40% seneste kvartal + 20% × 3 kvartaler. 99 = bedst."),
                ("Weinstein Stage", "Weinstein Stage Analysis", "S1=Bund, S2=Uptrend (køb her), S3=Top, S4=Downtrend (undgå)"),
                ("CapRisk", "Capitalization Risk", "DollarVol < 25M dagligt. Aktien er for illikvid til store positioner."),
            ]
            for term,full,explanation in terms:
                st.markdown(f"""
<div style='border-bottom:1px solid rgba(0,255,65,0.1);padding:8px 4px;font-family:Share Tech Mono;font-size:0.8rem'>
<span style='color:#00ff41;font-weight:700'>{term}</span>
<span style='color:#005f12;font-size:0.72rem'> — {full}</span><br>
<span style='color:#00cc33'>{explanation}</span>
</div>""", unsafe_allow_html=True)

if __name__=='__main__':
    main()
