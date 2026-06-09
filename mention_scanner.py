#!/usr/bin/env python3
"""
Mention Scanner
===============
Scanner Reddit, Yahoo Finance og Finviz for aktie-mentions.
Gemmer historik i SQLite og beregner relativ stigning dag-til-dag og 7v7.

Kørsel:
    python3 mention_scanner.py

Output:
    - rapport_YYYY-MM-DD.csv
    - mentions.db (historik)

Konfiguration: se CONFIG-sektionen nedenfor.
"""

import sqlite3
import re
import csv
import json
import datetime
import collections
import urllib.request
import urllib.parse
import urllib.error
import time
import os
import sys
import html

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

CONFIG = {
    # Reddit subreddits der scannes
    "subreddits": [
        "wallstreetbets",
        "stocks",
        "investing",
        "StockMarket",
        "options",
        "pennystocks",
        "smallstreetbets",
    ],

    # Antal posts per subreddit (max 100 per request)
    "reddit_limit": 100,

    # Reddit sortering: hot, new, top, rising
    "reddit_sort": "hot",

    # Yahoo Finance tickers til nyhedsscan (tomme = kun Reddit/Finviz)
    # Tilføj tickers her hvis du vil have Yahoo-nyheder for specifikke aktier
    "yahoo_tickers": [],

    # Finviz news: antal sider (1 side = ~20 nyheder)
    "finviz_pages": 3,

    # Stopord - ord der IKKE er tickers
    "stopwords": {
        "A", "I", "AM", "AN", "AS", "AT", "BE", "BY", "DO", "GO",
        "HE", "IF", "IN", "IS", "IT", "ME", "MY", "NO", "OF", "OK",
        "ON", "OR", "SO", "TO", "UP", "US", "WE", "AND", "ARE", "BUT",
        "CAN", "CEO", "CFO", "COO", "CTO", "DAY", "DID", "ETF", "FOR",
        "GET", "GOT", "HAS", "HAD", "HIM", "HIS", "HOW", "ITS", "LET",
        "MAY", "NEW", "NOT", "NOW", "OLD", "ONE", "OUR", "OUT", "OWN",
        "PUT", "SAY", "SEE", "SET", "SHE", "THE", "TOO", "TWO", "USE",
        "WAS", "WAY", "WHO", "WHY", "YET", "YOU", "YOUR", "ALL", "ANY",
        "APE", "ATH", "AYE", "BAG", "BIG", "BUY", "DIP", "EPS", "FAQ",
        "FED", "FUD", "GUH", "IMO", "IPO", "IRA", "LOL", "LOW", "LTD",
        "MAX", "MID", "MOD", "NET", "OTC", "PDF", "PLZ", "POV", "RIP",
        "ROI", "SEC", "SMA", "SPY", "STD", "TBH", "TDA", "TEN", "TOP",
        "USD", "WTF", "XD", "YOY", "QOQ", "ATM", "ITM", "OTM",
        "AI", "ML", "EV", "PE", "VC", "US", "UK", "EU", "UN",
        "EDIT", "TLDR", "YOLO", "FOMO", "HODL", "MOON", "LOSS",
        "GAIN", "CALL", "PUTS", "BULL", "BEAR", "LONG", "SHORT",
        "HOLD", "SELL", "CASH", "DEBT", "FUND", "RATE", "RISK",
        "STOP", "LOSS", "OPEN", "HIGH", "LOWS", "CLOSE", "AFTER",
        "BEFORE", "MARKET", "TRADE", "STOCK", "SHARE", "PRICE",
        "MONEY", "BANKS", "CHART", "WATCH", "PLAY", "PLAN",
        "NEWS", "DATA", "NEXT", "LAST", "THIS", "THAT", "WHAT",
        "WHEN", "WHERE", "WILL", "WITH", "FROM", "HAVE", "BEEN",
        "THEY", "THEM", "THAN", "THEN", "SOME", "SAID", "EACH",
        "MUCH", "ALSO", "INTO", "OVER", "JUST", "LIKE", "TIME",
        "YEAR", "MORE", "VERY", "WELL", "KNOW", "GOOD", "MADE",
        "MAKE", "TAKE", "LOOK", "COME", "THINK", "SAID", "WANT",
        "GIVE", "MOST", "TELL", "FEEL", "SEEM", "KEEP", "STILL",
        "BACK", "DOWN", "WEEK", "DAYS", "AAAA", "BBBB",
    },

    # Database fil
    "db_path": "mentions.db",

    # Output mappe
    "output_dir": ".",

    # Sekunder mellem requests (vær pæn mod serverne)
    "request_delay": 1.0,

    # User-agent til HTTP requests
    "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

# ─────────────────────────────────────────────
# SENTIMENT ORDLISTER
# ─────────────────────────────────────────────

POSITIVE_WORDS = {
    "buy", "bull", "bullish", "moon", "rocket", "pump", "long", "calls",
    "breakout", "squeeze", "surge", "rally", "gain", "profit", "win",
    "winner", "upside", "upgrade", "beat", "strong", "growth", "up",
    "higher", "rise", "rising", "boom", "explode", "soar", "fly",
    "undervalued", "cheap", "opportunity", "catalyst", "positive",
    "great", "amazing", "love", "hold", "hodl", "diamond", "hands",
    "potential", "momentum", "buy", "accumulate", "load", "dip",
}

NEGATIVE_WORDS = {
    "sell", "bear", "bearish", "short", "puts", "dump", "crash", "drop",
    "fall", "falling", "down", "lower", "loss", "lose", "loser", "bad",
    "overvalued", "expensive", "sell", "avoid", "warning", "risk",
    "danger", "decline", "negative", "weak", "slow", "bubble", "fraud",
    "scam", "rekt", "bag", "bagholder", "dead", "bankrupt", "fail",
    "trap", "fake", "disappointing", "miss", "missed", "downgrade",
}

# ─────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────

def init_db(db_path):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS mentions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker      TEXT NOT NULL,
            date        TEXT NOT NULL,
            source      TEXT NOT NULL,
            mentions    INTEGER DEFAULT 0,
            sentiment   REAL DEFAULT 0.0,
            created_at  TEXT DEFAULT (datetime('now'))
        )
    """)
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_ticker_date
        ON mentions (ticker, date)
    """)
    conn.commit()
    return conn


