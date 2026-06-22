"""
worker.py – Baggrunds-scanner for Trading Terminal Pro
Kører automatisk og opdaterer scanner.db uden at røre ved UI'et.

SCHEMA (dansk tid / CET):
  - Fuld scan af alle aktier:  08:00, 13:00, 16:00, 19:00, 21:00
  - Research email:            08:00
  - Mention scan:              08:00, 13:00, 16:00, 19:00, 21:00
  - BUY-kandidater:            Hver time
"""

import os
import fcntl
import time
import logging
import subprocess
import sys
from datetime import datetime

import scanner_db as sdb

# ── Enkelt-instans lås ───────────────────────────────────────
_LOCK_FILE = '/tmp/scanner_worker.lock'
_lock_fh = None

def _acquire_lock():
    global _lock_fh
    _lock_fh = open(_LOCK_FILE, 'w')
    try:
        fcntl.flock(_lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _lock_fh.write(str(os.getpid()))
        _lock_fh.flush()
    except IOError:
        print(f"[worker] En anden instans kører allerede — afslutter (PID {os.getpid()})", flush=True)
        sys.exit(0)

# ── Logging ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('worker.log'),
        logging.StreamHandler()
    ]
)
LOG = logging.getLogger('worker')

# ── Tidspunkter for fuld scan (24-timers format) ─────────────
FULL_SCAN_HOURS = {8, 13, 16, 19, 21}  # dansk tid — dækker EU-åbning, US-åbning, mid-session og close


def push_to_github():
    """Push seneste scan-data til GitHub så Streamlit Cloud opdaterer."""
    try:
        ts = datetime.now().strftime('%Y-%m-%d %H:%M')
        subprocess.run(['git', 'add', 'scanner.db', 'signals_history.json',
                        'positions.json', 'watchlist.json'],
                       capture_output=True, cwd=os.path.dirname(os.path.abspath(__file__)))
        result = subprocess.run(
            ['git', 'commit', '-m', f'scan: {ts}'],
            capture_output=True, text=True,
            cwd=os.path.dirname(os.path.abspath(__file__))
        )
        if 'nothing to commit' in result.stdout:
            LOG.info("Git: ingen ændringer at pushe")
            return
        push = subprocess.run(['git', 'push'],
                              capture_output=True, text=True,
                              cwd=os.path.dirname(os.path.abspath(__file__)))
        if push.returncode == 0:
            LOG.info("GitHub push ✅")
        else:
            LOG.warning(f"GitHub push fejlede: {push.stderr[:200]}")
    except Exception as e:
        LOG.warning(f"GitHub push fejl: {e}")


def run_scan(mode='full'):
    """Kør aktie-scanner som subprocess."""
    LOG.info(f"{'FULD' if mode == 'full' else 'BUY'} SCAN starter – {datetime.now().strftime('%H:%M')}")
    try:
        result = subprocess.run(
            [sys.executable, 'scan_runner.py', mode],
            capture_output=True,
            text=True,
            timeout=7200
        )
        if result.returncode == 0:
            LOG.info(f"SCAN færdig ✅\n{result.stdout[-500:] if result.stdout else ''}")
            push_to_github()
        else:
            LOG.error(f"SCAN fejlede ❌\n{result.stderr[-500:] if result.stderr else ''}")
    except subprocess.TimeoutExpired:
        LOG.error("SCAN timeout efter 2 timer")
    except Exception as e:
        LOG.error(f"SCAN fejl: {e}")


def run_research_agent():
    """Kør research agent som subprocess — sender HTML-email med top 5 analyse."""
    LOG.info("RESEARCH AGENT starter...")
    try:
        result = subprocess.run(
            [sys.executable, 'research_agent.py'],
            capture_output=True,
            text=True,
            timeout=300
        )
        if result.returncode == 0:
            LOG.info("RESEARCH AGENT færdig ✅")
        else:
            LOG.error(f"RESEARCH AGENT fejlede ❌\n{result.stderr[-300:] if result.stderr else ''}")
    except subprocess.TimeoutExpired:
        LOG.error("RESEARCH AGENT timeout efter 5 minutter")
    except Exception as e:
        LOG.error(f"RESEARCH AGENT fejl: {e}")


def run_mention_scan():
    """Kør mention scanner som subprocess."""
    LOG.info("MENTION SCAN starter...")
    try:
        result = subprocess.run(
            [sys.executable, 'mention_scanner.py'],
            capture_output=True,
            text=True,
            timeout=600
        )
        if result.returncode == 0:
            LOG.info("MENTION SCAN færdig ✅")
        else:
            LOG.error(f"MENTION SCAN fejlede ❌\n{result.stderr[-300:] if result.stderr else ''}")
    except subprocess.TimeoutExpired:
        LOG.error("MENTION SCAN timeout efter 10 minutter")
    except Exception as e:
        LOG.error(f"MENTION SCAN fejl: {e}")


def main():
    _acquire_lock()
    LOG.info("=" * 55)
    LOG.info("  WORKER STARTER")
    LOG.info("=" * 55)

    sdb.init_db()

    last_full_hour = None
    last_buy_hour  = None

    # Kør fuld scan + mention scan ved opstart
    LOG.info("Opstart – kører fuld scan + mention scan...")
    run_scan('full')
    run_mention_scan()

    while True:
        now    = datetime.now()
        hour   = now.hour
        minute = now.minute

        # ── Fuld scan + mention scan: 08:00, 13:00, 16:00, 19:00, 21:00 ──
        if hour in FULL_SCAN_HOURS and last_full_hour != hour:
            last_full_hour = hour
            run_scan('full')
            run_mention_scan()
            if hour == 8:
                run_research_agent()

        # ── BUY scan: hver hele time (kun i minute < 5 vinduet) ──
        elif minute < 5 and last_buy_hour != hour:
            last_buy_hour = hour
            run_scan('buy')
            # Efter et langt BUY-scan: kør fuld scan hvis et vindue blev overskredet
            now2 = datetime.now()
            if now2.hour in FULL_SCAN_HOURS and last_full_hour != now2.hour:
                last_full_hour = now2.hour
                LOG.info(f"Indhenter misset fuld scan for time {now2.hour}")
                run_scan('full')
                run_mention_scan()

        time.sleep(60)


if __name__ == '__main__':
    main()