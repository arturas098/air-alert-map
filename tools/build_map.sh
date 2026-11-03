#!/usr/bin/env bash
# Perkuria data/map.topo.json iš Natural Earth 10m duomenų.
# Reikia: npm i -g mapshaper ; curl
set -euo pipefail
cd "$(dirname "$0")/.." ; mkdir -p .ne ; cd .ne
NE=https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson
for f in admin_0_countries admin_1_states_provinces rivers_lake_centerlines lakes roads railroads populated_places_simple; do
  [ -s ne_10m_$f.geojson ] || curl -fL -o ne_10m_$f.geojson $NE/ne_10m_$f.geojson
done
BB="0,42,56,74"
mapshaper ne_10m_admin_0_countries.geojson -filter '["LTU","LVA","EST","FIN","POL","RUS","BLR","SWE","NOR","DEU","UKR","DNK","CZE","SVK","AUT","HUN","ROU","MDA","NLD"].indexOf(ADM0_A3)>-1' -clip bbox=$BB -filter-fields ADM0_A3,NAME -rename-layers c -o c.json format=geojson force
mapshaper ne_10m_admin_1_states_provinces.geojson -filter '["LTU","LVA","EST","FIN","POL","RUS","BLR"].indexOf(adm0_a3)>-1' -clip bbox=$BB -filter-fields adm0_a3,name -rename-layers r -o r.json format=geojson force
mapshaper ne_10m_roads.geojson -clip bbox=$BB -filter 'scalerank<=7' -each 'm = scalerank<=4 ? 1 : 0' -dissolve m -rename-layers rd -o rd.json format=geojson force
mapshaper ne_10m_railroads.geojson -clip bbox=$BB -filter 'scalerank<=8' -dissolve -rename-layers rl -o rl.json format=geojson force
mapshaper ne_10m_rivers_lake_centerlines.geojson -clip bbox=$BB -dissolve scalerank -rename-layers rv -o rv.json format=geojson force
mapshaper ne_10m_lakes.geojson -clip bbox=$BB -filter-fields scalerank -rename-layers lk -o lk.json format=geojson force
mapshaper ne_10m_populated_places_simple.geojson -clip bbox=$BB -filter 'scalerank<=7 && ["Kaliningrad","Malmö","Hammerfest"].indexOf(name)<0' -filter-fields name,scalerank,adm0_a3,featurecla -rename-layers pl -o pl.json format=geojson force
mapshaper -i c.json r.json rv.json lk.json rd.json rl.json pl.json combine-files -simplify interval=600 keep-shapes -o ../data/map.topo.json format=topojson quantization=4e4 force