def save_mentions(conn, date_str, ticker_data):
    """
    ticker_data: dict { ticker: { source: {mentions, sentiment_sum, sentiment_count} } }
    """
    c = conn.cursor()
    for ticker, sources in ticker_data.items():
        for source, data in sources.items():
            mentions = data["mentions"]
            sent_count = data["sentiment_count"]
            sentiment = (data["sentiment_sum"] / sent_count) if sent_count > 0 else 0.0

            # Upsert: hvis (ticker, date, source) allerede findes, opdater
            c.execute("""
                INSERT INTO mentions (ticker, date, source, mentions, sentiment)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT DO NOTHING
            """, (ticker, date_str, source, mentions, round(sentiment, 3)))

            # Hvis ovenstående ikke virkede (ældre SQLite), prøv update
            c.execute("""
                UPDATE mentions
                SET mentions = ?, sentiment = ?
                WHERE ticker = ? AND date = ? AND source = ?
                  AND (mentions != ? OR sentiment != ?)
            """, (mentions, round(sentiment, 3), ticker, date_str, source,
                  mentions, round(sentiment, 3)))

    conn.commit()


def get_mentions_for_date(conn, date_str):
    c = conn.cursor()
    c.execute("""
        SELECT ticker, SUM(mentions), AVG(sentiment)
        FROM mentions
        WHERE date = ?
        GROUP BY ticker
    """, (date_str,))
    return {row[0]: {"mentions": row[1], "sentiment": row[2]} for row in c.fetchall()}


