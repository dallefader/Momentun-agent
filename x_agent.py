"""
x_agent.py – Momentum Mike X Agent
Genererer opslag baseret på scanner + mentions + portefølje.
Du godkender hvert opslag inden det sendes.
"""

import json
import logging
import time
import os
import sqlite3
from datetime import datetime, date

import anthropic
import tweepy
import yfinance as yf

import scanner_db as sdb
import portfolio as pf

# ─────────────────────────────────────────────
# KONFIGURATION ← udfyld disse
# ─────────────────────────────────────────────

ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
X_API_KEY          = os.environ.get("X_API_KEY", "")
X_API_SECRET       = os.environ.get("X_API_SECRET", "")
X_ACCESS_TOKEN     = os.environ.get("X_ACCESS_TOKEN", "")
X_ACCESS_SECRET    = os.environ.get("X_ACCESS_SECRET", "")
X_BEARER_TOKEN     = os.environ.get("X_BEARER_TOKEN", "")

MENTIONS_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mentions.db")

# ─────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('x_agent.log'),
        logging.StreamHandler()
    ]
)
LOG = logging.getLogger('x_agent')

BUY_SIGNALS = {'BUY NOW', 'BUY BREAKOUT', 'BUILD POSITION', 'STARTER BUY'}

MIKE_PERSONALITY = """
Du er Momentum Mike – en data-drevet trader der kører et offentligt algoritmisk handelseksperiment.

Din personlighed:
- Selvironisk og ydmyg – du tager data seriøst men aldrig dig selv
- Transparent – du viser ALTID både vindere og tabere
- Underholdende men seriøs – "sjovt men seriøst eksperiment"
- Du siger ALDRIG "køb dette" – du siger "scanner flagged this"
- Du lover ALDRIG afkast
- Du er altid præcis med datoer og priser

Din stemme i eksempler:
  Signal: "The scanner just flagged $TICKER. Stage 2. RS Rank XX. I don't know if this works. The algorithm does."
  Tab: "$TICKER stopped out. -X%. Scanner was wrong. Or the market was. Either way — full transparency. 🧪"
  Win: "X days ago the scanner flagged $TICKER at $XX. Today: $XX. +X%. Not luck. Just signals. 🧪"

Regler:
- Max 280 tegn per tweet
- Brug altid $TICKER format (cashtag)
- Max 2 hashtags – altid #MomentumMike + én relevant
- Brug 🧪 emoji som Momentum Mike's signatur
- Skriv på engelsk
- Hook i første linje – stop scrollet
"""


# ─────────────────────────────────────────────
# X API
# ─────────────────────────────────────────────

def get_x_client():
    return tweepy.Client(
        bearer_token=X_BEARER_TOKEN,
        consumer_key=X_API_KEY,
        consumer_secret=X_API_SECRET,
        access_token=X_ACCESS_TOKEN,
        access_token_secret=X_ACCESS_SECRET
    )


def post_tweet(text):
    """Post tweet til X."""
    client = get_x_client()
    response = client.create_tweet(text=text)
    return response.data['id']


# ─────────────────────────────────────────────
# MENTIONS DATA
# ─────────────────────────────────────────────

def get_trending_mentions(top_n=5):
    """Hent tickers med størst stigning i mentions i dag."""
    if not os.path.exists(MENTIONS_DB):
        return []
    conn = sqlite3.connect(MENTIONS_DB)
    today = date.today().isoformat()
    yesterday = (date.today().replace(day=date.today().day - 1)).isoformat()
    c = conn.cursor()
    c.execute("""
        SELECT ticker, SUM(mentions) as today_mentions
        FROM mentions WHERE date = ?
        GROUP BY ticker ORDER BY today_mentions DESC LIMIT 20
    """, (today,))
    today_data = {r[0]: r[1] for r in c.fetchall()}
    c.execute("""
        SELECT ticker, SUM(mentions) as yest_mentions
        FROM mentions WHERE date = ?
        GROUP BY ticker
    """, (yesterday,))
    yest_data = {r[0]: r[1] for r in c.fetchall()}
    conn.close()

    results = []
    for ticker, today_m in today_data.items():
        yest_m = yest_data.get(ticker, 0)
        if today_m >= 5:
            change = float('inf') if yest_m == 0 else ((today_m - yest_m) / yest_m) * 100
            results.append({"ticker": ticker, "mentions": today_m, "change": change})

    results.sort(key=lambda x: x["mentions"], reverse=True)
    return results[:top_n]


# ─────────────────────────────────────────────
# GENERÉR OPSLAG
# ─────────────────────────────────────────────

