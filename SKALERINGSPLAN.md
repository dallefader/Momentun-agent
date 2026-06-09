# Skaleringsplan — Trading Scanner til 5000 aktier, 24/7 på Mac mini

*Udarbejdet som senior arkitekt-review. Mål: skalere fra ~650 aktier i en monolitisk Streamlit-app til 5000 aktier med kontinuerlig rolling-opdatering og en overvågningsagent der videregiver information til dig.*

---

## 1. Den korte version

Vi flytter fra én monolitisk app der henter, beregner og viser ALT ved hver sideindlæsning, til en arkitektur med fire adskilte lag: en **ingestion-worker** der henter data i ruller i baggrunden, et **lager** (SQLite) der gemmer resultaterne, en **præsentation** (Streamlit) der læser fra lageret øjeblikkeligt, og en **overvågningsagent** der både alarmerer (regelbaseret) og fortolker (Claude) og sender besked til dig via email, push og iMessage.

Den vigtigste indsigt: ved 5000 aktier KAN man ikke hente alt synkront ved sideindlæsning — det ville tage 10-20+ minutter og udløse Yahoo-rate-limits. Data-indhentning skal afkobles fra visning. Det er hele kernen i planen.

---

## 2. Hvorfor den nuværende arkitektur ikke skalerer

Den nuværende v6 henter alle aktier via `yfinance` ved hver scan, beregner indikatorer i samme synkrone gennemløb, og cacher resultatet i Streamlit's hukommelse i 15 minutter. Det fungerer fint ved 650 aktier (30-90 sekunder). Men:

Ved 5000 aktier bliver det 100 chunks à 50 tickere. Selv ved optimistiske 2-3 sekunder pr. chunk er det 5-15 minutter alene til download — før indikator-beregning. En bruger der åbner siden ville vente i mange minutter på hver kold cache. Det er ubrugeligt til en "løbende opdaterende" terminal.

Dertil kommer at Yahoo rate-limiter aggressivt når man fyrer tusindvis af requests af i træk. Den nuværende "hent alt på én gang"-model vil blive blokeret. Og fordi intet gemmes på disk mellem kørsler, genberegnes alt fra bunden hver gang — spild af både tid og Yahoo-godwill.

Konklusionen er klar: indhentning skal ske kontinuerligt i baggrunden, resultaterne skal persisteres, og UI'et skal kun læse færdige resultater.

---

## 3. Den nye arkitektur — fire lag

**Lag 1 — Ingestion-worker (baggrundsproces).** En Python-daemon der kører konstant via macOS `launchd`. Den vedligeholder et lokalt pris-historik-lager, så den kun henter NYE bars inkrementelt i stedet for at trække et helt års historik hver gang. Den cykler gennem universet i chunks med rate-limit-venlige forsinkelser, beregner indikatorer + signaler efter hver chunk, og skriver resultatet til lageret.