def get_mentions_for_range(conn, start_date, end_date):
    c = conn.cursor()
    c.execute("""
        SELECT ticker, SUM(mentions), AVG(sentiment)
        FROM mentions
        WHERE date >= ? AND date <= ?
        GROUP BY ticker
    """, (start_date, end_date))
    return {row[0]: {"mentions": row[1], "sentiment": row[2]} for row in c.fetchall()}


# ─────────────────────────────────────────────
# TICKER EXTRACTION
# ─────────────────────────────────────────────

def extract_tickers_from_text(text, stopwords):
    """
    Finder ticker-kandidater i tekst.
    Prioriterer $TICKER format, men finder også rene uppercase ord.
    Returnerer: dict { ticker: (mentions, sentiment_score) }
    """
    if not text:
        return {}

    text_lower = text.lower()
    words = text.split()

    ticker_mentions = collections.defaultdict(int)

    # 1. $TICKER format (højeste prioritet)
    dollar_tickers = re.findall(r'\$([A-Z]{1,5})\b', text)
    for t in dollar_tickers:
        if t not in stopwords and len(t) >= 1:
            ticker_mentions[t] += 2  # Vægt 2 for eksplicit $-mention

    # 2. Rene uppercase ord (1-5 bogstaver)
    upper_words = re.findall(r'\b([A-Z]{1,5})\b', text)
    for t in upper_words:
        if t not in stopwords and len(t) >= 2:
            ticker_mentions[t] += 1

    # Beregn sentiment for denne tekst
    pos = sum(1 for w in words if w.lower() in POSITIVE_WORDS)
    neg = sum(1 for w in words if w.lower() in NEGATIVE_WORDS)
    total = pos + neg
    sentiment = (pos - neg) / total if total > 0 else 0.0

    return ticker_mentions, sentiment


# ─────────────────────────────────────────────
# DATA SOURCES
# ─────────────────────────────────────────────

def fetch_url(url, headers=None, delay=True):
    if delay:
        time.sleep(CONFIG["request_delay"])
    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", CONFIG["user_agent"])
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"  [FEJL] {url[:60]}... → {e}")
        return None


def scrape_reddit(subreddit, sort="hot", limit=100):
    """Henter posts fra Reddit JSON API — ingen login kræves."""
    url = f"https://www.reddit.com/r/{subreddit}/{sort}.json?limit={limit}"
    raw = fetch_url(url, headers={"Accept": "application/json"})
    if not raw:
        return []

    try:
        data = json.loads(raw)
        posts = data.get("data", {}).get("children", [])
        texts = []
        for post in posts:
            p = post.get("data", {})
            title = p.get("title", "")
            body = p.get("selftext", "")
            texts.append(f"{title} {body}")
        return texts
    except Exception as e:
        print(f"  [FEJL] Reddit parse ({subreddit}): {e}")
        return []


def scrape_yahoo_finance_news(ticker):
    """Henter seneste nyheder fra Yahoo Finance RSS."""
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
    raw = fetch_url(url)
    if not raw:
        return []

    # Simpel regex-parse af RSS
    items = re.findall(r'<title><!\[CDATA\[(.*?)\]\]></title>', raw)
    descriptions = re.findall(r'<description><!\[CDATA\[(.*?)\]\]></description>', raw)
    return [html.unescape(t) + " " + html.unescape(d)
            for t, d in zip(items, descriptions)]


def scrape_finviz_news(pages=3):
    """Henter nyheder fra Finviz news-siden."""
    texts = []
    for page in range(1, pages + 1):
        url = f"https://finviz.com/news.ashx?v=3&p={page}"
        raw = fetch_url(url)
        if not raw:
            continue

        # Find nyhedsoverskrifter
        headlines = re.findall(
            r'class="nn-tab-link"[^>]*>(.*?)</a>',
            raw, re.DOTALL
        )
        for h in headlines:
            clean = re.sub(r'<[^>]+>', '', h).strip()
            if clean:
                texts.append(clean)

    return texts


