"""
scanner_core.py — Streamlit-fri ALGORITME-KERNE.

FASE 2: Dette modul er den KANONISKE kilde til scanner-algoritmen, så både
UI'et (scanner_v7.py) og baggrunds-workeren (ingestion_worker.py) regner
PRÆCIS det samme. Ingen streamlit, ingen yfinance-cache — rene funktioner
der kan importeres hvor som helst.

VIGTIGT: Indikator-funktionerne og derive_states her er KOPIERET 1:1 fra
scanner_v7.py og verificeres byte-for-byte ved generering. compute_scan()
indeholder den eksakte per-ticker-loop fra fetch_scanner_data, løftet ordret,
så et givent datasæt giver identiske signaler uanset om det er UI'et eller
workeren der beregner. Ændringer i algoritmen skal fremover ske HER.
"""
from __future__ import annotations
import logging
import numpy as np
import pandas as pd

LOG = logging.getLogger("scanner_core")

# ════════════════════════════════════════════════════════════════════
# KONSTANTER (kopieret 1:1 fra scanner_v7.py)
# ════════════════════════════════════════════════════════════════════
CONFIG = {
    'rsi_period': 14, 'sma_fast': 20, 'sma_mid': 60, 'sma_long': 200,
    'atr_fast': 5, 'atr_slow': 20, 'breakout_distance': 0.06,
    'squeeze_factor': 0.78, 'min_avg_vol': 200_000,
    'min_dollar_vol': 8_000_000,                       # nu USD-normaliseret via FX
    'max_retries': 3,
    'retry_backoff_base': 2.0,                         # sek for exponential backoff
    'forward_return_horizons': [20, 60, 120],          # backtest forward returns
    'min_history_days': 210,
}

CURRENCY_BY_REGION = {
    'US':'USD','Denmark':'DKK','Sweden':'SEK','Norway':'NOK','Finland':'EUR',
    'Germany':'EUR','UK':'GBP','France':'EUR','Netherlands':'EUR',
    'Switzerland':'CHF','Spain':'EUR','Italy':'EUR','Japan':'JPY',
    'HongKong':'HKD','SouthKorea':'KRW','Taiwan':'TWD','India':'INR',
    'Canada':'CAD','Australia':'AUD','Brazil':'BRL','Israel':'ILS',
    'Global':'USD','Europe':'EUR','Commodities':'USD','Crypto':'USD',
    'Unknown':'USD',
}

REGION_INDEX = {
    'US':          'SPY',
    'Denmark':     '^OMXC25',
    'Sweden':      '^OMXS30',
    'Norway':      '^OSEBX',
    'Finland':     '^OMXH25',
    'Germany':     '^GDAXI',
    'UK':          '^FTSE',
    'France':      '^FCHI',
    'Netherlands': '^AEX',
    'Switzerland': '^SSMI',
    'Spain':       '^IBEX',
    'Italy':       'FTSEMIB.MI',
    'Japan':       '^N225',
    'HongKong':    '^HSI',
    'SouthKorea':  '^KS11',
    'Taiwan':      '^TWII',
    'India':       '^BSESN',
    'Canada':      '^GSPTSE',
    'Australia':   '^AXJO',
    'Brazil':      '^BVSP',
    'Israel':      '^TA125.TA',
    'Global':      'SPY',
    'Europe':      'VGK',
    'Commodities': 'GLD',
    'Crypto':      'BITO',
}

