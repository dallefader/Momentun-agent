# Sådan fungerer scanneren

**Skrevet til:** Alle der vil forstå præcis hvad scanneren gør og hvorfor  
**Tone:** Uformel, men teknisk præcis  
**Version:** scanner_core.py · Juni 2026

---

## Hvad er en momentum-scanner?

En momentum-scanner er et system der automatisk gennemgår et stort antal aktier og sorterer dem efter teknisk styrke. I stedet for at du sidder og kigger på hundredvis af charts selv, gør scanneren det for dig — og fortæller dig hvilke aktier der er i en position du skal handle på, hvilke der er tæt på at være det, og hvilke du skal holde dig fra.

Det er ikke et prognoseværktøj. Scanneren forudsiger ikke kurser. Den beskriver en tilstand — præcis som den ser ud i dag — og sætter den i et hierarki.

---

## Universet — hvad scanner vi egentlig?

Scanneren har et fast defineret univers på knap **1.700 aktier**. Det er ikke tilfældigt sammensat — universet er håndplukket og inkluderer:

- **Amerikanske aktier** — primært mid- og large cap inden for tech, AI, finans, sundhed, industri og energi. Her er alt fra Apple og NVIDIA til mindre vækstnavne.
- **Europæiske aktier** — nordiske (Danmark, Sverige, Norge), tyske, franske, britiske og flere andre markeder. Fx Novo Nordisk, ASML, SAP.
- **Asiatiske aktier** — japanske, koreanske og hongkongske navne som Samsung, TSMC og Toyota.

Hvert aktie i universet er defineret med fire egenskaber: **ticker-symbol, navn, sektor og region**. Sektor bruges til at gruppere signaler, region bruges til at vide hvilken valuta aktien handles i og hvilken datakilde der skal bruges.

---

## Hvorfra og hvordan hentes dataen?

Scanneren henter to slags data: **historiske kurser** og **FX-kurser**.

### Historiske kurser

Der bruges to datakilder afhængig af, hvilken aktie det er:

**FMP (Financial Modeling Prep)** — bruges til alle amerikanske aktier. FMP er en betalt finansiel API der leverer stabil, struktureret OHLCV-data (Open, High, Low, Close, Volume) tilbage ~14 måneder. Hvert kald henter én aktie ad gangen med en lille forsinkelse mellem kaldene for ikke at overbelaste API'et.

**yfinance** — bruges til europæiske og asiatiske aktier med børssuffixer som `.OL` (Oslo), `.ST` (Stockholm), `.CO` (København), `.DE` (Frankfurt) osv. yfinance er gratis men langsommere og mere ustabil — derfor har hvert kald en timeout på 30 sekunder og automatisk retry ved fejl.

Begge kilder returnerer en daglig tidsserie med ca. 14 måneder historik. Det er nok til at beregne SMA200, ATR, IBD RS Rank og alle øvrige indikatorer.

### FX-kurser

For at sammenligne likviditet på tværs af markeder skal al dollar-volumen konverteres til USD. FX-kurser hentes live fra FMP API. Hvis API'et fejler, bruges hardcodede fallback-kurser (DKK: 0.145, NOK: 0.092, KRW: 0.00074 osv.).

### Hvornår sker det?

En baggrunds-proces (`worker.py`) kører hele tiden og styrer hvornår scans afvikles:

| Tidspunkt | Hvad sker der |
|---|---|
| 08:00 | Fuld scan + morgenmail med top 5 analyse |
| 13:00 | Fuld scan |
| 16:00 | Fuld scan (dækker US-åbning) |
| 19:00 | Fuld scan |
| 21:00 | Fuld scan (efter US-close) |
| Hver hele time | Hurtig scan — kun aktuelle BUY-kandidater |

En fuld scan af ~1.700 aktier tager typisk 30–60 minutter. Resultaterne gemmes i en lokal SQLite-database (`scanner.db`), og dashboardet læser derfra.

---

## Hvad er en tilstand?

Når scanneren er færdig med en aktie, placerer den den i én af seks **tilstande**. En tilstand er en præcis teknisk beskrivelse af, hvad aktien gør lige nu — og hvad du skal gøre ved den. Tilstanden afgøres 100% af regler. Enten opfylder aktien betingelserne, eller den gør ikke.