def scrape_stocktwits_trending():
    """Henter trending tickers fra StockTwits (offentligt API)."""
    url = "https://api.stocktwits.com/api/2/trending/symbols.json"
    raw = fetch_url(url)
    if not raw:
        return []

    try:
        data = json.loads(raw)
        symbols = data.get("symbols", [])
        texts = []
        for s in symbols:
            ticker = s.get("symbol", "")
            title = s.get("title", "")
            texts.append(f"${ticker} {title}")
        return texts
    except Exception as e:
        print(f"  [FEJL] StockTwits: {e}")
        return []


# ─────────────────────────────────────────────
# ANALYSE
# ─────────────────────────────────────────────

def aggregate_texts(texts, stopwords):
    """
    Kører ticker-extraction på alle tekster.
    Returnerer: dict { ticker: {mentions, sentiment_sum, sentiment_count} }
    """
    aggregated = collections.defaultdict(lambda: {
        "mentions": 0,
        "sentiment_sum": 0.0,
        "sentiment_count": 0,
    })

    for text in texts:
        if not text.strip():
            continue
        ticker_counts, sentiment = extract_tickers_from_text(text, stopwords)
        for ticker, count in ticker_counts.items():
            aggregated[ticker]["mentions"] += count
            aggregated[ticker]["sentiment_sum"] += sentiment
            aggregated[ticker]["sentiment_count"] += 1

    return dict(aggregated)


def calculate_changes(today_data, yesterday_data, week_data, prev_week_data):
    """
    Beregner dag-til-dag og 7v7 ændringer.
    Ingen minimumsgrænse — alle tickers inkluderes.
    """
    all_tickers = set(today_data.keys()) | set(yesterday_data.keys())

    results = []
    for ticker in all_tickers:
        today_m = today_data.get(ticker, {}).get("mentions", 0)
        yesterday_m = yesterday_data.get(ticker, {}).get("mentions", 0)
        week_m = week_data.get(ticker, {}).get("mentions", 0)
        prev_week_m = prev_week_data.get(ticker, {}).get("mentions", 0)
        sentiment = today_data.get(ticker, {}).get("sentiment", 0.0) or 0.0

        # Dag-til-dag change
        if yesterday_m > 0:
            dtd_pct = ((today_m - yesterday_m) / yesterday_m) * 100
        elif today_m > 0:
            dtd_pct = float("inf")  # Ny ticker i dag
        else:
            dtd_pct = 0.0

        # 7 vs 7 change
        if prev_week_m > 0:
            w7_pct = ((week_m - prev_week_m) / prev_week_m) * 100
        elif week_m > 0:
            w7_pct = float("inf")
        else:
            w7_pct = 0.0

        results.append({
            "ticker": ticker,
            "mentions_today": today_m,
            "mentions_yesterday": yesterday_m,
            "dtd_pct": dtd_pct,
            "mentions_7d": week_m,
            "mentions_prev_7d": prev_week_m,
            "w7_pct": w7_pct,
            "sentiment": round(sentiment, 3),
        })

    return results


def format_pct(val):
    if val == float("inf"):
        return "NY"
    if val == 0.0:
        return "0%"
    return f"{val:+.1f}%"


# ─────────────────────────────────────────────
# RAPPORT
# ─────────────────────────────────────────────

def write_csv(results, date_str, output_dir):
    filename = os.path.join(output_dir, f"rapport_{date_str}.csv")
    fieldnames = [
        "ticker",
        "mentions_today",
        "mentions_yesterday",
        "dtd_pct",
        "mentions_7d",
        "mentions_prev_7d",
        "w7_pct",
        "sentiment",
    ]
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in results:
            writer.writerow({
                **row,
                "dtd_pct": format_pct(row["dtd_pct"]),
                "w7_pct": format_pct(row["w7_pct"]),
            })
    return filename