**Lag 2 — Lager (SQLite).** En enkelt fil-baseret database — ingen server, perfekt til én maskine. Den indeholder fem tabeller: `prices` (OHLCV-historik pr. ticker, til inkrementelle opdateringer og charts), `scan_results` (seneste beregnede snapshot, én række pr. ticker — det UI'et læser), `signals_history` (daglige BUY-snapshots til backtest), `universe` (de 5000 tickere + metadata), og `diagnostics` (indhentnings-sundhed). SQLite klarer dette uden problemer; hvis vi senere vil lave tunge analytiske queries over historik, kan vi skifte til DuckDB.

**Lag 3 — Præsentation (Streamlit).** Stort set samme UI som v6, men datakilden er nu databasen i stedet for live yfinance. Sideindlæsning bliver sub-sekund fordi alt er forberegnet. Hver ticker viser et "sidst opdateret"-timestamp, så du kan se hvor frisk data er.

**Lag 4 — Overvågningsagent.** To dele, jf. dit valg. En **deterministisk alarm-motor** der kører efter hver indhentnings-cyklus, sammenligner nye resultater med forrige, og udløser notifikationer ved konkrete hændelser. Og en **Claude AI-digest** der periodisk læser databasen og skriver naturligt-sprog resuméer samt kan svare på spørgsmål.

---

## 4. Hardware — Mac mini

En Mac mini med M-serie-chip (M2 eller M4) er rigeligt. Anbefaling: 16 GB RAM for headroom når du holder pris-historik for 5000 aktier i hukommelsen under beregning. Maskinen kører 24/7 og bruger meget lidt strøm (typisk 7-30W).

macOS er faktisk et godt valg her, ikke kun pga. iMessage-muligheden, men også fordi `launchd` er en robust scheduler der genstarter dine processer hvis de crasher. Python installeres via Homebrew eller pyenv. Hele scanneren porteres uændret — koden er ren Python og kører identisk på macOS.

---

## 5. Rolling chunk-ingestion — sådan danser vi med Yahoo

Dette er det tekniske hjerte. Tre principper gør Yahoo til en medspiller i stedet for en modstander:

**Inkrementel hentning.** Vi henter den fulde historik ÉN gang (backfill), gemmer den lokalt, og derefter henter vi kun de seneste få dages bars (`period='5d'`) og fletter dem ind. Det reducerer datamængden pr. request dramatisk og dermed rate-limit-presset.

**Tiered refresh-frekvens.** Ikke alle aktier behøver opdateres lige ofte. Tier A (dine positioner + watchlist + aktive BUY-kandidater) opdateres hvert 5-10 minut. Tier B (resten af det likvide univers) hvert 30-60 minut. Tier C (fuld historik-backfill og validering) om natten. På den måde er det du faktisk handler på altid friskt, mens den lange hale opdateres roligere.

**Rate-limit-venlig rytme.** Forsinkelser mellem chunks (1-2 sek + jitter) for at undgå genkendelige burst-mønstre, exponential backoff ved fejl (har vi), og Stooq-failover (har vi). Vi tracker per-ticker sidste-succes-timestamp og nedprioriterer kronisk fejlende tickere automatisk.

Med denne model cykler de 5000 aktier igennem over fx 30-60 minutter, og hver enkelt aktie bliver løbende opdateret uden at vi nogensinde sender en kæmpe burst.

---

## 6. Universe-håndtering ved 5000 aktier

Universet flyttes fra den hardkodede Python-liste til `universe`-tabellen i databasen med felterne ticker, navn, sektor, region, valuta, tier, aktiv-flag og sidst-valideret. Den lookup-funktion vi byggede genbruges til nem tilføjelse — den slår op og indsætter i tabellen.

At skaffe 5000 GYLDIGE Yahoo-symboler er i sig selv et stykke arbejde. Den realistiske vej er at seede fra indeks-konstituenter: S&P 1500, Russell 2000, STOXX 600, Nikkei 225, OMX Norden osv. Disse lister findes offentligt (fx Wikipedia eller CSV-kilder), men hvert symbol skal mappes til Yahoo's konvention. Vi bygger en valideringsworker der periodisk tjekker om hver ticker stadig returnerer data og flagger døde symboler (som de `HZNP` og `AGN` vi allerede fandt) — så universet ikke rådner.

---

## 7. Overvågningsagenten — begge dele

**Den deterministiske alarm-motor** kører efter hver indhentnings-cyklus og sammenligner det nye snapshot med det forrige. Den udløser notifikationer ved konkrete, konfigurerbare hændelser: nyt BUY NOW- eller BUY BREAKOUT-signal, en position der krydser under sit stop, et regimeskift (RISK_ON ↔ RISK_OFF), et watchlist-navn der træder ind i Stage 2, eller et volumen-spike/squeeze der udløses. Det er hurtigt, forudsigeligt og koster ingenting at drive.

**Claude AI-digesten** kører på fastlagte tidspunkter (fx morgen-brief, midt-på-dagen-puls, og luk-resumé). Den læser scan_results, signals_history og dine positioner, og skriver et naturligt-sprog resumé: "Markedet er RISK_ON. 12 nye Stage-2-setups dukkede op i dag, koncentreret i Energy og Semiconductors. Din DVN-position er +7,7% men nærmer sig stop ved X. Tre af gårsdagens BUY NOW-signaler er allerede +3% i snit." Den kan også svare på ad-hoc spørgsmål fra dig.

Den smukke arbejdsdeling: alarm-motoren fanger det tidskritiske med det samme, mens Claude leverer overblik og fortolkning når du har brug for at forstå helheden.

---

## 8. Notifikationer — email, push og iMessage

**Email** egner sig til de længere digests — morgen-brief og EOD-resumé i indbakken. Sættes op via SMTP (fx Gmail med app-password) eller en transaktionel mail-tjeneste.

**Push (ntfy eller Pushover)** er til de tidskritiske alarmer der skal poppe op på telefonen med det samme. ntfy er gratis og open-source (kan endda self-hostes på Mac mini'en); Pushover koster et engangsbeløb på ~$5 men er ekstremt enkel. Begge er bare et HTTP POST fra Python.

**iMessage** — din Mac-specifikke fordel. Mac mini'en kan sende iMessages til dit telefonnummer via AppleScript (`osascript`), så længe den er logget ind på dit Apple-ID i Beskeder-appen. Det giver native blå bobler på din iPhone uden nogen tredjepartstjeneste. Forbehold: det kræver at Mac mini'en har Beskeder kørende og de rette Automation/Full Disk Access-tilladelser, og Apple ændrer en sjælden gang AppleScript-adfærd så det kan kræve vedligehold. Men til personligt brug er det elegant og gratis.

Den fornuftige opsætning: hurtige alarmer via push + iMessage, længere digests via email.

---

## 9. Faseinddelt køreplan

**Fase 0 — Mac mini-fundament.** Opsæt maskinen, installer Python-miljø via Homebrew, port v6 over, og bekræft at den kører identisk. Lav ingen arkitektur-ændringer endnu — bare få den nuværende app til at køre stabilt på den nye maskine.

**Fase 1 — Lager-laget.** Introducer SQLite. Migrér v6 så den skriver scan-resultater til databasen og læser derfra i stedet for in-memory cache. Stadig samme univers-størrelse — vi ændrer kun HVOR data bor, ikke hvor mange. Dette er det vigtigste enkelt-skridt, fordi det afkobler beregning fra visning.

**Fase 2 — Ingestion-worker.** Byg baggrunds-daemonen: inkrementel hentning, lokalt historik-lager, rolling chunks med tiered frekvens, og `launchd`-opsætning så den kører 24/7 og genstarter ved crash. Nu opdaterer data sig selv løbende, og Streamlit bliver ren læser.

**Fase 3 — Skalér til 5000.** Seed universet fra indeks-konstituenter, byg valideringsworkeren der luger døde tickere ud, og tune chunk-rytmen så fuld cyklus rammer en fornuftig kadence uden Yahoo-ballade. Her presser vi systemet og finder de reelle rate-limit-grænser.

**Fase 4 — Alarm-motor + notifikationer.** Byg den deterministiske diff-motor og koble email, push og iMessage på. Konfigurerbare triggers så du kun får besked om det der betyder noget for dig.

**Fase 5 — Claude-digest-agent.** Periodiske AI-resuméer + interaktiv Q&A oven på databasen. Her kommer den "agent der holder øje konstant og videregiver information" til sin ret.

**Fase 6 — Hærdning.** Auto-genstart, sundheds-overvågning af selve workeren (en alarm hvis ingestion stopper!), backup af databasen, og log-rotation. Det kedelige men kritiske der gør forskellen på et hobby-projekt og noget du tør stole på.

---

## 10. Risici og faldgruber

**Yahoo rate-limits ved skala** er den klart største risiko. Hele ingestion-designet (inkrementel, tiered, jitter, failover) er bygget for at afbøde det, men ved 5000 aktier nærmer vi os grænsen for hvad en gratis uofficiel kilde tåler. Det er her en betalt kilde før eller siden bliver relevant (se afsnit 12).

**Datakvalitet ved 5000** falder — der vil være langt flere junk-tickere, splits, NaN-spækkede serier og delistede navne end ved 650. Valideringsworkeren og de defensive checks vi allerede byggede (NaN-filtre, 'Close'-checks) bliver endnu vigtigere.

**Signal-støj.** Med 5000 aktier vil der altid være snesevis af BUY-signaler. Stage 2 hard-filteret og rankingen bliver afgørende for at du ikke drukner. Vi bør overveje strammere likviditetsgrænser og måske en "kun top N efter score"-visning som standard.

**Mac mini-pålidelighed.** En maskine der kører 24/7 skal overvåge sig selv. Hvis ingestion-workeren dør klokken 3 om natten skal du have besked — ellers viser UI'et forældet data uden at nogen opdager det.

**iMessage-skrøbelighed.** AppleScript-automation er elegant men kan brydes af macOS-opdateringer. Hav push (ntfy) som backup-kanal så du aldrig er afhængig af én skrøbelig mekanisme.

---

## 11. Omkostninger

Mac mini M4 (16 GB anbefales): ca. 5.000-7.000 kr. engangsudgift. yfinance: gratis. ntfy: gratis (Pushover ~35 kr. engang). iMessage: gratis. Claude API til digest-agenten: afhænger af frekvens, anslået 35-200 kr./måned ved nogle få daglige resuméer. Strøm: forsvindende lille. Eventuel betalt datakilde senere: EOD Historical Data ca. 140-560 kr./md, Polygon fra ca. 200 kr./md.

Samlet for at komme i gang: hardware + stort set nul løbende omkostninger udover Claude-API'en, indtil/hvis du beslutter dig for en betalt datakilde.

---

## 12. Hvornår en betalt datakilde bliver nødvendig

Vi starter yfinance-only, men du skal kende tærsklerne hvor det giver mening at betale. Det bliver relevant når: den kroniske fejlrate ved 5000 aktier overstiger din tolerance (sig >10% af universet der konsekvent fejler), når en fuld refresh-cyklus tager så lang tid at data ikke længere er aktuelt nok, eller når/hvis du vil have intraday i stedet for kun daglige EOD-data.

EOD Historical Data er det bedste prisleje for daglige slutkurser i denne skala — den er bygget til præcis det her og fjerner Yahoo-smerten helt. Polygon er stærkere hvis du senere vil have intraday/realtid. Min anbefaling: byg pipelinen kildeagnostisk (et tyndt data-lag som ingestion-workeren kalder), så vi kan skifte fra yfinance til en betalt kilde ved at ændre ÉT modul, uden at røre resten af systemet.

---

## 13. Næste skridt

Når du har Mac mini'en, foreslår jeg vi starter med **Fase 1 (lager-laget)** allerede på din nuværende maskine — det kan vi gøre nu, uafhængigt af hardwaren, og det er den enkeltstående ændring der gør mest forskel. Derefter Fase 2 (ingestion-worker), som er der den løbende opdatering bliver virkelig.

Sig til når du vil have mig til at skrive koden til Fase 1, så bygger vi lager-laget og migrerer v6 til at læse fra databasen.