**BUY NOW** er det stærkeste signal. Aktien er i en bekræftet optrend, volumen er steget mindst 10% over normalen, RSI er i sundt momentum-territorium, og aktien er i Weinstein Stage 2. Alt peger i samme retning på samme tid. Det er her du handler.

**BUY BREAKOUT** betyder at aktien er tæt på at bryde igennem sin seneste modstand — den er inden for 6% af sit 20-dages højdepunkt og har de tekniske forudsætninger på plads. Entry sker på selve bruddet, ikke før.

**BUILD POSITION** er akkumulering med institutionel bekræftelse. Aktien konsoliderer tæt på sin korte støtte, volumen er normalt til svagt stigende, og mønsteret ligner det store penge køber stille og roligt op. Bygges gradvist — ikke alt på én gang.

**STARTER BUY** er det samme mønster som BUILD POSITION, men uden den institutionelle bekræftelse. Den tekniske struktur er der, men man ved endnu ikke om det er smart penge eller bare støj. Lille startposition — du øger hvis aktien bekræfter.

**WATCHLIST** er ikke et handlingssignal. Aktien er ikke klar, men den holder øje med. Typisk fordi én eller to betingelser mangler — fx at SMA20 ikke er over SMA60 endnu, eller at aktien stadig er under SMA200.

**EXIT** er et sælg-signal. Aktien viser mindst tre af fire klassiske svaghedstegn samtidig og har negativt momentum. Positionen lukkes.

Scoren (0–100) giver nuancen inden for hver tilstand. To aktier kan begge være BUY NOW, men én scorer 88 og den anden 61. Den høje score betyder at flere understøttende faktorer er aktive på samme tid — mere conviction bag signalet.

---

## Trin 1 — De rå indikatorer

Før scanneren kan beslutte noget, beregner den en række tekniske tal. Tænk på dem som rå ingredienser.

---

### SMA20, SMA60, SMA200 — de tre gennemsnit

**SMA** = Simple Moving Average. Bare et gennemsnit af de seneste N lukkekurser.

- **SMA20** = gennemsnit af de seneste 20 handelsdage (~1 måned)
- **SMA60** = gennemsnit af de seneste 60 handelsdage (~3 måneder)
- **SMA200** = gennemsnit af de seneste 200 handelsdage (~1 år)

De bruges som "støtteniveauer" — hvad er aktiens baseline på kort, mellem og lang sigt?

Hvis prisen er over SMA200: aktien er overordnet set i optrend.  
Hvis SMA20 er over SMA60: den kortsigtede bevægelse er stærkere end den mellemlangsigtede — momentum peger opad.

---

### RSI(14) — er aktien oversolgt eller overkøbt?

**RSI** = Relative Strength Index. Beregnes over 14 dage. Skala 0–100.

- **Under 30** = oversolgt (aktien er faldet hurtigt, kan bounce)
- **Over 70** = overkøbt (aktien er steget hurtigt, kan konsolidere)
- **46–72** = det søde felt — momentum uden at være for langt ude

RSI over 84 er et aktivt advarselssignal i scanneren: aktien er så overkøbt at den ryger i EXTENDED-tilstand, og du skal ikke købe den nu.

**RSI Trend** er den simple forskel: RSI nu minus RSI for 5 dage siden. Stiger RSI? Faldende? Det fortæller om momentumet accelererer eller aftager.

---

### ATR(5) og ATR(20) — volatilitet og squeeze

**ATR** = Average True Range. Måler hvor meget en aktie bevæger sig om dagen — men smartere end bare High minus Low, fordi den også tager gap-opens med.

**True Range for én dag** er det største af:
```
1. High − Low               (dagens intradag-spænd)
2. |High − gårsdagens Close|  (gap op + rally)
3. |Low  − gårsdagens Close|  (gap ned + fald)
```

**ATR(n)** = gennemsnit af True Range over n dage.

- **ATR(5)** = kortsigtets volatilitet (seneste uge)
- **ATR(20)** = normal/baseline-volatilitet (seneste måned)

**Squeeze** opstår når:
```
ATR(5) < ATR(20) × 0.78
```