def print_terminal_report(results, date_str):
    print("\n" + "═" * 70)
    print(f"  MENTION SCANNER — {date_str}")
    print("═" * 70)

    # Top 20 absolut
    top_absolute = sorted(results, key=lambda x: x["mentions_today"], reverse=True)[:20]
    print(f"\n📊 TOP 20 — ABSOLUT (flest mentions i dag)\n")
    print(f"  {'TICKER':<8} {'I DAG':>7} {'I GÅR':>7} {'DAG/DAG':>9} {'7D':>7} {'PREV 7D':>8} {'7V7':>9}  SENTIMENT")
    print("  " + "─" * 68)
    for r in top_absolute:
        sent_icon = "▲" if r["sentiment"] > 0.1 else ("▼" if r["sentiment"] < -0.1 else "─")
        print(
            f"  {r['ticker']:<8} "
            f"{r['mentions_today']:>7} "
            f"{r['mentions_yesterday']:>7} "
            f"{format_pct(r['dtd_pct']):>9} "
            f"{r['mentions_7d']:>7} "
            f"{r['mentions_prev_7d']:>8} "
            f"{format_pct(r['w7_pct']):>9}  "
            f"{sent_icon} {r['sentiment']:+.2f}"
        )

    # Top 20 relativ stigning (dag-til-dag) — minimum 2 mentions i dag
    def sort_key_dtd(x):
        if x["dtd_pct"] == float("inf"):
            return 99999
        return x["dtd_pct"]

    top_relative_dtd = sorted(
        [r for r in results if r["mentions_today"] >= 2],
        key=sort_key_dtd,
        reverse=True
    )[:20]

    print(f"\n🚀 TOP 20 — RELATIV STIGNING (dag-til-dag)\n")
    print(f"  {'TICKER':<8} {'DAG/DAG':>9} {'I DAG':>7} {'I GÅR':>7}  SENTIMENT")
    print("  " + "─" * 45)
    for r in top_relative_dtd:
        sent_icon = "▲" if r["sentiment"] > 0.1 else ("▼" if r["sentiment"] < -0.1 else "─")
        print(
            f"  {r['ticker']:<8} "
            f"{format_pct(r['dtd_pct']):>9} "
            f"{r['mentions_today']:>7} "
            f"{r['mentions_yesterday']:>7}  "
            f"{sent_icon} {r['sentiment']:+.2f}"
        )

    # Top 20 relativ stigning (7v7) — minimum 3 mentions seneste 7 dage
    def sort_key_7v7(x):
        if x["w7_pct"] == float("inf"):
            return 99999
        return x["w7_pct"]

    top_relative_7v7 = sorted(
        [r for r in results if r["mentions_7d"] >= 3],
        key=sort_key_7v7,
        reverse=True
    )[:20]

    print(f"\n📈 TOP 20 — RELATIV STIGNING (7 vs 7 dage)\n")
    print(f"  {'TICKER':<8} {'7V7':>9} {'7D MENTIONS':>12} {'PREV 7D':>8}  SENTIMENT")
    print("  " + "─" * 50)
    for r in top_relative_7v7:
        sent_icon = "▲" if r["sentiment"] > 0.1 else ("▼" if r["sentiment"] < -0.1 else "─")
        print(
            f"  {r['ticker']:<8} "
            f"{format_pct(r['w7_pct']):>9} "
            f"{r['mentions_7d']:>12} "
            f"{r['mentions_prev_7d']:>8}  "
            f"{sent_icon} {r['sentiment']:+.2f}"
        )

    print("\n" + "═" * 70 + "\n")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    today = datetime.date.today()
    today_str = today.isoformat()
    yesterday_str = (today - datetime.timedelta(days=1)).isoformat()
    week_start_str = (today - datetime.timedelta(days=6)).isoformat()
    prev_week_end_str = (today - datetime.timedelta(days=7)).isoformat()
    prev_week_start_str = (today - datetime.timedelta(days=13)).isoformat()

    print(f"\n{'═'*70}")
    print(f"  MENTION SCANNER — starter {today_str}")
    print(f"{'═'*70}\n")

    # Init database
    conn = init_db(CONFIG["db_path"])
    print(f"[DB] Forbundet til {CONFIG['db_path']}")

    # ── LAG 1: Datahentning ──────────────────────────────────────────────

    all_texts_by_source = {}

    # Reddit
    print(f"\n[REDDIT] Henter fra {len(CONFIG['subreddits'])} subreddits...")
    reddit_texts = []
    for sub in CONFIG["subreddits"]:
        print(f"  r/{sub}...", end=" ", flush=True)
        texts = scrape_reddit(sub, CONFIG["reddit_sort"], CONFIG["reddit_limit"])
        print(f"{len(texts)} posts")
        reddit_texts.extend(texts)
    all_texts_by_source["reddit"] = reddit_texts

    # StockTwits trending
    print(f"\n[STOCKTWITS] Henter trending symbols...")
    st_texts = scrape_stocktwits_trending()
    print(f"  {len(st_texts)} trending symbols")
    all_texts_by_source["stocktwits"] = st_texts

    # Yahoo Finance nyheder (hvis tickers er konfigureret)
    if CONFIG["yahoo_tickers"]:
        print(f"\n[YAHOO] Henter nyheder for {len(CONFIG['yahoo_tickers'])} tickers...")
        yahoo_texts = []
        for ticker in CONFIG["yahoo_tickers"]:
            print(f"  {ticker}...", end=" ", flush=True)
            texts = scrape_yahoo_finance_news(ticker)
            print(f"{len(texts)} nyheder")
            yahoo_texts.extend(texts)
        all_texts_by_source["yahoo"] = yahoo_texts

    # Finviz news
    print(f"\n[FINVIZ] Henter nyheder ({CONFIG['finviz_pages']} sider)...")
    finviz_texts = scrape_finviz_news(CONFIG["finviz_pages"])
    print(f"  {len(finviz_texts)} overskrifter")
    all_texts_by_source["finviz"] = finviz_texts

    # ── LAG 2: Ticker extraction + aggregering ───────────────────────────

    print(f"\n[ANALYSE] Ekstraherer tickers og beregner mentions...")
    stopwords = CONFIG["stopwords"]

    ticker_by_source = {}
    total_texts = 0
    for source, texts in all_texts_by_source.items():
        total_texts += len(texts)
        ticker_by_source[source] = aggregate_texts(texts, stopwords)
        unique = len(ticker_by_source[source])
        print(f"  {source}: {len(texts)} tekster → {unique} unikke ticker-kandidater")

    print(f"\n  Total: {total_texts} tekster analyseret")

    # Gem i database
    print(f"\n[DB] Gemmer dagens data ({today_str})...")
    # Strukturér til save_mentions format
    for source, ticker_data in ticker_by_source.items():
        save_data = {
            ticker: {source: data}
            for ticker, data in ticker_data.items()
        }
        save_mentions(conn, today_str, save_data)
    print(f"  Gemt.")

    # ── LAG 3: Beregn ændringer fra historik ────────────────────────────

    print(f"\n[RAPPORT] Beregner ændringer...")

    today_agg   = get_mentions_for_date(conn, today_str)
    yest_agg    = get_mentions_for_date(conn, yesterday_str)
    week_agg    = get_mentions_for_range(conn, week_start_str, today_str)
    prev_w_agg  = get_mentions_for_range(conn, prev_week_start_str, prev_week_end_str)

    results = calculate_changes(today_agg, yest_agg, week_agg, prev_w_agg)

    # Sorter default: mentions i dag, faldende
    results.sort(key=lambda x: x["mentions_today"], reverse=True)

    # Terminal output
    print_terminal_report(results, today_str)

    # CSV output
    csv_path = write_csv(results, today_str, CONFIG["output_dir"])
    print(f"[CSV] Gemt: {csv_path}")
    print(f"[DB]  Historik: {CONFIG['db_path']}\n")

    conn.close()


if __name__ == "__main__":
    main()
