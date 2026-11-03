#!/usr/bin/env python3
"""Oro pavojus · Baltija — surinkėjas.

Tikrina oficialius šaltinius ir rašo alerts.json (repo šaknyje).
Tik standartinė Python biblioteka — veikia GitHub Actions, Termux, bet kur.

    python3 collector/collector.py            # rašo ./alerts.json
    python3 collector/collector.py --print    # tik parodo

Kiekvienas šaltinis izoliuotas: jei vienas lūžta, kiti veikia, o klaida
įrašoma į _meta.sources. Šalies lygis = didžiausias iš jos šaltinių.
Jei visi šalies šaltiniai neveikė → level "none" (Nenustatyta).
"""
from __future__ import annotations

import html
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

UA = "air-alert-map/0.1 (+https://github.com/arturas098/air-alert-map)"
TIMEOUT = 20
NOW = datetime.now(timezone.utc)
RANK = {"none": 0, "white": 1, "yellow": 2, "red": 3}

COUNTRIES = ["LTU", "LVA", "EST", "FIN", "POL"]
METEOALARM = {
    "LTU": "lithuania", "LVA": "latvia", "EST": "estonia",
    "FIN": "finland", "POL": "poland",
}


# ---------------------------------------------------------------- helpers
def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        raw = r.read()
        cs = r.headers.get_content_charset() or "utf-8"
    return raw.decode(cs, errors="replace")


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def child_text(el, name: str) -> str:
    for c in el:
        if local(c.tag) == name:
            return (c.text or "").strip()
    return ""