UNIVERSE = [
    # ── USA TECH / AI ──────────────────────────────────────
    ('AAPL','Apple','Tech','US','CORE'),('MSFT','Microsoft','Tech','US','CORE'),
    ('GOOGL','Alphabet','Tech','US','CORE'),('META','Meta','Tech','US','CORE'),
    ('NVDA','NVIDIA','AI','US','CORE'),('AMD','AMD','AI','US','CORE'),
    ('AVGO','Broadcom','AI','US','CORE'),('MU','Micron','AI','US','CORE'),
    ('INTC','Intel','AI','US','CORE'),('QCOM','Qualcomm','AI','US','CORE'),
    ('ARM','ARM Holdings','AI','US','CORE'),('SMCI','Super Micro','AI','US','CORE'),
    ('PLTR','Palantir','AI','US','CORE'),('TSM','TSMC','AI','US','CORE'),
    ('ADBE','Adobe','Tech','US','CORE'),('CRM','Salesforce','Tech','US','CORE'),
    ('NOW','ServiceNow','Tech','US','CORE'),('SNOW','Snowflake','Tech','US','CORE'),
    ('CRWV','CoreWeave','AI','US','EXTENDED'),
    ('NBIS','Nebius Group','AI','US','EXTENDED'),
    ('IREN','IREN Limited','AI','US','EXTENDED'),
    ('APLD','Applied Digital','AI','US','EXTENDED'),
    ('CORZ','Core Scientific','AI','US','EXTENDED'),
    ('WULF','TeraWulf','AI','US','EXTENDED'),
    ('CIFR','Cipher Mining','Momentum','US','EXTENDED'),
    ('HUT','Hut 8 Corp','Momentum','US','EXTENDED'),
    ('ASTS','AST SpaceMobile','Tech','US','EXTENDED'),
    ('LUNR','Intuitive Machines','Industrials','US','EXTENDED'),
    ('SPIR','Spire Global','Tech','US','EXTENDED'),
    ('PL','Planet Labs','Tech','US','EXTENDED'),
    ('DXYZ','Destiny Tech100','Financials','US','EXTENDED'),
    ('XOVR','ERShares Crossover ETF','Financials','US','EXTENDED'),
    ('SPGI','S&P Global','Financials','US','EXTENDED'),
    ('MCO','Moodys','Financials','US','EXTENDED'),
    ('ICE','Intercontinental Exchange','Financials','US','EXTENDED'),
    ('CME','CME Group','Financials','US','EXTENDED'),
    ('MSCI','MSCI Inc','Financials','US','EXTENDED'),
    ('TRV','Travelers','Financials','US','EXTENDED'),
    ('PGR','Progressive','Financials','US','EXTENDED'),
    ('ALL','Allstate','Financials','US','EXTENDED'),
    ('MET','MetLife','Financials','US','EXTENDED'),
    ('PRU','Prudential','Financials','US','EXTENDED'),
    ('AFL','Aflac','Financials','US','EXTENDED'),
    ('USB','US Bancorp','Financials','US','EXTENDED'),
    ('PNC','PNC Financial','Financials','US','EXTENDED'),
    ('TFC','Truist Financial','Financials','US','EXTENDED'),
    ('MTB','M&T Bank','Financials','US','EXTENDED'),
    ('FITB','Fifth Third','Financials','US','EXTENDED'),
    ('HBAN','Huntington','Financials','US','EXTENDED'),
    ('RF','Regions Financial','Financials','US','EXTENDED'),
    ('CFG','Citizens Financial','Financials','US','EXTENDED'),
    ('KEY','KeyCorp','Financials','US','EXTENDED'),
    ('DELL','Dell Technologies','Tech','US','EXTENDED'),
    ('HPQ','HP Inc','Tech','US','EXTENDED'),
    ('IBM','IBM','Tech','US','EXTENDED'),
    ('ACN','Accenture','Tech','US','EXTENDED'),
    ('CTSH','Cognizant','Tech','US','EXTENDED'),
    ('WIT','Wipro','Tech','US','EXTENDED'),
    ('INFY','Infosys','Tech','US','EXTENDED'),
    ('SAP','SAP SE','Tech','US','EXTENDED'),
    ('TEAM','Atlassian','Tech','US','EXTENDED'),
    ('ZM','Zoom','Tech','US','EXTENDED'),
    ('DOCU','DocuSign','Tech','US','EXTENDED'),
    ('BOX','Box Inc','Tech','US','EXTENDED'),
    ('TWLO','Twilio','Tech','US','EXTENDED'),
    ('MDB','MongoDB','Tech','US','EXTENDED'),
    ('ESTC','Elastic','Tech','US','EXTENDED'),
    ('CFLT','Confluent','Tech','US','EXTENDED'),
    ('HUBS','HubSpot','Tech','US','EXTENDED'),
    ('VEEV','Veeva Systems','Tech','US','EXTENDED'),
    ('WDAY','Workday','Tech','US','EXTENDED'),
    ('ADSK','Autodesk','Tech','US','EXTENDED'),
    ('MSFT','Microsoft','Tech','US','EXTENDED'),
    ('RELY','Remitly','Financials','US','EXTENDED'),
    ('ASAN','Asana','Tech','US','EXTENDED'),
    ('BRZE','Braze','Tech','US','EXTENDED'),
    ('DOMO','Domo Inc','Tech','US','EXTENDED'),
    ('FROG','JFrog','Tech','US','EXTENDED'),
    ('GITLAB','GitLab','Tech','US','EXTENDED'),
    ('SQSP','Squarespace','Tech','US','EXTENDED'),
    ('WIX','Wix.com','Tech','US','EXTENDED'),
    ('WEBR','Weber Inc','Consumer','US','EXTENDED'),
    ('TASK','TaskUs','Tech','US','EXTENDED'),
    ('EXLS','ExlService','Tech','US','EXTENDED'),
    ('EPAM','EPAM Systems','Tech','US','EXTENDED'),
    ('GLOB','Globant','Tech','US','EXTENDED'),
    ('ARCO','Arcos Dorados','Consumer','US','EXTENDED'),
    ('VTEX','VTEX','Tech','US','EXTENDED'),
    ('ONEM','One Medical','Healthcare','US','EXTENDED'),
    ('CERT','Certara','Healthcare','US','EXTENDED'),
    ('SDGR','Schrodinger','Healthcare','US','EXTENDED'),
    ('ABSM','Absci','Healthcare','US','EXTENDED'),
    ('ABCL','AbCellera','Healthcare','US','EXTENDED'),
    ('IMVT','Immunovant','Healthcare','US','EXTENDED'),
    ('KYMR','Kymera Therapeutics','Healthcare','US','EXTENDED'),
    ('ARQT','Arcutis Biotherapeutics','Healthcare','US','EXTENDED'),
    ('TARS','Tarsus Pharma','Healthcare','US','EXTENDED'),
    ('DAWN','Day One Pharma','Healthcare','US','EXTENDED'),
    ('IMCR','Immunocore','Healthcare','US','EXTENDED'),
    ('RCKT','Rocket Pharma','Healthcare','US','EXTENDED'),
    ('FOLD','Amicus Therapeutics','Healthcare','US','EXTENDED'),
    ('RARE','Ultragenyx','Healthcare','US','EXTENDED'),
    ('ALNY','Alnylam Pharma','Healthcare','US','EXTENDED'),
    ('IONS','Ionis Pharma','Healthcare','US','EXTENDED'),
    ('SRPT','Sarepta Therapeutics','Healthcare','US','EXTENDED'),
    ('BMRN','BioMarin','Healthcare','US','EXTENDED'),
    ('ACAD','Acadia Pharma','Healthcare','US','EXTENDED'),
    ('SAGE','Sage Therapeutics','Healthcare','US','EXTENDED'),
    ('PTGX','Protagonist Therapeutics','Healthcare','US','EXTENDED'),
    ('PRGO','Perrigo','Healthcare','US','EXTENDED'),
    ('JAZZ','Jazz Pharma','Healthcare','US','EXTENDED'),
    ('SUPN','Supernus Pharma','Healthcare','US','EXTENDED'),
    ('INVA','Innoviva','Healthcare','US','EXTENDED'),
    ('PAHC','Phibro Animal Health','Healthcare','US','EXTENDED'),
    ('ZTS','Zoetis','Healthcare','US','EXTENDED'),
    ('ELAN','Elanco Animal Health','Healthcare','US','EXTENDED'),
    ('PCRX','Pacira BioSciences','Healthcare','US','EXTENDED'),
    ('HRMY','Harmony Biosciences','Healthcare','US','EXTENDED'),
    ('ADMA','ADMA Biologics','Healthcare','US','EXTENDED'),
    ('HALO','Halozyme','Healthcare','US','EXTENDED'),
    ('ARGX','argenx','Healthcare','US','EXTENDED'),
    ('ROIV','Roivant Sciences','Healthcare','US','EXTENDED'),
    ('SWTX','SpringWorks','Healthcare','US','EXTENDED'),
    ('KRTX','Karuna Therapeutics','Healthcare','US','EXTENDED'),
    ('CEREVEL','Cerevel Therapeutics','Healthcare','US','EXTENDED'),
    ('NRIX','Nurix Therapeutics','Healthcare','US','EXTENDED'),
    ('REATA','Reata Pharma','Healthcare','US','EXTENDED'),
    ('PTCT','PTC Therapeutics','Healthcare','US','EXTENDED'),
    ('AKBA','Akebia Therapeutics','Healthcare','US','EXTENDED'),
    ('AVXL','Anavex Life Sciences','Healthcare','US','EXTENDED'),
    ('BCRX','BioCryst Pharma','Healthcare','US','EXTENDED'),
    ('CORT','Corcept Therapeutics','Healthcare','US','EXTENDED'),
    ('TVTX','Travere Therapeutics','Healthcare','US','EXTENDED'),
    ('PRAX','Praxis Precision Medicine','Healthcare','US','EXTENDED'),
    ('IRON','Disc Medicine','Healthcare','US','EXTENDED'),
    ('XENE','Xenon Pharma','Healthcare','US','EXTENDED'),
    ('URGN','UroGen Pharma','Healthcare','US','EXTENDED'),
    ('DVAX','Dynavax','Healthcare','US','EXTENDED'),
    ('NVAX','Novavax','Healthcare','US','EXTENDED'),
    ('SIGA','SIGA Technologies','Healthcare','US','EXTENDED'),
    ('AGEN','Agenus','Healthcare','US','EXTENDED'),
    ('ADXS','Advaxis','Healthcare','US','EXTENDED'),
    ('IMMU','Immunomedics','Healthcare','US','EXTENDED'),
    ('TGTX','TG Therapeutics','Healthcare','US','EXTENDED'),
    ('MORF','Morphic Therapeutic','Healthcare','US','EXTENDED'),
    ('PRLD','Prelude Therapeutics','Healthcare','US','EXTENDED'),
    ('ACRO','Acrotech Biopharma','Healthcare','US','EXTENDED'),
    ('AKRO','Akero Therapeutics','Healthcare','US','EXTENDED'),
    ('ELVN','Eleven Therapeutics','Healthcare','US','EXTENDED'),
    ('CGEM','Cullinan Oncology','Healthcare','US','EXTENDED'),
    ('IKNA','Ikena Oncology','Healthcare','US','EXTENDED'),
    ('HOOK','Hookipa Pharma','Healthcare','US','EXTENDED'),
    ('ONCO','Onconova Therapeutics','Healthcare','US','EXTENDED'),
    ('ATXS','Astex Therapeutics','Healthcare','US','EXTENDED'),
    ('VBIV','VBI Vaccines','Healthcare','US','EXTENDED'),
    ('OCUL','Ocugen','Healthcare','US','EXTENDED'),
    ('EYEG','EyeGate Pharma','Healthcare','US','EXTENDED'),
    ('OPRT','Oportun Financial','Financials','US','EXTENDED'),
    ('ATLC','Atlanticus Holdings','Financials','US','EXTENDED'),
    ('EZCORP','EZCORP','Financials','US','EXTENDED'),
    ('EZPW','EZCORP','Financials','US','EXTENDED'),
    ('FCNCA','First Citizens','Financials','US','EXTENDED'),
    ('WTFC','Wintrust Financial','Financials','US','EXTENDED'),
    ('PACW','PacWest Bancorp','Financials','US','EXTENDED'),
    ('WAL','Western Alliance','Financials','US','EXTENDED'),
    ('FHB','First Hawaiian','Financials','US','EXTENDED'),
    ('BANR','Banner Financial','Financials','US','EXTENDED'),
    ('CVBF','CVB Financial','Financials','US','EXTENDED'),
    ('TBBK','The Bancorp','Financials','US','EXTENDED'),
    ('PRFT','Perficient','Tech','US','EXTENDED'),
    ('NSIT','Insight Direct','Tech','US','EXTENDED'),
    ('CDW','CDW Corp','Tech','US','EXTENDED'),
    ('PCCO','PC Connection','Tech','US','EXTENDED'),
    ('SYX','Systemax','Tech','US','EXTENDED'),
    ('PLUS','ePlus Inc','Tech','US','EXTENDED'),
    ('SCSC','ScanSource','Tech','US','EXTENDED'),
    ('AVT','Avnet','Tech','US','EXTENDED'),
    ('ARW','Arrow Electronics','Tech','US','EXTENDED'),
    ('BDC','Belden','Tech','US','EXTENDED'),
    ('CABO','Cable One','Tech','US','EXTENDED'),
    ('WOW','Wide Open West','Tech','US','EXTENDED'),
    ('LBRDA','Liberty Broadband','Tech','US','EXTENDED'),
    ('CHTR','Charter Communications','Tech','US','EXTENDED'),
    ('CMCSA','Comcast','Tech','US','EXTENDED'),
    ('TMUS','T-Mobile','Tech','US','EXTENDED'),
    ('VZ','Verizon','Tech','US','EXTENDED'),
    ('T','AT&T','Tech','US','EXTENDED'),
    ('LUMN','Lumen Technologies','Tech','US','EXTENDED'),
    ('CNSL','Consolidated Comms','Tech','US','EXTENDED'),
    ('SHEN','Shenandoah Telecom','Tech','US','EXTENDED'),
    ('GSAT','Globalstar','Tech','US','EXTENDED'),
    ('VSAT','Viasat','Tech','US','EXTENDED'),
    ('MAXN','Maxeon Solar','Energy','US','EXTENDED'),
    ('ARRY','Array Technologies','Energy','US','EXTENDED'),
    ('SHLS','Shoals Technologies','Energy','US','EXTENDED'),
    ('SEDG','SolarEdge','Energy','US','EXTENDED'),
    ('RUN','Sunrun','Energy','US','EXTENDED'),
    ('NOVA','Sunnova Energy','Energy','US','EXTENDED'),
    ('SPWR','SunPower','Energy','US','EXTENDED'),
    ('CSIQ','Canadian Solar','Energy','US','EXTENDED'),
    ('JKS','JinkoSolar','Energy','US','EXTENDED'),
    ('DQ','Daqo New Energy','Energy','US','EXTENDED'),
    ('GEN','Green Energy Capital','Energy','US','EXTENDED'),
    ('AMRC','Ameresco','Energy','US','EXTENDED'),
    ('PEGI','Pattern Energy','Energy','US','EXTENDED'),
    ('AES','AES Corp','Energy','US','EXTENDED'),
    ('BEP','Brookfield Renewable','Energy','US','EXTENDED'),
    ('CWEN','Clearway Energy','Energy','US','EXTENDED'),
    ('NEP','NextEra Energy Partners','Energy','US','EXTENDED'),
    ('HASI','Hannon Armstrong','Energy','US','EXTENDED'),
    ('GPRE','Green Plains','Energy','US','EXTENDED'),
    ('REX','REX Energy','Energy','US','EXTENDED'),
    ('PTEN','Patterson-UTI','Energy','US','EXTENDED'),
    ('NBR','Nabors Industries','Energy','US','EXTENDED'),
    ('HP','Helmerich Payne','Energy','US','EXTENDED'),
    ('PES','Pioneer Energy','Energy','US','EXTENDED'),
    ('WHD','Cactus Inc','Energy','US','EXTENDED'),
    ('RES','RPC Inc','Energy','US','EXTENDED'),
    ('NINE','Nine Energy','Energy','US','EXTENDED'),
    ('KLXE','KLX Energy','Energy','US','EXTENDED'),
    ('OII','Oceaneering','Energy','US','EXTENDED'),
    ('TDW','Tidewater','Energy','US','EXTENDED'),
    ('BORR','Borr Drilling','Energy','US','EXTENDED'),
    ('VAL','Valaris','Energy','US','EXTENDED'),
    ('RIG','Transocean','Energy','US','EXTENDED'),
    ('DO','Diamond Offshore','Energy','US','EXTENDED'),
    ('NE','Noble Corp','Energy','US','EXTENDED'),
    ('PAAS','Pan American Silver','Materials','US','EXTENDED'),
    ('FSM','Fortuna Silver','Materials','US','EXTENDED'),
    ('MAG','MAG Silver','Materials','US','EXTENDED'),
    ('SVM','Silvercorp Metals','Materials','US','EXTENDED'),
    ('SILV','SilverCrest Metals','Materials','US','EXTENDED'),
    ('GATO','Gatos Silver','Materials','US','EXTENDED'),
    ('USAS','Americas Gold Silver','Materials','US','EXTENDED'),
    ('AUY','Yamana Gold','Materials','US','EXTENDED'),
    ('BTG','B2Gold','Materials','US','EXTENDED'),
    ('DRD','DRDGold','Materials','US','EXTENDED'),
    ('HMY','Harmony Gold','Materials','US','EXTENDED'),
    ('SAND','Sandstorm Gold','Materials','US','EXTENDED'),
    ('MMX','Maverix Metals','Materials','US','EXTENDED'),
    ('OR','Osisko Gold','Materials','US','EXTENDED'),
    ('TFPM','Triple Flag Precious','Materials','US','EXTENDED'),
    ('USAU','US Gold Corp','Materials','US','EXTENDED'),
    ('GORO','Gold Resource','Materials','US','EXTENDED'),
    ('MUX','McEwen Mining','Materials','US','EXTENDED'),
    ('GPL','Great Panther','Materials','US','EXTENDED'),
    ('BCMN','BacTech Environmental','Materials','US','EXTENDED'),
    ('NXE','NexGen Energy','Energy','US','EXTENDED'),
    ('DNN','Denison Mines','Energy','US','EXTENDED'),
    ('URG','Ur-Energy','Energy','US','EXTENDED'),
    ('UEC','Uranium Energy','Energy','US','EXTENDED'),
    ('UUUU','Energy Fuels','Energy','US','EXTENDED'),
    ('BQSF','Basecamp Research','Energy','US','EXTENDED'),
    ('LTBR','Lightbridge Corp','Energy','US','EXTENDED'),
    ('LEU','Centrus Energy','Energy','US','EXTENDED'),
    ('URNM','Sprott Uranium Miners','Energy','US','EXTENDED'),
    ('NLR','VanEck Uranium Nuclear','Energy','US','EXTENDED'),
    ('ACNB','ACNB Corp','Financials','US','EXTENDED'),
    ('AROW','Arrow Financial','Financials','US','EXTENDED'),
    ('BFIN','BankFinancial','Financials','US','EXTENDED'),
    ('BSVN','Bank7 Corp','Financials','US','EXTENDED'),
    ('BYFC','Broadway Financial','Financials','US','EXTENDED'),
    ('CBNK','Capital Bancorp','Financials','US','EXTENDED'),
    ('CCBG','Capital City Bank','Financials','US','EXTENDED'),
    ('CFFN','Capitol Federal','Financials','US','EXTENDED'),
    ('CLBK','Community Bank System','Financials','US','EXTENDED'),
    ('CZWI','Citizens Community','Financials','US','EXTENDED'),
    ('ESSA','ESSA Bancorp','Financials','US','EXTENDED'),
    ('FBIZ','First Business','Financials','US','EXTENDED'),
    ('FBNC','First Bancorp','Financials','US','EXTENDED'),
    ('FCCO','First Community','Financials','US','EXTENDED'),
    ('FFBC','First Financial Bancorp','Financials','US','EXTENDED'),
    ('FFWM','First Financial Northwest','Financials','US','EXTENDED'),
    ('FISI','Financial Institutions','Financials','US','EXTENDED'),
    ('FMBH','First Mid Bancshares','Financials','US','EXTENDED'),
    ('FNWB','First Northwest Bancorp','Financials','US','EXTENDED'),
    ('GABC','German American Bancorp','Financials','US','EXTENDED'),
    ('GBCI','Glacier Bancorp','Financials','US','EXTENDED'),
    ('HBCP','Home Bancorp','Financials','US','EXTENDED'),
    ('HIFS','Hingham Institution','Financials','US','EXTENDED'),
    ('HTBI','HomeTrust Bancshares','Financials','US','EXTENDED'),
    ('HWBK','Hawthorn Bancorp','Financials','US','EXTENDED'),
    ('IBTX','Independent Bank Group','Financials','US','EXTENDED'),
    ('INBK','Interstate Bankshares','Financials','US','EXTENDED'),
    ('KRNY','Kearny Financial','Financials','US','EXTENDED'),
    ('LKFN','Lakeland Financial','Financials','US','EXTENDED'),
    ('MBWM','Mercantile Bank','Financials','US','EXTENDED'),
    ('MCBC','Mackinac Savings','Financials','US','EXTENDED'),
    ('MGYR','Magyar Bancorp','Financials','US','EXTENDED'),
    ('MNSB','MainStreet Bankshares','Financials','US','EXTENDED'),
    ('MVBF','MVB Financial','Financials','US','EXTENDED'),
    ('MYFW','First Western Financial','Financials','US','EXTENDED'),
    ('NBN','Northeast Bank','Financials','US','EXTENDED'),
    ('NBTB','NBT Bancorp','Financials','US','EXTENDED'),
    ('NCBS','Nicolet Bankshares','Financials','US','EXTENDED'),
    ('NFBK','Northfield Bancorp','Financials','US','EXTENDED'),
    ('NKSH','National Bankshares','Financials','US','EXTENDED'),
    ('NMIH','NMI Holdings','Financials','US','EXTENDED'),
    ('NRIM','Northrim BanCorp','Financials','US','EXTENDED'),
    ('OCFC','OceanFirst Financial','Financials','US','EXTENDED'),
    ('OFG','OFG Bancorp','Financials','US','EXTENDED'),
    ('OFLX','Omega Flex','Industrials','US','EXTENDED'),
    ('OPHC','OptimumBank','Financials','US','EXTENDED'),
    ('ORRF','Orrstown Financial','Financials','US','EXTENDED'),
    ('OVBC','Ohio Valley Financial','Financials','US','EXTENDED'),
    ('PBCT','Peoples Bancorp CT','Financials','US','EXTENDED'),
    ('PBFS','Pioneer Bankshares','Financials','US','EXTENDED'),
    ('PBHC','Pathfinder Bancorp','Financials','US','EXTENDED'),
    ('PCSB','PCSB Financial','Financials','US','EXTENDED'),
    ('PDFS','PDF Solutions','Tech','US','EXTENDED'),
    ('PFBC','Preferred Bank','Financials','US','EXTENDED'),
    ('PKBK','Parke Bancorp','Financials','US','EXTENDED'),
    ('PLBC','Plumas Bank','Financials','US','EXTENDED'),
    ('PMFS','Pamrapo Bancorp','Financials','US','EXTENDED'),
    ('PNFP','Pinnacle Financial','Financials','US','EXTENDED'),
    ('PPBI','Pacific Premier','Financials','US','EXTENDED'),
    ('PWOD','Penns Woods Bancorp','Financials','US','EXTENDED'),
    ('RNST','Renasant Corp','Financials','US','EXTENDED'),
    ('SASR','Sandy Spring Bancorp','Financials','US','EXTENDED'),
    ('SBCF','Seacoast Banking','Financials','US','EXTENDED'),
    ('SBSI','Southside Bancshares','Financials','US','EXTENDED'),
    ('SCZC','Southern California','Financials','US','EXTENDED'),
    ('SEIC','SEI Investments','Financials','US','EXTENDED'),
    ('SMBC','Southern Missouri','Financials','US','EXTENDED'),
    ('SMBK','SmartFinancial Bancorp','Financials','US','EXTENDED'),
    ('SRCE','1st Source Corp','Financials','US','EXTENDED'),
    ('STBA','S&T Bancorp','Financials','US','EXTENDED'),
    ('STXB','Spirit of Texas','Financials','US','EXTENDED'),
    ('SVNX','Seven Hills Financial','Financials','US','EXTENDED'),
    ('TCBX','Third Century Bancorp','Financials','US','EXTENDED'),
    ('TCFC','The Community Financial','Financials','US','EXTENDED'),
    ('TRMK','Trustmark Corp','Financials','US','EXTENDED'),
    ('TRST','TrustCo Bancorp','Financials','US','EXTENDED'),
    ('TZOO','Travelzoo','Consumer','US','EXTENDED'),
    ('UBSI','United Bankshares','Financials','US','EXTENDED'),
    ('UFCS','United Fire Group','Financials','US','EXTENDED'),
    ('UNTY','Unity Bancorp','Financials','US','EXTENDED'),
    ('UVSP','Univest Financial','Financials','US','EXTENDED'),
    ('VBTX','Veritex Holdings','Financials','US','EXTENDED'),
    ('VCNX','Vaccinex','Healthcare','US','EXTENDED'),
    ('VFIN','Valley Financial','Financials','US','EXTENDED'),
    ('VLYPP','Valley National','Financials','US','EXTENDED'),
    ('VSEC','VSE Corp','Industrials','US','EXTENDED'),
    ('WABC','Westamerica Bancorp','Financials','US','EXTENDED'),
    ('WASH','Washington Trust','Financials','US','EXTENDED'),
    ('WBKC','Wolverine Bancorp','Financials','US','EXTENDED'),
    ('WFSL','Washington Federal','Financials','US','EXTENDED'),
    ('WNEB','Western New England','Financials','US','EXTENDED'),
    ('WSBC','WesBanco','Financials','US','EXTENDED'),
    ('WTBA','West Bancorporation','Financials','US','EXTENDED'),
    ('ZION','Zions Bancorporation','Financials','US','EXTENDED'),
    # ── US INDUSTRIALS SMALL CAP ───────────────────────────
    ('AAON','AAON Inc','Industrials','US','EXTENDED'),
    ('ACCO','ACCO Brands','Industrials','US','EXTENDED'),
    ('AEIS','Advanced Energy Ind','Industrials','US','EXTENDED'),
    ('AGCO','AGCO Corp','Industrials','US','EXTENDED'),
    ('AIRC','Apartment Income REIT','RealEstate','US','EXTENDED'),
    ('AJRD','Aerojet Rocketdyne','Industrials','US','EXTENDED'),
    ('ALGT','Allegiant Travel','Industrials','US','EXTENDED'),
    ('ALIT','Alight Inc','Tech','US','EXTENDED'),
    ('ALK','Alaska Air','Industrials','US','EXTENDED'),
    ('AMWD','American Woodmark','Industrials','US','EXTENDED'),
    ('APOG','Apogee Enterprises','Industrials','US','EXTENDED'),
    ('ARCB','ArcBest Corp','Industrials','US','EXTENDED'),
    ('AROC','Archrock','Energy','US','EXTENDED'),
    ('ATRO','Astronics','Industrials','US','EXTENDED'),
    ('AVAV','AeroVironment','Industrials','US','EXTENDED'),
    ('AWI','Armstrong World','Industrials','US','EXTENDED'),
    ('BBWI','Bath Body Works','Consumer','US','EXTENDED'),
    ('BCC','Boise Cascade','Materials','US','EXTENDED'),
    ('BCPC','Balchem Corp','Materials','US','EXTENDED'),
    ('BFAM','Bright Horizons','Consumer','US','EXTENDED'),
    ('BGS','B&G Foods','Consumer','US','EXTENDED'),
    ('BJRI','BJ Restaurants','Consumer','US','EXTENDED'),
    ('BKE','Buckle Inc','Consumer','US','EXTENDED'),
    ('BKNG','Booking Holdings','Consumer','US','EXTENDED'),
    ('BMI','Badger Meter','Industrials','US','EXTENDED'),
    ('BOOT','Boot Barn','Consumer','US','EXTENDED'),
    ('BRC','Brady Corp','Industrials','US','EXTENDED'),
    ('BRX','Brixmor Property','RealEstate','US','EXTENDED'),
    ('BSIG','BrightSphere Investment','Financials','US','EXTENDED'),
    ('BWA','BorgWarner','Industrials','US','EXTENDED'),
    ('CADE','Cadence Bank','Financials','US','EXTENDED'),
    ('CAKE','Cheesecake Factory','Consumer','US','EXTENDED'),
    ('CALM','Cal-Maine Foods','Consumer','US','EXTENDED'),
    ('CAMT','Camtek Ltd','Tech','US','EXTENDED'),
    ('CBRL','Cracker Barrel','Consumer','US','EXTENDED'),
    ('CBT','Cabot Corp','Materials','US','EXTENDED'),
    ('CCOI','Cogent Communications','Tech','US','EXTENDED'),
    ('CENTA','Central Garden Pet','Consumer','US','EXTENDED'),
    ('CEVA','CEVA Inc','Tech','US','EXTENDED'),
    ('CFX','Colfax Corp','Industrials','US','EXTENDED'),
    ('CHEF','Chefs Warehouse','Consumer','US','EXTENDED'),
    ('CIR','CIRCOR International','Industrials','US','EXTENDED'),
    ('CIVI','Civitas Resources','Energy','US','EXTENDED'),
    ('CLB','Core Laboratories','Energy','US','EXTENDED'),
    ('CLFD','Clearfield Inc','Tech','US','EXTENDED'),
    ('CLW','Clearwater Paper','Materials','US','EXTENDED'),
    ('CMCO','Columbus McKinnon','Industrials','US','EXTENDED'),
    ('CNMD','CONMED Corp','Healthcare','US','EXTENDED'),
    ('CNO','CNO Financial','Financials','US','EXTENDED'),
    ('CNS','Cohen Steers','Financials','US','EXTENDED'),
    ('CNXN','PC Connection','Tech','US','EXTENDED'),
    ('COHU','Cohu Inc','Tech','US','EXTENDED'),
    ('CPSI','Computer Programs','Tech','US','EXTENDED'),
    ('CRK','Comstock Resources','Energy','US','EXTENDED'),
    ('CSWI','CSW Industrials','Industrials','US','EXTENDED'),
    ('CTBI','Community Bankers Trust','Financials','US','EXTENDED'),
    ('CTS','CTS Corp','Tech','US','EXTENDED'),
    ('CUZ','Cousins Properties','RealEstate','US','EXTENDED'),
    ('DAN','Dana Inc','Industrials','US','EXTENDED'),
    ('DGICA','Donegal Group','Financials','US','EXTENDED'),
    ('DLB','Dolby Laboratories','Tech','US','EXTENDED'),
    ('DORM','Dorman Products','Industrials','US','EXTENDED'),
    ('DRH','DiamondRock Hospitality','RealEstate','US','EXTENDED'),
    ('DY','Dycom Industries','Industrials','US','EXTENDED'),
    ('EAT','Brinker International','Consumer','US','EXTENDED'),
    ('EFC','Ellington Financial','Financials','US','EXTENDED'),
    ('EGP','EastGroup Properties','RealEstate','US','EXTENDED'),
    ('EGBN','Eagle Bancorp','Financials','US','EXTENDED'),
    ('EMBC','Embecta Corp','Healthcare','US','EXTENDED'),
    ('ENR','Energizer Holdings','Consumer','US','EXTENDED'),
    ('ENVA','Enova International','Financials','US','EXTENDED'),
    ('EPR','EPR Properties','RealEstate','US','EXTENDED'),
    ('EVI','EVI Industries','Industrials','US','EXTENDED'),
    ('EXTR','Extreme Networks','Tech','US','EXTENDED'),
    ('FCPT','Four Corners Property','RealEstate','US','EXTENDED'),
    ('FDUS','Fidus Investment','Financials','US','EXTENDED'),
    ('FELE','Franklin Electric','Industrials','US','EXTENDED'),
    ('FHI','Federated Hermes','Financials','US','EXTENDED'),
    ('FLO','Flowers Foods','Consumer','US','EXTENDED'),
    ('FLS','Flowserve','Industrials','US','EXTENDED'),
    ('FLXS','Flexsteel Industries','Consumer','US','EXTENDED'),
    ('FNB','FNB Corp','Financials','US','EXTENDED'),
    ('FOCS','Focus Financial','Financials','US','EXTENDED'),
    ('FORR','Forrester Research','Tech','US','EXTENDED'),
    ('FOXF','Fox Factory','Industrials','US','EXTENDED'),
    ('FR','First Industrial','RealEstate','US','EXTENDED'),
    ('FRME','First Merchants','Financials','US','EXTENDED'),
    ('FULT','Fulton Financial','Financials','US','EXTENDED'),
    ('GFF','Griffon Corp','Industrials','US','EXTENDED'),
    ('GGAL','Grupo Financiero Galicia','Financials','US','EXTENDED'),
    ('GHC','Graham Holdings','Consumer','US','EXTENDED'),
    ('GKOS','Glaukos Corp','Healthcare','US','EXTENDED'),
    ('GL','Globe Life','Financials','US','EXTENDED'),
    ('GLDD','Great Lakes Dredge','Industrials','US','EXTENDED'),
    ('GMED','Globus Medical','Healthcare','US','EXTENDED'),
    ('GOOD','Gladstone Commercial','RealEstate','US','EXTENDED'),
    ('GPC','Genuine Parts','Consumer','US','EXTENDED'),
    ('GPMT','Granite Point Mortgage','Financials','US','EXTENDED'),
    ('GTX','Garrett Motion','Industrials','US','EXTENDED'),
    ('GTYH','GTY Technology','Tech','US','EXTENDED'),
    ('GVA','Granite Construction','Industrials','US','EXTENDED'),
    ('HAE','Haemonetics','Healthcare','US','EXTENDED'),
    ('HCC','Warrior Met Coal','Materials','US','EXTENDED'),
    ('HCCI','Heritage Crystal Clean','Industrials','US','EXTENDED'),
    ('HCI','HCI Group','Financials','US','EXTENDED'),
    ('HCSG','Healthcare Services','Healthcare','US','EXTENDED'),
    ('HIW','Highwoods Properties','RealEstate','US','EXTENDED'),
    ('HLX','Helix Energy','Energy','US','EXTENDED'),
    ('HMST','HomeStreet','Financials','US','EXTENDED'),
    ('HOLI','Hollysys Automation','Tech','US','EXTENDED'),
    ('HONE','HarborOne Bancorp','Financials','US','EXTENDED'),
    ('HOTH','Hoth Therapeutics','Healthcare','US','EXTENDED'),
    ('HPK','HighPeak Energy','Energy','US','EXTENDED'),
    ('HRTH','Harte-Hanks','Consumer','US','EXTENDED'),
    ('HSII','Heidrick Struggles','Industrials','US','EXTENDED'),
    ('HTLD','Heartland Express','Industrials','US','EXTENDED'),
    ('HUBG','Hub Group','Industrials','US','EXTENDED'),
    ('HVT','Haverty Furniture','Consumer','US','EXTENDED'),
    ('HWKN','Hawkins Inc','Materials','US','EXTENDED'),
    ('IAA','IAA Inc','Industrials','US','EXTENDED'),
    ('IART','Integra LifeSciences','Healthcare','US','EXTENDED'),
    ('IBCP','Independent Bank Corp','Financials','US','EXTENDED'),
    ('ICAD','iCAD Inc','Healthcare','US','EXTENDED'),
    ('ICFI','ICF International','Industrials','US','EXTENDED'),
    ('ICHR','Ichor Holdings','Tech','US','EXTENDED'),
    ('IDYS','Indus Holding','Consumer','US','EXTENDED'),
    ('IEC','IEC Electronics','Tech','US','EXTENDED'),
    ('IIIN','Insteel Industries','Materials','US','EXTENDED'),
    ('INFU','InfuSystem Holdings','Healthcare','US','EXTENDED'),
    ('INGN','Inogen Inc','Healthcare','US','EXTENDED'),
    ('INMD','InMode Ltd','Healthcare','US','EXTENDED'),
    ('INSW','International Seaways','Energy','US','EXTENDED'),
    ('IOSP','Innospec Inc','Materials','US','EXTENDED'),
    ('IPAR','Inter Parfums','Consumer','US','EXTENDED'),
    ('IPGP','IPG Photonics','Tech','US','EXTENDED'),
    ('IRBT','iRobot Corp','Tech','US','EXTENDED'),
    ('IRET','Investors Real Estate','RealEstate','US','EXTENDED'),
    ('IRT','Independence Realty','RealEstate','US','EXTENDED'),
    ('ITIC','Investors Title','Financials','US','EXTENDED'),
    ('JACK','Jack in the Box','Consumer','US','EXTENDED'),
    ('JBGS','JBG SMITH Properties','RealEstate','US','EXTENDED'),
    ('JBLU','JetBlue Airways','Industrials','US','EXTENDED'),
    ('JOE','St Joe Company','RealEstate','US','EXTENDED'),
    ('JOBY','Joby Aviation','Industrials','US','EXTENDED'),
    ('JOUT','Johnson Outdoors','Consumer','US','EXTENDED'),
    ('KAI','Kadant Inc','Industrials','US','EXTENDED'),
    ('KALU','Kaiser Aluminum','Materials','US','EXTENDED'),
    ('KAMN','Kaman Corp','Industrials','US','EXTENDED'),
    ('KAR','OPENLANE Inc','Consumer','US','EXTENDED'),
    ('KFRC','Kforce Inc','Industrials','US','EXTENDED'),
    ('KIDS','OrthoPediatrics','Healthcare','US','EXTENDED'),
    ('KIRK','Kirklands','Consumer','US','EXTENDED'),
    ('KMT','Kennametal','Industrials','US','EXTENDED'),
    ('KN','Knowles Corp','Tech','US','EXTENDED'),
    ('KNSA','Kiniksa Pharma','Healthcare','US','EXTENDED'),
    ('KOP','Koppers Holdings','Materials','US','EXTENDED'),
    ('KPLT','Katapult Holdings','Financials','US','EXTENDED'),
    ('KROS','Keros Therapeutics','Healthcare','US','EXTENDED'),
    ('KRT','Karat Packaging','Materials','US','EXTENDED'),
    ('KRYS','Krystal Biotech','Healthcare','US','EXTENDED'),
    ('KSS','Kohls Corp','Consumer','US','EXTENDED'),
    ('KTB','Kontoor Brands','Consumer','US','EXTENDED'),
    ('LBRT','Liberty Oilfield','Energy','US','EXTENDED'),
    ('LCI','Lannett Company','Healthcare','US','EXTENDED'),
    ('LCII','LCI Industries','Consumer','US','EXTENDED'),
    ('LGND','Ligand Pharma','Healthcare','US','EXTENDED'),
    ('LGF-A','Lions Gate Entertainment','Consumer','US','EXTENDED'),
    ('LHCG','LHC Group','Healthcare','US','EXTENDED'),
    ('LMB','Limbach Holdings','Industrials','US','EXTENDED'),
    ('LNTH','Lantheus Holdings','Healthcare','US','EXTENDED'),
    ('LOVE','Lovesac Company','Consumer','US','EXTENDED'),
    ('LPX','Louisiana-Pacific','Materials','US','EXTENDED'),
    ('LQDT','Liquidity Services','Industrials','US','EXTENDED'),
    ('LSTR','Landstar System','Industrials','US','EXTENDED'),
    ('LTC','LTC Properties','RealEstate','US','EXTENDED'),
    ('LWAY','Lifeway Foods','Consumer','US','EXTENDED'),
    ('LXP','LXP Industrial','RealEstate','US','EXTENDED'),
    ('LZB','La-Z-Boy','Consumer','US','EXTENDED'),
    ('MASI','Masimo Corp','Healthcare','US','EXTENDED'),
    ('MATW','Matthews International','Industrials','US','EXTENDED'),
    ('MAXR','Maxar Technologies','Tech','US','EXTENDED'),
    ('MBUU','Malibu Boats','Consumer','US','EXTENDED'),
    ('MC','Moelis Company','Financials','US','EXTENDED'),
    ('MCRI','Monarch Casino','Consumer','US','EXTENDED'),
    ('MED','Medifast','Consumer','US','EXTENDED'),
    ('MEOH','Methanex','Materials','US','EXTENDED'),
    ('MGEE','MGE Energy','Utilities','US','EXTENDED'),
    ('MGY','Magnolia Oil Gas','Energy','US','EXTENDED'),
    ('MLAB','Mesa Labs','Tech','US','EXTENDED'),
    ('MLKN','MillerKnoll','Consumer','US','EXTENDED'),
    ('MMAC','MMA Capital','Financials','US','EXTENDED'),
    ('MMSI','Merit Medical Systems','Healthcare','US','EXTENDED'),
    ('MMS','MAXIMUS Inc','Industrials','US','EXTENDED'),
    ('MNRO','Monro Muffler','Consumer','US','EXTENDED'),
    ('MOG-A','Moog Inc','Industrials','US','EXTENDED'),
    ('MOWI','Mowi ASA','Consumer','US','EXTENDED'),
    ('MPW','Medical Properties','RealEstate','US','EXTENDED'),
    ('MRGN','Margin Media','Tech','US','EXTENDED'),
    ('MRX','Marex Group','Financials','US','EXTENDED'),
    ('MSA','MSA Safety','Industrials','US','EXTENDED'),
    ('MSGE','Madison Square Garden','Consumer','US','EXTENDED'),
    ('MTH','Meritage Homes','Industrials','US','EXTENDED'),
    ('MTRN','Materion Corp','Materials','US','EXTENDED'),
    ('MWA','Mueller Water','Industrials','US','EXTENDED'),
    ('MXL','MaxLinear','Tech','US','EXTENDED'),
    ('MYPS','PLAYSTUDIOS','Tech','US','EXTENDED'),
    ('NAT','Nordic American Tankers','Energy','US','EXTENDED'),
    ('NDAQ','Nasdaq Inc','Financials','US','EXTENDED'),
    ('NDSN','Nordson Corp','Industrials','US','EXTENDED'),
    ('NEO','NeoGenomics','Healthcare','US','EXTENDED'),
    ('NEOG','Neogen Corp','Healthcare','US','EXTENDED'),
    ('NGS','Natural Gas Services','Energy','US','EXTENDED'),
    ('NHI','National Health Investors','RealEstate','US','EXTENDED'),
    ('NJR','New Jersey Resources','Utilities','US','EXTENDED'),
    ('NNN','NNN REIT','RealEstate','US','EXTENDED'),
    ('NRDS','NerdWallet','Financials','US','EXTENDED'),
    ('NSP','Insperity','Industrials','US','EXTENDED'),
    ('NTUS','Natus Medical','Healthcare','US','EXTENDED'),
    ('NURO','NeuroMetrix','Healthcare','US','EXTENDED'),
    ('NUS','Nu Skin Enterprises','Consumer','US','EXTENDED'),
    ('NVT','nVent Electric','Industrials','US','EXTENDED'),
    ('NWLI','National Western Life','Financials','US','EXTENDED'),
    ('NX','Quanex Building','Industrials','US','EXTENDED'),
    ('NYT','New York Times','Consumer','US','EXTENDED'),
    ('NYTG','NY Times Group','Consumer','US','EXTENDED'),
    ('OAS','Oasis Petroleum','Energy','US','EXTENDED'),
    ('OB','Outbrain','Tech','US','EXTENDED'),
    ('OGS','ONE Gas','Utilities','US','EXTENDED'),
    ('OMER','Omeros Corp','Healthcare','US','EXTENDED'),
    ('OMF','OneMain Financial','Financials','US','EXTENDED'),
    ('OMFL','Invesco Russell 1000','Financials','US','EXTENDED'),
    ('ONB','Old National Bancorp','Financials','US','EXTENDED'),
    ('OPCH','Option Care Health','Healthcare','US','EXTENDED'),
    ('OPK','OPKO Health','Healthcare','US','EXTENDED'),
    ('ORION','Orion Energy Systems','Energy','US','EXTENDED'),
    ('ORLY','OReilly Automotive','Consumer','US','EXTENDED'),
    ('OSK','Oshkosh Corp','Industrials','US','EXTENDED'),
    ('OSW','OneSpaWorld','Consumer','US','EXTENDED'),
    ('OTC','Open Text Corp','Tech','US','EXTENDED'),
    ('OTEX','Open Text','Tech','US','EXTENDED'),
    ('OXM','Oxford Industries','Consumer','US','EXTENDED'),
    ('PARR','Par Pacific','Energy','US','EXTENDED'),
    ('PATK','Patrick Industries','Industrials','US','EXTENDED'),
    ('PAYX','Paychex','Tech','US','EXTENDED'),
    ('PBF','PBF Energy','Energy','US','EXTENDED'),
    ('PBPB','Potbelly Corp','Consumer','US','EXTENDED'),
    ('PCH','PotlatchDeltic','Materials','US','EXTENDED'),
    ('PDM','Piedmont Office Realty','RealEstate','US','EXTENDED'),
    ('PEBO','Peoples Bancorp','Financials','US','EXTENDED'),
    ('PEB','Pebblebrook Hotel','RealEstate','US','EXTENDED'),
    ('PERI','Perion Network','Tech','US','EXTENDED'),
    ('PFGC','Performance Food Group','Consumer','US','EXTENDED'),
    ('PHR','Phreesia','Tech','US','EXTENDED'),
    ('PINC','Premier Inc','Healthcare','US','EXTENDED'),
    ('PKE','Park Electrochemical','Materials','US','EXTENDED'),
    ('PKOH','Park Ohio Holdings','Industrials','US','EXTENDED'),
    ('PLAB','Photronics Inc','Tech','US','EXTENDED'),
    ('PLAY','Dave Busters','Consumer','US','EXTENDED'),
    ('PLT','Plantronics','Tech','US','EXTENDED'),
    ('PLXS','Plexus Corp','Tech','US','EXTENDED'),
    ('PMVP','PMV Pharma','Healthcare','US','EXTENDED'),
    ('PNTG','Pennant Group','Healthcare','US','EXTENDED'),
    ('POWI','Power Integrations','Tech','US','EXTENDED'),
    ('PRDO','Perdoceo Education','Consumer','US','EXTENDED'),
    ('PRG','PROG Holdings','Financials','US','EXTENDED'),
    ('PRGS','Progress Software','Tech','US','EXTENDED'),
    ('PRM','Perimeter Solutions','Materials','US','EXTENDED'),
    ('PRO','PROS Holdings','Tech','US','EXTENDED'),
    ('PROV','Provident Financial','Financials','US','EXTENDED'),
    ('PRPB','Prestige Consumer Healthcare','Healthcare','US','EXTENDED'),
    ('PRSC','The Providence Service','Industrials','US','EXTENDED'),
    ('PSMT','PriceSmart','Consumer','US','EXTENDED'),
    ('PUMP','ProPetro Holding','Energy','US','EXTENDED'),
    ('PVAC','Penn Virginia','Energy','US','EXTENDED'),
    ('PWSC','PowerSchool Holdings','Tech','US','EXTENDED'),
    ('PZN','Pzena Investment','Financials','US','EXTENDED'),
    ('QNST','QuinStreet','Tech','US','EXTENDED'),
    ('QUAD','Quad Graphics','Industrials','US','EXTENDED'),
    ('QDEL','QuidelOrtho','Healthcare','US','EXTENDED'),
    ('QFIN','360 DigiTech','Financials','US','EXTENDED'),
    ('QHC','Quorum Health','Healthcare','US','EXTENDED'),
    ('QLYS','Qualys Inc','Tech','US','EXTENDED'),
    ('RAMP','LiveRamp Holdings','Tech','US','EXTENDED'),
    ('RBC','RBC Bearings','Industrials','US','EXTENDED'),
    ('RBCAA','Republic Bancorp','Financials','US','EXTENDED'),
    ('RCM','R1 RCM','Healthcare','US','EXTENDED'),
    ('RCUS','Arcus Biosciences','Healthcare','US','EXTENDED'),
    ('RDN','Radian Group','Financials','US','EXTENDED'),
    ('RDVT','Red Violet','Tech','US','EXTENDED'),
    ('REZI','Resideo Technologies','Tech','US','EXTENDED'),
    ('RGP','Resources Connection','Industrials','US','EXTENDED'),
    ('RGS','Regis Corp','Consumer','US','EXTENDED'),
    ('RICK','RCI Hospitality','Consumer','US','EXTENDED'),
    ('RLAY','Relay Therapeutics','Healthcare','US','EXTENDED'),
    ('RMNI','Rimini Street','Tech','US','EXTENDED'),
    ('RNG','RingCentral','Tech','US','EXTENDED'),
    ('RNGR','Ranger Energy Services','Energy','US','EXTENDED'),
    ('ROAD','Construction Partners','Industrials','US','EXTENDED'),
    ('ROCK','Gibraltar Industries','Industrials','US','EXTENDED'),
    ('ROIC','Retail Opportunity','RealEstate','US','EXTENDED'),
    ('ROLL','RBC Bearings','Industrials','US','EXTENDED'),
    ('RPRX','Royalty Pharma','Healthcare','US','EXTENDED'),
    ('RRR','Red Rock Resorts','Consumer','US','EXTENDED'),
    ('RXO','RXO Inc','Industrials','US','EXTENDED'),
    ('RYAM','Rayonier Advanced','Materials','US','EXTENDED'),
    ('RYN','Rayonier Inc','RealEstate','US','EXTENDED'),
    ('SAFE','Safehold Inc','RealEstate','US','EXTENDED'),
    ('SAMA','Schultze Special Purpose','Financials','US','EXTENDED'),
    ('SAMG','Silvercrest Asset','Financials','US','EXTENDED'),
    ('SANM','Sanmina Corp','Tech','US','EXTENDED'),
    ('SBRA','Sabra Health Care','RealEstate','US','EXTENDED'),
    ('SCI','Service Corp International','Consumer','US','EXTENDED'),
    ('SDXC','SoundThinking','Tech','US','EXTENDED'),
    ('SEAS','SeaWorld Entertainment','Consumer','US','EXTENDED'),
    ('SELF','Global Self Storage','RealEstate','US','EXTENDED'),
    ('SEM','Select Medical','Healthcare','US','EXTENDED'),
    ('SENEA','Seneca Foods','Consumer','US','EXTENDED'),
    ('SFM','Sprouts Farmers Market','Consumer','US','EXTENDED'),
    ('SFNC','Simmons First National','Financials','US','EXTENDED'),
    ('SGH','SGH Inc','Tech','US','EXTENDED'),
    ('SGHT','Sight Sciences','Healthcare','US','EXTENDED'),
    ('SHO','Sunstone Hotel Investors','RealEstate','US','EXTENDED'),
    ('SHOO','Steve Madden','Consumer','US','EXTENDED'),
    ('SIG','Signet Jewelers','Consumer','US','EXTENDED'),
    ('SITC','SITE Centers','RealEstate','US','EXTENDED'),
    ('SKYW','SkyWest Inc','Industrials','US','EXTENDED'),
    ('SLCA','US Silica Holdings','Materials','US','EXTENDED'),
    ('SLP','Simulations Plus','Tech','US','EXTENDED'),
    ('SLVM','Sylvamo Corp','Materials','US','EXTENDED'),
    ('SM','SM Energy','Energy','US','EXTENDED'),
    ('SMPL','Simply Good Foods','Consumer','US','EXTENDED'),
    ('SNEX','StoneX Group','Financials','US','EXTENDED'),
    ('SNGX','Soligenix','Healthcare','US','EXTENDED'),
    ('SONO','Sonos Inc','Tech','US','EXTENDED'),
    ('SPB','Spectrum Brands','Consumer','US','EXTENDED'),
    ('SPTN','SpartanNash','Consumer','US','EXTENDED'),
    ('SRG','Seritage Growth','RealEstate','US','EXTENDED'),
    ('SSTK','Shutterstock','Tech','US','EXTENDED'),
    ('STAA','STAAR Surgical','Healthcare','US','EXTENDED'),
    ('STC','Stewart Information','Financials','US','EXTENDED'),
    ('STEP','StepStone Group','Financials','US','EXTENDED'),
    ('STGW','Stagwell Inc','Consumer','US','EXTENDED'),
    ('STKS','One Stop Systems','Tech','US','EXTENDED'),
    ('STRA','Strategic Education','Consumer','US','EXTENDED'),
    ('STRL','Sterling Infrastructure','Industrials','US','EXTENDED'),
    ('SUM','Summit Materials','Materials','US','EXTENDED'),
    ('SVC','Service Properties Trust','RealEstate','US','EXTENDED'),
    ('SVRA','Savara Inc','Healthcare','US','EXTENDED'),
    ('SWI','SolarWinds','Tech','US','EXTENDED'),
    ('SWKH','SWK Holdings','Financials','US','EXTENDED'),
    ('SWX','Southwest Gas','Utilities','US','EXTENDED'),
    ('SXC','SunCoke Energy','Materials','US','EXTENDED'),
    ('SXI','Standex International','Industrials','US','EXTENDED'),
    ('SYBT','Stock Yards Bancorp','Financials','US','EXTENDED'),
    ('SYKE','Sykes Enterprises','Tech','US','EXTENDED'),
    ('TALO','Talos Energy','Energy','US','EXTENDED'),
    ('TAST','Carrols Restaurant','Consumer','US','EXTENDED'),
    ('TBNK','Territorial Bancorp','Financials','US','EXTENDED'),
    ('TCMD','Tactile Systems','Healthcare','US','EXTENDED'),
    ('TDS','Telephone Data Systems','Tech','US','EXTENDED'),
    ('TDUP','ThredUp Inc','Consumer','US','EXTENDED'),
    ('TENB','Tenable Holdings','Tech','US','EXTENDED'),
    ('TFSL','TFS Financial','Financials','US','EXTENDED'),
    ('THC','Tenet Healthcare','Healthcare','US','EXTENDED'),
    ('THFF','First Financial Corp','Financials','US','EXTENDED'),
    ('TILE','Interface Inc','Industrials','US','EXTENDED'),
    ('TKR','Timken Co','Industrials','US','EXTENDED'),
    ('TLYS','Tillys Inc','Consumer','US','EXTENDED'),
    ('TMST','TimkenSteel','Materials','US','EXTENDED'),
    ('TNDM','Tandem Diabetes Care','Healthcare','US','EXTENDED'),
    ('TOWN','Towne Bank','Financials','US','EXTENDED'),
    ('TREK','Systemax','Tech','US','EXTENDED'),
    ('TRMD','TORM PLC','Energy','US','EXTENDED'),
    ('TRNC','Tronc Inc','Consumer','US','EXTENDED'),
    ('TROW','T Rowe Price','Financials','US','EXTENDED'),
    ('TRUE','TrueCar','Tech','US','EXTENDED'),
    ('TRVI','Trevi Therapeutics','Healthcare','US','EXTENDED'),
    ('TSC','TriState Capital','Financials','US','EXTENDED'),
    ('TSVT','2seventy bio','Healthcare','US','EXTENDED'),
    ('TTC','Toro Company','Industrials','US','EXTENDED'),
    ('TTGT','TechTarget','Tech','US','EXTENDED'),
    ('TTM','Tata Motors','Consumer','US','EXTENDED'),
    ('TTSH','Tile Shop Holdings','Consumer','US','EXTENDED'),
    ('TUEM','Tuesday Morning','Consumer','US','EXTENDED'),
    ('TWI','Titan International','Industrials','US','EXTENDED'),
    ('TWKS','Thoughtworks','Tech','US','EXTENDED'),
    ('TXG','10x Genomics','Healthcare','US','EXTENDED'),
    ('TXRH','Texas Roadhouse','Consumer','US','EXTENDED'),
    ('UFI','Unifi Inc','Materials','US','EXTENDED'),
    ('UFPT','UFP Technologies','Industrials','US','EXTENDED'),
    ('UIS','Unisys Corp','Tech','US','EXTENDED'),
    ('ULCC','Frontier Group','Industrials','US','EXTENDED'),
    ('UMBF','UMB Financial','Financials','US','EXTENDED'),
    ('UNF','UniFirst Corp','Industrials','US','EXTENDED'),
    ('UNVR','Univar Solutions','Materials','US','EXTENDED'),
    ('UPH','Upheaval Health','Healthcare','US','EXTENDED'),
    ('UPLD','Upland Software','Tech','US','EXTENDED'),
    ('USPH','US Physical Therapy','Healthcare','US','EXTENDED'),
    ('UTHR','United Therapeutics','Healthcare','US','EXTENDED'),
    ('VCYT','Veracyte','Healthcare','US','EXTENDED'),
    ('VECO','Veeco Instruments','Tech','US','EXTENDED'),
    ('VGR','Vector Group','Consumer','US','EXTENDED'),
    ('VHC','VirnetX Holding','Tech','US','EXTENDED'),
    ('VIRC','Virco Manufacturing','Consumer','US','EXTENDED'),
    ('VIRT','Virtu Financial','Financials','US','EXTENDED'),
    ('VLGEA','Village Super Market','Consumer','US','EXTENDED'),
    ('VMD','Viemed Healthcare','Healthcare','US','EXTENDED'),
    ('VNO','Vornado Realty','RealEstate','US','EXTENDED'),
    ('VNRX','VolitionRx','Healthcare','US','EXTENDED'),
    ('VRAY','ViewRay Inc','Healthcare','US','EXTENDED'),
    ('VRE','Veris Residential','RealEstate','US','EXTENDED'),
    ('VRTS','Virtus Investment','Financials','US','EXTENDED'),
    ('VSCO','Victorias Secret','Consumer','US','EXTENDED'),
    ('VSH','Vishay Intertechnology','Tech','US','EXTENDED'),
    ('VSPR','Vesper Healthcare','Healthcare','US','EXTENDED'),
    ('VSTA','Vasta Platform','Consumer','US','EXTENDED'),
    ('VTOL','Bristow Group','Industrials','US','EXTENDED'),
    ('VVOS','Vivos Therapeutics','Healthcare','US','EXTENDED'),
    ('VYGR','Voyager Therapeutics','Healthcare','US','EXTENDED'),
    ('WAFD','Washington Federal','Financials','US','EXTENDED'),
    ('WD','Walker Dunlop','Financials','US','EXTENDED'),
    ('WDFC','WD-40 Company','Consumer','US','EXTENDED'),
    ('WEN','Wendys Company','Consumer','US','EXTENDED'),
    ('WETF','WisdomTree Investments','Financials','US','EXTENDED'),
    ('WGO','Winnebago Industries','Consumer','US','EXTENDED'),
    ('WKC','World Kinect','Energy','US','EXTENDED'),
    ('WLY','John Wiley Sons','Consumer','US','EXTENDED'),
    ('WMG','Warner Music Group','Consumer','US','EXTENDED'),
    ('WNC','Wabash National','Industrials','US','EXTENDED'),
    ('WOLF','Wolfspeed','Tech','US','EXTENDED'),
    ('WOR','Worthington Industries','Materials','US','EXTENDED'),
    ('WRK','WestRock Company','Materials','US','EXTENDED'),
    ('WRLD','World Acceptance','Financials','US','EXTENDED'),
    ('WSC','WillScot Mobile Mini','Industrials','US','EXTENDED'),
    ('WSFS','WSFS Financial','Financials','US','EXTENDED'),
    ('WT','WisdomTree','Financials','US','EXTENDED'),
    ('WTM','White Mountains Insurance','Financials','US','EXTENDED'),
    ('WTRG','Essential Utilities','Utilities','US','EXTENDED'),
    ('WTS','Watts Water Technologies','Industrials','US','EXTENDED'),
    ('XNCR','Xencor','Healthcare','US','EXTENDED'),
    ('XPEL','XPEL Inc','Consumer','US','EXTENDED'),
    ('XPER','Xperi Inc','Tech','US','EXTENDED'),
    ('YELP','Yelp Inc','Tech','US','EXTENDED'),
    ('YORW','York Water','Utilities','US','EXTENDED'),
    ('YOU','Clear Secure','Tech','US','EXTENDED'),
    ('YSX','Yunji Inc','Consumer','US','EXTENDED'),
    ('YTEN','Yield10 Bioscience','Healthcare','US','EXTENDED'),
    ('ZETA','Zeta Global','Tech','US','EXTENDED'),
    ('ZI','ZoomInfo','Tech','US','EXTENDED'),
    ('ZIMV','ZimVie Inc','Healthcare','US','EXTENDED'),
    ('ZLAB','Zymeworks','Healthcare','US','EXTENDED'),
    ('ZUO','Zuora Inc','Tech','US','EXTENDED'),
    ('ZVRA','Zevra Therapeutics','Healthcare','US','EXTENDED'),
    ('ZYME','Zymeworks','Healthcare','US','EXTENDED'),
    ('ANSS','Ansys','Tech','US','EXTENDED'),
    ('PTC','PTC Inc','Tech','US','EXTENDED'),
    ('CDAY','Ceridian','Tech','US','EXTENDED'),
    ('PAYC','Paycom','Tech','US','EXTENDED'),
    ('PCTY','Paylocity','Tech','US','EXTENDED'),
    ('APPF','AppFolio','Tech','US','EXTENDED'),
    ('NCNO','nCino','Tech','US','EXTENDED'),
    ('ALTR','Altair','Tech','US','EXTENDED'),
    ('CDNS','Cadence Design','Tech','US','EXTENDED'),
    ('SNPS','Synopsys','Tech','US','EXTENDED'),
    ('AKAM','Akamai','Tech','US','EXTENDED'),
    ('FTNT','Fortinet','Tech','US','EXTENDED'),
    ('ZS','Zscaler','Tech','US','EXTENDED'),
    ('S','SentinelOne','Tech','US','EXTENDED'),
    ('CYBR','CyberArk','Tech','US','EXTENDED'),
    ('RPM','RPM International','Tech','US','EXTENDED'),
    ('CVS','CVS Health','Healthcare','US','EXTENDED'),
    ('MCK','McKesson','Healthcare','US','EXTENDED'),
    ('ABC','AmerisourceBergen','Healthcare','US','EXTENDED'),
    ('CAH','Cardinal Health','Healthcare','US','EXTENDED'),
    ('HCA','HCA Healthcare','Healthcare','US','EXTENDED'),
    ('CNC','Centene','Healthcare','US','EXTENDED'),
    ('MOH','Molina Healthcare','Healthcare','US','EXTENDED'),
    ('ANTM','Anthem','Healthcare','US','EXTENDED'),
    ('ZBH','Zimmer Biomet','Healthcare','US','EXTENDED'),
    ('BSX','Boston Scientific','Healthcare','US','EXTENDED'),
    ('BDX','Becton Dickinson','Healthcare','US','EXTENDED'),
    ('BAX','Baxter','Healthcare','US','EXTENDED'),
    ('MTD','Mettler-Toledo','Healthcare','US','EXTENDED'),
    ('HOLX','Hologic','Healthcare','US','EXTENDED'),
    ('AMED','Amedisys','Healthcare','US','EXTENDED'),
    ('ENSG','Ensign Group','Healthcare','US','EXTENDED'),
    ('EXAS','Exact Sciences','Healthcare','US','EXTENDED'),
    ('NTRA','Natera','Healthcare','US','EXTENDED'),
    ('PACB','PacBio','Healthcare','US','EXTENDED'),
    ('ILMN','Illumina','Healthcare','US','EXTENDED'),
    ('IQV','IQVIA','Healthcare','US','EXTENDED'),
    ('CRL','Charles River Labs','Healthcare','US','EXTENDED'),
    ('MEDP','Medpace','Healthcare','US','EXTENDED'),
    ('LOW','Lowes','Consumer','US','EXTENDED'),
    ('TJX','TJX Companies','Consumer','US','EXTENDED'),
    ('ROST','Ross Stores','Consumer','US','EXTENDED'),
    ('BURL','Burlington','Consumer','US','EXTENDED'),
    ('M','Macys','Consumer','US','EXTENDED'),
    ('GPS','Gap','Consumer','US','EXTENDED'),
    ('ANF','Abercrombie','Consumer','US','EXTENDED'),
    ('AEO','American Eagle','Consumer','US','EXTENDED'),
    ('PVH','PVH Corp','Consumer','US','EXTENDED'),
    ('RL','Ralph Lauren','Consumer','US','EXTENDED'),
    ('TPR','Tapestry','Consumer','US','EXTENDED'),
    ('CPRI','Capri Holdings','Consumer','US','EXTENDED'),
    ('VFC','VF Corp','Consumer','US','EXTENDED'),
    ('HBI','Hanesbrands','Consumer','US','EXTENDED'),
    ('KO','Coca-Cola','Consumer','US','EXTENDED'),
    ('PEP','PepsiCo','Consumer','US','EXTENDED'),
    ('MDLZ','Mondelez','Consumer','US','EXTENDED'),
    ('GIS','General Mills','Consumer','US','EXTENDED'),
    ('K','Kellogg','Consumer','US','EXTENDED'),
    ('CPB','Campbell Soup','Consumer','US','EXTENDED'),
    ('HRL','Hormel','Consumer','US','EXTENDED'),
    ('SJM','JM Smucker','Consumer','US','EXTENDED'),
    ('MKC','McCormick','Consumer','US','EXTENDED'),
    ('CLX','Clorox','Consumer','US','EXTENDED'),
    ('CHD','Church Dwight','Consumer','US','EXTENDED'),
    ('PG','Procter Gamble','Consumer','US','EXTENDED'),
    ('CL','Colgate','Consumer','US','EXTENDED'),
    ('KMB','Kimberly-Clark','Consumer','US','EXTENDED'),
    ('EL','Estee Lauder','Consumer','US','EXTENDED'),
    ('ULTA','Ulta Beauty','Consumer','US','EXTENDED'),
    ('COTY','Coty Inc','Consumer','US','EXTENDED'),
    ('DIS','Disney','Consumer','US','EXTENDED'),
    ('PARA','Paramount','Consumer','US','EXTENDED'),
    ('WBD','Warner Bros Discovery','Consumer','US','EXTENDED'),
    ('FOX','Fox Corp','Consumer','US','EXTENDED'),
    ('SIRI','Sirius XM','Consumer','US','EXTENDED'),
    ('LYV','Live Nation','Consumer','US','EXTENDED'),
    ('SPOT','Spotify','Consumer','US','EXTENDED'),
    ('PINS','Pinterest','Tech','US','EXTENDED'),
    ('SNAP','Snap','Tech','US','EXTENDED'),
    ('RDDT','Reddit','Tech','US','EXTENDED'),
    ('MTCH','Match Group','Consumer','US','EXTENDED'),
    ('IAC','IAC Inc','Consumer','US','EXTENDED'),
    ('MMM','3M','Industrials','US','EXTENDED'),
    ('GD','General Dynamics','Industrials','US','EXTENDED'),
    ('LHX','L3Harris','Industrials','US','EXTENDED'),
    ('TDG','TransDigm','Industrials','US','EXTENDED'),
    ('HEI','HEICO','Industrials','US','EXTENDED'),
    ('TXT','Textron','Industrials','US','EXTENDED'),
    ('SPR','Spirit AeroSystems','Industrials','US','EXTENDED'),
    ('KTOS','Kratos Defense','Industrials','US','EXTENDED'),
    ('BWXT','BWX Technologies','Industrials','US','EXTENDED'),
    ('CACI','CACI International','Industrials','US','EXTENDED'),
    ('SAIC','SAIC','Industrials','US','EXTENDED'),
    ('LDOS','Leidos','Industrials','US','EXTENDED'),
    ('BAH','Booz Allen Hamilton','Industrials','US','EXTENDED'),
    ('MANT','ManTech','Industrials','US','EXTENDED'),
    ('CSX','CSX Corp','Industrials','US','EXTENDED'),
    ('NSC','Norfolk Southern','Industrials','US','EXTENDED'),
    ('UNP','Union Pacific','Industrials','US','EXTENDED'),
    ('CP','Canadian Pacific','Industrials','US','EXTENDED'),
    ('CNI','Canadian National','Industrials','US','EXTENDED'),
    ('JBHT','JB Hunt','Industrials','US','EXTENDED'),
    ('XPO','XPO Inc','Industrials','US','EXTENDED'),
    ('ODFL','Old Dominion','Industrials','US','EXTENDED'),
    ('SAIA','Saia Inc','Industrials','US','EXTENDED'),
    ('CHRW','CH Robinson','Industrials','US','EXTENDED'),
    ('EXPD','Expeditors','Industrials','US','EXTENDED'),
    ('GWW','WW Grainger','Industrials','US','EXTENDED'),
    ('MSC','MSC Industrial','Industrials','US','EXTENDED'),
    ('FAST','Fastenal','Industrials','US','EXTENDED'),
    ('AIT','Applied Industrial','Industrials','US','EXTENDED'),
    ('WSO','Watsco','Industrials','US','EXTENDED'),
    ('TT','Trane Technologies','Industrials','US','EXTENDED'),
    ('CARR','Carrier Global','Industrials','US','EXTENDED'),
    ('OTIS','Otis Worldwide','Industrials','US','EXTENDED'),
    ('JCI','Johnson Controls','Industrials','US','EXTENDED'),
    ('GNRC','Generac','Industrials','US','EXTENDED'),
    ('REVG','REV Group','Industrials','US','EXTENDED'),
    ('WMS','Advanced Drainage','Industrials','US','EXTENDED'),
    ('MRO','Marathon Oil','Energy','US','EXTENDED'),
    ('APA','APA Corp','Energy','US','EXTENDED'),
    ('CLR','Continental Resources','Energy','US','EXTENDED'),
    ('MTDR','Matador Resources','Energy','US','EXTENDED'),
    ('CHRD','Chord Energy','Energy','US','EXTENDED'),
    ('PR','Permian Resources','Energy','US','EXTENDED'),
    ('VTLE','Vital Energy','Energy','US','EXTENDED'),
    ('KMI','Kinder Morgan','Energy','US','EXTENDED'),
    ('WMB','Williams Companies','Energy','US','EXTENDED'),
    ('OKE','ONEOK','Energy','US','EXTENDED'),
    ('EPD','Enterprise Products','Energy','US','EXTENDED'),
    ('ET','Energy Transfer','Energy','US','EXTENDED'),
    ('MPLX','MPLX LP','Energy','US','EXTENDED'),
    ('LNG','Cheniere Energy','Energy','US','EXTENDED'),
    ('NFE','New Fortress Energy','Energy','US','EXTENDED'),
    ('TELL','Tellurian','Energy','US','EXTENDED'),
    ('RRC','Range Resources','Energy','US','EXTENDED'),
    ('EQT','EQT Corp','Energy','US','EXTENDED'),
    ('AR','Antero Resources','Energy','US','EXTENDED'),
    ('CNX','CNX Resources','Energy','US','EXTENDED'),
    ('EIX','Edison International','Utilities','US','EXTENDED'),
    ('XEL','Xcel Energy','Utilities','US','EXTENDED'),
    ('WEC','WEC Energy','Utilities','US','EXTENDED'),
    ('ES','Eversource','Utilities','US','EXTENDED'),
    ('ETR','Entergy','Utilities','US','EXTENDED'),
    ('PPL','PPL Corp','Utilities','US','EXTENDED'),
    ('CMS','CMS Energy','Utilities','US','EXTENDED'),
    ('NI','NiSource','Utilities','US','EXTENDED'),
    ('OGE','OGE Energy','Utilities','US','EXTENDED'),
    ('EVRG','Evergy','Utilities','US','EXTENDED'),
    ('NRG','NRG Energy','Utilities','US','EXTENDED'),
    ('VST','Vistra Energy','Utilities','US','EXTENDED'),
    ('CEG','Constellation Energy','Utilities','US','EXTENDED'),
    ('NTR','Nutrien','Utilities','US','EXTENDED'),
    ('OKLO','Oklo Inc','Utilities','US','EXTENDED'),
    ('SMR','NuScale Power','Utilities','US','EXTENDED'),
    ('NEM','Newmont','Materials','US','EXTENDED'),
    ('GOLD','Barrick Gold','Materials','US','EXTENDED'),
    ('AEM','Agnico Eagle','Materials','US','EXTENDED'),
    ('WPM','Wheaton Precious','Materials','US','EXTENDED'),
    ('RGLD','Royal Gold','Materials','US','EXTENDED'),
    ('AGI','Alamos Gold','Materials','US','EXTENDED'),
    ('KGC','Kinross Gold','Materials','US','EXTENDED'),
    ('HL','Hecla Mining','Materials','US','EXTENDED'),
    ('CDE','Coeur Mining','Materials','US','EXTENDED'),
    ('EGO','Eldorado Gold','Materials','US','EXTENDED'),
    ('PPG','PPG Industries','Materials','US','EXTENDED'),
    ('SHW','Sherwin-Williams','Materials','US','EXTENDED'),
    ('CE','Celanese','Materials','US','EXTENDED'),
    ('LYB','LyondellBasell','Materials','US','EXTENDED'),
    ('DOW','Dow Inc','Materials','US','EXTENDED'),
    ('DD','DuPont','Materials','US','EXTENDED'),
    ('EMN','Eastman Chemical','Materials','US','EXTENDED'),
    ('HUN','Huntsman','Materials','US','EXTENDED'),
    ('WLK','Westlake Chemical','Materials','US','EXTENDED'),
    ('AMT','American Tower','RealEstate','US','EXTENDED'),
    ('CCI','Crown Castle','RealEstate','US','EXTENDED'),
    ('SBAC','SBA Communications','RealEstate','US','EXTENDED'),
    ('PLD','Prologis','RealEstate','US','EXTENDED'),
    ('EQIX','Equinix','RealEstate','US','EXTENDED'),
    ('DLR','Digital Realty','RealEstate','US','EXTENDED'),
    ('WELL','Welltower','RealEstate','US','EXTENDED'),
    ('VTR','Ventas','RealEstate','US','EXTENDED'),
    ('O','Realty Income','RealEstate','US','EXTENDED'),
    ('SPG','Simon Property','RealEstate','US','EXTENDED'),
    ('MAC','Macerich','RealEstate','US','EXTENDED'),
    ('ARE','Alexandria RE','RealEstate','US','EXTENDED'),
    ('BXP','Boston Properties','RealEstate','US','EXTENDED'),
    ('SLG','SL Green','RealEstate','US','EXTENDED'),
    ('EQR','Equity Residential','RealEstate','US','EXTENDED'),
    ('AVB','AvalonBay','RealEstate','US','EXTENDED'),
    ('ESS','Essex Property','RealEstate','US','EXTENDED'),
    ('MAA','Mid-America Apt','RealEstate','US','EXTENDED'),
    ('UDR','UDR Inc','RealEstate','US','EXTENDED'),
    ('RGTI','Rigetti Computing','AI','US','EXTENDED'),
    ('QBTS','D-Wave Quantum','AI','US','EXTENDED'),
    ('QUBT','Quantum Computing','AI','US','EXTENDED'),
    ('IONQ','IonQ','AI','US','EXTENDED'),
    ('ARQQ','Arqit Quantum','AI','US','EXTENDED'),
    ('BTBT','Bit Digital','Momentum','US','EXTENDED'),
    ('MSTR','MicroStrategy','Momentum','US','EXTENDED'),
    ('COIN','Coinbase','Financials','US','EXTENDED'),
    ('HOOD','Robinhood','Financials','US','EXTENDED'),
    ('NU','Nu Holdings','Financials','US','EXTENDED'),
    ('UPST','Upstart','Financials','US','EXTENDED'),
    ('LC','LendingClub','Financials','US','EXTENDED'),
    ('OPEN','Opendoor','RealEstate','US','EXTENDED'),
    ('RDFN','Redfin','RealEstate','US','EXTENDED'),
    ('CARG','CarGurus','Consumer','US','EXTENDED'),
    ('VRM','Vroom','Consumer','US','EXTENDED'),
    ('CVNA','Carvana','Consumer','US','EXTENDED'),
    ('KMX','CarMax','Consumer','US','EXTENDED'),
    ('AN','AutoNation','Consumer','US','EXTENDED'),
    ('PAG','Penske Auto','Consumer','US','EXTENDED'),
    ('FNF','Fidelity National','Financials','US','EXTENDED'),
    ('RNR','RenaissanceRe','Financials','US','EXTENDED'),
    ('RYAN','Ryan Specialty','Financials','US','EXTENDED'),
    ('CUBI','Customers Bancorp','Financials','US','EXTENDED'),
    ('HOPE','Hope Bancorp','Financials','US','EXTENDED'),
    ('BANF','BancFirst','Financials','US','EXTENDED'),
    ('BPOP','Popular Inc','Financials','US','EXTENDED'),
    ('FFIN','First Financial','Financials','US','EXTENDED'),
    ('CATY','Cathay General','Financials','US','EXTENDED'),
    ('IBOC','International Bancshares','Financials','US','EXTENDED'),
    ('TCBK','TriCo Bancshares','Financials','US','EXTENDED'),
    ('BOKF','BOK Financial','Financials','US','EXTENDED'),
    ('SNV','Synovus','Financials','US','EXTENDED'),
    ('COLB','Columbia Banking','Financials','US','EXTENDED'),
    ('SFBS','ServisFirst','Financials','US','EXTENDED'),
    ('CSWC','Capital Southwest','Financials','US','EXTENDED'),
    ('ARCC','Ares Capital','Financials','US','EXTENDED'),
    ('GBDC','Golub Capital','Financials','US','EXTENDED'),
    ('TPVG','TriplePoint Venture','Financials','US','EXTENDED'),
    ('OBDC','Blue Owl Capital','Financials','US','EXTENDED'),
    ('FSK','FS KKR Capital','Financials','US','EXTENDED'),
    ('PSEC','Prospect Capital','Financials','US','EXTENDED'),
    ('MAIN','Main Street Capital','Financials','US','EXTENDED'),
    ('HTGC','Hercules Capital','Financials','US','EXTENDED'),
    ('TRIN','Trinity Capital','Financials','US','EXTENDED'),
    ('GAIN','Gladstone Investment','Financials','US','EXTENDED'),
    ('WHR','Whirlpool','Consumer','US','EXTENDED'),
    ('LEG','Leggett Platt','Consumer','US','EXTENDED'),
    ('MHK','Mohawk Industries','Consumer','US','EXTENDED'),
    ('FBHS','Fortune Brands','Consumer','US','EXTENDED'),
    ('ALLE','Allegion','Industrials','US','EXTENDED'),
    ('SWK','Stanley Black Decker','Industrials','US','EXTENDED'),
    ('TUL','Tupperware','Consumer','US','EXTENDED'),
    ('HAS','Hasbro','Consumer','US','EXTENDED'),
    ('MAT','Mattel','Consumer','US','EXTENDED'),
    ('JAKK','JAKKS Pacific','Consumer','US','EXTENDED'),
    ('CENT','Central Garden Pet','Consumer','US','EXTENDED'),
    ('FRPT','Freshpet','Consumer','US','EXTENDED'),
    ('CHWY','Chewy','Consumer','US','EXTENDED'),
    ('WOOF','Petco','Consumer','US','EXTENDED'),
    ('BOWL','Bowlero','Consumer','US','EXTENDED'),
    ('PLNT','Planet Fitness','Consumer','US','EXTENDED'),
    ('XPOF','Xponential Fitness','Consumer','US','EXTENDED'),
    ('PTON','Peloton','Consumer','US','EXTENDED'),
    ('NLS','Nautilus','Consumer','US','EXTENDED'),
    ('ACHR','Archer Aviation','Industrials','US','EXTENDED'),
    ('LILM','Lilium','Industrials','US','EXTENDED'),
    ('EVEX','Eve Holding','Industrials','US','EXTENDED'),
    ('BLDE','Blade Air Mobility','Industrials','US','EXTENDED'),
    ('FLYY','Surf Air Mobility','Industrials','US','EXTENDED'),
    ('OWLT','Owlet','Healthcare','US','EXTENDED'),
    ('SWAV','ShockWave Medical','Healthcare','US','EXTENDED'),
    ('INSP','Inspire Medical','Healthcare','US','EXTENDED'),
    ('DXCM','Dexcom','Healthcare','US','EXTENDED'),
    ('PODD','Insulet','Healthcare','US','EXTENDED'),
    ('ABMD','Abiomed','Healthcare','US','EXTENDED'),
    ('NVCR','NovaCure','Healthcare','US','EXTENDED'),
    ('HAYW','Hayward Holdings','Industrials','US','EXTENDED'),
    ('LMAT','LeMaitre Vascular','Healthcare','US','EXTENDED'),
    ('LFUS','Littelfuse','Tech','US','EXTENDED'),
    ('NOVT','Novanta','Tech','US','EXTENDED'),
    ('MKSI','MKS Instruments','Tech','US','EXTENDED'),
    ('ONTO','Onto Innovation','Tech','US','EXTENDED'),
    ('ACLS','Axcelis Technologies','Tech','US','EXTENDED'),
    ('IIVI','Coherent Corp','Tech','US','EXTENDED'),
    ('LITE','Lumentum','Tech','US','EXTENDED'),
    ('VIAV','Viavi Solutions','Tech','US','EXTENDED'),
    ('UCTT','Ultra Clean Holdings','Tech','US','EXTENDED'),
    ('FORM','FormFactor','Tech','US','EXTENDED'),
    ('AMKR','Amkor Technology','Tech','US','EXTENDED'),
    ('SITM','SiTime','Tech','US','EXTENDED'),
    ('ALGM','Allegro MicroSystems','Tech','US','EXTENDED'),
    ('LASR','nLIGHT','Tech','US','EXTENDED'),
    ('MTSI','MACOM Technology','Tech','US','EXTENDED'),
    ('SWKS','Skyworks','Tech','US','EXTENDED'),
    ('QRVO','Qorvo','Tech','US','EXTENDED'),
    ('CRUS','Cirrus Logic','Tech','US','EXTENDED'),
    ('DIOD','Diodes Inc','Tech','US','EXTENDED'),
    ('SLAB','Silicon Laboratories','Tech','US','EXTENDED'),
    ('MLNX','Mellanox','Tech','US','EXTENDED'),
    ('AMBA','Ambarella','Tech','US','EXTENDED'),
    ('NVEC','NVE Corp','Tech','US','EXTENDED'),
    ('OSIS','OSI Systems','Tech','US','EXTENDED'),
    ('GILT','Gilat Satellite','Tech','US','EXTENDED'),
    ('PCTI','PCTEL Inc','Tech','US','EXTENDED'),
    ('SMTC','Semtech','Tech','US','EXTENDED'),
    ('IDCC','InterDigital','Tech','US','EXTENDED'),
    ('RMBS','Rambus','Tech','US','EXTENDED'),
    ('XPERI','Xperi Inc','Tech','US','EXTENDED'),
    ('DV','DoubleVerify','Tech','US','EXTENDED'),
    ('IAS','Integral Ad Science','Tech','US','EXTENDED'),
    ('MGNI','Magnite','Tech','US','EXTENDED'),
    ('TTD','Trade Desk','Tech','US','EXTENDED'),
    ('APPS','Digital Turbine','Tech','US','EXTENDED'),
    ('IRONSRC','ironSource','Tech','US','EXTENDED'),
    ('APP','AppLovin','Tech','US','EXTENDED'),
    ('UNITY','Unity Software','Tech','US','EXTENDED'),
    ('RBLX','Roblox','Tech','US','EXTENDED'),
    ('TTWO','Take-Two Interactive','Tech','US','EXTENDED'),
    ('EA','Electronic Arts','Tech','US','EXTENDED'),
    ('ATVI','Activision Blizzard','Tech','US','EXTENDED'),
    ('PLTK','Playtika','Tech','US','EXTENDED'),
    ('SKLZ','Skillz','Tech','US','EXTENDED'),
    ('GMBL','Esports Entertainment','Tech','US','EXTENDED'),
    ('GENI','Genius Sports','Tech','US','EXTENDED'),
    ('SGHC','Super Group','Consumer','US','EXTENDED'),
    ('RSI','Rush Street Interactive','Consumer','US','EXTENDED'),
    ('GAN','GAN Limited','Consumer','US','EXTENDED'),
    ('EVERI','Everi Holdings','Consumer','US','EXTENDED'),
    ('AGS','PlayAGS','Consumer','US','EXTENDED'),
    ('ACMR','ACM Research','Tech','US','EXTENDED'),
    ('AEHR','Aehr Test Systems','Tech','US','EXTENDED'),
    ('PRCT','Procept BioRobotics','Healthcare','US','EXTENDED'),
    ('AXNX','Axonics','Healthcare','US','EXTENDED'),
    ('IRTC','iRhythm','Healthcare','US','EXTENDED'),
    ('AVNS','Avanos Medical','Healthcare','US','EXTENDED'),
    ('ATRC','AtriCure','Healthcare','US','EXTENDED'),
    ('NVST','Envista Holdings','Healthcare','US','EXTENDED'),
    ('XRAY','Dentsply Sirona','Healthcare','US','EXTENDED'),
    ('ALGN','Align Technology','Healthcare','US','EXTENDED'),
    ('SRDX','Surmodics','Healthcare','US','EXTENDED'),
    ('NARI','Inari Medical','Healthcare','US','EXTENDED'),
    ('SITE','SiteOne Landscape','Industrials','US','EXTENDED'),
    ('POOL','Pool Corp','Industrials','US','EXTENDED'),
    ('BECN','Beacon Roofing','Industrials','US','EXTENDED'),
    ('IBP','Installed Building','Industrials','US','EXTENDED'),
    ('BLDR','Builders FirstSource','Industrials','US','EXTENDED'),
    ('TREX','Trex Company','Industrials','US','EXTENDED'),
    ('AZEK','AZEK Company','Industrials','US','EXTENDED'),
    ('PGTI','PGT Innovations','Industrials','US','EXTENDED'),
    ('NVR','NVR Inc','Industrials','US','EXTENDED'),
    ('PHM','PulteGroup','Industrials','US','EXTENDED'),
    ('DHI','DR Horton','Industrials','US','EXTENDED'),
    ('LEN','Lennar','Industrials','US','EXTENDED'),
    ('TOL','Toll Brothers','Industrials','US','EXTENDED'),
    ('MDC','MDC Holdings','Industrials','US','EXTENDED'),
    ('TMHC','Taylor Morrison','Industrials','US','EXTENDED'),
    ('SKY','Skyline Champion','Industrials','US','EXTENDED'),
    ('CVCO','Cavco Industries','Industrials','US','EXTENDED'),
    ('UCP','UCP Inc','Industrials','US','EXTENDED'),
    ('CCS','Century Communities','Industrials','US','EXTENDED'),
    ('GRBK','Green Brick Partners','Industrials','US','EXTENDED'),
    ('LGIH','LGI Homes','Industrials','US','EXTENDED'),
    ('SMCI','Super Micro','AI','US','EXTENDED'),
    ('VRT','Vertiv Holdings','AI','US','EXTENDED'),
    ('GTLB','GitLab','Tech','US','EXTENDED'),
    ('DSGX','Descartes Systems','Tech','US','EXTENDED'),
    ('LSPD','Lightspeed Commerce','Tech','US','EXTENDED'),
    ('TOST','Toast Inc','Tech','US','EXTENDED'),
    ('PAR','PAR Technology','Tech','US','EXTENDED'),
    ('OLO','Olo Inc','Tech','US','EXTENDED'),
    ('INST','Instructure','Tech','US','EXTENDED'),
    ('CWAN','Clearwater Analytics','Tech','US','EXTENDED'),
    ('ALKT','Alkami Technology','Tech','US','EXTENDED'),
    ('ENFN','Enfusion','Tech','US','EXTENDED'),
    ('FLYW','Flywire','Financials','US','EXTENDED'),
    ('RPAY','Repay Holdings','Financials','US','EXTENDED'),
    ('PAYO','Payoneer','Financials','US','EXTENDED'),
    ('NVEI','Nuvei','Financials','US','EXTENDED'),
    ('FOUR','Shift4 Payments','Financials','US','EXTENDED'),
    ('DLO','DLocal','Financials','US','EXTENDED'),
    ('PSFE','Paysafe','Financials','US','EXTENDED'),
    ('IIIV','i2c Inc','Financials','US','EXTENDED'),
    ('PAYS','Paysign','Financials','US','EXTENDED'),
    ('PRAA','PRA Group','Financials','US','EXTENDED'),
    ('ECPG','Encore Capital','Financials','US','EXTENDED'),
    ('ELVT','Elevate Credit','Financials','US','EXTENDED'),
    ('LIAN','Lian Group','Financials','US','EXTENDED'),
    ('XP','XP Inc','Financials','US','EXTENDED'),
    ('PX','P10 Holdings','Financials','US','EXTENDED'),
    ('BLUE','bluebird bio','Healthcare','US','EXTENDED'),
    ('FATE','Fate Therapeutics','Healthcare','US','EXTENDED'),
    ('NTLA','Intellia Therapeutics','Healthcare','US','EXTENDED'),
    ('BEAM','Beam Therapeutics','Healthcare','US','EXTENDED'),
    ('EDIT','Editas Medicine','Healthcare','US','EXTENDED'),
    ('VERV','Verve Therapeutics','Healthcare','US','EXTENDED'),
    ('GRPH','Graphite Bio','Healthcare','US','EXTENDED'),
    ('PRIME','Prime Medicine','Healthcare','US','EXTENDED'),
    ('ARBK','Argo Blockchain','Momentum','US','EXTENDED'),
    ('BITF','Bitfarms','Momentum','US','EXTENDED'),
    ('HIVE','HIVE Digital','Momentum','US','EXTENDED'),
    ('MIGI','Migi & Dali','Momentum','US','EXTENDED'),
    ('SATO','Satoshi Island','Momentum','US','EXTENDED'),
    ('BTCS','BTCS Inc','Momentum','US','EXTENDED'),
    ('XBTC','Super Bitcoin','Momentum','US','EXTENDED'),
    ('BSRT','Bitwise Bitcoin','Momentum','US','EXTENDED'),
    ('GBTC','Grayscale Bitcoin','Momentum','US','EXTENDED'),
    ('ETHE','Grayscale Ethereum','Momentum','US','EXTENDED'),
    ('IBIT','iShares Bitcoin','Momentum','US','EXTENDED'),
    ('FBTC','Fidelity Bitcoin','Momentum','US','EXTENDED'),
    ('ARKB','ARK Bitcoin','Momentum','US','EXTENDED'),
    ('BRRR','Valkyrie Bitcoin','Momentum','US','EXTENDED'),
    ('HODL','VanEck Bitcoin','Momentum','US','EXTENDED'),
    ('DEFI','Hashdex Bitcoin','Momentum','US','EXTENDED'),
    ('EZBC','Franklin Bitcoin','Momentum','US','EXTENDED'),
    ('BTCO','Invesco Bitcoin','Momentum','US','EXTENDED'),
    ('ARKA','ARK 21Shares','Momentum','US','EXTENDED'),
    ('LAD','Lithia Motors','Consumer','US','EXTENDED'),
    ('DDOG','Datadog','Tech','US','CORE'),('NET','Cloudflare','Tech','US','CORE'),
    ('CRWD','CrowdStrike','Tech','US','CORE'),('PANW','Palo Alto','Tech','US','CORE'),
    ('ORCL','Oracle','Tech','US','CORE'),('UBER','Uber','Tech','US','CORE'),
    ('SHOP','Shopify','Tech','US','CORE'),('INTU','Intuit','Tech','US','CORE'),
    ('AI','C3.ai','AI','US','EXTENDED'),('SOUN','SoundHound','AI','US','EXTENDED'),
    ('BBAI','BigBear.ai','AI','US','EXTENDED'),('RXRX','Recursion','AI','US','EXTENDED'),
    ('ANET','Arista Networks','Tech','US','CORE'),('MRVL','Marvell','AI','US','CORE'),
    ('MPWR','Monolithic Power','AI','US','CORE'),('ON','ON Semi','AI','US','CORE'),
    ('TXN','Texas Instruments','AI','US','CORE'),('AMAT','Applied Materials','AI','US','CORE'),
    ('LRCX','Lam Research','AI','US','CORE'),('KLAC','KLA Corp','AI','US','CORE'),
    ('ASML','ASML US','AI','US','CORE'),
    # ── USA FINANCIALS ─────────────────────────────────────
    ('JPM','JPMorgan','Financials','US','CORE'),('GS','Goldman Sachs','Financials','US','CORE'),
    ('MS','Morgan Stanley','Financials','US','CORE'),('BAC','Bank of America','Financials','US','CORE'),
    ('WFC','Wells Fargo','Financials','US','CORE'),('C','Citigroup','Financials','US','CORE'),
    ('V','Visa','Financials','US','CORE'),('MA','Mastercard','Financials','US','CORE'),
    ('AXP','Amex','Financials','US','CORE'),('BLK','BlackRock','Financials','US','CORE'),
    ('SCHW','Schwab','Financials','US','CORE'),('COF','Capital One','Financials','US','CORE'),
    ('SOFI','SoFi','Financials','US','EXTENDED'),('AFRM','Affirm','Financials','US','EXTENDED'),
    ('SQ','Block','Financials','US','EXTENDED'),('PYPL','PayPal','Financials','US','EXTENDED'),
    # ── USA ENERGY ─────────────────────────────────────────
    ('XOM','Exxon Mobil','Energy','US','CORE'),('CVX','Chevron','Energy','US','CORE'),
    ('COP','ConocoPhillips','Energy','US','CORE'),('DVN','Devon Energy','Energy','US','LIVE'),
    ('EOG','EOG Resources','Energy','US','CORE'),('OXY','Occidental','Energy','US','CORE'),
    ('FANG','Diamondback','Energy','US','CORE'),('PSX','Phillips 66','Energy','US','CORE'),
    ('VLO','Valero','Energy','US','CORE'),('MPC','Marathon Petroleum','Energy','US','CORE'),
    ('SLB','Schlumberger','Energy','US','CORE'),('HAL','Halliburton','Energy','US','CORE'),
    ('CCJ','Cameco','Energy','US','EXTENDED'),('ENPH','Enphase','Energy','US','EXTENDED'),
    ('FSLR','First Solar','Energy','US','EXTENDED'),('BE','Bloom Energy','Energy','US','EXTENDED'),
    ('PLUG','Plug Power','Energy','US','EXTENDED'),('DINO','HF Sinclair','Energy','US','EXTENDED'),
    # ── USA HEALTHCARE ─────────────────────────────────────
    ('LLY','Eli Lilly','Healthcare','US','CORE'),('UNH','UnitedHealth','Healthcare','US','CORE'),
    ('REGN','Regeneron','Healthcare','US','CORE'),('VRTX','Vertex','Healthcare','US','CORE'),
    ('JNJ','J&J','Healthcare','US','CORE'),('MRK','Merck','Healthcare','US','CORE'),
    ('ABBV','AbbVie','Healthcare','US','CORE'),('BMY','Bristol-Myers','Healthcare','US','CORE'),
    ('AMGN','Amgen','Healthcare','US','CORE'),('GILD','Gilead','Healthcare','US','CORE'),
    ('PFE','Pfizer','Healthcare','US','CORE'),('MRNA','Moderna','Healthcare','US','EXTENDED'),
    ('BNTX','BioNTech','Healthcare','US','EXTENDED'),('ISRG','Intuitive Surg','Healthcare','US','CORE'),
    ('TMO','Thermo Fisher','Healthcare','US','EXTENDED'),('DHR','Danaher','Healthcare','US','EXTENDED'),
    ('SYK','Stryker','Healthcare','US','EXTENDED'),('EW','Edwards Life','Healthcare','US','EXTENDED'),
    ('IDXX','IDEXX Labs','Healthcare','US','EXTENDED'),('GEHC','GE HealthCare','Healthcare','US','EXTENDED'),
    ('HUM','Humana','Healthcare','US','EXTENDED'),('ELV','Elevance','Healthcare','US','EXTENDED'),
    ('CI','Cigna','Healthcare','US','EXTENDED'),('CRSP','CRISPR','Healthcare','US','EXTENDED'),
    # ── USA CONSUMER ───────────────────────────────────────
    ('AMZN','Amazon','Consumer','US','CORE'),('TSLA','Tesla','Consumer','US','CORE'),
    ('NFLX','Netflix','Consumer','US','CORE'),('COST','Costco','Consumer','US','CORE'),
    ('HD','Home Depot','Consumer','US','CORE'),('WMT','Walmart','Consumer','US','CORE'),
    ('TGT','Target','Consumer','US','CORE'),('NKE','Nike','Consumer','US','CORE'),
    ('SBUX','Starbucks','Consumer','US','CORE'),('MCD','McDonalds','Consumer','US','CORE'),
    ('YUM','Yum Brands','Consumer','US','CORE'),('CMG','Chipotle','Consumer','US','CORE'),
    ('LULU','Lululemon','Consumer','US','EXTENDED'),('CELH','Celsius','Consumer','US','EXTENDED'),
    ('BYDDY','BYD','Consumer','US','EXTENDED'),('RIVN','Rivian','Consumer','US','EXTENDED'),
    ('LCID','Lucid','Consumer','US','EXTENDED'),('NIO','NIO','Consumer','US','EXTENDED'),
    ('DKNG','DraftKings','Consumer','US','EXTENDED'),('ABNB','Airbnb','Consumer','US','EXTENDED'),
    ('DASH','DoorDash','Consumer','US','EXTENDED'),('MELI','MercadoLibre','Consumer','US','EXTENDED'),
    ('RCL','Royal Caribbean','Consumer','US','EXTENDED'),('CCL','Carnival','Consumer','US','EXTENDED'),
    ('MGM','MGM Resorts','Consumer','US','EXTENDED'),('LVS','Las Vegas Sands','Consumer','US','EXTENDED'),
    ('WYNN','Wynn Resorts','Consumer','US','EXTENDED'),('ETSY','Etsy','Consumer','US','EXTENDED'),
    # ── USA INDUSTRIALS ────────────────────────────────────
    ('CAT','Caterpillar','Industrials','US','CORE'),('GE','GE Aerospace','Industrials','US','CORE'),
    ('RTX','RTX','Industrials','US','CORE'),('LMT','Lockheed Martin','Industrials','US','CORE'),
    ('NOC','Northrop Grumman','Industrials','US','CORE'),('BA','Boeing','Industrials','US','CORE'),
    ('HON','Honeywell','Industrials','US','CORE'),('GEV','GE Vernova','Industrials','US','CORE'),
    ('PWR','Quanta Services','Industrials','US','EXTENDED'),('ALSN','Allison Trans','Industrials','US','EXTENDED'),
    ('HPE','HP Enterprise','Tech','US','EXTENDED'),('DAL','Delta Air','Industrials','US','EXTENDED'),
    ('UAL','United Airlines','Industrials','US','EXTENDED'),('AAL','American Air','Industrials','US','EXTENDED'),
    ('UPS','UPS','Industrials','US','EXTENDED'),('FDX','FedEx','Industrials','US','EXTENDED'),
    ('DE','John Deere','Industrials','US','EXTENDED'),('EMR','Emerson','Industrials','US','EXTENDED'),
    ('ETN','Eaton','Industrials','US','EXTENDED'),('HUBB','Hubbell','Industrials','US','EXTENDED'),
    ('AXON','Axon Enterprise','Industrials','US','EXTENDED'),
    # ── USA MATERIALS ──────────────────────────────────────
    ('FCX','Freeport-McMoRan','Materials','US','CORE'),('NUE','Nucor','Materials','US','CORE'),
    ('LIN','Linde','Materials','US','CORE'),('ALB','Albemarle','Materials','US','EXTENDED'),
    ('MP','MP Materials','Materials','US','EXTENDED'),('CF','CF Industries','Materials','US','EXTENDED'),
    ('MOS','Mosaic','Materials','US','EXTENDED'),('STLD','Steel Dynamics','Materials','US','EXTENDED'),
    ('RS','Reliance Steel','Materials','US','EXTENDED'),('X','US Steel','Materials','US','EXTENDED'),
    # ── USA UTILITIES ──────────────────────────────────────
    ('NEE','NextEra Energy','Utilities','US','CORE'),('DUK','Duke Energy','Utilities','US','CORE'),
    ('SO','Southern Co','Utilities','US','CORE'),('AEP','AEP','Utilities','US','EXTENDED'),
    ('EXC','Exelon','Utilities','US','EXTENDED'),('PCG','PG&E','Utilities','US','EXTENDED'),
    # ── USA MOMENTUM / CRYPTO ──────────────────────────────
    ('MARA','Marathon Digital','Momentum','US','CORE'),('RIOT','Riot Platforms','Momentum','US','CORE'),

    # ── DANMARK ────────────────────────────────────────────
    ('NOVO-B.CO','Novo Nordisk','Healthcare','Denmark','CORE'),
    ('DSV.CO','DSV','Industrials','Denmark','EXTENDED'),
    ('DANSKE.CO','Danske Bank','Financials','Denmark','EXTENDED'),
    ('MAERSK-B.CO','AP Moeller Maersk','Industrials','Denmark','EXTENDED'),
    ('PNDORA.CO','Pandora','Consumer','Denmark','EXTENDED'),
    ('GMAB.CO','Genmab','Healthcare','Denmark','EXTENDED'),
    ('VWS.CO','Vestas','Industrials','Denmark','EXTENDED'),
    ('ORSTED.CO','Orsted','Utilities','Denmark','EXTENDED'),
    ('ALMB.CO','Alm. Brand','Financials','Denmark','EXTENDED'),
    ('JYSK.CO','Jyske Bank','Financials','Denmark','EXTENDED'),
    ('TRMD-A.CO','TORM','Energy','Denmark','EXTENDED'),
    ('SPG.CO','SP Group','Industrials','Denmark','EXTENDED'),
    ('AGF-B.CO','AGF','Consumer','Denmark','EXTENDED'),
    ('PARKEN.CO','PARKEN','Consumer','Denmark','EXTENDED'),
    ('ASTK.CO','Asetek','Tech','Denmark','EXTENDED'),
    ('BETCO.ST','Better Collective','Consumer','Denmark','EXTENDED'),

    # ── SVERIGE ────────────────────────────────────────────
    ('EVO.ST','Evolution','Tech','Sweden','CORE'),
    ('VOLV-B.ST','Volvo','Industrials','Sweden','EXTENDED'),
    ('ERIC-B.ST','Ericsson','Tech','Sweden','EXTENDED'),
    ('ATCO-A.ST','Atlas Copco','Industrials','Sweden','EXTENDED'),
    ('SAND.ST','Sandvik','Industrials','Sweden','EXTENDED'),
    ('INVE-B.ST','Investor AB','Financials','Sweden','EXTENDED'),
    ('NDA-SE.ST','Nordea','Financials','Sweden','EXTENDED'),
    ('SECU-B.ST','Securitas','Industrials','Sweden','EXTENDED'),
    ('SKA-B.ST','Skanska','Industrials','Sweden','EXTENDED'),
    ('MILDEF.ST','MilDef Group','Industrials','Sweden','EXTENDED'),
    ('CLAV.ST','Clavister','Tech','Sweden','EXTENDED'),
    ('VSURE.ST','Verisure','Tech','Sweden','EXTENDED'),
    ('SPRINT.ST','Sprint Bioscience','Healthcare','Sweden','EXTENDED'),
    ('NANEXA.ST','Nanexa','Healthcare','Sweden','EXTENDED'),
    ('SINCH.ST','Sinch','Tech','Sweden','EXTENDED'),
    ('EMBRAC-B.ST','Embracer','Tech','Sweden','EXTENDED'),

    # ── NORGE ──────────────────────────────────────────────
    ('EQNR.OL','Equinor','Energy','Norway','EXTENDED'),
    ('DNB.OL','DNB Bank','Financials','Norway','EXTENDED'),
    ('KOG.OL','Kongsberg Gruppen','Industrials','Norway','EXTENDED'),
    ('TEL.OL','Telenor','Tech','Norway','EXTENDED'),
    ('NAS.OL','Norwegian Air','Industrials','Norway','EXTENDED'),
    ('KIT.OL','Kitron','Industrials','Norway','EXTENDED'),
    ('KAHOT.OL','Kahoot','Tech','Norway','EXTENDED'),

    # ── NEDERLANDENE ───────────────────────────────────────
    ('ASML.AS','ASML','AI','Netherlands','CORE'),
    ('ASM.AS','ASM International','AI','Netherlands','CORE'),
    ('BESI.AS','BE Semiconductor','AI','Netherlands','CORE'),
    ('ADYEN.AS','Adyen','Tech','Netherlands','EXTENDED'),
    ('INGA.AS','ING','Financials','Netherlands','EXTENDED'),
    ('PHIA.AS','Philips','Healthcare','Netherlands','EXTENDED'),

    # ── TYSKLAND ───────────────────────────────────────────
    ('SAP.DE','SAP','Tech','Germany','CORE'),
    ('IFX.DE','Infineon','AI','Germany','CORE'),
    ('RHM.DE','Rheinmetall','Industrials','Germany','CORE'),
    ('SIE.DE','Siemens','Industrials','Germany','EXTENDED'),
    ('ALV.DE','Allianz','Financials','Germany','EXTENDED'),
    ('MBG.DE','Mercedes-Benz','Consumer','Germany','EXTENDED'),
    ('BMW.DE','BMW','Consumer','Germany','EXTENDED'),
    ('BAYN.DE','Bayer','Healthcare','Germany','EXTENDED'),
    ('MRK.DE','Merck KGaA','Healthcare','Germany','EXTENDED'),

    # ── UK ─────────────────────────────────────────────────
    ('SHEL.L','Shell','Energy','UK','EXTENDED'),
    ('BP.L','BP','Energy','UK','EXTENDED'),
    ('AZN.L','AstraZeneca','Healthcare','UK','EXTENDED'),
    ('GSK.L','GSK','Healthcare','UK','EXTENDED'),
    ('RR.L','Rolls-Royce','Industrials','UK','EXTENDED'),
    ('BA.L','BAE Systems','Industrials','UK','EXTENDED'),
    ('RIO.L','Rio Tinto','Materials','UK','EXTENDED'),
    ('GLEN.L','Glencore','Materials','UK','EXTENDED'),
    ('HSBA.L','HSBC','Financials','UK','EXTENDED'),
    ('REL.L','RELX','Tech','UK','EXTENDED'),
    ('EXPN.L','Experian','Tech','UK','EXTENDED'),

    # ── FRANKRIG ───────────────────────────────────────────
    ('MC.PA','LVMH','Consumer','France','EXTENDED'),
    ('RMS.PA','Hermes','Consumer','France','EXTENDED'),
    ('AIR.PA','Airbus','Industrials','France','EXTENDED'),
    ('HO.PA','Thales','Industrials','France','EXTENDED'),
    ('TTE.PA','TotalEnergies','Energy','France','EXTENDED'),
    ('BNP.PA','BNP Paribas','Financials','France','EXTENDED'),
    ('SAN.PA','Sanofi','Healthcare','France','EXTENDED'),
    ('CAP.PA','Capgemini','Tech','France','EXTENDED'),
    ('STMPA.PA','STMicro','AI','France','EXTENDED'),

    # ── SCHWEIZ ────────────────────────────────────────────
    ('ROG.SW','Roche','Healthcare','Switzerland','EXTENDED'),
    ('NOVN.SW','Novartis','Healthcare','Switzerland','EXTENDED'),
    ('UBSG.SW','UBS','Financials','Switzerland','EXTENDED'),
    ('ABBN.SW','ABB','Industrials','Switzerland','EXTENDED'),
    ('LOGN.SW','Logitech','Tech','Switzerland','EXTENDED'),
    ('NESN.SW','Nestle','Consumer','Switzerland','EXTENDED'),

    # ── SPANIEN / ITALIEN ──────────────────────────────────
    ('IBE.MC','Iberdrola','Utilities','Spain','EXTENDED'),
    ('SAN.MC','Banco Santander','Financials','Spain','EXTENDED'),
    ('ITX.MC','Inditex','Consumer','Spain','EXTENDED'),
    ('ENEL.MI','Enel','Utilities','Italy','EXTENDED'),
    ('ENI.MI','ENI','Energy','Italy','EXTENDED'),
    ('UCG.MI','UniCredit','Financials','Italy','EXTENDED'),

    # ── FINLAND ────────────────────────────────────────────
    ('NOKIA.HE','Nokia','Tech','Finland','EXTENDED'),
    ('KNEBV.HE','Kone','Industrials','Finland','EXTENDED'),

    # ── JAPAN ──────────────────────────────────────────────
    ('7203.T','Toyota','Consumer','Japan','EXTENDED'),
    ('6758.T','Sony','Tech','Japan','EXTENDED'),
    ('9984.T','SoftBank','Tech','Japan','EXTENDED'),
    ('6861.T','Keyence','AI','Japan','EXTENDED'),
    ('6501.T','Hitachi','Industrials','Japan','EXTENDED'),
    ('8306.T','Mitsubishi UFJ','Financials','Japan','EXTENDED'),
    ('7267.T','Honda','Consumer','Japan','EXTENDED'),
    ('6902.T','Denso','Industrials','Japan','EXTENDED'),

    # ── HONG KONG ──────────────────────────────────────────
    ('0700.HK','Tencent','Tech','HongKong','EXTENDED'),
    ('9988.HK','Alibaba','Consumer','HongKong','EXTENDED'),
    ('3690.HK','Meituan','Consumer','HongKong','EXTENDED'),
    ('1810.HK','Xiaomi','Tech','HongKong','EXTENDED'),

    # ── ASIEN ØVRIGE ───────────────────────────────────────
    ('005930.KS','Samsung','Tech','SouthKorea','EXTENDED'),
    ('000660.KS','SK Hynix','AI','SouthKorea','EXTENDED'),
    ('2330.TW','TSMC TW','AI','Taiwan','EXTENDED'),
    ('INFY.NS','Infosys','Tech','India','EXTENDED'),
    ('TCS.NS','Tata Consultancy','Tech','India','EXTENDED'),
    ('RELIANCE.NS','Reliance','Energy','India','EXTENDED'),

    # ── SEKTOR ETF'er ──────────────────────────────────────
    ('XLE','Energy SPDR','ETF','US','EXTENDED'),
    ('XLK','Tech SPDR','ETF','US','EXTENDED'),
    ('XLF','Financials SPDR','ETF','US','EXTENDED'),
    ('XLV','Healthcare SPDR','ETF','US','EXTENDED'),
    ('XLI','Industrials SPDR','ETF','US','EXTENDED'),
    ('XLB','Materials SPDR','ETF','US','EXTENDED'),
    ('XLY','Consumer Disc SPDR','ETF','US','EXTENDED'),
    ('XLP','Consumer Stap SPDR','ETF','US','EXTENDED'),
    ('XLU','Utilities SPDR','ETF','US','EXTENDED'),
    ('SOXX','Semiconductors','ETF','US','EXTENDED'),
    ('ARKK','ARK Innovation','ETF','US','EXTENDED'),
    ('BOTZ','Robotics AI','ETF','Global','EXTENDED'),
    ('CIBR','Cybersecurity','ETF','US','EXTENDED'),
    ('ITA','Defense','ETF','US','EXTENDED'),
    ('BITO','Bitcoin ETF','ETF','Crypto','EXTENDED'),
    ('GLD','Gold ETF','ETF','Commodities','EXTENDED'),
    ('SLV','Silver ETF','ETF','Commodities','EXTENDED'),
    ('COPX','Copper Miners','ETF','Commodities','EXTENDED'),
    ('VGK','Europe ETF','ETF','Europe','EXTENDED'),
    ('EEM','Emerging Markets','ETF','Global','EXTENDED'),

    # ── USA TECH EKSTRA ────────────────────────────────────
    ('OKTA','Okta','Tech','US','EXTENDED'),
    ('NXPI','NXP Semi','AI','US','EXTENDED'),
    ('MCHP','Microchip Tech','AI','US','EXTENDED'),
    ('ADI','Analog Devices','AI','US','EXTENDED'),
    ('LAM','Lam Research','AI','US','EXTENDED'),
    # ── USA FINANS EKSTRA ──────────────────────────────────
    ('STT','State Street','Financials','US','EXTENDED'),
    ('BK','BNY Mellon','Financials','US','EXTENDED'),
    ('CBOE','Cboe Global','Financials','US','EXTENDED'),
    ('FIS','FIS','Financials','US','EXTENDED'),
    ('FI','Fiserv','Financials','US','EXTENDED'),
    ('GPN','Global Payments','Financials','US','EXTENDED'),
    ('WEX','WEX Inc','Financials','US','EXTENDED'),
    ('ALLY','Ally Financial','Financials','US','EXTENDED'),
    ('DFS','Discover Financial','Financials','US','EXTENDED'),
    ('SYF','Synchrony','Financials','US','EXTENDED'),
    # ── USA HEALTHCARE EKSTRA ──────────────────────────────
    ('MDT','Medtronic','Healthcare','US','EXTENDED'),
    ('ABT','Abbott Labs','Healthcare','US','EXTENDED'),
    ('INCY','Incyte','Healthcare','US','EXTENDED'),
    ('EXEL','Exelixis','Healthcare','US','EXTENDED'),
    ('HZNP','Horizon Therapeutics','Healthcare','US','EXTENDED'),
    ('VTRS','Viatris','Healthcare','US','EXTENDED'),
    ('AGN','Allergan','Healthcare','US','EXTENDED'),
    # ── USA CONSUMER EKSTRA ────────────────────────────────
    ('BBY','Best Buy','Consumer','US','EXTENDED'),
    ('DG','Dollar General','Consumer','US','EXTENDED'),
    ('DLTR','Dollar Tree','Consumer','US','EXTENDED'),
    ('KR','Kroger','Consumer','US','EXTENDED'),
    ('FIVE','Five Below','Consumer','US','EXTENDED'),
    ('OLLI','Ollies Bargain','Consumer','US','EXTENDED'),
    ('URBN','Urban Outfitters','Consumer','US','EXTENDED'),
    ('REYN','Reynolds Consumer','Consumer','US','EXTENDED'),
    ('PM','Philip Morris','Consumer','US','EXTENDED'),
    ('MO','Altria','Consumer','US','EXTENDED'),
    ('BTI','BAT','Consumer','US','EXTENDED'),
    ('DEO','Diageo','Consumer','US','EXTENDED'),
    ('STZ','Constellation Brands','Consumer','US','EXTENDED'),
    ('BF-B','Brown-Forman','Consumer','US','EXTENDED'),
    ('TAP','Molson Coors','Consumer','US','EXTENDED'),
    ('SAM','Boston Beer','Consumer','US','EXTENDED'),
    # ── USA INDUSTRIALS EKSTRA ─────────────────────────────
    ('ITW','Illinois Tool','Industrials','US','EXTENDED'),
    ('PH','Parker Hannifin','Industrials','US','EXTENDED'),
    ('ROK','Rockwell Auto','Industrials','US','EXTENDED'),
    ('AME','Ametek','Industrials','US','EXTENDED'),
    ('XYL','Xylem','Industrials','US','EXTENDED'),
    ('GGG','Graco','Industrials','US','EXTENDED'),
    ('MIDD','Middleby','Industrials','US','EXTENDED'),
    ('WM','Waste Management','Industrials','US','EXTENDED'),
    ('RSG','Republic Services','Industrials','US','EXTENDED'),
    ('CSGP','CoStar Group','Industrials','US','EXTENDED'),
    ('VRSK','Verisk Analytics','Industrials','US','EXTENDED'),
    ('DRS','Leonardo DRS','Industrials','US','EXTENDED'),
    ('HII','Huntington Ingalls','Industrials','US','EXTENDED'),
    # ── USA REAL ESTATE / REIT ─────────────────────────────
    ('VICI','VICI Properties','RealEstate','US','EXTENDED'),
    ('WPC','W P Carey','RealEstate','US','EXTENDED'),
    ('EXR','Extra Space Storage','RealEstate','US','EXTENDED'),
    # ── USA ENERGY EKSTRA ──────────────────────────────────
    ('CTRA','Coterra Energy','Energy','US','EXTENDED'),
    ('OVV','Ovintiv','Energy','US','EXTENDED'),
    ('BKR','Baker Hughes','Energy','US','EXTENDED'),
    ('NOV','NOV Inc','Energy','US','EXTENDED'),
    ('FTI','TechnipFMC','Energy','US','EXTENDED'),
    ('NR','Newpark Resources','Energy','US','EXTENDED'),
    # ── USA MATERIALS EKSTRA ───────────────────────────────
    ('AA','Alcoa','Materials','US','EXTENDED'),
    ('CENX','Century Aluminum','Materials','US','EXTENDED'),
    ('CMC','Commercial Metals','Materials','US','EXTENDED'),
    ('ATI','ATI Inc','Materials','US','EXTENDED'),
    ('ARCH','Arch Resources','Materials','US','EXTENDED'),
    ('AMR','Alpha Met Resources','Materials','US','EXTENDED'),
    ('CSTM','Constellium','Materials','US','EXTENDED'),
    ('FNV','Franco-Nevada','Materials','US','EXTENDED'),
    # ── AUSTRALIEN / NZ ────────────────────────────────────
    ('BHP','BHP Group','Materials','Australia','EXTENDED'),
    ('RIO','Rio Tinto US','Materials','Australia','EXTENDED'),
    ('VALE','Vale SA','Materials','Brazil','EXTENDED'),
    # ── CANADA ─────────────────────────────────────────────
    ('CNQ','Canadian Natural','Energy','Canada','EXTENDED'),
    ('SU','Suncor Energy','Energy','Canada','EXTENDED'),
    ('CVE','Cenovus Energy','Energy','Canada','EXTENDED'),
    ('IMO','Imperial Oil','Energy','Canada','EXTENDED'),
    ('TRP','TC Energy','Energy','Canada','EXTENDED'),
    ('ENB','Enbridge','Energy','Canada','EXTENDED'),
    ('CNR','CN Railway','Industrials','Canada','EXTENDED'),
    ('BAM','Brookfield Asset','Financials','Canada','EXTENDED'),
    ('MFC','Manulife','Financials','Canada','EXTENDED'),
    ('SLF','Sun Life','Financials','Canada','EXTENDED'),
    ('TD','TD Bank','Financials','Canada','EXTENDED'),
    ('RY','Royal Bank Canada','Financials','Canada','EXTENDED'),
    ('BNS','Bank of Nova Scotia','Financials','Canada','EXTENDED'),
    ('BMO','Bank of Montreal','Financials','Canada','EXTENDED'),
    ('CM','CIBC','Financials','Canada','EXTENDED'),
    ('CSU','Constellation Soft','Tech','Canada','EXTENDED'),
    # ── ISRAEL / ANDRE ─────────────────────────────────────
    ('NICE','NICE Systems','Tech','Israel','EXTENDED'),
    ('CHKP','Check Point','Tech','Israel','EXTENDED'),
    ('MNDY','Monday.com','Tech','Israel','EXTENDED'),
    ('GLBE','Global-E Online','Tech','Israel','EXTENDED'),
    # ── SCHWEIZ EKSTRA ─────────────────────────────────────
    ('GIVN.SW','Givaudan','Consumer','Switzerland','EXTENDED'),
    ('SREN.SW','Swiss Re','Financials','Switzerland','EXTENDED'),
    ('ZURN.SW','Zurich Insurance','Financials','Switzerland','EXTENDED'),
    ('ALC.SW','Alcon','Healthcare','Switzerland','EXTENDED'),
    ('STMN.SW','Straumann','Healthcare','Switzerland','EXTENDED'),
    # ── FRANKRIG EKSTRA ────────────────────────────────────
    ('OR.PA','LOreal','Consumer','France','EXTENDED'),
    ('KER.PA','Kering','Consumer','France','EXTENDED'),
    ('RI.PA','Pernod Ricard','Consumer','France','EXTENDED'),
    ('DSY.PA','Dassault Systemes','Tech','France','EXTENDED'),
    ('ATO.PA','Atos','Tech','France','EXTENDED'),
    ('ORA.PA','Orange','Tech','France','EXTENDED'),
    ('VIE.PA','Veolia','Industrials','France','EXTENDED'),
    ('SGO.PA','Saint-Gobain','Materials','France','EXTENDED'),
    ('LR.PA','Legrand','Industrials','France','EXTENDED'),
    # ── NEDERLAND EKSTRA ───────────────────────────────────
    ('HEIA.AS','Heineken','Consumer','Netherlands','EXTENDED'),
    ('AKZA.AS','Akzo Nobel','Materials','Netherlands','EXTENDED'),
    ('UNA.AS','Unilever NL','Consumer','Netherlands','EXTENDED'),
    ('WKL.AS','Wolters Kluwer','Tech','Netherlands','EXTENDED'),
    # ── TYSKLAND EKSTRA ────────────────────────────────────
    ('DTE.DE','Deutsche Telekom','Tech','Germany','EXTENDED'),
    ('DPW.DE','Deutsche Post','Industrials','Germany','EXTENDED'),
    ('MUV2.DE','Munich Re','Financials','Germany','EXTENDED'),
    ('HEN3.DE','Henkel','Consumer','Germany','EXTENDED'),
    ('VOW3.DE','Volkswagen','Consumer','Germany','EXTENDED'),
    ('ADS.DE','Adidas','Consumer','Germany','EXTENDED'),
    ('PUM.DE','Puma','Consumer','Germany','EXTENDED'),
    ('BAS.DE','BASF','Materials','Germany','EXTENDED'),
    ('1COV.DE','Covestro','Materials','Germany','EXTENDED'),
    ('LHA.DE','Lufthansa','Industrials','Germany','EXTENDED'),
    # ── UK EKSTRA ──────────────────────────────────────────
    ('ULVR.L','Unilever','Consumer','UK','EXTENDED'),
    ('DGE.L','Diageo','Consumer','UK','EXTENDED'),
    ('BATS.L','BAT UK','Consumer','UK','EXTENDED'),
    ('IMB.L','Imperial Brands','Consumer','UK','EXTENDED'),
    ('VOD.L','Vodafone','Tech','UK','EXTENDED'),
    ('BT-A.L','BT Group','Tech','UK','EXTENDED'),
    ('LLOY.L','Lloyds Banking','Financials','UK','EXTENDED'),
    ('BARC.L','Barclays','Financials','UK','EXTENDED'),
    ('NWG.L','NatWest','Financials','UK','EXTENDED'),
    ('STAN.L','Standard Chartered','Financials','UK','EXTENDED'),
    ('PRU.L','Prudential','Financials','UK','EXTENDED'),
    ('LGEN.L','Legal & General','Financials','UK','EXTENDED'),
    ('CPG.L','Compass Group','Consumer','UK','EXTENDED'),
    ('SGE.L','Sage Group','Tech','UK','EXTENDED'),
    ('AUTO.L','Auto Trader','Tech','UK','EXTENDED'),
    ('III.L','3i Group','Financials','UK','EXTENDED'),
    ('WEIR.L','Weir Group','Industrials','UK','EXTENDED'),
    ('SMT.L','Scottish Mortgage','Financials','UK','EXTENDED'),
    # ── SCANDINAVIEN EKSTRA ────────────────────────────────
    ('STERV.HE','Stora Enso','Materials','Finland','EXTENDED'),
    ('UPM.HE','UPM-Kymmene','Materials','Finland','EXTENDED'),
    ('METSO.HE','Metso','Industrials','Finland','EXTENDED'),
    ('NESTE.HE','Neste','Energy','Finland','EXTENDED'),
    ('SAMPO.HE','Sampo','Financials','Finland','EXTENDED'),
    ('OUT1V.HE','Outokumpu','Materials','Finland','EXTENDED'),
    ('FORTUM.HE','Fortum','Utilities','Finland','EXTENDED'),
    ('ELISA.HE','Elisa','Tech','Finland','EXTENDED'),
    ('TEM1V.HE','Telia Finland','Tech','Finland','EXTENDED'),
    ('TDC.CO','TDC Net','Tech','Denmark','EXTENDED'),
    ('NETC.CO','Netcompany','Tech','Denmark','EXTENDED'),
    ('RBREW.CO','Royal Unibrew','Consumer','Denmark','EXTENDED'),
    ('CARL-B.CO','Carlsberg','Consumer','Denmark','EXTENDED'),
    ('FLS.CO','FLSmidth','Industrials','Denmark','EXTENDED'),
    ('GN.CO','GN Audio','Tech','Denmark','EXTENDED'),
    ('AMBU-B.CO','Ambu','Healthcare','Denmark','EXTENDED'),
    ('CHR.CO','Chr. Hansen','Healthcare','Denmark','EXTENDED'),
    ('COLO-B.CO','Coloplast','Healthcare','Denmark','EXTENDED'),
    ('NZYM-B.CO','Novozymes','Healthcare','Denmark','EXTENDED'),
    ('SYDB.CO','Sydbank','Financials','Denmark','EXTENDED'),
    ('DEMANT.CO','Demant','Healthcare','Denmark','EXTENDED'),
    ('NTG.CO','NTG Nordic','Industrials','Denmark','EXTENDED'),
    ('ROCK-B.CO','Rockwool','Materials','Denmark','EXTENDED'),
    ('DFDS.CO','DFDS','Industrials','Denmark','EXTENDED'),
    ('MAB.CO','Matas','Consumer','Denmark','EXTENDED'),
    ('AOJ-P.CO','Alm. Brand Forsikring','Financials','Denmark','EXTENDED'),
    ('NNIT.CO','NNIT','Tech','Denmark','EXTENDED'),
    ('BOUV.CO','Bouygues','Industrials','Denmark','EXTENDED'),
    ('SPNO.CO','Sparekassen Nord','Financials','Denmark','EXTENDED'),
    ('NKT.CO','NKT','Industrials','Denmark','EXTENDED'),
    ('VICTOR-B.CO','Victoria Properties','RealEstate','Denmark','EXTENDED'),
    ('HEM.CO','Hemonto','Financials','Denmark','EXTENDED'),
    # ── NORGE EKSTRA ───────────────────────────────────────
    ('MOWI.OL','Mowi','Consumer','Norway','EXTENDED'),
    ('SALM.OL','SalMar','Consumer','Norway','EXTENDED'),
    ('LSG.OL','Leroy Seafood','Consumer','Norway','EXTENDED'),
    ('AUSS.OL','Austevoll Seafood','Consumer','Norway','EXTENDED'),
    ('AKSO.OL','Aker Solutions','Energy','Norway','EXTENDED'),
    ('SUBC.OL','Subsea 7','Energy','Norway','EXTENDED'),
    ('TGS.OL','TGS','Energy','Norway','EXTENDED'),
    ('PGS.OL','PGS','Energy','Norway','EXTENDED'),
    ('AKERBP.OL','Aker BP','Energy','Norway','EXTENDED'),
    ('VAR.OL','Vår Energi','Energy','Norway','EXTENDED'),
    ('RECSI.OL','REC Silicon','Energy','Norway','EXTENDED'),
    ('NEL.OL','Nel ASA','Energy','Norway','EXTENDED'),
    ('SCATC.OL','Scatec','Energy','Norway','EXTENDED'),
    ('BAKKA.OL','Bakkafrost','Consumer','Norway','EXTENDED'),
    ('GRIEG.OL','Grieg Seafood','Consumer','Norway','EXTENDED'),
    ('AKER.OL','Aker ASA','Industrials','Norway','EXTENDED'),
    ('YAR.OL','Yara International','Materials','Norway','EXTENDED'),
    ('ORK.OL','Orkla','Consumer','Norway','EXTENDED'),
    ('SRBANK.OL','SR-Bank','Financials','Norway','EXTENDED'),
    ('SBANKEN.OL','SpareBank 1','Financials','Norway','EXTENDED'),
    ('GJF.OL','Gjensidige','Financials','Norway','EXTENDED'),
    ('STRO.OL','Strongpoint','Tech','Norway','EXTENDED'),
    ('ZAL.OL','Zalaris','Tech','Norway','EXTENDED'),
    # ── SVERIGE EKSTRA ─────────────────────────────────────
    ('HM-B.ST','H&M','Consumer','Sweden','EXTENDED'),
    ('ESSITY-B.ST','Essity','Consumer','Sweden','EXTENDED'),
    ('HUSQ-B.ST','Husqvarna','Consumer','Sweden','EXTENDED'),
    ('SWED-A.ST','Swedbank','Financials','Sweden','EXTENDED'),
    ('SHB-A.ST','Handelsbanken','Financials','Sweden','EXTENDED'),
    ('SEB-A.ST','SEB Bank','Financials','Sweden','EXTENDED'),
    ('LUNE.ST','Lundin Energy','Energy','Sweden','EXTENDED'),
    ('ASSA-B.ST','ASSA ABLOY','Industrials','Sweden','EXTENDED'),
    ('ALFA.ST','Alfa Laval','Industrials','Sweden','EXTENDED'),
    ('NIBE-B.ST','NIBE Industrier','Industrials','Sweden','EXTENDED'),
    ('HEXA-B.ST','Hexagon','Tech','Sweden','EXTENDED'),
    ('TEL2-B.ST','Tele2','Tech','Sweden','EXTENDED'),
    ('TELIA.ST','Telia','Tech','Sweden','EXTENDED'),
    ('BOLL.ST','Boliden','Materials','Sweden','EXTENDED'),
    ('SSAB-A.ST','SSAB','Materials','Sweden','EXTENDED'),
    ('SKF-B.ST','SKF','Industrials','Sweden','EXTENDED'),
    ('INDT.ST','Indutrade','Industrials','Sweden','EXTENDED'),
    ('LIAB.ST','Lifco','Industrials','Sweden','EXTENDED'),
    ('CAST.ST','Castellum','RealEstate','Sweden','EXTENDED'),
    ('FABG.ST','Fabege','RealEstate','Sweden','EXTENDED'),

    # ── REFERENCE INDEKS – hentes automatisk til RS Trend ──
    ('^OMXC25',  'C25 Ref',    'REF','Denmark',     'EXTENDED'),
    ('^OMXS30',  'OMX30 Ref',  'REF','Sweden',      'EXTENDED'),
    ('^OSEBX',   'OBX Ref',    'REF','Norway',       'EXTENDED'),
    ('^GDAXI',   'DAX Ref',    'REF','Germany',      'EXTENDED'),
    ('^FTSE',    'FTSE Ref',   'REF','UK',            'EXTENDED'),
    ('^FCHI',    'CAC Ref',    'REF','France',        'EXTENDED'),
    ('^AEX',     'AEX Ref',    'REF','Netherlands',   'EXTENDED'),
    ('^SSMI',    'SMI Ref',    'REF','Switzerland',   'EXTENDED'),
    ('^N225',    'Nikkei Ref', 'REF','Japan',         'EXTENDED'),
    ('^HSI',     'HSI Ref',    'REF','HongKong',      'EXTENDED'),
    ('^KS11',    'KOSPI Ref',  'REF','SouthKorea',    'EXTENDED'),
    ('^GSPTSE',  'TSX Ref',    'REF','Canada',        'EXTENDED'),
    ('^BSESN',   'BSE Ref',    'REF','India',         'EXTENDED'),
]

