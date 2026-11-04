#!/usr/bin/env python3
"""data/regions.json – sričių (admin-1) pavadinimų žodynas surinkėjui.
Naudoja .ne/ne_10m_admin_1_states_provinces.geojson (žr. build_map.sh)."""
import json
from pathlib import Path
R = Path(__file__).resolve().parent.parent
d = json.load(open(R / ".ne/ne_10m_admin_1_states_provinces.geojson", encoding="utf-8"))
out = []
for f in d["features"]:
    p = f["properties"]; a = p["adm0_a3"]; iso = p["iso_3166_2"]
    if iso in ("UA-43", "UA-40"):
        a = "UKR"          # Krymas, Sevastopolis
    if a not in ("EST", "FIN", "POL", "UKR"):   # LT ir LV – data/ltlv.json (geoBoundaries)
        continue
    names = set()
    for k in ("name", "name_local", "name_en", "name_pl", "name_uk", "name_ru", "name_de", "name_alt", "woe_name", "gn_name"):
        if p.get(k):
            names.update(x.strip() for x in str(p[k]).split("|") if x.strip())
    out.append({"iso": iso, "cc": a, "name": p["name"], "names": sorted(names)})
(R / "data/regions.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
print(len(out), "sritys")
