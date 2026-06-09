"""
portfolio.py – Virtuel portefølje tracker for Momentum Mike
Gemmer alle trades i SQLite og beregner performance.
"""

import sqlite3
from datetime import datetime, date
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "portfolio.db")


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker          TEXT NOT NULL,
            name            TEXT,
            signal          TEXT,
            score           INTEGER,
            sector          TEXT,
            region          TEXT,
            entry_price     REAL NOT NULL,
            entry_date      TEXT NOT NULL,
            exit_price      REAL,
            exit_date       TEXT,
            return_pct      REAL,
            status          TEXT DEFAULT 'OPEN',
            x_posted        INTEGER DEFAULT 0,
            x_post_content  TEXT,
            created_at      TEXT DEFAULT (datetime('now'))
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS performance (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            date            TEXT NOT NULL,
            total_trades    INTEGER,
            open_trades     INTEGER,
            closed_trades   INTEGER,
            win_rate        REAL,
            avg_return      REAL,
            total_return    REAL,
            created_at      TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()


def add_trade(ticker, name, signal, score, sector, region, entry_price):
    """Tilføj ny trade til porteføljen."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO trades (ticker, name, signal, score, sector, region,
                           entry_price, entry_date, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')
    """, (ticker, name, signal, score, sector, region,
          entry_price, date.today().isoformat()))
    trade_id = c.lastrowid
    conn.commit()
    conn.close()
    return trade_id


def close_trade(ticker, exit_price):
    """Luk en åben trade."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT id, entry_price FROM trades
        WHERE ticker = ? AND status = 'OPEN'
        ORDER BY entry_date DESC LIMIT 1
    """, (ticker,))
    row = c.fetchone()
    if not row:
        conn.close()
        return None
    trade_id, entry_price = row
    return_pct = ((exit_price - entry_price) / entry_price) * 100
    c.execute("""
        UPDATE trades SET exit_price=?, exit_date=?, return_pct=?, status='CLOSED'
        WHERE id=?
    """, (exit_price, date.today().isoformat(), round(return_pct, 2), trade_id))
    conn.commit()
    conn.close()
    return round(return_pct, 2)


def mark_posted(trade_id, post_content):
    """Marker trade som postet på X."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        UPDATE trades SET x_posted=1, x_post_content=? WHERE id=?
    """, (post_content, trade_id))
    conn.commit()
    conn.close()


def get_open_trades():
    """Hent alle åbne trades."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT id, ticker, name, signal, score, sector,
               entry_price, entry_date, x_posted
        FROM trades WHERE status = 'OPEN'
        ORDER BY entry_date DESC
    """)
    rows = c.fetchall()
    conn.close()
    return [{"id": r[0], "ticker": r[1], "name": r[2], "signal": r[3],
             "score": r[4], "sector": r[5], "entry_price": r[6],
             "entry_date": r[7], "x_posted": r[8]} for r in rows]


def get_performance():
    """Beregn samlet performance."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM trades")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM trades WHERE status='OPEN'")
    open_n = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM trades WHERE status='CLOSED'")
    closed = c.fetchone()[0]
    c.execute("""
        SELECT AVG(return_pct), SUM(return_pct),
               SUM(CASE WHEN return_pct > 0 THEN 1 ELSE 0 END)
        FROM trades WHERE status='CLOSED'
    """)
    row = c.fetchone()
    conn.close()
    avg_ret = round(row[0] or 0, 2)
    total_ret = round(row[1] or 0, 2)
    winners = row[2] or 0
    win_rate = round((winners / closed * 100) if closed > 0 else 0, 1)
    return {
        "total_trades": total,
        "open_trades": open_n,
        "closed_trades": closed,
        "win_rate": win_rate,
        "avg_return": avg_ret,
        "total_return": total_ret
    }


def get_trades_for_followup(days=7):
    """Hent trades der er X dage gamle og klar til follow-up opslag."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT id, ticker, name, signal, entry_price, entry_date, x_posted
        FROM trades
        WHERE status = 'OPEN'
        AND x_posted = 1
        AND CAST(julianday('now') - julianday(entry_date) AS INTEGER) = ?
    """, (days,))
    rows = c.fetchall()
    conn.close()
    return [{"id": r[0], "ticker": r[1], "name": r[2], "signal": r[3],
             "entry_price": r[4], "entry_date": r[5]} for r in rows]


if __name__ == "__main__":
    init_db()
    perf = get_performance()
    print(f"Portfolio: {perf['total_trades']} trades | "
          f"Open: {perf['open_trades']} | "
          f"Win rate: {perf['win_rate']}% | "
          f"Avg return: {perf['avg_return']}%")