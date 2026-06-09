"""
research_agent.py – Daglig research-agent for Trading Terminal Pro
Kører kl. 08:00, henter top 10 BUY-kandidater fra scanner.db,
laver dybdeanalyse via Claude API og sender HTML-email.
"""

import os
import smtplib
import logging
import time
import json
import re
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic

import scanner_db as sdb

# ─────────────────────────────────────────────
# KONFIGURATION ← udfyld disse
# ─────────────────────────────────────────────

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
EMAIL_FROM        = os.environ.get("EMAIL_FROM", "")
EMAIL_TO          = os.environ.get("EMAIL_TO", "")
EMAIL_PASSWORD    = os.environ.get("EMAIL_PASSWORD", "")

TOP_N = 5
BUY_SIGNALS = {'BUY NOW', 'BUY BREAKOUT', 'BUILD POSITION', 'STARTER BUY'}

# ─────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
LOG = logging.getLogger('research_agent')


def get_candidates():
    scan = sdb.read_scan_results()
    if scan.empty:
        LOG.warning("Ingen scan-data i databasen")
        return []
    candidates = scan[
        scan['buy'].isin(BUY_SIGNALS) &
        (scan['sector'] != 'REF')
    ].head(TOP_N)
    return candidates.to_dict(orient='records')