# ════════════════════════════════════════════════════════════════════
# FX — streamlit-fri udgave (workeren cacher selv via DB/intervals)
# ════════════════════════════════════════════════════════════════════
def fetch_fx_rates_live(yf_module=None):
    """Hent spot-kurser til USD. Identisk logik som UI'ets fetch_fx_rates,
    men uden @st.cache_data. yf_module injiceres for testbarhed."""
    currencies = sorted({c for c in CURRENCY_BY_REGION.values() if c != 'USD'})
    rates = {'USD': 1.0}
    if yf_module is not None:
        fx_tickers = [f"{c}USD=X" for c in currencies]
        try:
            raw = yf_module.download(fx_tickers, period='5d', interval='1d',
                                     group_by='ticker', auto_adjust=True,
                                     progress=False, threads=True)
            for c in currencies:
                tk = f"{c}USD=X"
                try:
                    df = raw[tk] if len(fx_tickers) > 1 else raw
                    series = df['Close'].dropna()
                    if len(series) > 0:
                        rates[c] = float(series.iloc[-1])
                except Exception as e:
                    LOG.warning(f"FX lookup failed for {c}: {e}")
        except Exception as e:
            LOG.error(f"FX batch fetch failed: {e}")
    defaults = {'DKK':0.145,'EUR':1.08,'SEK':0.095,'NOK':0.092,'GBP':1.27,
                'CHF':1.12,'JPY':0.0066,'HKD':0.128,'KRW':0.00074,'TWD':0.031,
                'INR':0.012,'CAD':0.73,'AUD':0.66,'BRL':0.20,'ILS':0.27,'TRY':0.030}
    for c, d in defaults.items():
        rates.setdefault(c, d)
    return rates

