# Trading Terminal Pro

Momentum-scanner der overvåger 1713 aktier fra US, Norden, Europa og Asien. Systemet henter data dagligt, beregner tekniske signaler og præsenterer resultater i et Streamlit-dashboard.

---

## Hurtig reference

**Start dashboard**
```bash
cd ~/momentum_agent && source venv/bin/activate && streamlit run scanner_v7.py
```

**Åbn kildekode**
```bash
open ~/momentum_agent/scanner_v7.py
```

**Kør manuel scan nu**
```bash
cd ~/momentum_agent && source venv/bin/activate && python3 scan_runner.py full
```

**Worker status**
```bash
launchctl list | grep scanner
tail -20 ~/momentum_agent/worker.log
```

**Stop / start worker**
```bash
launchctl stop com.db.scanner.worker
launchctl start com.db.scanner.worker
```

---

## Arkitektur

```
worker.py          Hoved-daemon. Styrer scan-tidsplan og starter subprocesser.
scan_runner.py     Kører selve scannet. Henter data via FMP + yfinance.
scanner_core.py    UNIVERSE (1713 aktier) + compute_scan algoritme + signallogik.
scanner_v7.py      Streamlit-dashboard. Læser fra scanner.db.
scanner_db.py      SQLite-lag. Læse/skrive til scanner.db.
fmp_fetcher.py     Financial Modeling Prep API + yfinance datahentning.
research_agent.py  Daglig AI-analyse af top 5 BUY-kandidater. Sender HTML-email.
mention_scanner.py Scanner Reddit, Yahoo Finance og Finviz for aktie-mentions.
```

---

## Scan-tidsplan (dansk tid)

| Tidspunkt | Handling |
|---|---|
| 08:00 | Fuld scan + research email + mention scan |
| 13:00 | Fuld scan + mention scan |
| 16:00 | Fuld scan + mention scan (30 min efter US åbner) |
| 19:00 | Fuld scan + mention scan (mid US session) |
| 21:00 | Fuld scan + mention scan |
| Hver hele time | BUY-scan (kun aktuelle BUY-kandidater) |

---

## Signaler

| Signal | Beskrivelse |
|---|---|
| **BUY NOW** | Momentum bekræftet. Stage 2, volumen +10% over snit, RSI 50–80. Stærkeste signal. |
| **BUY BREAKOUT** | Tæt på 20-dages top, volumen over snit, RSI 44–78. Breakout ikke fuldt bekræftet. |
| **BUILD POSITION** | Institutionel akkumulering. Sidelæns bevægelse med stigende volumen. Byg gradvist. |
| **STARTER BUY** | Svagere setup eller RISK_OFF miljø. Lille position. |
| **EXTENDED — WAIT** | RSI >84 eller pris >14% over SMA20. Vent på pullback. |
| **WATCHLIST** | Stage 2 men ingen aktionabel opsætning endnu. |
| **EXIT** | Sælg. Setup brudt. |

---

## Scoring (0–100)

**Trend Score (TS)** — Pris vs. SMA200/60/20, RS-trend, higher lows. Max 82 point.

**Setup Score (SS)** — Akkumulering, squeeze, institutionel flow, volumen. Max 50 point.

**Risk Penalty (RP)** — Trækkes fra. Lav likviditet (-14), RISK_OFF (-10), svag RS (-6), overkøbt (-8).

---

## Datafiler

| Fil | Indhold |
|---|---|
| `scanner.db` | SQLite. Seneste scan-snapshot + metadata. |
| `signals_history.json` | Historiske BUY-signaler til backtest. Må aldrig slettes. |
| `positions.json` | Portefølje-positioner. |
| `watchlist.json` | Manuel watchlist. |
| `custom_universe.json` | Brugertilføjede aktier ud over standarduniverset. |
| `fmp_key.txt` | Financial Modeling Prep API-nøgle. |
| `worker.log` | Worker-log. Viser scan-aktivitet. |
| `worker_error.log` | Fejl fra worker. |

---

## launchd (automatisk opstart)

Worker kører automatisk via macOS launchd og genstarter ved crash eller reboot.

```bash
# Installer (kun første gang)
cp ~/momentum_agent/com.db.scanner.worker.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.db.scanner.worker.plist

# Genstart
launchctl stop com.db.scanner.worker
launchctl start com.db.scanner.worker
```

---

## Data

- **US-aktier** → Financial Modeling Prep API (fmp_key.txt)
- **EU/Asia-aktier** → yfinance (suffiks .CO, .ST, .OL, .L, .DE, .PA osv.)
- **FX-rater** → FMP med fallback til faste defaults
- **Historik** → 420 dages OHLCV pr. aktie

FMP Starter-planen dækker US-aktier. Aktier med 402-fejl (premium endpoint) falder tilbage til yfinance.
