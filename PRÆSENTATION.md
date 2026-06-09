# Teknisk Aktie-Scanner
### Systematisk momentum-analyse · Globale markeder · Juni 2026

---

&nbsp;

---

# 01 — Hvad er dette?

En regelbaseret momentum-scanner. Den gennemgår **1.684 globale aktier** og beregner for hver aktie tre outputs:

&nbsp;

<span style="color:#4FC3F7">**Tilstand**</span> — én af seks klassifikationer baseret på tekniske betingelser. Ingen skøn. Enten opfylder aktien reglerne, eller den gør ikke.

<span style="color:#81C784">**Score 0–100**</span> — summen af TrendScore + SetupScore − RiskPenalty. Måler conviction bag tilstanden. To aktier i samme tilstand kan score 91 og 64 — scoren afslører forskellen.

<span style="color:#FFB74D">**Stop-loss**</span> — volatilitetsjusteret exitniveau. Beregnet individuelt fra ATR(20), ikke en fast procent.

&nbsp;

Scanneren er ikke et prognoseværktøj. Den beskriver en teknisk tilstand præcis som den ser ud på scantidspunktet. Hvert point i scoren kan spores til en konkret betingelse i koden. Ingen black box.

&nbsp;

**Seneste scan:** `2026-06-09 kl. 19:26` · `1.713 aktier analyseret` · Regime: `RISK_OFF`

| Parameter | Værdi |
|---|---|
| Univers | 1.684 aktier (hardcoded) |
| Analyseret seneste scan | 1.713 (inkl. nye og udgåede) |
| Datakilde US | FMP API (betalt) |
| Datakilde EU/Asien | yfinance (gratis, timeout 30s) |
| Scan-frekvens | 5× dagligt + hourly BUY-scan |
| Historik per aktie | ~14 måneder OHLCV |

---

# 02 — Universet: Geografi

**1.684 aktier** · håndplukket · tre geografiske blokke

&nbsp;

### Geografisk fordeling

```
USA      ████████████████████████████████████████████  1.471   87%
Europa   ██████                                          208   12%
Asien    ░                                                20    1%
```

&nbsp;

> ⚠️ **Disclaimer — Asien-kategorien:** Flere asiatiske selskaber er registreret under US eller Europa i universet fordi de er noteret via ADR (American Depositary Receipt) eller på europæiske børser. Eksempel: TSMC er registreret som `TSM` på NYSE under US, og Samsung handles primært via `005930.KS` på Seoul Stock Exchange. De 20 aktier i Asien-kategorien er dem der handles direkte på lokale asiatiske børser.

&nbsp;

| Region | Aktier | Eksempler |
|---|---|---|
| **USA** | 1.471 | Apple, NVIDIA, JPMorgan — inkl. ADR'er for asiatiske selskaber |
| **Europa** | 208 | Novo Nordisk, ASML, SAP, Shell |
| **Asien (lokale børser)** | 20 | Toyota (.T), Samsung (.KS), Tencent (.HK), TSMC (.TW) |

&nbsp;

### Europa — fordeling på lande

```
Danmark      ████████████                39
Sverige      ███████████                 36
Norge        █████████                   30
UK           █████████                   29
Tyskland     █████                       18
Frankrig     █████                       18
Canada       █████                       16
Schweiz      ███                         11
Finland      ███                         11
Holland      ███                         10
```

---

# 03 — Universet: Sektorer

### Sektorfordeling — alle 1.684 aktier

```
Financials   ████████████████████████     303   18%
Tech         ████████████████████         270   16%
Consumer     ███████████████████          239   14%
Healthcare   ███████████████████          235   14%
Industrials  █████████████████            223   13%
Energy       ███████████                  135    8%
Materials    ████████                      99    6%
Real Estate  ████                          59    4%
AI           ███                           44    3%
Utilities    ██                            32    2%
Momentum     █                             25    1%
ETF          █                             20    1%
```

&nbsp;

Scanneren er bredt eksponeret uden sektorkoncentration. De fire største sektorer (Financials, Tech, Consumer, Healthcare) udgør tilsammen 62% af universet — spredt nok til at fange rotationer mellem sektorer, men med nok vægt i de sektorer der historisk genererer flest momentum-signaler.

&nbsp;

> *AI er registreret som separat sektor fremfor en del af Tech — det skyldes at AI-navne har en anden volatilitetsprofil og ofte kræver anderledes positionsstyring.*

---

# 04 — Data & infrastruktur