def sma(arr, n):
    if arr is None or len(arr)<n: return None
    return float(np.mean(arr[-n:]))

def rolling_sma(closes, n):
    """Vektoriseret SMA-serie — bruges til stage og chart."""
    return pd.Series(closes).rolling(n).mean().values

def calc_rsi(closes, period=14):
    # UÆNDRET fra v4 — simpel sum-baseret RSI
    if closes is None or len(closes)<period+1: return None
    gains=losses=0.0
    for i in range(len(closes)-period,len(closes)):
        d=closes[i]-closes[i-1]
        if d>=0: gains+=d
        else: losses+=abs(d)
    ag=gains/period; al=losses/period
    if al==0 and ag==0: return 50.0
    if al==0: return 100.0
    return 100.0-(100.0/(1.0+ag/al))

def calc_atr(highs,lows,closes,period=20):
    # UÆNDRET fra v4
    if highs is None or len(highs)<period+1: return None
    trs=[max(highs[i]-lows[i],abs(highs[i]-closes[i-1]),abs(lows[i]-closes[i-1])) for i in range(1,len(highs))]
    if len(trs)<period: return None
    return float(np.mean(trs[-period:]))

def calc_ibd_rs_raw(c):
    """IBD-style vægtet relative-strength på 252-handelsdages basis.
    Vægte: 40/20/20/20 for seneste til ældste kvartal (standard IBD)."""
    n = len(c)
    if n < 200: return None
    try:
        q4 = c[-1]   / c[-64]  - 1 if n >= 64  else 0
        q3 = c[-64]  / c[-127] - 1 if n >= 127 else 0
        q2 = c[-127] / c[-189] - 1 if n >= 189 else 0
        q1 = c[-189] / c[-min(252,n)] - 1 if n >= 190 else 0
        return q4*0.40 + q3*0.20 + q2*0.20 + q1*0.20
    except Exception:
        return None