def analyse_candidate(client, row):
    ticker  = row.get('ticker', '')
    name    = row.get('name', ticker)
    signal  = row.get('buy', '')
    score   = row.get('score', 0)
    price   = row.get('price', 0)
    rsi     = row.get('rsi', 0)
    rs_rank = row.get('rs_rank', 0)
    stage   = row.get('stage', '')
    sector  = row.get('sector', '')
    region  = row.get('region', '')
    dpct    = row.get('dpct', 0)

    LOG.info(f"  Analyserer {ticker} ({signal}, score={score})")

    prompt = f"""Du er en erfaren aktieanalytiker. Analyser {ticker} ({name}) grundigt.

Scanner-signal:
- Signal: {signal} | Score: {score}/100 | Pris: {price} | Daglig: {dpct}%
- RSI: {rsi} | RS Rank: {rs_rank}/99 | Stage: {stage}
- Sektor: {sector} | Region: {region}

Brug web search og find PRÆCISE, OPDATEREDE tal for alle punkter:

FUNDAMENTALS (find konkrete tal):
- P/E ratio (Pris/Indtjening) – er aktien billig eller dyr?
- EPS-vækst (Indtjening per aktie) – vækstrate seneste år og forventet
- Omsætningsvækst – seneste kvartals vækst år-over-år
- Bruttomargin – profitabilitet på kernedrift
- Gæld/Egenkapital (D/E ratio) – soliditet
- Frit cash flow – genererer de reelle penge?
- ROE (Afkast på egenkapital) – bruger de kapitalen effektivt?
- Insiderkøb – har ledelsen købt aktier for nylig?

SENESTE NYHEDER (seneste 30 dage):
- Hvad er sket? Vigtige begivenheder, udmeldinger, kontrakter?
- Er der noget der driver kursen op eller ned?

KOMMENDE KATALYSATORER:
- Næste regnskabsdato – hvornår præcist?
- Produktlanceringer, FDA-godkendelser, kontrakter, kapitalmarkedsdage?
- Hvad kan flytte aktien de næste 30-90 dage?

ANALYTIKER-KONSENSUS:
- Konsensus-rating (Stærkt Køb/Køb/Hold/Sælg)
- Gennemsnitligt kursmål og upside fra nuværende kurs
- Seneste op- eller nedjusteringer

RISICI:
- Hvad kan gå galt? Konkurrence, regulering, makro, gæld?

VERDICT:
- Er dette en god handelsmulighed givet signalet?

Svar KUN med dette JSON (ingen markdown, ingen backticks):
{{
  "ticker": "{ticker}",
  "name": "{name}",
  "signal": "{signal}",
  "score": {score},
  "verdict": "KØB" eller "HOLD ØJE" eller "SPRING OVER",
  "confidence": "HØJ" eller "MIDDEL" eller "LAV",
  "pe_ratio": "tal eller Ukendt",
  "eps_growth": "% tal eller Ukendt",
  "revenue_growth": "% tal eller Ukendt",
  "gross_margin": "% tal eller Ukendt",
  "debt_equity": "tal eller Ukendt",
  "free_cash_flow": "beløb eller Ukendt",
  "roe": "% tal eller Ukendt",
  "insider_buying": "Ja / Nej / Ukendt",
  "news": "2-3 sætninger om de vigtigste nyheder",
  "catalysts": "2-3 sætninger om kommende katalysatorer",
  "earnings_date": "dato eller Ukendt",
  "analyst_rating": "konsensus rating",
  "analyst_target": "kursmål og upside %",
  "risks": "1-2 sætninger om hovedrisici",
  "verdict_reason": "2-3 sætninger om den samlede vurdering"
}}"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1500,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": prompt}]
        )
        text = next((b.text for b in response.content if b.type == "text"), "")
        text = text.replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(text)
        except Exception:
            m = re.search(r'\{[\s\S]*\}', text)
            if m:
                return json.loads(m.group())
    except Exception as e:
        LOG.error(f"  Analyse fejlede for {ticker}: {e}")

    return {
        "ticker": ticker, "name": name, "signal": signal, "score": score,
        "verdict": "FEJL", "confidence": "LAV",
        "pe_ratio": "—", "eps_growth": "—", "revenue_growth": "—",
        "gross_margin": "—", "debt_equity": "—", "free_cash_flow": "—",
        "roe": "—", "insider_buying": "—",
        "news": "Analyse fejlede", "catalysts": "—", "earnings_date": "Ukendt",
        "analyst_rating": "—", "analyst_target": "—",
        "risks": "—", "verdict_reason": "Teknisk fejl"
    }


def metric_row(label, value, highlight=False):
    color = "#00d4aa" if highlight else "#e2e8f0"
    return f"""
    <tr>
      <td style="padding:7px 16px;color:#64748b;font-size:12px;
                 font-family:monospace;border-bottom:1px solid #1e2d45;
                 white-space:nowrap">{label}</td>
      <td style="padding:7px 16px;color:{color};font-size:12px;
                 font-family:monospace;font-weight:600;
                 border-bottom:1px solid #1e2d45;text-align:right">{value}</td>
    </tr>"""


def build_email(analyses, regime, n_candidates):
    now      = datetime.now().strftime("%d. %b %Y")
    now_full = datetime.now().strftime("%d. %b %Y, %H:%M")

    regime_color = {'RISK_ON': '#00d4aa', 'RISK_OFF': '#ef4444', 'NEUTRAL': '#f59e0b'}.get(regime, '#888')
    regime_label = {'RISK_ON': '▲ RISK ON', 'RISK_OFF': '▼ RISK OFF', 'NEUTRAL': '◆ NEUTRAL'}.get(regime, regime)

    verdict_cfg = {
        'KØB':         ('#00d4aa', '#003322', '#00d4aa'),
        'HOLD ØJE':    ('#f59e0b', '#2a1f00', '#f59e0b'),
        'SPRING OVER': ('#ef4444', '#2a0000', '#ef4444'),
        'FEJL':        ('#888888', '#1a1a1a', '#888888'),
    }

    signal_colors = {
        'BUY NOW':        '#00ff88',
        'BUY BREAKOUT':   '#00cc66',
        'BUILD POSITION': '#3b82f6',
        'STARTER BUY':    '#a855f7',
    }

    cards = ''
    for i, a in enumerate(analyses):
        ticker   = a.get('ticker', '')
        name     = a.get('name', '')
        signal   = a.get('signal', '')
        score    = a.get('score', 0)
        verdict  = a.get('verdict', 'FEJL')
        conf     = a.get('confidence', '')
        earnings = a.get('earnings_date', 'Ukendt')
        vc, vbg, vborder = verdict_cfg.get(verdict, verdict_cfg['FEJL'])
        sc = signal_colors.get(signal, '#888')

        earnings_badge = ''
        if earnings and earnings != 'Ukendt':
            earnings_badge = f"""
            <div style="background:#1a1200;border:1px solid #f59e0b;
                        border-radius:6px;padding:10px 16px;margin-bottom:16px;
                        display:flex;align-items:center;gap:10px">
              <span style="font-size:16px">📅</span>
              <div>
                <div style="font-size:10px;color:#f59e0b;font-family:monospace;
                            letter-spacing:.1em;text-transform:uppercase">REGNSKAB</div>
                <div style="font-size:14px;color:#fff;font-family:monospace;
                            font-weight:700">{earnings}</div>
              </div>
            </div>"""

        cards += f"""
        <div style="background:#111827;border:1px solid #1e2d45;
                    border-radius:12px;overflow:hidden;margin-bottom:28px">

          <!-- Aktie header -->
          <div style="background:#0f172a;padding:16px 20px;
                      border-bottom:1px solid #1e2d45">
            <div style="display:flex;align-items:center;
                        justify-content:space-between;flex-wrap:wrap;gap:8px">
              <div style="display:flex;align-items:center;gap:12px">
                <span style="font-family:monospace;font-size:22px;font-weight:700;
                             color:#00d4aa">{ticker}</span>
                <span style="color:#64748b;font-size:13px">{name}</span>
              </div>
              <div style="display:flex;align-items:center;gap:8px">
                <span style="background:{sc}18;color:{sc};font-family:monospace;
                             font-size:11px;padding:4px 10px;border-radius:4px;
                             border:1px solid {sc}44;font-weight:700">{signal}</span>
                <span style="background:{vbg};color:{vc};font-family:monospace;
                             font-size:11px;padding:4px 12px;border-radius:4px;
                             border:1px solid {vborder};font-weight:700">
                  {verdict} · {conf}</span>
              </div>
            </div>
            <div style="margin-top:8px">
              <div style="background:#1e2d45;border-radius:4px;height:4px;width:100%">
                <div style="background:linear-gradient(90deg,#00d4aa,#3b82f6);
                            border-radius:4px;height:4px;
                            width:{score}%"></div>
              </div>
              <div style="font-size:10px;color:#64748b;font-family:monospace;
                          margin-top:4px">SCORE: {score}/100</div>
            </div>
          </div>

          <!-- Body -->
          <div style="padding:20px">
            {earnings_badge}

            <!-- To kolonner: nøgletal + analyse -->
            <table style="width:100%;border-collapse:collapse">
              <tr>
                <!-- Venstre: Nøgletal -->
                <td style="width:40%;vertical-align:top;padding-right:16px">
                  <div style="font-size:10px;color:#3b82f6;font-family:monospace;
                              letter-spacing:.1em;text-transform:uppercase;
                              margin-bottom:8px">📊 NØGLETAL</div>
                  <table style="width:100%;border-collapse:collapse;
                                background:#0a0e17;border-radius:8px;overflow:hidden;
                                border:1px solid #1e2d45">
                    {metric_row("P/E Ratio", a.get('pe_ratio','—'))}
                    {metric_row("EPS Vækst", a.get('eps_growth','—'))}
                    {metric_row("Omsætningsvækst", a.get('revenue_growth','—'))}
                    {metric_row("Bruttomargin", a.get('gross_margin','—'))}
                    {metric_row("Gæld/Egenkapital", a.get('debt_equity','—'))}
                    {metric_row("Frit Cash Flow", a.get('free_cash_flow','—'))}
                    {metric_row("ROE", a.get('roe','—'))}
                    {metric_row("Insiderkøb", a.get('insider_buying','—'), highlight=a.get('insider_buying','') == 'Ja')}
                  </table>

                  <div style="margin-top:16px">
                    <div style="font-size:10px;color:#3b82f6;font-family:monospace;
                                letter-spacing:.1em;text-transform:uppercase;
                                margin-bottom:8px">💬 ANALYTIKERE</div>
                    <div style="background:#0a0e17;border:1px solid #1e2d45;
                                border-radius:8px;padding:12px">
                      <div style="font-size:13px;color:#00d4aa;font-family:monospace;
                                  font-weight:700;margin-bottom:4px">
                        {a.get('analyst_rating','—')}</div>
                      <div style="font-size:12px;color:#94a3b8">
                        {a.get('analyst_target','—')}</div>
                    </div>
                  </div>
                </td>

                <!-- Højre: Analyse -->
                <td style="width:60%;vertical-align:top">

                  <div style="margin-bottom:16px">
                    <div style="font-size:10px;color:#3b82f6;font-family:monospace;
                                letter-spacing:.1em;text-transform:uppercase;
                                margin-bottom:6px">📰 SENESTE NYHEDER</div>
                    <div style="font-size:13px;color:#c4d0e0;line-height:1.7">
                      {a.get('news','—')}</div>
                  </div>

                  <div style="margin-bottom:16px">
                    <div style="font-size:10px;color:#3b82f6;font-family:monospace;
                                letter-spacing:.1em;text-transform:uppercase;
                                margin-bottom:6px">🚀 KOMMENDE KATALYSATORER</div>
                    <div style="font-size:13px;color:#c4d0e0;line-height:1.7">
                      {a.get('catalysts','—')}</div>
                  </div>

                  <div style="margin-bottom:16px">
                    <div style="font-size:10px;color:#3b82f6;font-family:monospace;
                                letter-spacing:.1em;text-transform:uppercase;
                                margin-bottom:6px">⚠️ RISICI</div>
                    <div style="font-size:13px;color:#c4d0e0;line-height:1.7">
                      {a.get('risks','—')}</div>
                  </div>

                  <!-- Konklusion -->
                  <div style="background:{vbg};border:1px solid {vborder};
                              border-left:4px solid {vc};border-radius:8px;
                              padding:14px 16px">
                    <div style="font-size:10px;color:{vc};font-family:monospace;
                                letter-spacing:.1em;text-transform:uppercase;
                                margin-bottom:6px">✅ KONKLUSION</div>
                    <div style="font-size:13px;color:#e2e8f0;line-height:1.7">
                      {a.get('verdict_reason','—')}</div>
                  </div>

                </td>
              </tr>
            </table>
          </div>
        </div>"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0;padding:0;background:#0a0e17;
             font-family:'Segoe UI',Arial,sans-serif;color:#e2e8f0">
  <div style="max-width:760px;margin:0 auto;padding:24px 16px">

    <!-- TOP HEADER -->
    <div style="text-align:center;padding:32px 0 24px">
      <div style="font-family:monospace;font-size:28px;font-weight:900;
                  color:#ffffff;letter-spacing:4px;text-transform:uppercase">
        MOMENTUM MIKE
      </div>
      <div style="font-size:13px;color:#64748b;font-family:monospace;
                  margin-top:4px;letter-spacing:2px">
        {len(analyses)} KANDIDATER ANALYSERET · {now}
      </div>
      <div style="width:60px;height:2px;background:#00d4aa;
                  margin:16px auto 0"></div>
    </div>

    <!-- REGIME STRIP -->
    <div style="background:#111827;border:1px solid #1e2d45;border-radius:10px;
                padding:14px 20px;margin-bottom:24px;display:flex;
                align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px">
      <div style="display:flex;align-items:center;gap:20px">
        <div>
          <div style="font-size:9px;color:#64748b;font-family:monospace;
                      letter-spacing:.1em;text-transform:uppercase">MARKED REGIME</div>
          <div style="font-size:16px;font-weight:700;color:{regime_color};
                      font-family:monospace">{regime_label}</div>
        </div>
        <div style="width:1px;height:32px;background:#1e2d45"></div>
        <div>
          <div style="font-size:9px;color:#64748b;font-family:monospace;
                      letter-spacing:.1em;text-transform:uppercase">KANDIDATER</div>
          <div style="font-size:16px;font-weight:700;color:#e2e8f0;
                      font-family:monospace">{n_candidates} fundet</div>
        </div>
        <div style="width:1px;height:32px;background:#1e2d45"></div>
        <div>
          <div style="font-size:9px;color:#64748b;font-family:monospace;
                      letter-spacing:.1em;text-transform:uppercase">GENERERET</div>
          <div style="font-size:13px;font-weight:600;color:#e2e8f0;
                      font-family:monospace">{now_full}</div>
        </div>
      </div>
    </div>

    <!-- KANDIDATER -->
    {cards}

    <!-- FOOTER -->
    <div style="text-align:center;padding:24px 0;
                border-top:1px solid #1e2d45;margin-top:8px">
      <div style="font-family:monospace;font-size:11px;color:#334155">
        MOMENTUM MIKE · Automatisk analyse · Ikke finansiel rådgivning
      </div>
    </div>

  </div>