### To datakilder — én pipeline

**Financial Modeling Prep (FMP)**  
Betalt API. Bruges til alle amerikanske aktier. Leverer stabil OHLCV-data (Open, High, Low, Close, Volume) med ~14 måneders historik per aktie. Timeout: 15 sekunder.

&nbsp;

**yfinance**  
Gratis kilde. Bruges til europæiske og asiatiske aktier (`.OL`, `.ST`, `.CO`, `.DE` m.fl.). Mere ustabil — timeout-beskyttet med 30 sekunders grænse og automatisk retry ved fejl.

&nbsp;

### Scan-skema (dansk tid)

```
08:00  ████  Fuld scan + morgenanalyse på email
13:00  ████  Fuld scan
16:00  ████  Fuld scan  ←  dækker US market open
19:00  ████  Fuld scan
21:00  ████  Fuld scan  ←  efter US market close
──────────────────────────────────────────────
Hver hele time:  Hurtig scan — kun BUY-kandidater
```

&nbsp;

En fuld scan tager 30–60 minutter. Resultaterne gemmes i en lokal SQLite-database. Dashboardet læser altid fra seneste scan.

---

# 05 — Scoren: hvad måler den?

Scoren er ikke en enkelt indikator — den er summen af tre uafhængige komponenter der måler tre forskellige ting:

&nbsp;

<span style="color:#4FC3F7">**TrendScore**</span> — *er den strukturelle trend sund?*

Måler om aktien er i en optrend på tværs af tidsrammer: er prisen over SMA200 (lang sigt)? Er SMA20 over SMA60 (kort over mellemlang)? Stiger RS Rank relativt til resten? Hvert spørgsmål giver point individuelt. Maks ~82 point.

&nbsp;

<span style="color:#81C784">**SetupScore**</span> — *er der et konkret, handlingsbart setup?*

Måler om aktien er i en teknisk position der historisk forudgår et udbrud: er der en squeeze? Er aktien tæt på sin modstand? Er der akkumuleringsmønster? Disse betingelser er sjældne — det er meningen. Maks ~90 point.

&nbsp;

<span style="color:#FF8A65">**RiskPenalty**</span> — *hvad trækker ned?*

Fratrækker point for faktorer der øger risikoen: er aktien illikvid? Er markedet i RISK_OFF? Er der svaghedstegn? Penalty'en er designet til at filtrere signaler der ellers ville se gode ud på overfladen.

&nbsp;

```
Score  =  TrendScore  +  SetupScore  −  RiskPenalty
         (maks ~82)      (maks ~90)     (op til −50)
```

&nbsp;

**Hvorfor denne struktur?**  
TrendScore alene ville give høje scorer til alle aktier i optrend — også dem der er overkøbte, illikvide eller midt i et svaghedsmønster. SetupScore alene ville fange setups uanset den overordnede trend. Kombinationen kræver at *begge* er aktive på samme tid — og at ingen åbenlyse risici modvirker dem.

&nbsp;

En score over 65 indikerer at trend, setup og likviditet alle er på plads. Under 35 mangler typisk mindst to af komponenterne.

---

# 05b — Scorefordeling

Baseret på seneste scan · **1.713 aktier analyseret**

&nbsp;

### Hvordan fordeler scoren sig?

```
Score 80–100  ████                                      140    8%
Score 65–79   ██████                                    219   13%
Score 50–64   ████████                                  297   17%
Score 35–49   █████                                     181   11%
Score  0–34   ████████████████████████                  876   51%
```

&nbsp;

Over halvdelen af universet scorer under 35. Det er ikke en fejl — det er meningen.

Scanneren er ikke designet til at finde mange signaler. Den er designet til at finde de **rigtige** signaler. En lav gennemsnitsscore er tegn på en reel og stringent algoritme.

&nbsp;

### Hvad driver scoren?

```
Gennemsnitlig TrendScore (ts)   ████████████████████████████████  34 / ~82 maks
Gennemsnitlig SetupScore  (ss)  █████████                         15 / ~90 maks
Gennemsnitlig RiskPenalty (rp)  ████████████████                 −17
                                ─────────────────────────────────
Gennemsnitlig totalscore        ██████████████████████████        32 / 100
```

&nbsp;

De fleste aktier opnår en moderat TrendScore fordi de er i en delvis trend — men SetupScoren er lav fordi konkrete setup-betingelser (squeeze, breakout, akkumulering) sjældent er aktive. RiskPenalty trækker yderligere ned.