Det vil sige: kortsigtets volatilitet er faldet til under 78% af den normale volatilitet. Aktien handler i et unormalt stramt interval. Det er ikke tilfældigt — det betyder typisk at der bygges energi op, og at et udbrud er tæt på.

**Hvorfor præcis 0.78?**  
Det er empirisk kalibrering. 0.90 ville fange alt for mange tilfældige rolige dage. 0.60 ville kun fange ekstreme squeezes og give meget få signaler. 0.78 er sweet spot'et — det kræver en reel kompression på 22%+ før det tæller. Det er et tunbart parameter i `CONFIG` og kan justeres.

**ATR(20) bruges også i stop-loss** — se stop-sektionen nedenfor.

---

### VolRatio (`volr`) og rvol50 — er der nogen hjemme?

Disse to måler begge det samme: er dagens volumen usædvanlig?

**`volr`** = dagens volumen / gennemsnitsvolumen de seneste 20 dage  
**`rvol50`** = dagens volumen / gennemsnitsvolumen de seneste 50 dage

`volr = 1.5` betyder 50% over den kortsigtede norm.  
`rvol50 = 1.5` betyder 50% over den langsigtsede norm.

**Kun `volr` bruges i signallogikken.** De konkrete krav er:
- MOMENTUM_ACTIVE kræver `volr ≥ 1.10`
- BREAKOUT_READY kræver `volr 0.95–3.0`
- Accumulation kræver `volr ≥ 0.90`

**`rvol50` er et display-tal** til dig. Det hjælper dig med at vurdere om et spike er reelt. Eksempel: `volr = 2.0` ser imponerende ud — men hvis `rvol50 = 0.8` betyder det at de seneste 20 dage har været usædvanligt stille, og spiken er ikke så stor som den ser ud mod en normal baseline.

---

### DistHigh20 — hvor tæt er aktien på modstanden?

```
DistHigh20 = (20-dages high − pris) / 20-dages high
```

Måler afstanden fra aktuel pris til det højeste punkt de seneste 20 dage. 

- `DistHigh20 = 0.03` = aktien er 3% under sin 20-dages top
- `DistHigh20 = 0.00` = aktien handler på sin 20-dages top lige nu

BREAKOUT_READY kræver `DistHigh20 ≤ 6%` — aktien skal altså allerede banker på døren.

---

### HigherLow — stiger bunden?

```
HigherLow = Low(seneste 5 dage) > Low(seneste 20 dage)
```

Simpel binær betingelse. Siger bare: er den kortsigtede bund højere end den mellemlangsigtede bund? Ja/Nej.

Hvis ja: køberne træder ind tidligere og tidligere. Det er et klart tegn på at der er stigende efterspørgsel i aktien.

---

### IBD RS Rank — vinder aktien mod resten?

IBD RS Rank rangerer aktien mod hele universet baseret på vægtet 12-måneders afkast.

Formlen deler det seneste år op i fire kvartaler og vægter det seneste kvartal højest:

```
RS_raw = q4×0.40 + q3×0.20 + q2×0.20 + q1×0.20

q4 = seneste kvartal  (mest relevant — vægtes 40%)
q3 = kvartal 2       (20%)
q2 = kvartal 3       (20%)
q1 = ældste kvartal  (20%)
```

Herefter percentil-rangeres alle aktier 0–99:
- **RS Rank 90** = aktien har klaret sig bedre end 90% af universet
- **RS Rank 50** = median — halvdelen gør det bedre, halvdelen dårligere
- **RS Rank 10** = aktien er en af de svageste i universet

**RS Trend** er noget andet: aktuel pris/lokalt indeks vs. for 21 dage siden. Det fortæller om aktien vinder eller taber markedsandele *lige nu* — på kort sigt.

---

### Weinstein Stage — den overordnede struktur

Weinstein Stage er det vigtigste enkeltfilter i scanneren. Det inddeler alle aktier i fire faser baseret på to ting: er prisen over eller under SMA200, og stiger eller falder SMA200?