def generate_post(client, post_type, context):
    """Generér et X-opslag via Claude."""
    prompt = f"""{MIKE_PERSONALITY}

Genér ET X-opslag af typen: {post_type}

Kontekst:
{json.dumps(context, indent=2, ensure_ascii=False)}

Krav:
- Max 280 tegn
- Stærk hook i første linje
- Brug $TICKER cashtag
- Max 2 hashtags
- Slut med 🧪
- Skriv KUN selve tweet-teksten – ingen forklaringer

Tweet:"""

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text.strip().strip('"')


def get_current_price(ticker):
    """Hent aktuel pris via yfinance."""
    try:
        tk = yf.Ticker(ticker)
        price = tk.info.get('regularMarketPrice') or tk.info.get('currentPrice')
        return round(float(price), 2) if price else None
    except:
        return None


# ─────────────────────────────────────────────
# GODKENDELSESFLOW
# ─────────────────────────────────────────────

def approve_and_post(post_text, post_type, trade_data=None):
    """Vis opslag til godkendelse og post hvis godkendt."""
    print("\n" + "═" * 60)
    print(f"  📱 MOMENTUM MIKE – {post_type}")
    print("═" * 60)
    print(f"\n{post_text}\n")
    print(f"  Tegn: {len(post_text)}/280")
    print("═" * 60)
    print("\n  [G] Godkend og post")
    print("  [R] Rediger")
    print("  [S] Skip")
    print()

    choice = input("  Dit valg: ").strip().upper()

    if choice == 'G':
        try:
            tweet_id = post_tweet(post_text)
            LOG.info(f"✅ Postet! Tweet ID: {tweet_id}")
            if trade_data:
                pf.mark_posted(trade_data['id'], post_text)
            print(f"\n  ✅ Postet! https://x.com/MomentumMikeAI/status/{tweet_id}\n")
            return True
        except Exception as e:
            LOG.error(f"Post fejlede: {e}")
            print(f"\n  ❌ Fejl: {e}\n")
            return False

    elif choice == 'R':
        new_text = input("\n  Ny tekst (Enter for at beholde original):\n  > ").strip()
        if new_text:
            return approve_and_post(new_text, post_type, trade_data)
        return approve_and_post(post_text, post_type, trade_data)

    else:
        print("  ⏭️  Skipped\n")
        return False


# ─────────────────────────────────────────────
# POST-TYPER
# ─────────────────────────────────────────────

def post_new_signal(client, candidate):
    """Post nyt BUY-signal og tilføj til portefølje."""
    ticker  = candidate['ticker']
    name    = candidate.get('name', ticker)
    signal  = candidate.get('buy', '')
    score   = candidate.get('score', 0)
    price   = candidate.get('price', 0)
    rs_rank = candidate.get('rs_rank', 0)
    stage   = candidate.get('stage', '')
    sector  = candidate.get('sector', '')

    context = {
        "ticker": ticker,
        "name": name,
        "signal": signal,
        "score": score,
        "price": price,
        "rs_rank": rs_rank,
        "stage": stage,
        "sector": sector,
        "type": "Nyt scanner-signal – præsenter det som et eksperiment"
    }

    post_text = generate_post(client, "NYT SIGNAL", context)

    trade_data = None
    if approve_and_post(post_text, f"NYT SIGNAL – {ticker}"):
        trade_id = pf.add_trade(ticker, name, signal, score, sector, '', price)
        trade_data = {"id": trade_id}
        pf.mark_posted(trade_id, post_text)
        LOG.info(f"Trade tilføjet: {ticker} @ {price}")


def post_followup(client, trade, current_price):
    """Post follow-up opslag på en trade efter X dage."""
    entry_price = trade['entry_price']
    entry_date  = trade['entry_date']
    ticker      = trade['ticker']
    return_pct  = round(((current_price - entry_price) / entry_price) * 100, 2)
    days_held   = (date.today() - datetime.strptime(entry_date, '%Y-%m-%d').date()).days

    context = {
        "ticker": ticker,
        "entry_price": entry_price,
        "current_price": current_price,
        "return_pct": return_pct,
        "days_held": days_held,
        "entry_date": entry_date,
        "winning": return_pct > 0,
        "type": "Follow-up opslag – vis resultatet transparent"
    }

    post_type = f"{'✅ WIN' if return_pct > 0 else '❌ TAB'} FOLLOW-UP"
    post_text = generate_post(client, post_type, context)
    approve_and_post(post_text, f"{post_type} – {ticker}", trade)


def post_portfolio_update(client):
    """Post ugentlig portefølje-opdatering."""
    perf = pf.get_performance()
    if perf['total_trades'] == 0:
        return

    context = {
        "total_trades": perf['total_trades'],
        "open_trades": perf['open_trades'],
        "closed_trades": perf['closed_trades'],
        "win_rate": perf['win_rate'],
        "avg_return": perf['avg_return'],
        "total_return": perf['total_return'],
        "type": "Ugentlig P&L opdatering – transparent og ydmyg"
    }

    post_text = generate_post(client, "PORTEFØLJE UPDATE", context)
    approve_and_post(post_text, "PORTEFØLJE UPDATE")