---

# 06 — Signalfordeling

**Data:** Scan kørt `2026-06-09 kl. 19:26` · `1.713 aktier` · Regime: `RISK_OFF`

&nbsp;

### Fordeling af aktier per signal

| Signal | Antal | Andel | Fordeling |
|---|---:|---:|---|
| <span style="color:#9E9E9E">WATCHLIST</span> | 1.455 | 85% | <span style="color:#9E9E9E">████████████████████████████████████████</span> |
| <span style="color:#EF5350">EXIT</span> | 173 | 10% | <span style="color:#EF5350">████████</span> |
| <span style="color:#FFA726">EXTENDED</span> | 41 | 2% | <span style="color:#FFA726">██</span> |
| <span style="color:#66BB6A">STARTER BUY</span> | 18 | 1% | <span style="color:#66BB6A">░</span> |
| <span style="color:#42A5F5">BUY BREAKOUT</span> | 17 | 1% | <span style="color:#42A5F5">░</span> |
| <span style="color:#26C6DA">BUILD POSITION</span> | 9 | 0,5% | <span style="color:#26C6DA">░</span> |
| <span style="color:#AB47BC">BUY NOW</span> | 0 | 0% | · |

&nbsp;

### Gennemsnitsscore per signal

| Signal | Score | Fordeling |
|---|---:|---|
| <span style="color:#42A5F5">BUY BREAKOUT</span> | 100 | <span style="color:#42A5F5">████████████████████████████████████████</span> |
| <span style="color:#26C6DA">BUILD POSITION</span> | 99 | <span style="color:#26C6DA">███████████████████████████████████████</span> |
| <span style="color:#66BB6A">STARTER BUY</span> | 88 | <span style="color:#66BB6A">██████████████████████████████████</span> |
| <span style="color:#FFA726">EXTENDED</span> | 57 | <span style="color:#FFA726">██████████████████████</span> |
| <span style="color:#9E9E9E">WATCHLIST</span> | 37 | <span style="color:#9E9E9E">███████████████</span> |
| <span style="color:#EF5350">EXIT</span> | 0 | · |

&nbsp;

BUY BREAKOUT og BUILD POSITION scorer begge ~100 fordi de kræver at næsten alle setup-betingelser er aktive simultant. En aktie der delvist opfylder kravene klassificeres som WATCHLIST — ikke som et halvvejs BUY-signal.

---

# 07 — Signalanalyse

### Er fordelingen forventet?

&nbsp;

<span style="color:#AB47BC">**BUY NOW — 0 signaler**</span> `FORVENTET`

Kræver bekræftet udbrud, volumen +10%, Stage 2 og neutral/bull regime — alt simultant. I et neutralt marked er 0–30 signaler normalt. BUY NOW opstår i korte vinduer og forsvinder hurtigt.

&nbsp;

<span style="color:#42A5F5">**BUY BREAKOUT — 17 signaler (1%)**</span> `FORVENTET`

Stram betingelse: inden for 6% af 20-dages high med strukturel opbakning. 15–25 signaler er normalt. Entry sker på selve bruddet — ikke før. **Risiko:** falske breakouts kræver opfølgning med volumenkonfirmation dagen efter.

&nbsp;

<span style="color:#26C6DA">**BUILD POSITION — 9 signaler (0,5%)**</span> `LIDT LAVT`

Det institutionelle filter (ifs ≥ 65 eller inst_accum) er stramt. Mange akkumulerer teknisk, men færre opfylder begge betingelser. Normalt interval er 10–20 signaler. Lav count i dag afspejler en bred markedskonsolidering.

&nbsp;

<span style="color:#66BB6A">**STARTER BUY — 18 signaler (1%)**</span> `FORVENTET`

Samme struktur som BUILD POSITION uden institutionel bekræftelse. Bredere filter giver naturligt lidt flere signaler. **Risiko:** lavere conviction end BUILD POSITION — kræver tæt stop-loss og løbende opfølgning.

&nbsp;

<span style="color:#FFA726">**EXTENDED — 41 signaler (2%)**</span> `FORVENTET`

RSI > 84 eller pris > SMA20 × 1.14. En lille gruppe stærke aktier løber altid foran. Ikke handlingsbart nu — men disse er ofte morgendagens BUY BREAKOUT-kandidater efter konsolidering.

&nbsp;

<span style="color:#9E9E9E">**WATCHLIST — 1.455 signaler (85%)**</span> `FORVENTET`