</body>
</html>"""


def send_email(html, n_analyses):
    now     = datetime.now().strftime("%d. %b %Y")
    subject = f"📈 Momentum Mike – {n_analyses} kandidater analyseret · {now}"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO
    msg.attach(MIMEText(html, "html", "utf-8"))
    LOG.info(f"Sender email til {EMAIL_TO}...")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(EMAIL_FROM, EMAIL_PASSWORD)
        smtp.send_message(msg)
    LOG.info("Email sendt! ✅")


def main():
    LOG.info("=" * 55)
    LOG.info("  MOMENTUM MIKE – RESEARCH AGENT")
    LOG.info("=" * 55)

    client     = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    candidates = get_candidates()

    if not candidates:
        LOG.warning("Ingen BUY-kandidater – afbryder")
        return

    LOG.info(f"Fandt {len(candidates)} kandidater – analyserer...")

    meta   = sdb.get_scan_meta()
    regime = meta.get('regime', 'NEUTRAL') if meta else 'NEUTRAL'

    analyses = []
    for row in candidates:
        analysis = analyse_candidate(client, row)
        analyses.append(analysis)
        time.sleep(5)

    html = build_email(analyses, regime, len(candidates))
    send_email(html, len(analyses))
    LOG.info("Momentum Mike færdig ✅")


if __name__ == '__main__':
    main()