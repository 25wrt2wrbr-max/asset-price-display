#!/usr/bin/env python3
"""Collect a broader fixed research universe, without replacing prior data.

This is a present-day selection, not a point-in-time universe. Missing symbols
and delisted securities are not counted as negative observations.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import time
from urllib.parse import quote

import forecast_collect
import server

ROOT = pathlib.Path(__file__).resolve().parent
DESTINATION = ROOT / "research" / "market-history-extended.json"
START = int(dt.datetime(1990, 1, 1, tzinfo=dt.timezone.utc).timestamp())

# Fixed lists, including the original sample, chosen before evaluating results.
EXTRA = {
    "us_equity": "ABT ABBV ACN AIG ALL AMAT AXP AMGN APD BK BKNG BLK BMY BRK-B BSX C CARR CB CI CL CMCSA COF COP CSX CVS DE DHR DUK EMR EXC F FDX GD GILD GM GS HAL HON HPQ ICE INTU ISRG KHC KMB LLY LMT LOW MDLZ MDT MET MMM MO MRK MS MU NEE NEM NOW OXY PAYX PCAR PEP PLD PM PYPL QCOM RTX SBUX SCHW SLB SO SPGI T TGT TJX TMUS TSN TXN UNP UPS USB VZ WBA WFC WM XEL AON ADI AJG ALGN ALK ATO AZO BAX BBY BDX BIIB BRO CAG CDNS CE CERN CF CHD CINF CNP CTAS CTLT CT SHW CMG CMS CNC COO CPB CPRT CRL CRWD CSGP CTVA CTRA D DAL DD DFS DG DGX DHI DOV DOW DPZ DRI DVN DXCM EA EBAY ECL ED EIX EL EQIX EQR ES ESS ETN EVRG EW EXPE FAST FANG FIS FITB FMC FOXA FRT FTNT GDDY GPC GPN GRMN GWW HAS HBAN HCA HES HIG HII HOLX HPE HRL HSIC HST HSY HUM IEX IDXX ILMN INCY IP IPG IQV IR IT ITW IVZ JCI JKHY JNJ JNPR K KEY KEYS KIM KLAC KMI KMX KR L LDOS LEG LEN LH LIN LKQ LNT LRCX LUV LVS LW LYB MA MAA MAR MAS MCD MCHP MCK MCO MGM MKC MKTX MLM MMC MNST MOS MPC MRNA MRO MSCI MTB MTCH MTD NCLH NDAQ NDSN NOC NRG NSC NTAP NTRS NUE NVAX NVR O ODFL OMC ORLY OTIS ODFL PARA PAYC PFG PGR PH PHM PKG PNC PNR PPL PRU PSX PTC PWR RCL REG REGN RF RHI RMD ROK ROL ROP ROST RSG SBAC SEE SJM SNA SNPS SRE STT STX STZ SWK SWKS SYF SYY TAP TDG TDY TER TFC TFX TMO TROW TRV TSCO TT TTWO TXT UAL UDR UHS URI VFC VLO VMC VRSK VRSN VTR VTRS VRTX VTR WAB WAT WDC WEC WELL WHR WMB WST WTW WY WYNN XOM XRAY XYL YUM ZBH ZBRA ZION ZTS".split(),
    "fund": "AGG BND SHY TIP TIPS EMB BIL IEF IEI SHV BSV BIV EDV GOVT MUB JNK DBC PDBC XLP XLY XLI XLU XLV XLB XLC XBI IBB SMH SOXX VGT VHT VFH VDE VNQ REET SCHD VYM VTV VUG VBR VB VOO IVV RSP MTUM QUAL USMV SPLV IWF IWD IJR IJH MDY VEA VWO VGK EWJ EWZ EWY INDA FXI MCHI ACWI VT URTH DIA IAU GDX GDXJ PPLT DBA CORN UNG UUP FXE FXY BITO".split(),
    "crypto": "BNB-USD TRX-USD XLM-USD XMR-USD ETC-USD EOS-USD ZEC-USD DASH-USD NEO-USD ATOM-USD ALGO-USD MATIC-USD FIL-USD UNI-USD AAVE-USD VET-USD ICP-USD SHIB-USD SAND-USD MANA-USD HBAR-USD EGLD-USD THETA-USD XTZ-USD MKR-USD COMP-USD NEAR-USD APT-USD ARB-USD OP-USD SUI-USD PEPE-USD".split(),
    "currency": "EURGBP=X EURCHF=X EURAUD=X EURCAD=X GBPJPY=X GBPCHF=X GBPAUD=X GBPCAD=X AUDJPY=X AUDCAD=X AUDCHF=X NZDJPY=X NZDCAD=X NZDCHF=X CADJPY=X CADCHF=X CHFJPY=X SGD=X HKD=X INR=X CNY=X KRW=X MXN=X BRL=X ZAR=X NOK=X SEK=X DKK=X THB=X IDR=X MYR=X TWD=X".split(),
}


def collect():
    if DESTINATION.exists():
        raise FileExistsError(f"Refusing to overwrite {DESTINATION}; archive it manually first")
    universe = {name: list(dict.fromkeys(forecast_collect.UNIVERSE[name] + symbols))
                for name, symbols in EXTRA.items()}
    symbols = {symbol: category for category, items in universe.items() for symbol in items}
    now = dt.datetime.now(dt.timezone.utc)
    urls = {symbol: f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}?period1={START}&period2={int(time.time())}&interval=1d" for symbol in symbols}
    data = {"collected_at": now.isoformat(), "source": "Yahoo Finance daily chart via Moli; close, not dividend-adjusted",
            "selection": "Fixed present-day illustrative list; not point-in-time; delisted assets generally missing",
            "universe": symbols, "missing": {}, "bars": {}, "timezones": {}, "window_months": 3}
    items = list(symbols)
    for start in range(0, len(items), 10):
        chunk = items[start:start + 10]
        try:
            answers = server.moli_batch_get([urls[s] for s in chunk])
        except server.UpstreamError as exc:
            data["missing"].update({s: str(exc) for s in chunk})
            continue
        for symbol in chunk:
            status, body = answers.get(urls[symbol], (0, ""))
            try:
                if status != 200:
                    raise ValueError(f"HTTP {status}")
                zone, rows = forecast_collect.clean(json.loads(body), now)
                data["bars"][symbol], data["timezones"][symbol] = rows, zone
            except (ValueError, KeyError, TypeError) as exc:
                data["missing"][symbol] = str(exc)
        print(f"Processed {min(start + 10, len(items))}/{len(items)}; received {len(data['bars'])}", flush=True)
    if not data["bars"]:
        raise RuntimeError("No series received; existing research file left intact")
    if DESTINATION.exists():
        raise FileExistsError(f"Refusing to overwrite {DESTINATION}; archive it manually first")
    DESTINATION.write_text(json.dumps(data, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Saved {len(data['bars'])}/{len(symbols)} histories to {DESTINATION}; missing: {data['missing']}")


if __name__ == "__main__":
    collect()