Pipeline til fremtidige signaler. De fleste aktier er aldrig i en tradeable position på noget givet tidspunkt. Lav gennemsnitsscore (37) bekræfter at de fleste er langt fra et signal — ikke bare tæt på.

&nbsp;

<span style="color:#EF5350">**EXIT — 173 signaler (10%)**</span> `ACCEPTABELT — OBSERVER`

5–15% EXIT er normalt i blandede markedsforhold. Over 20% ville signalere bred markedsnedtur. 10% er i den øvre ende af normalen — indikerer at en gruppe aktier er under strukturelt pres, men ikke en systemisk nedtur.

---

# 08 — Scoring: sådan beregnes det

**Score (0–100) = TrendScore + SetupScore − RiskPenalty**

&nbsp;

### TrendScore — er trenden sund?

```
Pris > SMA200               ████████████████████████  +24  ← primær optrend
SMA20 > SMA60               ██████████████████        +18  ← momentum intakt
RS Trend stigende           ████████████              +12  ← vinder mod markedet
Pris > SMA20                ██████████                +10  ← over kortsigtet støtte
HigherLow                   ████████                   +8  ← stigende bund
Institutionel flow (ifs/10) ██████████                +10  ← proxy for smart penge
                            ─────────────────────────────
                                               maks   ~82
```

&nbsp;

### SetupScore — er der et konkret setup?

```
Breakout Ready-flag         ██████████████████████    +22  ← banker på modstanden
Accumulation-flag           ████████████████████      +20  ← base dannes
Institutional Build-flag    ██████████████████        +18  ← inst. akkumulering
Momentum Active-flag        ████████████████          +16  ← udbrud bekræftet
Likviditetsscore (ls/10)    ██████████                +10  ← dolvol i USD
Squeeze (ATR5 < ATR20×0.78) ██████                     +6  ← energi komprimeret
Tight range (ATR/pris≤4.5%) ██████                     +6  ← stram konsolidering
RSI 46–72                   ██████                     +6  ← sundt momentum
DistHigh20 ≤ 7%             ██████                     +6  ← nær modstand
VolRatio ≥ 0.95             ██████                     +6  ← normalt/stigende vol.
                            ─────────────────────────────
                                               maks   ~90
```

&nbsp;

### RiskPenalty — trækkes fra

```
Likviditet ikke godkendt    ██████████████            −14  ← < 200k aktier / 8M USD
Failed Setup                ██████████████            −14  ← ≥3 svaghedstegn aktive
RISK_OFF regime             ██████████                −10  ← marked i nedtur
Overkøbt / extended         ████████                   −8  ← løbet for langt
Weakening                   ████████                   −8  ← ≥2 svaghedstegn
RS Trend faldende           ██████                     −6  ← taber mod markedet
Cap Risk (< 25M USD dagligt)██████                     −6  ← illikvid
```

---

# 09 — Tilstande

Hvert aktie ender i én af seks tilstande. Tilstanden er algoritmisk — ingen skøn.

&nbsp;

### BUY NOW
Bekræftet udbrud. Alt peger i samme retning på én gang: Stage 2, volumen +10% over norm, RSI 50–80, neutral/bull regime. Højeste conviction. Handler nu.

**Typisk scoreinterval:** 75–100

&nbsp;

### BUY BREAKOUT
Aktien er inden for 6% af sin 20-dages modstand med teknisk momentum og Weinstein Stage 2. Entry sker på selve bruddet. Bekræft med volumen dagen efter.

**Typisk scoreinterval:** 65–100

&nbsp;

### BUILD POSITION
Institutionel akkumulering bekræftet (ifs ≥ 65 eller inst_accum flag). Aktien konsoliderer tæt på sin SMA20. Bygges gradvist — ikke alt på én gang.

**Typisk scoreinterval:** 60–100

&nbsp;

### STARTER BUY
Samme tekniske struktur som BUILD POSITION, men uden institutionel bekræftelse. Lille startposition. Øg kun hvis aktien bekræfter med stigende volumen.

**Typisk scoreinterval:** 50–95

&nbsp;

### WATCHLIST
Ikke klar — én eller to betingelser mangler. Pipeline til fremtidige signaler. Ingen direkte handling.

**Typisk scoreinterval:** 0–70

&nbsp;

### EXIT
Mindst tre af fire svaghedstegn aktive + negativt momentum (RSI < 42 eller pris < Low5). Luk positionen.

