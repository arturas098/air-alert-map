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
        link = ""
        for c in e:
            if local(c.tag) == "link" and c.get("href"):
                link = c.get("href"); break
        out.append(Alert(level=level, kind="weather",
                         text=f"{event} — {area}".strip(" —"),
                         time=(onset or NOW).isoformat(), url=link, src="MeteoAlarm"))
    return out


# ---------------------------------------------------------------- Lenkija: Alert RCB (gov.pl)
RCB_AIR = re.compile(r"powietrz|atak|dron|rakiet|lotnictw", re.I)
RCB_SKIP = re.compile(r"trening|ćwicz|cwicz|test", re.I)
RCB_END = re.compile(r"odwoł|odwol|zakończ|zakonczon|brak zagro", re.I)


def rcb() -> list[Alert]:
    page = fetch("https://www.gov.pl/web/rcb/komunikaty")
    # elementai: data dd.mm.yyyy ir nuoroda su pavadinimu "Alert RCB - ..."
    items = []
    for m in re.finditer(r'href="(/web/rcb/[^"]+)"[^>]*>(.*?)</a>', page, re.S):
        title = strip_tags(m.group(2))
        if not title.lower().startswith("alert rcb"):
            continue
        # data – artimiausia prieš nuorodą
        before = page[max(0, m.start() - 600):m.start()]
        dates = re.findall(r"(\d{2}\.\d{2}\.\d{4})", before)
        d = parse_dt(dates[-1]) if dates else None
        items.append((d, title, "https://www.gov.pl" + m.group(1)))
    out: list[Alert] = []
    from zoneinfo import ZoneInfo
    today = NOW.astimezone(ZoneInfo("Europe/Warsaw")).date()
    for d, title, url in items:
        if not d or (today - d.date()).days > 0:      # tik šiandienos
            continue
        if RCB_SKIP.search(title):
            continue
        if RCB_END.search(title):
            break                                      # naujesnis atšaukimas – senesni nebegalioja
        kind = "air" if RCB_AIR.search(title) else "weather" if re.search(
            r"burz|wiatr|deszcz|upał|upal|śnieg|snieg|mróz|mroz|powód|powod|oblodz", title, re.I) else "other"
        out.append(Alert(level="yellow", kind=kind, text=title, time=d.isoformat(), url=url, src="Alert RCB"))
    return out[:1]


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


# ---------------------------------------------------------------- sujungimas
SOURCES = {
    "LTU": [("lt72", lt72)],
    "EST": [("kriis", kriis)],
    "POL": [("rcb", rcb)],
}
for cc, slug in METEOALARM.items():
    SOURCES.setdefault(cc, []).append((f"meteoalarm-{slug}", lambda s=slug: meteoalarm(s)))


def collect() -> dict:
    result: dict = {}
    meta = {"checked": NOW.isoformat(timespec="seconds"), "sources": {}}
    for cc in COUNTRIES:
        alerts: list[Alert] = []
        ok = 0
        for name, fn in SOURCES.get(cc, []):
            t0 = time.time()
            try:
                got = fn()
                alerts += got
                ok += 1
                meta["sources"][name] = {"ok": True, "n": len(got), "ms": int((time.time() - t0) * 1000)}
            except Exception as ex:  # noqa: BLE001
                meta["sources"][name] = {"ok": False, "err": f"{type(ex).__name__}: {ex}"[:200]}
        if alerts:
            # karas pirmiau už orus esant tam pačiam lygiui
            alerts.sort(key=lambda a: (RANK[a["level"]], a.get("kind") == "air"), reverse=True)
            top = alerts[0]
            extra = len(alerts) - 1
            text = top["text"] + (f"  (+{extra} kiti įspėjimai)" if extra else "")
            result[cc] = {"level": top["level"], "kind": top["kind"], "text": text,
                          "time": top["time"], "url": top.get("url", ""), "src": top["src"]}
        elif ok:
            result[cc] = {"level": "white", "text": "Aktyvių perspėjimų nėra.",
                          "time": meta["checked"]}
        else:
            result[cc] = {"level": "none", "text": "Šaltiniai šiuo metu nepasiekiami.",
                          "time": meta["checked"]}
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
