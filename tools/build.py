#!/usr/bin/env python3
"""Sukuria vieną savarankišką index.html (veikia be interneto).
Naudojimas:  python3 tools/build.py   (iš repo šaknies)"""
from pathlib import Path
R = Path(__file__).resolve().parent.parent
s = (R/"web/src.html").read_text(encoding="utf-8")
s = s.replace("/*D3*/", (R/"vendor/d3.min.js").read_text(encoding="utf-8"))
s = s.replace("/*TOPOJSON*/", (R/"vendor/topojson-client.min.js").read_text(encoding="utf-8"))
s = s.replace("/*MAPDATA*/", (R/"data/map.topo.json").read_text(encoding="utf-8"))
(R/"index.html").write_text(s, encoding="utf-8")
print("index.html", round(len(s)/1e6,2), "MB")
