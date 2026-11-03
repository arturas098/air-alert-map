# CLAUDE.md: air-alert-map

Vartotojas rašo lietuviškai, atsakyk lietuviškai.

- UI kodas: `web/src.html`. Po kiekvieno pakeitimo paleisk `python3 tools/build.py` ir commitink sugeneruotą `index.html`.
- Patikrink vaizdą su Playwright (mobile 412×900 ir desktop 1400×900), paspausk „Demo“ du kartus.
- `alerts.json` formatas ir šalių raktai: README. Šaltiniai: `docs/SOURCES.md`.
- Šalys be viešų šaltinių (KGD, BLR, RUS) turi `hidden:true`, joms langelių nerodyti.
- Dokumentacija dubliuojama Google Drive aplanke „APK air-alert-map“ (My Drive šaknis).