def weinstein_stage(c, s200_series):
    """Stage klassifikation:
       1=accumulation base, 2=advancing (pris>SMA200, SMA200 stigende),
       3=distribution, 4=declining. Position-tradere køber primært i Stage 2."""
    if len(c) < 210: return 0, '?'
    p = float(c[-1])
    s = s200_series[-1] if not pd.isna(s200_series[-1]) else None
    s_4w = s200_series[-20] if len(s200_series) >= 20 and not pd.isna(s200_series[-20]) else s
    if s is None or s_4w is None: return 0, '?'
    rising = s > s_4w
    if p > s and rising:     return 2, 'S2✅'
    if p > s and not rising: return 3, 'S3⚠️'
    if p < s and not rising: return 4, 'S4❌'
    return 1, 'S1🔄'

def derive_states(price,sma20,sma60,sma200,rsi,rsi_trend,low5,dist_h20,
                  vol_ratio,liq_pass,atr20,squeeze,rs_trend,higher_low,
                  inst_accum,cap_risk,trend,trend200,market_regime,
                  ifs,ls,stage_num,rs_rank):
    ts=0
    if price>sma200: ts+=24
    if sma20>sma60:  ts+=18
    if price>sma20:  ts+=10
    if rs_trend=='UP': ts+=12
    if higher_low: ts+=8
    ts+=min(10,int((ifs or 0)/10))

    tight=(atr20/price)<=0.045 if(atr20 and price>0) else False
    accum=(trend=='BUY' and trend200=='LONG TREND' and rsi is not None
           and 38<=rsi<=64 and vol_ratio is not None and vol_ratio>=0.90
           and abs((price-sma20)/sma20)<=0.06 and rs_trend in('UP','FLAT',''))
    ib=accum and(inst_accum or(ifs or 0)>=65)
    br=(trend=='BUY' and trend200=='LONG TREND' and rs_trend in('UP','FLAT','')
        and dist_h20 is not None and 0<=dist_h20<=CONFIG['breakout_distance']
        and vol_ratio is not None and 0.95<=vol_ratio<=3.0
        and rsi is not None and 44<=rsi<=78
        and(squeeze or(dist_h20 is not None and dist_h20<=0.03)))
    ma=(br and vol_ratio is not None and vol_ratio>=1.10
        and rsi is not None and 50<=rsi<=80 and liq_pass and market_regime!='RISK_OFF')
    ext=(rsi is not None and rsi>84) or price>sma20*1.14
    w1=price<sma20; w2=sma20<sma60; w3=price<sma200; w4=rs_trend=='DOWN'
    wc=sum([w1,w2,w3,w4])
    wk=wc>=2 or(price<sma20 and rs_trend=='DOWN')
    fs=wc>=3 and((rsi is not None and rsi<42) or price<low5)

    # ── ENESTE AFTALTE NYHED: Stage 2 hard filter ──
    if stage_num != 2:
        accum = ib = br = ma = False

    ss=0
    if accum: ss+=20
    if tight: ss+=6
    if ib:    ss+=18
    if br:    ss+=22
    if ma:    ss+=16
    if squeeze: ss+=6
    if rsi is not None and 46<=rsi<=72: ss+=6
    if dist_h20 is not None and dist_h20<=0.07: ss+=6
    if vol_ratio is not None and vol_ratio>=0.95: ss+=6
    ss+=min(10,int((ls or 0)/10))

    rp=0
    if not liq_pass: rp+=14
    if market_regime=='RISK_OFF': rp+=10
    if rs_trend=='DOWN': rp+=6
    if ext: rp+=8
    if cap_risk: rp+=6
    if wk: rp+=8
    if fs: rp+=14

    pri=max(0,min(100,ts+ss-rp))

    if fs:   st_='FAILED_SETUP'
    elif ext: st_='EXTENDED'
    elif ma:  st_='MOMENTUM_ACTIVE'
    elif br:  st_='BREAKOUT_READY'
    elif ib:  st_='INSTITUTIONAL_BUILD'
    elif accum: st_='ACCUMULATION'
    elif wk:  st_='WEAKENING'
    else:     st_='NO_SETUP'

    am={'ACCUMULATION':'STARTER','INSTITUTIONAL_BUILD':'BUILD',
        'BREAKOUT_READY':'BREAKOUT_ENTRY','MOMENTUM_ACTIVE':'MOMENTUM_ENTRY',
        'EXTENDED':'EXTENDED','WEAKENING':'REDUCE','FAILED_SETUP':'EXIT'}
    ac=am.get(st_,'WATCHLIST')
    # RISK_OFF påvirker kun score (rp+=10 ovenfor) — ikke hvilken action aktien tildeles.
    # Derved vises alle aktier korrekt i dashboardet uanset markedsregime.
    # if market_regime=='RISK_OFF' and ac in('BUILD','BREAKOUT_ENTRY','MOMENTUM_ENTRY'): ac='STARTER'

    bm={'STARTER':'STARTER BUY','BUILD':'BUILD POSITION',
        'BREAKOUT_ENTRY':'BUY BREAKOUT','MOMENTUM_ENTRY':'BUY NOW','EXTENDED':'EXTENDED — WAIT'}
    buy=bm.get(ac,'WATCHLIST')
    sell='EXIT' if ac=='EXIT' else('REDUCE' if ac=='REDUCE' else 'HOLD')

    stop=round(sma20,2)
    if st_=='MOMENTUM_ACTIVE' and atr20: stop=round(max(low5,price-1.5*atr20),2)
    elif st_=='INSTITUTIONAL_BUILD' and atr20: stop=round(max(low5,sma20-0.5*atr20),2)

    # Stop må aldrig ligge over (eller på) aktuel pris — sammenlign på 2 decimaler
    # for at undgå floating point edge cases (f.eks. stop=1.71, pris=1.7100001)
    if stop is not None and price is not None and round(stop, 4) >= round(price, 4):
        stop = None

    return {'ts':ts,'ss':ss,'rp':rp,'score':pri,'setup':st_,'action':ac,
            'buy':buy,'sell':sell,'stop':stop}