**Typisk scoreinterval:** 0–23

---

# 10 — Weinstein Stage

Det overordnede strukturfilter. Alle BUY-signaler kræver **Stage 2** — ingen undtagelser.

&nbsp;

```
         SMA200 stiger?
              │
       ┌──────┴──────┐
      JA             NEJ
       │               │
  Pris > SMA200?   Pris > SMA200?
  ┌────┴────┐      ┌────┴────┐
 JA        NEJ   JA        NEJ
  │          │    │          │
 S2 ✅      S1 🔄 S3 ⚠️      S4 ❌
 KØB        VÆR   DISTRIBUTION NEDTREND
            PARAT
```

&nbsp;

| Stage | Hvad det betyder | Handling |
|---|---|---|
| **S2 ✅** | Primær optrend. Pris og SMA200 peger begge op. | Køb |
| **S1 🔄** | Bund-akkumulering. SMA200 vender, men pris stadig under. | Overvåg — S1 Pipeline |
| **S3 ⚠️** | Topdannelse. Pris over SMA200, men trenden drejer. | Undgå nye positioner |
| **S4 ❌** | Primær nedtrend. Begge peger ned. | Rør den ikke |

&nbsp;

*SMA200 "stiger" defineres som: SMA200 nu > SMA200 for 20 handelsdage siden.*

---

# 11 — Stop-loss

Aldrig en fast procent. Altid skaleret til aktiens faktiske volatilitet via ATR(20).

&nbsp;

```
MOMENTUM_ACTIVE     stop = max(Low5,  pris − 1.5 × ATR20)
INSTITUTIONAL_BUILD stop = max(Low5,  SMA20 − 0.5 × ATR20)
Alle andre          stop = SMA20
Stop ≥ pris         stop = None  →  vises som —
```

&nbsp;

**ATR(20)** = gennemsnit af True Range de seneste 20 dage.  
**True Range** = max(High−Low, |High−gårsCl|, |Low−gårsCl|) — fanger gap-opens.

`max(Low5, ...)` sikrer at stoppet aldrig placeres over en støtte der allerede er brudt.

&nbsp;

**Eksempel:** Aktie med pris 100 og ATR20 = 3.0
```
BUY NOW:  stop = max(Low5,  100 − 1.5×3.0) = max(Low5, 95.5)
```
Stoppet er 4.5% under pris — ikke vilkårligt, men præcis 1.5 normale dages bevægelse.

---

# 12 — S1 Pipeline

Aktier der ikke er BUY endnu, men nærmer sig Stage 2-bruddet.

&nbsp;

**Filterkrav:**

```
Weinstein Stage  = S1  (SMA200 stiger, pris stadig under)
SMA20 > SMA60         intern kortsigtet trend allerede positiv
Afstand til SMA200 ≤ 12%   (konfigurerbar 1–25%)
RS Rank ≥ 50          relativ styrke bygger sig op
```

Sorteret efter afstand til SMA200 — de nærmeste øverst.

&nbsp;

S1 Pipeline er ikke et handelssignal. Det er en struktureret watchlist over aktier der potentielt bryder til Stage 2 inden for de kommende uger. Ingen position åbnes herfra — den bruges til at identificere kandidater tidligt og have dem klar.

&nbsp;

> *En aktie der bevæger sig fra S1 Pipeline til BUY BREAKOUT vil typisk gøre det på 2–8 uger. De fleste gør det ikke. Det er meningen med et filter.*

---

# 13 — Backtest: Live Forward Returns

Scanneren logger alle BUY-signaler dagligt. Forward returns beregnes løbende mod aktuelle priser.

&nbsp;

**Periode:** 20. maj – 9. juni 2026 · **20 dage** · **416 unikke signaler**

&nbsp;

> *20 dage er statistisk kort. Tallene herunder er indikative — ikke konklusive. Momentum-strategier måles typisk på 60–120-dages horisonter.*

&nbsp;

### Samlet performance

```
Signaler analyseret    416
Gennemsnitligt afkast   −0.8%
Hit-rate (pos. return)   52%
Bedste enkelthandel     +25.4%   MRVL  (BUY NOW)
Værste enkelthandel     −32.4%   PL    (BUILD POSITION)
```

&nbsp;

### Performance per signal