| Stage | Betingelse | Hvad det betyder |
|-------|-----------|-----------------|
| **S1🔄** | Pris < SMA200, men SMA200 *stiger* | Bund-akkumulering. Patienter venter her. |
| **S2✅** | Pris > SMA200, og SMA200 *stiger* | Primær optrend. **Her køber du.** |
| **S3⚠️** | Pris > SMA200, men SMA200 *falder* | Topdannelse. Sælg eller undgå nye positioner. |
| **S4❌** | Pris < SMA200, og SMA200 *falder* | Primær nedtrend. Rør den ikke. |

**Alle BUY-signaler kræver Stage 2.** Hvis en aktie er i S1, S3 eller S4, sættes alle setup-flag til False uanset hvad andre indikatorer siger. Den kan maksimalt ende på WATCHLIST.

**Hvad "SMA200 stiger" præcis betyder i koden:** SMA200 nu sammenlignes med SMA200 for 20 handelsdage siden (~4 uger). Hvis den er højere nu end for 4 uger siden, stiger den.

---

### trend200 — den simple version af Weinstein

`trend200` er bare:

```python
trend200 = 'LONG TREND'       # pris > SMA200
trend200 = 'WEAK LONG TREND'  # pris < SMA200
```

Det er binært — ingen hældning, ingen tidsfaktor. Det lyder som Weinstein men er simplere: det handler kun om *er vi over stregen* og bruges som en betingelse inde i signalberegningerne. Weinstein tager desuden stilling til om SMA200 stiger eller falder.

`WEAK LONG TREND` medfører at alle BUY-setup-flag slukkes — og aktien havner på WATCHLIST.

---

### Dollar Volume (dolvol_usd) — er der penge nok?

```
dolvol_usd = gennemsnitsvolumen(20d) × pris × FX-rate
```

Alt konverteres til USD via live FX-kurser fra FMP API (med hardcodede fallbacks). Det er vigtigt fordi en koreansk aktie handles i KRW og en norsk i NOK — man kan ikke sammenligne rå volumental på tværs af valutaer.

Likviditetsfilter:
- Mindst **200.000 aktier** dagligt
- Mindst **8.000.000 USD** i daglig dollar-volumen

Aktier der ikke passerer dette filter straffes med −14 i RiskPenalty og kan ikke opnå et BUY-signal.

---

## Trin 2 — ifs (Institutional Flow Score)

**ifs** er en intern score 0–100 der bruges som proxy for institutionel akkumulering. Den er ikke en direkte indikator — den er en sammenvejning af seks betingelser der tilsammen siger: "ligner dette en aktie som smart penge køber?"

| Betingelse | Point |
|---|---|
| VolRatio > 1.15 (15% over norm) | +20 |
| HigherLow = true | +20 |
| RS Trend = UP | +20 |
| Pris > SMA20 | +20 |
| RSI 42–68 | +20 |
| Pris > SMA200 ("LONG TREND") | +10 |
| `inst_accum` flag fra FMP-data | +10 |

Maks: 100. Capped med `min(ifs, 100)`.

**ifs bruges tre steder:**

1. **TrendScore** — `ts += min(10, int(ifs / 10))` — dvs. ifs=100 giver 10 point, ifs=50 giver 5 point
2. **INSTITUTIONAL_BUILD filter** — `ifs ≥ 65` er nok til at opkvalificere fra ACCUMULATION til INSTITUTIONAL_BUILD, selvom der ikke er et eksternt `inst_accum`-flag
3. **`ia`-flag** (inst_accum intern) — bruges i opbygning af ifs selv som et af de seks inputs

---

## Trin 3 — Scoring

**Score (0–100) = TrendScore + SetupScore − RiskPenalty**

Ingen af de tre delscore er capped individuelt — men summen klippes til 0–100.

---

### TrendScore (ts) — er trenden sund?

| Betingelse | Point | Hvad det fortæller |
|---|---|---|
| Pris > SMA200 | +24 | Aktien er i primær optrend |
| SMA20 > SMA60 | +18 | Kortsigtet momentum over mellemlangsigtet |
| Pris > SMA20 | +10 | Aktien holder sig over sin kortsigtede støtte |
| RS Trend = UP | +12 | Aktien vinder mod sit lokale marked de seneste 21 dage |
| HigherLow = true | +8 | Stigende bund — køberne er aktive |
| ifs / 10 (maks 10) | +0–10 | Institutionel flow proxy |