def ticker_is_gbp_pence(ticker: str) -> bool:
    """LSE-aktier (.L) handles typisk i pence — yfinance returnerer rå pris i GBp."""
    return ticker.endswith('.L')

def to_usd(price_local, region, ticker, fx_rates):
    """Konvertér lokalpris til USD. GBp behandles som rå lokal valuta uden konvertering."""
    if price_local is None or price_local <= 0:
        return 0.0
    cur = CURRENCY_BY_REGION.get(region, 'USD')
    rate = fx_rates.get(cur, 1.0)
    return price_local * rate

# ════════════════════════════════════════════════════════════════════
# compute_scan — den eksakte per-ticker-loop løftet ordret fra
# fetch_scanner_data i scanner_v7.py. Tager FÆRDIGT hentet OHLCV-data
# (all_raw) og returnerer (df_out, dropped_reasons). Ingen netværk her.
# ════════════════════════════════════════════════════════════════════
def compute_scan(all_raw, universe, fx_rates, market_regime='NEUTRAL'):
    info_map = {t[0]: t for t in universe}
    results = []
    # 4) Sikkerhedsfilter: drop kun DataFrames der mangler 'Close' — ingen min-historik her.
    # Aktier med kort historik inkluderes stadig i universet (med begrænsede indikatorer).
    all_raw = {t: df for t, df in all_raw.items()
               if df is not None and 'Close' in df.columns and len(df) >= 1}

    # 5) IBD RS raw + percentile rank på tværs af hele universet
    rs_raws = {t: calc_ibd_rs_raw(df['Close'].squeeze().values) for t, df in all_raw.items()}
    valid_rs = {}
    for k, v in rs_raws.items():
        if v is None:
            continue
        # Sikr at værdien er en scalar — ikke en array
        try:
            valid_rs[k] = float(np.squeeze(v))
        except Exception:
            pass
    rs_ranks=pd.Series(valid_rs).rank(pct=True).multiply(99).round(0).astype(int) if valid_rs else pd.Series()

    # Track hvorfor tickere bliver droppet i per-ticker indikator-loopet
    dropped_reasons = []   # liste af (ticker, årsag)

    for ticker,df in all_raw.items():
        try:
            info=info_map.get(ticker,(ticker,ticker,'Unknown','Unknown','CORE'))
            # Sikkerhedscheck — disse skulle aldrig fejle her, men hvis de gør, log årsagen
            if 'Close' not in df.columns:
                dropped_reasons.append((ticker, "mangler 'Close' kolonne efter normalisering"))
                continue
            c=df['Close'].squeeze().values; h=df['High'].squeeze().values
            l=df['Low'].squeeze().values;   v=df['Volume'].squeeze().values
            n=len(c)
            if n<20:
                dropped_reasons.append((ticker, f"kun {n} dages historik (kræver minimum 20)"))
                continue
            price=float(c[-1])
            if price<=0 or price>1_000_000:
                dropped_reasons.append((ticker, f"pris uden for range: {price}"))
                continue
            prev=float(c[-2])
            dpct=(price/prev-1)*100 if prev>0 else 0
            if abs(dpct)>50: dpct=0

            sma20v=sma(c,20); sma60v=sma(c,60); sma200v=sma(c,200)
            if any(x is None for x in [sma20v,sma60v,sma200v]):
                dropped_reasons.append((ticker, "SMA-beregning returnerede None (NaN i data?)"))
                continue
            # NaN-check på de kritiske værdier — Yahoo's danske data er ofte NaN-spækket
            if any(pd.isna(x) for x in [sma20v,sma60v,sma200v,price,prev]):
                dropped_reasons.append((ticker, "NaN i SMA eller pris (Yahoo data-kvalitet)"))
                continue
            rsiv=calc_rsi(c,14)
            atr5v=calc_atr(h,l,c,5); atr20v=calc_atr(h,l,c,20)
            high20=float(np.max(c[-20:]))
            low5v=float(np.min(l[-5:])); low20v=float(np.min(l[-20:]))
            avg_v20=float(np.mean(v[-20:])); avg_v50=float(np.mean(v[-50:])) if n>=50 else avg_v20
            last_vol=float(v[-1])
            volr=last_vol/avg_v20 if avg_v20>0 else None
            rvol50=last_vol/avg_v50 if avg_v50>0 else None

            # ── FX-NORMALISERET DOLLAR VOLUME ──
            region = info[3] if len(info)>3 else 'US'
            currency = CURRENCY_BY_REGION.get(region, 'USD')
            fx_rate = fx_rates.get(currency, 1.0) if fx_rates else 1.0
            dolvol = avg_v20 * price            # lokal valuta
            dolvol_usd = dolvol * fx_rate       # USD — bruges til filtre og scoring
            dist_h20=(high20-price)/high20 if high20>0 else None
            hl=low5v>low20v
            lp=avg_v20>=CONFIG['min_avg_vol'] and dolvol_usd>=CONFIG['min_dollar_vol']
            cap_r=dolvol_usd<25_000_000
            sqz=bool(atr5v and atr20v and atr5v<atr20v*CONFIG['squeeze_factor'])
            rsi_prev5=calc_rsi(c[:-5],14) if n>19 else rsiv
            rsi_t='UP' if(rsiv and rsi_prev5 and rsiv>rsi_prev5) else('DOWN' if(rsiv and rsi_prev5 and rsiv<rsi_prev5) else 'FLAT')

            # ── RS TREND MOD LOKALT INDEKS ──
            local_idx = REGION_INDEX.get(region, 'SPY')
            # Brug lokalt indeks hvis det er i all_raw, ellers SPY, ellers FLAT
            # Eksplicit None-check — 'DataFrame or X' kaster ValueError
            ref_df = all_raw.get(local_idx)
            if ref_df is None:
                ref_df = all_raw.get('SPY')
            if ref_df is not None:
                ref_closes = ref_df['Close'].squeeze().values
                if len(ref_closes)>=21 and n>=21:
                    ref_now  = float(ref_closes[-1])
                    ref_past = float(ref_closes[-21])
                    if ref_now>0 and ref_past>0:
                        rs_now  = price / ref_now
                        rs_past = float(c[-21]) / ref_past
                        rs_t = 'UP' if rs_now>rs_past else('DOWN' if rs_now<rs_past else 'FLAT')
                    else: rs_t='FLAT'
                else: rs_t='FLAT'
            else: rs_t='FLAT'

            trend='BUY' if sma20v>sma60v else('SELL' if sma20v<sma60v else 'HOLD')
            trend200='LONG TREND' if price>sma200v else 'WEAK LONG TREND'

            ia=(trend=='BUY' and trend200=='LONG TREND' and rsiv is not None
                and 40<=rsiv<=64 and rs_t in('UP','FLAT') and rsi_t in('UP','FLAT')
                and volr is not None and volr>=0.95 and hl and dist_h20 is not None and dist_h20<=0.10)

            ifs=0
            if volr and volr>1.15: ifs+=20
            if hl: ifs+=20
            if rs_t=='UP': ifs+=20
            if price>sma20v: ifs+=20
            if rsiv and 42<=rsiv<=68: ifs+=20
            if trend200=='LONG TREND': ifs+=10
            if ia: ifs+=10
            ifs=min(ifs,100)

            ls=0
            if avg_v20>=5_000_000: ls+=40
            elif avg_v20>=1_000_000: ls+=25
            elif avg_v20>=200_000: ls+=12
            if dolvol_usd>=100_000_000: ls+=30
            elif dolvol_usd>=30_000_000: ls+=20
            elif dolvol_usd>=8_000_000: ls+=10
            if volr and volr>=1.0: ls+=20
            if not cap_r: ls+=10
            ls=min(ls,100)

            # Vektoriseret SMA200-serie — O(N), ikke O(N²) som i v4
            s200arr = rolling_sma(c, 200)
            stn,stl=weinstein_stage(c,s200arr)
            rs_rank=int(rs_ranks.get(ticker,0)) if ticker in rs_ranks.index else 0
            w52h=float(np.max(c[-252:])) if n>=252 else float(np.max(c))
            w52l=float(np.min(c[-252:])) if n>=252 else float(np.min(c))
            atr_pct=atr20v/price*100 if(atr20v and price>0) else 0

            # v5: stn og rs_rank sendes ind for Stage 2 hard filter + RS-bonus
            sigres=derive_states(price,sma20v,sma60v,sma200v,rsiv,rsi_t,low5v,dist_h20,
                             volr,lp,atr20v,sqz,rs_t,hl,ia,cap_r,trend,trend200,
                             market_regime,ifs,ls,stn,rs_rank)
            results.append({
                'ticker':ticker,'name':info[1],'sector':info[2],'region':info[3],'tier':info[4] if len(info)>4 else 'CORE',
                'price':round(price,2),'dpct':round(dpct,1),
                'rsi':round(rsiv,1) if rsiv else None,'rsi_t':rsi_t,
                'sma20':round(sma20v,2),'sma60':round(sma60v,2),'sma200':round(sma200v,2),
                'trend':trend,'trend200':trend200,
                'high20':round(high20,2),'low5':round(low5v,2),
                'dh20':round(dist_h20*100,1) if dist_h20 is not None else None,
                'volr':round(volr,2) if volr else None,'rvol50':round(rvol50,2) if rvol50 else None,
                'avgvol':round(avg_v20,0),'dolvol_m':round(dolvol/1e6,1),
                'liq':'✅' if lp else '❌','lp':lp,
                'atr20':round(atr20v,2) if atr20v else None,'atr_pct':round(atr_pct,1),
                'sqz':'⚡' if sqz else '—','sqz_b':sqz,
                'rs_t':rs_t,'hl':'✅' if hl else '—','ia':'✅' if ia else '—','cap':'⚠️' if cap_r else '—',
                'ifs':ifs,'ls':ls,'stn':stn,'stage':stl,'rs_rank':rs_rank,
                'w52h':round(w52h,2),'w52l':round(w52l,2),
                'dist52':round((w52h-price)/w52h*100,1) if w52h>0 else 0,
                'ts':sigres['ts'],'ss':sigres['ss'],'rp':sigres['rp'],'score':sigres['score'],
                'setup':sigres['setup'],'buy':sigres['buy'],'sell':sigres['sell'],'stop':sigres['stop'],
                'dolvol_usd_m':round(dolvol_usd/1e6,1),'currency':currency,
                'spark':[round(float(x),2) for x in c[-40:]],   # mini-chart data til forsiden
            })
        except Exception as e:
            # Log den faktiske exception så vi kan se hvilke tickere fejler hvorfor
            dropped_reasons.append((ticker, f"{type(e).__name__}: {str(e)[:120]}"))
            continue

    df_out=pd.DataFrame(results)
    if not df_out.empty:
        df_out=df_out.sort_values('score',ascending=False).reset_index(drop=True)

    return df_out, dropped_reasons


