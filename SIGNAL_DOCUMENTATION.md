# Momentum Mike — Signal Dokumentation
**Version:** scanner_core.py · Juni 2026  
**Formål:** Præcis teknisk beskrivelse af alle signaler til professionel brug

---

## Arkitektur

Scanneren kører én gang per ticker og beregner to ting parallelt:

1. **Indikatorer** — rå tekniske tal (RSI, SMA, ATR, volumen, IBD RS Rank, Weinstein Stage)
2. **derive_states()** — kombinerer indikatorerne til en **Setup-tilstand**, en **Score (0–100)** og et **Signal**

Signalet er altid et direkte output af Setup-tilstanden — ikke en selvstændig beregning.

---

## Indikatorer der bruges

| Indikator | Beregning | Formål |
|-----------|-----------|--------|
| **SMA20** | Simpelt 20-dages gennemsnit af lukkekurs | Kortsigtet trend |
| **SMA60** | Simpelt 60-dages gennemsnit | Mellemlangsigtet trend |
| **SMA200** | Simpelt 200-dages gennemsnit | Primær langsigtet trend |
| **RSI(14)** | Standard Wilder RSI, 14 perioder | Momentum / overkøbt-oversolgt |
| **RSI Trend** | RSI nu vs. RSI for 5 dage siden | Stigende eller faldende momentum |
| **ATR(5) / ATR(20)** | Average True Range | Volatilitet og squeeze-detektion |
| **VolRatio** | Seneste dags volumen / 20-dages gennemsnitsvolumen | Relativ volumenaktivitet |
| **DistHigh20%** | (20-dages high − pris) / 20-dages high | Afstand til modstand |
| **HigherLow** | Low(seneste 5 dage) > Low(seneste 20 dage) | Stigende bund = købers kontrol |
| **IBD RS Rank** | Vægtet 12-mdrs afkast: 40% q4 + 20% q3 + 20% q2 + 20% q1, percentil-rangeret 0–99 | Relativ styrke vs. hele universet |
| **RS Trend** | Aktiens pris/lokalt indeks nu vs. for 21 dage siden | Vinder eller taber aktien mod sit marked? |
| **Weinstein Stage** | S2✅: pris > SMA200 og SMA200 stiger · S3⚠️: pris > SMA200 men SMA200 falder · S4❌: pris < SMA200 og SMA200 falder · S1🔄: pris < SMA200 men SMA200 stiger | Primært strukturfilter |
| **DollarVol (USD)** | Gennemsnitsvolumen(20d) × pris × FX-rate | Likviditet i USD |
| **Squeeze** | ATR(5) < ATR(20) × 0.78 | Komprimeret volatilitet = potentiel eksplosion |

---

## Tre delscore-komponenter

Score (0–100) = **TrendScore (ts)** + **SetupScore (ss)** − **RiskPenalty (rp)**

### TrendScore (ts) — max ~82 point
| Betingelse | Point |
|------------|-------|
| Pris > SMA200 | +24 |
| SMA20 > SMA60 | +18 |
| Pris > SMA20 | +10 |
| RS Trend = UP | +12 |
| HigherLow = true | +8 |
| InstFlowScore / 10 (max 10) | +0–10 |

### SetupScore (ss) — max ~90 point
| Betingelse | Point |
|------------|-------|
| Accumulation-flag | +20 |
| Institutional Build-flag | +18 |
| Breakout Ready-flag | +22 |
| Momentum Active-flag | +16 |
| Squeeze aktiv | +6 |
| Tight range (ATR/pris ≤ 4.5%) | +6 |
| RSI 46–72 | +6 |
| DistHigh20 ≤ 7% | +6 |
| VolRatio ≥ 0.95 | +6 |
| LiquidityScore / 10 (max 10) | +0–10 |

### RiskPenalty (rp) — trækkes fra
| Betingelse | Point |
|------------|-------|
| Likviditet ikke godkendt | −14 |
| Failed Setup (≥3 svaghedstegn + RSI<42 eller pris<Low5) | −14 |
| RISK_OFF markedsregime | −10 |
| Extended (RSI>84 eller pris>SMA20×1.14) | −8 |
| Weakening (≥2 svaghedstegn) | −8 |
| RS Trend = DOWN | −6 |
| Cap Risk (DollarVol < 25M USD) | −6 |

---

## Weinstein Stage — det primære strukturfilter

**Alle BUY-signaler kræver Stage 2.** Hvis en aktie er i Stage 1, 3 eller 4, sættes alle setup-flag til False, og aktien kan maksimalt opnå WATCHLIST.

| Stage | Betingelse | Betydning |
|-------|-----------|-----------|
| **S1🔄** | Pris < SMA200, SMA200 stiger | Bund-akkumulering — for tidlig |
| **S2✅** | Pris > SMA200 og SMA200 stiger | Primær optrend — **KØB HER** |
| **S3⚠️** | Pris > SMA200, men SMA200 falder | Distribution / topdannelse |
| **S4❌** | Pris < SMA200 og SMA200 falder | Primær nedtrend — undgå |

---

## De 7 Setup-tilstande og deres krav

### 1. FAILED_SETUP → `EXIT` / Sell-signal
**Krav (alle skal opfyldes):** ≥3 af fire svaghedstegn aktive + (RSI < 42 ELLER pris < Low5)

De fire svaghedstegn:
- Pris < SMA20
- SMA20 < SMA60
- Pris < SMA200
- RS Trend = DOWN

> Aktien er i aktiv nedtur. Sælg-signal genereres.

---

### 2. EXTENDED → `EXTENDED — WAIT`
**Krav (ét af følgende):**
- RSI > 84, ELLER
- Pris > SMA20 × 1.14 (dvs. >14% over 20-dages gennemsnit)