**Maks ~82 point.**

---

### SetupScore (ss) — er der et konkret setup?

| Betingelse | Point | Hvad det fortæller |
|---|---|---|
| Accumulation-flag | +20 | Baser dannes — stram konsolidering med volumen |
| Institutional Build-flag | +18 | Akkumulering med institutionel bekræftelse |
| Breakout Ready-flag | +22 | Aktien banker på modstand — udbrud nær |
| Momentum Active-flag | +16 | Udbrud bekræftet med volumen og acceleration |
| Squeeze aktiv | +6 | ATR(5) < ATR(20) × 0.78 — energi bygges op |
| Tight range | +6 | ATR/pris ≤ 4.5% — aktien konsoliderer stramt |
| RSI 46–72 | +6 | Sundt momentum-niveau |
| DistHigh20 ≤ 7% | +6 | Tæt på modstanden |
| VolRatio ≥ 0.95 | +6 | Normalt til stigende volumen |
| ls / 10 (maks 10) | +0–10 | Likviditetsscore: ≥100M USD=30p, ≥30M=20p, ≥8M=10p |

**Maks ~90 point.**

---

### RiskPenalty (rp) — trækkes fra

| Betingelse | Point | Hvad det fortæller |
|---|---|---|
| Likviditet ikke godkendt | −14 | Under 200k aktier eller 8M USD dagligt |
| Failed Setup | −14 | ≥3 svaghedstegn + RSI<42 eller pris<Low5 |
| RISK_OFF regime | −10 | SPY/QQQ/IWM i nedtrend eller VIX forhøjet |
| Extended | −8 | RSI>84 eller pris>SMA20×1.14 — løbet for langt |
| Weakening | −8 | ≥2 svaghedstegn aktive |
| RS Trend = DOWN | −6 | Aktien taber mod sit marked |
| Cap Risk | −6 | dolvol_usd < 25M USD — lille og illikvid |

---

## Trin 4 — De 7 tilstande

Ud fra alle ovenstående beregninger placeres aktien i én af syv tilstande. Tilstanden bestemmer signalet.

---

### 1. FAILED_SETUP → `EXIT`

Aktien er i aktiv nedtur. Sælg-signal.

**Krav:**  
Mindst 3 af disse 4 svaghedstegn er aktive:
- Pris < SMA20
- SMA20 < SMA60
- Pris < SMA200
- RS Trend = DOWN

**Plus** mindst ét af:
- RSI < 42 (momentum er negativt)
- Pris < Low5 (aktien sætter nye korttids-lavpunkter)

---

### 2. EXTENDED → `EXTENDED — WAIT`

Aktien er løbet for langt og er teknisk overkøbt. Intet nyt køb.

**Krav (ét af følgende er nok):**
- RSI > 84
- Pris > SMA20 × 1.14 (mere end 14% over 20-dages gennemsnit)

Vent på at aktien konsoliderer og bygger en ny base.

---

### 3. MOMENTUM_ACTIVE → `BUY NOW`

Højeste prioritet. Aktien bryder ud med volumenkonfirmation.

**Krav (alle skal opfyldes):**
- Alt fra BREAKOUT_READY opfyldt (se nedenfor)
- VolRatio ≥ 1.10
- RSI 50–80
- Likviditet godkendt
- Markedsregime ≠ RISK_OFF
- Weinstein Stage = 2

---

### 4. BREAKOUT_READY → `BUY BREAKOUT`

Aktien er tæt på at bryde igennem med momentum.

**Krav (alle skal opfyldes):**
- SMA20 > SMA60
- Pris > SMA200
- RS Trend: UP eller FLAT
- DistHigh20: 0–6% (banker på modstanden)
- VolRatio: 0.95–3.0
- RSI: 44–78
- Squeeze ELLER DistHigh20 ≤ 3% (ét af de to er nok)
- Weinstein Stage = 2

---

### 5. INSTITUTIONAL_BUILD → `BUILD POSITION`

Aktien bygger base med institutionel deltagelse.

**Krav (alle skal opfyldes):**
- Alle Accumulation-betingelser opfyldt (se nedenfor)
- Plus: `inst_accum`-flag ELLER ifs ≥ 65