# ════════════════════════════════════════════════════════════════════
# FASE 2: REGIME + MARKEDSDATA (streamlit-fri) — sa workeren beregner
# samme regime som UI'et. derive_regime er kopieret 1:1 fra scanner_v7.
# ════════════════════════════════════════════════════════════════════
def fetch_market_data_live(yf_module, tickers=('SPY', 'QQQ', 'IWM', '^VIX')):
    """Minimal markedsdata til regime-beregning. Samme per-ticker matematik
    som UI'ets fetch_market_data, men kun de tickere derive_regime bruger."""
    rows = {}
    if yf_module is None:
        return rows
    all_tickers = list(tickers)
    try:
        raw = yf_module.download(all_tickers, period='6mo', interval='1d',
                                 group_by='ticker', auto_adjust=True, progress=False)
        for t in all_tickers:
            try:
                df = (raw[t] if len(all_tickers) > 1 else raw).dropna()
                if len(df) < 5:
                    continue
                c = df['Close'].squeeze().values
                p = float(c[-1]); prev = float(c[-2])
                d5 = float(c[-6]) if len(c) > 5 else prev
                d30 = float(c[-31]) if len(c) > 30 else prev
                pct1 = round((p / prev - 1) * 100, 1) if prev > 0 else 0
                pct5 = round((p / d5 - 1) * 100, 1) if d5 > 0 else 0
                pct30 = round((p / d30 - 1) * 100, 1) if d30 > 0 else 0
                s20 = float(np.mean(c[-20:])) if len(c) >= 20 else p
                s60 = float(np.mean(c[-60:])) if len(c) >= 60 else p
                trend = 'UP' if p > s20 > s60 else ('DOWN' if p < s20 < s60 else 'MIX')
                rows[t] = {'price': round(p, 2), 'pct1': pct1, 'pct5': pct5,
                           'pct30': pct30, 'trend': trend}
            except Exception:
                pass
    except Exception:
        pass
    return rows