```
Signal            N     Hit-rate   Avg return   Best    Worst
──────────────────────────────────────────────────────────────
BUY BREAKOUT     133      65%        +0.2%      +17.9%  −15.2%
BUY NOW           88      51%        −0.8%      +25.4%  −23.6%
STARTER BUY       80      48%        −1.1%      +23.9%  −23.0%
BUILD POSITION   115      42%        −1.8%       +9.1%  −32.4%
```

&nbsp;

**BUY BREAKOUT** er det stærkeste signal på kort sigt — 65% hit-rate og positiv gennemsnitsreturn. Det giver mening: et brud med volumen er et konkret, tidsdefineret event med et klart invaliderings-punkt.

**BUILD POSITION** underperformer på 20 dage — forventet. Det er et akkumuleringssignal designet til at holdes i 60–120 dage, ikke 20. Vurder igen ved 60-dages mark.

&nbsp;

### Sektorperformance

```
Real Estate   ████████████████████████████████  +1.5%   (14 signaler)
Financials    ███████████████████████████       +0.9%  (115 signaler)
Healthcare    ████████████████████████          +0.5%   (37 signaler)
Consumer      ████████████████████             −0.1%   (34 signaler)
Industrials   ██████████████████               −1.3%   (57 signaler)
Materials     ████████████████                 −1.5%   (25 signaler)
AI            ██████████████                   −1.8%   (34 signaler)
```

&nbsp;

Finanssektoren er den klart mest robuste i perioden — 115 signaler med positiv gennemsnitsreturn. AI-sektoren er den svageste, hvilket afspejler en bredere rotation væk fra AI-navne i perioden.

&nbsp;

### Top 5 — stærkeste signaler

```
MRVL     (BUY NOW)        +25.4%   Marvell Technology
ZVRA     (STARTER BUY)    +23.9%   Zevra Therapeutics
HUM      (BUY BREAKOUT)   +17.9%   Humana
ASML.AS  (BUY BREAKOUT)   +12.1%   ASML
SUBC.OL  (BUILD POSITION)  +9.1%   Subsea 7
```

&nbsp;

### Top 5 — svageste signaler

```
PL       (BUILD POSITION)  −32.4%   Planet Labs
ARRY     (BUY NOW)         −23.6%   Array Technologies
VCNX     (STARTER BUY)     −23.0%   Vaccinex
BE       (BUY NOW)         −17.7%   Bloom Energy
AVGO     (BUY NOW)         −16.7%   Broadcom
```

&nbsp;

De fem svageste er alle small- eller mid-cap med høj volatilitet. AVGO er en undtagelse som large-cap — signalet blev givet tæt på en top, hvilket understreger at Weinstein Stage 2 er en nødvendig men ikke tilstrækkelig betingelse alene.

&nbsp;

> *Når databasen indeholder 60+ dage, splittes tallene automatisk på horisonter: 1–19d, 20–59d, 60–119d og 120d+. Det vil give et mere retvisende billede af signalernes relle edge.*

---

# 15 — Systemarkitektur

```
 ┌─────────────────────────────────────────────┐
 │            UNIVERS — 1.684 aktier           │
 │   USA 87%  ·  Europa 12%  ·  Asien 1%       │
 └──────────────────┬──────────────────────────┘
                    │
        ┌───────────┴───────────┐
        │                       │
  FMP API (US)           yfinance (EU/Asien)
  Stabil, betalt          Gratis, timeout 30s
        │                       │
        └───────────┬───────────┘
                    │
          OHLCV · 14 mdr. historik
                    │
                    ▼
 ┌──────────────────────────────────────────────┐
 │            scanner_core.py                   │
 │                                              │
 │  Indikatorer: SMA · RSI · ATR · IBD RS Rank  │
 │               Weinstein Stage · VolRatio     │
 │                                              │
 │  Scoring:  TrendScore + SetupScore − Risk    │
 │                                              │
 │  Output:   Tilstand · Score · Stop-loss      │
 └──────────────────┬───────────────────────────┘
                    │
              scanner.db  (SQLite)
                    │
                    ▼
 ┌──────────────────────────────────────────────┐
 │            Dashboard (scanner_v7.py)         │
 │                                              │
 │  Scanner · Positioner · S1 Pipeline          │
 │  Benchmark · Backtest · RS Analyse           │
 └──────────────────────────────────────────────┘
```

&nbsp;

Worker-processen kører hele tiden i baggrunden og koordinerer scan-skemaet. Fuld scan: 5 gange dagligt. Hurtig BUY-scan: hver hele time.

&nbsp;

---

*scanner_core.py · Juni 2026*