> Aktien er overkøbt eller løbet for langt fra basen. Ingen ny position — vent på base.

---

### 3. MOMENTUM_ACTIVE → `BUY NOW`
**Krav (alle skal opfyldes, og kræver BREAKOUT_READY som fundament):**
- Alt fra Breakout Ready er opfyldt, PLUS:
- VolRatio ≥ 1.10 (mindst 10% over gennemsnitligt volumen)
- RSI 50–80
- Likviditet godkendt (AvgVol ≥ 200.000 aktier OG DollarVol ≥ 8M USD)
- Markedsregime ≠ RISK_OFF
- **Weinstein Stage = 2**

> Aktien bryder ud med acceleration og volumenbekræftelse. Højest prioritet.

---

### 4. BREAKOUT_READY → `BUY BREAKOUT`
**Krav (alle skal opfyldes):**
- Trend: SMA20 > SMA60 (kortsigtet over mellemlangsigtet)
- Trend200: Pris > SMA200
- RS Trend: UP eller FLAT
- DistHigh20: 0–6% under 20-dages high (aktien banker på modstanden)
- VolRatio: 0.95–3.0 (normalt til forhøjet volumen)
- RSI: 44–78
- Squeeze ELLER DistHigh20 ≤ 3%
- **Weinstein Stage = 2**

> Aktien er tæt på at bryde igennem 20-dages højden med teknisk momentum.

---

### 5. INSTITUTIONAL_BUILD → `BUILD POSITION`
**Krav (alle skal opfyldes):**
Accumulation-betingelserne opfyldt, PLUS:
- InstAccum = true (IA-flag), ELLER InstFlowScore ≥ 65

Accumulation-betingelserne:
- SMA20 > SMA60
- Pris > SMA200
- RSI: 38–64
- VolRatio ≥ 0.90
- Pris er inden for 6% af SMA20 (tæt på basen)
- RS Trend: UP, FLAT eller tom
- **Weinstein Stage = 2**

> Aktien bygger en stram base med institutionel akkumulering. Typisk entry-punkt.

---

### 6. ACCUMULATION → `STARTER BUY`
**Krav (alle skal opfyldes):**
- SMA20 > SMA60
- Pris > SMA200
- RSI: 38–64
- VolRatio ≥ 0.90
- Pris er inden for 6% af SMA20
- RS Trend: UP, FLAT eller tom
- **Weinstein Stage = 2**
- Opfylder IKKE INSTITUTIONAL_BUILD (dvs. hverken IA-flag eller InstFlowScore ≥ 65)

> Akkumulerings-mønster uden bekræftet institutionel deltagelse. Lille startposition.

---

### 7. WATCHLIST (alle øvrige)
Aktien opfylder ingen af ovenstående betingelser, og er ikke i WEAKENING eller FAILED_SETUP.

---

## Stop-loss beregning

| Setup | Stop-formel |
|-------|-------------|
| MOMENTUM_ACTIVE | `max(Low5, pris − 1.5 × ATR20)` |
| INSTITUTIONAL_BUILD | `max(Low5, SMA20 − 0.5 × ATR20)` |
| Alle andre | `SMA20` |
| Stop ≥ pris (logisk umuligt) | `None` — vises som `—` |

---

## Markedsregime

Regime beregnes fra SPY/QQQ/IWM trend + daglige bevægelser + VIX niveau og retning + breadth fra scanneren selv.

| Regime | Effekt på signaler |
|--------|-------------------|
| **BULL** | Fuld scoring, alle signaler aktive |
| **NEUTRAL** | Fuld scoring, alle signaler aktive |
| **RISK_OFF** | RiskPenalty +10 på alle aktier — signalnavne ændres ikke, men scorer lavere |

> I RISK_OFF regime nedgraderes aktier naturligt i score, men MOMENTUM_ACTIVE undertrykkes direkte (kræver regime ≠ RISK_OFF).

---

## Signal-hierarki (prioritet)

```
BUY NOW          ← Højeste prioritet. Momentum bekræftet med volumen.
BUY BREAKOUT     ← Nær udbrud. Breakout-entry.
BUILD POSITION   ← Institutionel akkumulering i base.
STARTER BUY      ← Teknisk akkumulering, lille startposition.
EXTENDED — WAIT  ← Teknisk overkøbt. Intet nyt køb.
WATCHLIST        ← Overvågning. Ikke klar.
EXIT             ← Failed setup. Sælg.
```

---

## Likviditetsfilter

Alle BUY-signaler kræver bestået likviditetsfilter:
- Gennemsnitligt dagligt volumen (20d) ≥ **200.000 aktier**
- Dagligt dollar-volumen (USD, FX-normaliseret) ≥ **8.000.000 USD**

Hvis likviditet ikke bestås: RiskPenalty +14, og LiquidityPass-flag = ❌.

---

## IBD RS Rank

Beregnes som vægtet 12-måneders afkast:
```
RS_raw = q4×0.40 + q3×0.20 + q2×0.20 + q1×0.20
```
Hvor q4 = seneste kvartal, q1 = ældste kvartal (ca. 1 år siden).

Alle aktier i universet percentil-rangeres 0–99. RS Rank 90 = bedre end 90% af universet.

---

## FX-normalisering

Alle dollar-volumen beregninger konverteres til USD:
```
DollarVol_USD = AvgVol20 × pris × FX_rate
```
FX-rater hentes fra FMP API. Ved API-fejl bruges hardcodede fallback-rater (NOK=0.092, SEK=0.095, KRW=0.00074 osv.).

---

*Dokumentation genereret fra scanner_core.py · Momentum Mike · Juni 2026*