def derive_regime(mkt,scan):
    """
    Forbedret regime-beregning:
    - Bruger BÅDE 6M trend OG daglig bevægelse
    - VIX niveau + VIX retning (faldende VIX = bullish)
    - Breadth fra scanneren
    - Kortsigtede momentum signaler
    """
    score=0
    if mkt:
        # Index trend (6M) – men vægter lavere nu
        for t,pts in [('SPY',1),('QQQ',1),('IWM',1)]:
            if t in mkt:
                tr=mkt[t]['trend']
                score+=pts if tr=='UP' else(-pts if tr=='DOWN' else 0)

        # Daglig bevægelse – er markedet grønt I DAG?
        for t,pts in [('SPY',2),('QQQ',1),('IWM',1)]:
            if t in mkt:
                pct=mkt[t].get('pct1',0) or 0
                score+=pts if pct>0.5 else(-pts if pct<-0.5 else 0)

        # 5-dages momentum
        for t,pts in [('SPY',1),('QQQ',1)]:
            if t in mkt:
                pct5=mkt[t].get('pct5',0) or 0
                score+=pts if pct5>1.0 else(-pts if pct5<-2.0 else 0)

        # VIX niveau
        if '^VIX' in mkt:
            v=mkt['^VIX']['price']
            score+=-3 if v>35 else(-2 if v>28 else(-1 if v>22 else(1 if v<18 else(2 if v<15 else 0))))

        # VIX retning – faldende VIX er bullish
        if '^VIX' in mkt:
            vix_pct=mkt['^VIX'].get('pct1',0) or 0
            score+=2 if vix_pct<-5 else(1 if vix_pct<-2 else(-1 if vix_pct>5 else 0))

    if not scan.empty:
        total=max(len(scan),1)
        a20=(scan['price']>scan['sma20']).sum()/total
        a200=(scan['price']>scan['sma200']).sum()/total
        score+=2 if a20>=0.55 else(-2 if a20<0.40 else 0)
        score+=2 if a200>=0.50 else(-2 if a200<0.35 else 0)
        buys=scan['buy'].isin(['BUY NOW','BUY BREAKOUT','STARTER BUY','BUILD POSITION']).sum()
        score+=1 if buys>=5 else(-1 if buys==0 else 0)

    if score>=6: return 'RISK_ON'
    if score<=0: return 'RISK_OFF'
    return 'NEUTRAL'