def post_mention_spike(client, mention):
    """Post om aktie med pludselig stigning i social mentions."""
    ticker   = mention['ticker']
    mentions = mention['mentions']
    change   = mention['change']

    scan = sdb.read_scan_results()
    scanner_signal = "Ikke i scanner"
    if not scan.empty:
        row = scan[scan['ticker'] == ticker]
        if not row.empty:
            scanner_signal = row.iloc[0]['buy']

    context = {
        "ticker": ticker,
        "mentions_today": mentions,
        "mention_change": f"+{change:.0f}%" if change != float('inf') else "NY",
        "scanner_signal": scanner_signal,
        "type": "Social media buzz – folk snakker om denne aktie"
    }

    post_text = generate_post(client, "MENTION SPIKE", context)
    approve_and_post(post_text, f"MENTION SPIKE – {ticker}")


def post_market_open(client):
    """Post ved US market open (kl. 15:30 dansk tid)."""
    scan = sdb.read_scan_results()
    meta = sdb.get_scan_meta()
    regime = meta.get('regime', 'NEUTRAL') if meta else 'NEUTRAL'

    buy_count = 0
    if not scan.empty:
        buy_count = len(scan[scan['buy'].isin(BUY_SIGNALS)])

    context = {
        "regime": regime,
        "buy_signals": buy_count,
        "time": "US market just opened",
        "type": "Market open tweet – hvad ser scanneren lige nu?"
    }

    post_text = generate_post(client, "MARKET OPEN", context)
    approve_and_post(post_text, "US MARKET OPEN")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    print("\n" + "═" * 60)
    print("  MOMENTUM MIKE – X AGENT")
    print("═" * 60)
    print("\nHvad vil du poste?\n")
    print("  [1] Nye BUY-signaler fra scanner")
    print("  [2] Follow-up på åbne trades (7/14/30 dage)")
    print("  [3] Portefølje-opdatering")
    print("  [4] Mention spike (hvad taler folk om?)")
    print("  [5] Market open tweet")
    print("  [6] Kør alle automatisk")
    print("  [Q] Afslut")
    print()

    choice = input("  Vælg: ").strip()

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    pf.init_db()

    if choice == '1':
        scan = sdb.read_scan_results()
        if scan.empty:
            print("Ingen scan-data.")
            return
        candidates = scan[
            scan['buy'].isin(BUY_SIGNALS) &
            (scan['sector'] != 'REF')
        ].head(5).to_dict(orient='records')

        print(f"\nFandt {len(candidates)} kandidater:\n")
        for i, c in enumerate(candidates):
            print(f"  [{i+1}] {c['ticker']} – {c['buy']} (score: {c['score']})")

        pick = input("\n  Vælg nummer (eller Enter for første): ").strip()
        idx = int(pick) - 1 if pick.isdigit() else 0
        post_new_signal(client, candidates[idx])

    elif choice == '2':
        open_trades = pf.get_open_trades()
        if not open_trades:
            print("Ingen åbne trades.")
            return
        for trade in open_trades:
            price = get_current_price(trade['ticker'])
            if price:
                post_followup(client, trade, price)
                time.sleep(5)

    elif choice == '3':
        post_portfolio_update(client)

    elif choice == '4':
        mentions = get_trending_mentions()
        if not mentions:
            print("Ingen mention-data.")
            return
        print(f"\nTop mentions i dag:\n")
        for i, m in enumerate(mentions):
            chg = f"+{m['change']:.0f}%" if m['change'] != float('inf') else "NY"
            print(f"  [{i+1}] {m['ticker']} – {m['mentions']} mentions ({chg})")

        pick = input("\n  Vælg nummer: ").strip()
        if pick.isdigit():
            idx = int(pick) - 1
            post_mention_spike(client, mentions[idx])

    elif choice == '5':
        post_market_open(client)

    elif choice == '6':
        LOG.info("Kører alle post-typer...")

        # Nye signaler
        scan = sdb.read_scan_results()
        if not scan.empty:
            candidates = scan[
                scan['buy'].isin(BUY_SIGNALS) &
                (scan['sector'] != 'REF')
            ].head(3).to_dict(orient='records')
            for c in candidates:
                post_new_signal(client, c)
                time.sleep(5)

        # Follow-ups
        for days in [7, 14, 30]:
            trades = pf.get_trades_for_followup(days)
            for trade in trades:
                price = get_current_price(trade['ticker'])
                if price:
                    post_followup(client, trade, price)
                    time.sleep(5)

        # Mention spikes
        mentions = get_trending_mentions(top_n=2)
        for m in mentions:
            post_mention_spike(client, m)
            time.sleep(5)

    print("\n✅ X Agent færdig\n")


if __name__ == '__main__':
    main()