def parse_dt(s: str) -> datetime | None:
    if not s:
        return None
    s = s.strip().replace("Z", "+00:00")
    for fmt in (None, "%a, %d %b %Y %H:%M:%S %z", "%d.%m.%Y"):
        try:
            d = datetime.fromisoformat(s) if fmt is None else datetime.strptime(s, fmt)
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def strip_tags(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


class Alert(dict):
    """{level, kind, text, time, url, src}"""


# ---------------------------------------------------------------- MeteoAlarm (orai, visos šalys)
# Jūros / uostų zonos – nedažom visos šalies dėl įspėjimo jūroje
MARINE = re.compile(r"baltic|gulf|port of|lagoon|marios|marių|\bbay\b|\bsea\b|coastal waters|"
                    r"meri\b|meren|kurkku|lahti\b|lahden|\bosa\b|saaristomeri|väinameri|moonsund|archipelago|"
                    r"\blaht\b|jūras|līcis|zatok|morze|morsk|offshore|harbour|harbor|\blake\b|järv|peipsi|ežer|ezers|jezior", re.I)
def meteoalarm(country_slug: str) -> list[Alert]:
    xml = fetch(f"https://feeds.meteoalarm.org/feeds/meteoalarm-legacy-atom-{country_slug}")
    root = ET.fromstring(xml)
    out: list[Alert] = []
    for e in root:
        if local(e.tag) != "entry":
            continue
        expires = parse_dt(child_text(e, "expires"))
        onset = parse_dt(child_text(e, "onset")) or parse_dt(child_text(e, "effective"))
        if expires and expires < NOW:
            continue
        if onset and onset > NOW + timedelta(hours=12):   # tik artimiausios 12 h
            continue
        aw = child_text(e, "awareness_level").lower()       # pvz. "2; yellow; Moderate"
        sev = child_text(e, "severity").lower()
        if "red" in aw or sev == "extreme":
            level = "red"
        elif "orange" in aw or sev == "severe":
            level = "red"
        elif "yellow" in aw or sev == "moderate":
            level = "yellow"
        else:
            continue
        event = child_text(e, "event") or child_text(e, "title")
        area = child_text(e, "areaDesc")
        if MARINE.search(area) or "coastal" in child_text(e, "awareness_type").lower():
            continue
        link = ""
        for c in e:
            if local(c.tag) == "link" and c.get("href"):
                link = c.get("href"); break
        expires_s = expires.isoformat() if expires else ""
        out.append(Alert(level=level, kind="weather",
                         text=f"{event} — {area}".strip(" —"), event=event, area=area,
                         severity=child_text(e, "severity"), expires=expires_s,
                         time=(onset or NOW).isoformat(), url=link, src="MeteoAlarm"))
    return out


# ---------------------------------------------------------------- Lenkija: Alert RCB (gov.pl)
# Sąraše (komunikaty) yra tik pavadinimas ir data, todėl skaitom patį straipsnį:
#  - galiojantis statusas = paskutinis pranešimas gijoje (jei po pavojaus yra „zakończył się…“ /
#    „brak zagrożenia“ / „odwołanie“ → pavojus baigtas),
#  - laikas iš teksto (HH:MM), sritys – iš vaivadijų / apskričių pavadinimų tekste.
# Jei pabaigos pranešimo nėra, oro pavojus laikomas pasibaigusiu po RCB_MAX_H valandų.
RCB_AIR = re.compile(r"powietrz|atak|dron|rakiet|lotnictw|obron", re.I)
RCB_SKIP = re.compile(r"trening|ćwicz|cwicz|\btest", re.I)
RCB_END = re.compile(r"odwoł|odwol|zakończ|zakoncz|brak zagro|zagrożenie minęło|koniec zagro", re.I)
RCB_START = re.compile(r"uwaga|zagroż|zagroz|atak|ostrzeg|podwyższ|podwyzsz|gotowoś|gotowos|śledź|sledz", re.I)
RCB_TIME = re.compile(r"(?<![\d.])([01]?\d|2[0-3]):([0-5]\d)(?![\d])")
RCB_MAX_H = 4


def rcb_ended(body: str) -> bool:
    """Ar paskutinis gijos pranešimas yra pabaiga? Pradžios žodžiai pačiame pabaigos sakinyje
    (pvz. „brak zagrożenia“) neskaičiuojami."""
    ends = [m.start() for m in RCB_END.finditer(body)]
    if not ends:
        return False
    starts = [m.start() for m in RCB_START.finditer(body)
              if not any(e - 60 <= m.start() <= e + 80 for e in ends)]
    return not starts or max(ends) > max(starts)


def rcb_article(url: str) -> str:
    page = fetch(url)
    m = re.search(r"<article.*?</article>", page, re.S) or re.search(r'class="editor-content".*?</div>\s*</div>', page, re.S)
    return strip_tags(m.group(0) if m else page)


def rcb() -> list[Alert]:
    from zoneinfo import ZoneInfo
    WAW = ZoneInfo("Europe/Warsaw")
    page = fetch("https://www.gov.pl/web/rcb/komunikaty")
    items = []
    for m in re.finditer(r'href="(/web/rcb/[^"]+)"[^>]*>(.*?)</a>', page, re.S):
        title = strip_tags(m.group(2))
        if not title.lower().startswith("alert rcb"):
            continue
        before = page[max(0, m.start() - 600):m.start()]
        dates = re.findall(r"(\d{2}\.\d{2}\.\d{4})", before)
        d = parse_dt(dates[-1]) if dates else None
        items.append((d.date() if d else None, title, "https://www.gov.pl" + m.group(1)))
    today = NOW.astimezone(WAW).date()
    out: list[Alert] = []
    for d, title, url in items:                       # naujausi pirmi
        if not d or (today - d).days > 1:             # šiandien arba vakar (po vidurnakčio)
            break
        if RCB_SKIP.search(title):
            continue
        if RCB_END.search(title):
            break                                     # naujesnis atšaukimas – senesni nebegalioja
        body = ""
        try:
            body = rcb_article(url)
        except Exception:                             # noqa: BLE001 – be straipsnio: tik pavadinimas
            pass
        text = f"{title} {body}"
        # paskutinis pranešimas gijoje: ar pabaiga eina po paskutinio pavojaus pranešimo?
        if rcb_ended(body):
            continue                                  # paskutinis pranešimas – atšaukimas
        kind = "air" if RCB_AIR.search(text) else "weather" if re.search(
            r"burz|wiatr|deszcz|upał|upal|śnieg|snieg|mróz|mroz|powód|powod|oblodz|ulew", text, re.I) else "other"
        times = [(int(h), int(mi)) for h, mi in RCB_TIME.findall(body)]
        onset = None
        if times:
            h, mi = times[0]
            onset = datetime(d.year, d.month, d.day, h, mi, tzinfo=WAW).astimezone(timezone.utc)
            if onset > NOW + timedelta(minutes=10):  # laikas iš vakar dienos
                onset -= timedelta(days=1)
        if kind == "air":
            if onset and NOW - onset > timedelta(hours=RCB_MAX_H):
                continue
            if not onset and d < today:
                continue
        elif d < today:
            continue
        regions = sorted(match_regions("POL", text))
        names = [next((n.split(" ", 1)[1] for n in r["names"] if n.lower().startswith("województwo ")), r["name"])
                 for r in REGIONS if r["iso"] in regions]
        out.append(Alert(level="yellow", kind=kind, text=title, event="Alert RCB",
                         area=("Województwa: " + ", ".join(names)) if names else title,
                         time=(onset.isoformat() if onset else datetime(d.year, d.month, d.day, tzinfo=WAW).isoformat()),
                         dateOnly=not onset,
                         expires=(onset + timedelta(hours=RCB_MAX_H)).isoformat() if (onset and kind == "air") else "",
                         url=url, src="Alert RCB", regionsHint=regions))
        break
    return out


# ---------------------------------------------------------------- Lietuva: lt72.lt (PAGD)
LT_RED = re.compile(r"ORO PAVOJUS \(RAUDONA\)|ORO PAVOJUS RAUDONA", re.I)
LT_YEL = re.compile(r"TIKĖTINAS ORO PAVOJUS|GELTONA PO RAUDONOS|\(GELTONA\)", re.I)
LT_END = re.compile(r"atšaukt|atsaukt|pavojus baigėsi|baigėsi", re.I)


def lt72() -> list[Alert]:
    """WordPress RSS. Naujausias įrašas per 6 h, jei ne atšaukimas."""
    xml = fetch("https://lt72.lt/feed/")
    root = ET.fromstring(xml)
    out: list[Alert] = []
    for it in root.iter("item"):
        title = child_text(it, "title")
        desc = strip_tags(child_text(it, "description"))
        d = parse_dt(child_text(it, "pubDate"))
        cats = " ".join((c.text or "") for c in it if local(c.tag) == "category").lower()
        if not d or NOW - d > timedelta(hours=6):
            continue
        if "perspėjimo pranešimai" not in cats and "perspejimo" not in cats and not LT_YEL.search(title + desc) and not LT_RED.search(title + desc):
            continue
        blob = f"{title} {desc}"
        if LT_END.search(blob):
            break
        if LT_RED.search(blob):
            lv, kind = "red", "air"
        elif LT_YEL.search(blob):
            lv, kind = "yellow", "air"
        else:
            lv, kind = "yellow", "other"
        out.append(Alert(level=lv, kind=kind, text=title, time=d.isoformat(),
                         url=child_text(it, "link"), src="lt72.lt (PAGD)"))
        break
    return out


# ---------------------------------------------------------------- Latvija: NBS pranešimai (lvportals.lv)
# Nacionālie bruņotie spēki kiekvieną „Iespējams apdraudējums Latvijas gaisa telpā … novados;
# informācija D. mēneša plkst. HH.MM“ skelbia valstybiniame portale LV portāls (VSIA Latvijas Vēstnesis).
LV_MONTHS = {"janvār": 1, "februār": 2, "mart": 3, "aprīl": 4, "maij": 5, "jūnij": 6, "jūlij": 7,
             "august": 8, "septembr": 9, "oktobr": 10, "novembr": 11, "decembr": 12}
LV_AIR = re.compile(r"apdraudējum\w*\s+latvijas\s+gaisa\s+telp", re.I)
LV_END = re.compile(r"beidzies|beigas|atcelt|vairs nav|nav apdraudējuma", re.I)
LV_MAX_H = 4


def lv_when(title: str) -> datetime | None:
    from zoneinfo import ZoneInfo
    m = re.search(r"(\d{1,2})\.\s*([a-zāčēģīķļņšūž]+)\s+plkst\.?\s*(\d{1,2})[.:](\d{2})", title, re.I)
    if not m:
        return None
    mon = next((v for k, v in LV_MONTHS.items() if m.group(2).lower().startswith(k)), None)
    if not mon:
        return None
    riga = ZoneInfo("Europe/Riga")
    yr = NOW.astimezone(riga).year
    d = datetime(yr, mon, int(m.group(1)), int(m.group(3)), int(m.group(4)), tzinfo=riga)
    if d > NOW + timedelta(days=1):
        d = d.replace(year=yr - 1)
    return d.astimezone(timezone.utc)


def lv_nbs() -> list[Alert]:
    page = fetch("https://lvportals.lv/dienaskartiba/visas-preses-relizes/autors:4462")
    seen = 0
    for m in re.finditer(r'href="(/dienaskartiba/\d+[^"]*)"[^>]*>(.*?)</a>', page, re.S):
        title = strip_tags(m.group(2))
        if not LV_AIR.search(title) and not (LV_END.search(title) and "gaisa" in title.lower()):
            continue
        seen += 1
        when = lv_when(title)
        if not when or NOW - when > timedelta(hours=LV_MAX_H):
            return []                        # naujausias pranešimas senas → aktyvaus pavojaus nėra
        if LV_END.search(title):
            return []                        # naujausias – pabaiga
        red = re.search(r"konstatēts|tūlītēj|patver|oranž", title, re.I)
        url = "https://lvportals.lv" + m.group(1)
        return [Alert(level="red" if red else "yellow", kind="air", event="Iespējams apdraudējums gaisa telpā",
                      area=title, text=title, time=when.isoformat(),
                      expires=(when + timedelta(hours=LV_MAX_H)).isoformat(), url=url, src="NBS · lvportals.lv")]
    if not seen and "dienaskartiba" not in page:
        raise ValueError("puslapio struktūra neatpažinta")
    return []


# ---------------------------------------------------------------- Lietuva: LRT (žiniasklaida, papildomas)
LRT_FEEDS = ["https://www.lrt.lt/?rss", "https://www.lrt.lt/naujienos/lietuvoje?rss", "https://www.lrt.lt/rss"]
LRT_END = re.compile(r"atšauk|atsauk|baigėsi|nebėra", re.I)


def lrt() -> list[Alert]:
    last_err = None
    for u in LRT_FEEDS:
        try:
            root = ET.fromstring(fetch(u))
            break
        except Exception as ex:  # noqa: BLE001
            last_err = ex
    else:
        raise RuntimeError(f"LRT RSS nepasiekiamas: {last_err}")
    for it in root.iter("item"):
        title = child_text(it, "title")
        desc = strip_tags(child_text(it, "description"))
        d = parse_dt(child_text(it, "pubDate"))
        blob = f"{title} {desc}"
        if not re.search(r"oro pavoj", blob, re.I):
            continue
        if not d or NOW - d > timedelta(hours=3):
            return []
        if LRT_END.search(title):
            return []
        lv = "red" if LT_RED.search(blob) or re.search(r"raudon|eikite į priedang", blob, re.I) else "yellow"
        return [Alert(level=lv, kind="air", event="Oro pavojus (pagal LRT)", area=title, text=title,
                      time=d.isoformat(), expires=(d + timedelta(hours=3)).isoformat(),
                      url=child_text(it, "link"), src="LRT (žiniasklaida)")]
    return []


# ---------------------------------------------------------------- Estija: kriis.ee RSS
EE_HIT = re.compile(r"EE-ALARM|ohuteav|public warning|threat alert|varju|shelter", re.I)
EE_SKIP = re.compile(r"\btest|katseta|exercise|õppus", re.I)


def kriis() -> list[Alert]:
    xml = fetch("https://kriis.ee/en/rss-feeds/rss.xml")
    root = ET.fromstring(xml)
    out: list[Alert] = []
    for it in root.iter("item"):
        title = child_text(it, "title")
        d = parse_dt(child_text(it, "pubDate"))
        if not d or NOW - d > timedelta(hours=6):
            continue
        if EE_HIT.search(title) and not EE_SKIP.search(title):
            kind = "air" if re.search(r"air|drone|õhu|droon", title, re.I) else "other"
            out.append(Alert(level="yellow", kind=kind, text=title, time=d.isoformat(),
                             url=child_text(it, "link"), src="kriis.ee"))
            break
    return out



# ---------------------------------------------------------------- Ukraina (sričių lygiu)
# Oficialūs: api.ukrainealarm.com (Mincifra + Ajax, „Повітряна тривога“), alerts.in.ua.
# Abiem reikia nemokamo rakto → GitHub Secrets UKRAINEALARM_KEY / ALERTS_IN_UA_TOKEN.
# Be rakto: ubilling.net.ua/aerialalerts (viešas agregatorius, NEoficialus).
import os
UA_ISO = {
    "автономна республіка крим": "UA-43", "крим": "UA-43", "ар крим": "UA-43", "республіка крим": "UA-43",
    "автономна республіка крим (арк)": "UA-43", "арк": "UA-43", "м. київ (київ)": "UA-30", "київ місто": "UA-30", "волинська область": "UA-07",
    "вінницька область": "UA-05", "дніпропетровська область": "UA-12", "донецька область": "UA-14",
    "житомирська область": "UA-18", "закарпатська область": "UA-21", "запорізька область": "UA-23",
    "івано-франківська область": "UA-26", "м. київ": "UA-30", "київ": "UA-30", "київська область": "UA-32",
    "кіровоградська область": "UA-35", "луганська область": "UA-09", "львівська область": "UA-46",
    "миколаївська область": "UA-48", "одеська область": "UA-51", "полтавська область": "UA-53",
    "рівненська область": "UA-56", "м. севастополь": "UA-40", "севастополь": "UA-40",
    "сумська область": "UA-59", "тернопільська область": "UA-61", "харківська область": "UA-63",
    "херсонська область": "UA-65", "хмельницька область": "UA-68", "черкаська область": "UA-71",
    "чернівецька область": "UA-77", "чернігівська область": "UA-74",
}
# alerts.in.ua /iot/active_air_raid_alerts_by_oblast.json grąžina 27 simbolių eilutę šia tvarka
AIU_ORDER = ["UA-43","UA-07","UA-05","UA-12","UA-14","UA-18","UA-21","UA-23","UA-26","UA-30","UA-32",
             "UA-35","UA-09","UA-46","UA-48","UA-51","UA-53","UA-56","UA-40","UA-59","UA-61","UA-63",
             "UA-65","UA-68","UA-71","UA-77","UA-74"]


UA_UNMATCHED: list[str] = []


def ua_iso(name: str) -> str | None:
    n = re.sub(r"\s+", " ", (name or "").strip().lower()).replace("’", "'").replace("ʼ", "'")
    n = n.replace("м.", "м. ").replace("  ", " ")
    iso = UA_ISO.get(n) or UA_ISO.get(n.replace("м. ", "")) or (
        "UA-43" if "крим" in n else "UA-40" if "севастоп" in n else None)
    if not iso and name and name not in UA_UNMATCHED:
        UA_UNMATCHED.append(name)
    return iso


def fetch_json(url: str, headers: dict | None = None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def ua_ukrainealarm() -> dict[str, bool]:
    key = os.environ.get("UKRAINEALARM_KEY")
    if not key:
        raise RuntimeError("nėra UKRAINEALARM_KEY")
    data = fetch_json("https://api.ukrainealarm.com/api/v3/alerts", {"Authorization": key})
    out = {}
    for r in data:
        if r.get("regionType") != "State":
            continue
        iso = ua_iso(r.get("regionName", ""))
        if iso:
            out[iso] = any((a.get("type") or "").upper() == "AIR" for a in r.get("activeAlerts", [])) or bool(r.get("activeAlerts"))
    return out


def ua_alertsinua() -> dict[str, bool]:
    tok = os.environ.get("ALERTS_IN_UA_TOKEN")
    if not tok:
        raise RuntimeError("nėra ALERTS_IN_UA_TOKEN")
    req = urllib.request.Request("https://api.alerts.in.ua/v1/iot/active_air_raid_alerts_by_oblast.json",
                                 headers={"User-Agent": UA, "Authorization": f"Bearer {tok}"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        st = json.loads(r.read().decode("utf-8"))
    if not isinstance(st, str) or len(st) != len(AIU_ORDER):
        raise ValueError(f"netikėtas atsakymas: {str(st)[:60]}")
    return {iso: ch in "AP" for iso, ch in zip(AIU_ORDER, st)}


def ua_ubilling() -> dict[str, bool]:
    d = fetch_json("https://ubilling.net.ua/aerialalerts/")
    cached = parse_dt((d.get("cachedat") or "").replace(" ", "T") + "+02:00")
    # cachedat – kada agregatorius paskutinį kartą atnaujino; >3 h → nepatikima
    if cached and NOW - cached > timedelta(hours=3):
        raise RuntimeError(f"pasenę duomenys ({d.get('cachedat')})")
    out = {}
    for name, v in (d.get("states") or {}).items():
        iso = ua_iso(name)
        if iso:
            out[iso] = bool(v.get("alertnow"))
    if len(out) < 20:
        raise ValueError(f"atpažinta tik {len(out)} sričių")
    return out


UA_SOURCES = [("ukrainealarm.com", ua_ukrainealarm, True), ("alerts.in.ua", ua_alertsinua, True),
              ("ubilling.net.ua", ua_ubilling, False)]


def ukraine(meta: dict) -> dict:
    for name, fn, official in UA_SOURCES:
        t0 = time.time()
        try:
            regions = fn()
            meta["sources"][name] = {"ok": True, "n": sum(regions.values()), "of": len(regions),
                                     "ms": int((time.time() - t0) * 1000)}
            if UA_UNMATCHED:
                meta["sources"][name]["unmatched"] = UA_UNMATCHED[:10]
        except Exception as ex:  # noqa: BLE001
            meta["sources"][name] = {"ok": False, "err": f"{type(ex).__name__}: {ex}"[:200]}
            continue
        note = ""
        # Krymas (okupuota teritorija) oficialiame žemėlapyje nuolat raudonas; jei šaltinis jo
        # nepateikia – rodom nuolatinį statusą ir aiškiai pažymim, kad tai ne gyvas duomuo
        if "UA-43" not in regions:
            regions["UA-43"] = True
            note = " Krymas – nuolatinis pavojus (okupuota teritorija; šaltinis jo nepateikia)."
        on = sorted(k for k, v in regions.items() if v)
        src = name + ("" if official else " (neoficialus)")
        if on:
            return {"level": "red", "kind": "air", "regions": {k: "red" for k in on}, "regionsOnly": True,
                    "text": f"Oro pavojus {len(on)} iš {len(regions)} sričių.{note}", "time": NOW.isoformat(timespec="seconds"),
                    "src": src, "url": "https://map.ukrainealarm.com/"}
        return {"level": "white", "regions": {}, "text": "Oro pavojaus nėra nė vienoje srityje.",
                "time": NOW.isoformat(timespec="seconds"), "src": src, "url": "https://map.ukrainealarm.com/"}
    return {"level": "none", "text": "Šaltiniai šiuo metu nepasiekiami.", "time": NOW.isoformat(timespec="seconds")}

# ---------------------------------------------------------------- sritys (admin-1)
import unicodedata
REGIONS = json.loads((Path(__file__).resolve().parent.parent / "data/regions.json").read_text(encoding="utf-8"))


def norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


_ALIASES: dict[str, list[tuple[str, str]]] = {}
for _r in REGIONS:
    for _n in _r["names"]:
        _k = norm(_n)
        # bendri žodžiai, kurie nėra pavadinimas
        _k = re.sub(r"\b(wojewodztwo|voivodeship|province|county|apskritis|maakond|bezirk|okreg|woiwodschaft|"
                    r"oblast|region|lan|laani|novads)\b", " ", _k).strip()
        _k = re.sub(r"\s+", " ", _k)
        if len(_k) >= 5:
            _ALIASES.setdefault(_r["cc"], []).append((_k, _r["iso"]))
            if _r["cc"] == "POL" and re.search(r"(sk|ck)ie$", _k) and " " not in _k:
                _ALIASES[_r["cc"]].append((_k[:-2], _r["iso"]))   # lubelskie → lubelsk(iego|im|ie)


for _v in _ALIASES.values():
    _v.sort(key=lambda x: -len(x[0]))   # ilgiausi pirmi: „pohjois pohjanmaa“ prieš „pohjanmaa“


def match_regions(cc: str, text: str) -> set[str]:
    t = " " + norm(text) + " "
    found = set()
    for k, iso in _ALIASES.get(cc, []):
        if f" {k}" in t:
            found.add(iso)
            t = t.replace(f" {k}", " " + "#" * len(k))   # sunaudojam, kad trumpesnis nepersidengtų
    return found


TONE_RANK = {"teal": 1, "yellow": 2, "red": 3}


def tone(a: dict) -> str:
    return a["level"] if a.get("kind") == "air" else "teal"


# ---------------------------------------------------------------- sujungimas
# (pavadinimas, funkcija, tipas) – tipas „air“ = karinio oro pavojaus šaltinis, „weather“ = orai
SOURCES = {
    "LTU": [("lt72", lt72, "air"), ("lrt", lrt, "air")],
    "LVA": [("lv-nbs", lv_nbs, "air")],
    "EST": [("kriis", kriis, "air")],
    "POL": [("rcb", rcb, "air")],
}
for cc, slug in METEOALARM.items():
    SOURCES.setdefault(cc, []).append((f"meteoalarm-{slug}", lambda s=slug: meteoalarm(s), "weather"))

AIR_NOTE = {"none": "Viešo oro pavojaus šaltinio šiai šaliai neturime.",
            "down": "Oro pavojaus šaltinis šiuo metu neveikia."}


def collect() -> dict:
    result: dict = {}
    meta = {"checked": NOW.isoformat(timespec="seconds"), "sources": {}}
    for cc in COUNTRIES:
        alerts: list[Alert] = []
        st = {"air": [], "weather": []}            # True/False kiekvienam šaltiniui
        for name, fn, typ in SOURCES.get(cc, []):
            t0 = time.time()
            try:
                got = fn()
                alerts += got
                st[typ].append(True)
                meta["sources"][name] = {"ok": True, "n": len(got), "ms": int((time.time() - t0) * 1000), "type": typ}
            except Exception as ex:  # noqa: BLE001
                st[typ].append(False)
                meta["sources"][name] = {"ok": False, "err": f"{type(ex).__name__}: {ex}"[:200], "type": typ}
        air = "ok" if any(st["air"]) else "down" if st["air"] else "none"
        weather = "ok" if any(st["weather"]) else "down" if st["weather"] else "none"
        base = {"air": air, "weather": weather}
        for a in alerts:   # kiekvienam įspėjimui – jo sritys (sluoksnių filtrui naršyklėje)
            a["regions"] = sorted(set(a.get("regionsHint") or []) or match_regions(cc, a.get("area") or a.get("text", "")))
            a.pop("regionsHint", None)
        if alerts:
            # karas pirmiau už orus esant tam pačiam lygiui
            alerts.sort(key=lambda a: (RANK[a["level"]], a.get("kind") == "air"), reverse=True)
            top = alerts[0]
            extra = len(alerts) - 1
            text = top["text"] + (f"  (+{extra} kiti įspėjimai)" if extra else "")
            if air != "ok" and not any(a.get("kind") == "air" for a in alerts):
                text += " · Oro pavojaus būsena nenustatyta."
            result[cc] = {**base, "level": top["level"], "kind": top["kind"], "text": text,
                          "time": top["time"], "url": top.get("url", ""), "src": top["src"],
                          "dateOnly": bool(top.get("dateOnly")),
                          "items": [dict(a) for a in alerts[:15]]}
            regions: dict[str, str] = {}
            all_matched = True
            for a in alerts:
                if not a["regions"]:
                    all_matched = False
                for iso in a["regions"]:
                    if TONE_RANK[tone(a)] > TONE_RANK.get(regions.get(iso, ""), 0):
                        regions[iso] = tone(a)
            if regions:
                result[cc]["regions"] = regions
                result[cc]["regionsOnly"] = all_matched
        elif air == "ok":
            result[cc] = {**base, "level": "white", "text": "Aktyvių perspėjimų nėra.", "time": meta["checked"]}
        else:
            # oro pavojaus šaltinio nėra arba jis neveikia – NE „saugu“, o „nenustatyta“
            wtxt = " Orų įspėjimų nėra." if weather == "ok" else " Orų šaltinis irgi nepasiekiamas." if weather == "down" else ""
            result[cc] = {**base, "level": "none", "text": "Oro pavojaus būsena nenustatyta. " + AIR_NOTE[air] + wtxt,
                          "time": meta["checked"]}
    result["UKR"] = ukraine(meta)
    result["UKR"]["air"] = "ok" if result["UKR"]["level"] != "none" else "down"
    result["_meta"] = meta
    return result


def main() -> int:
    data = collect()
    out = json.dumps(data, ensure_ascii=False, indent=1)
    if "--print" in sys.argv:
        print(out); return 0
    path = Path(__file__).resolve().parent.parent / "alerts.json"
    path.write_text(out + "\n", encoding="utf-8")
    bad = [k for k, v in data["_meta"]["sources"].items() if not v["ok"]]
    print("alerts.json:", {k: v["level"] for k, v in data.items() if not k.startswith("_")},
          "| neveikia:", bad or "-")
    return 0


if __name__ == "__main__":
    sys.exit(main())