---

### 6. ACCUMULATION → `STARTER BUY`

Teknisk akkumulering uden bekræftet institutionel deltagelse. Lille startposition.

**Krav (alle skal opfyldes):**
- SMA20 > SMA60
- Pris > SMA200
- RSI: 38–64
- VolRatio ≥ 0.90
- Pris inden for 6% af SMA20
- RS Trend: UP, FLAT eller tom
- Weinstein Stage = 2
- Opfylder *ikke* INSTITUTIONAL_BUILD

---

### 7. WATCHLIST

Aktien opfylder ingen af ovenstående — men er ikke i decideret nedtur. Hold øje.

---

## Signal-hierarki

```
BUY NOW          ← Momentum bekræftet med volumen. Højeste prioritet.
BUY BREAKOUT     ← Nær udbrud. Entry på breakout.
BUILD POSITION   ← Institutionel akkumulering i base. Byg gradvist.
STARTER BUY      ← Teknisk akkumulering. Lille startposition.
EXTENDED — WAIT  ← Overkøbt. Vent på base.
WATCHLIST        ← Ikke klar. Overvågning.
EXIT             ← Failed setup. Sælg.
```

---

## Stop-loss

Stop beregnes individuelt baseret på tilstand og aktiens volatilitet. Aldrig arbitrære procenter — altid skaleret til aktiens faktiske daglige bevægelse (ATR20).

| Tilstand | Formel | Logik |
|---|---|---|
| MOMENTUM_ACTIVE | `max(Low5, pris − 1.5 × ATR20)` | Stopper ud 1.5 normale dage under køb |
| INSTITUTIONAL_BUILD | `max(Low5, SMA20 − 0.5 × ATR20)` | Stopper under basen med lidt luft |
| Alle andre | `SMA20` | Støttegrænsen for trend |
| Stop ≥ pris | `None` — vises som `—` | Matematisk umuligt, men vi checker |

`Low5` er laveste daily low de seneste 5 dage. `max(Low5, ...)` sikrer at stoppet aldrig sættes over et reelt støtteniveau der allerede er brudt.

---

## Markedsregime

Scanneren beregner et markedsregime fra SPY, QQQ, IWM trend + daglige bevægelser + VIX niveau og retning + breadth fra universet selv.

| Regime | Effekt |
|---|---|
| **BULL** | Fuld scoring, alle signaler aktive |
| **NEUTRAL** | Fuld scoring, alle signaler aktive |
| **RISK_OFF** | RiskPenalty +10. MOMENTUM_ACTIVE undertrykkes direkte. |

I RISK_OFF nedgraderes aktier naturligt i score. Scorer der normalt ville give BUY NOW falder typisk nok til at lande på WATCHLIST eller BREAKOUT_READY i stedet.

---

## S1 Pipeline — hvad venter i kulissen?

S1-tabben viser aktier der endnu ikke er BUY, men nærmer sig. Filteret er:

- Weinstein Stage = S1 (pris < SMA200, men SMA200 stiger)
- SMA20 > SMA60 (intern trend er allerede positiv)
- Afstand til SMA200 ≤ 12% (justerbar — tæt på bruddet)
- RS Rank ≥ 50 (relativ styrke bygges op)
- Sorteret efter afstand til SMA200 ascending — de nærmeste øverst

Disse er ikke BUY-signaler. Det er en watchlist for "hvad kan blive Stage 2 inden for de næste uger."

---

## FX-normalisering

Alle volumen-baserede beregninger konverteres til USD:

```
dolvol_usd = AvgVol(20d) × pris × FX_rate
```

FX-kurser hentes live fra FMP API. Ved fejl bruges hardcodede fallbacks:

| Valuta | Fallback |
|---|---|
| DKK | 0.145 |
| NOK | 0.092 |
| SEK | 0.095 |
| KRW | 0.00074 |
| EUR | 1.08 |
| GBP | 1.27 |

Uden FX-normalisering ville en koreansk aktie med 10.000 KRW i pris se ud til at have ekstremt lav dollar-volumen, og Samsung ville fejlagtigt blive filtreret fra som illikvid.

---

*Dokumentation: Momentum Mike · scanner_core.py · Juni 2026*
