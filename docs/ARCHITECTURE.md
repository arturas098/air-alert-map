# Architektūra

Tikslas: jokio trečiųjų šalių serverio. Viskas veikia tavo įrenginyje.

```
  oficialūs šaltiniai (lt72.lt, 112.lv, kriis.ee, gov.pl/rcb, Yle, MeteoAlarm, FMI)
                │  HTTP polling kas 30–60 s
                ▼
  ┌─────────────────────────────┐        ┌──────────────────────────┐
  │ surinkėjas (collector)      │        │ telefono notifikacijos   │
  │  A) Termux + Python         │◄───────│ (NotificationListener)   │
  │  B) APK fono servisas       │        │ cell broadcast / SMS     │
  └─────────────┬───────────────┘        └──────────────────────────┘
                │ rašo alerts.json
                ▼
  index.html (šis žemėlapis) ── WebView / naršyklė ── notifikacija pasikeitus lygiui
```

## Variantai
**A. Termux (greičiausia pradėti)**
- `pkg install python git`, `git clone` šį repo
- `python collector.py` kas N s rašo `alerts.json` ir paleidžia `http.server` → `http://localhost:8080`
- Push: `termux-notification` (Termux:API) arba savas ntfy

**B. Savas APK (galutinis)**
- WebView rodo `index.html` iš assets
- Kotlin `WorkManager` / foreground service tikrina šaltinius (CORS netrukdo)
- `NotificationListenerService` → momentinis signalas iš cell broadcast / SMS / 112 programėlių
- Notifikacija, kai lygis pakyla (`none/white → yellow → red`)

**C. GitHub Pages**
- Statinis žemėlapis prieinamas iš bet kur. Duomenų čia nebus: Pages nemoka tikrinti šaltinių, o naršyklė blokuoja svetimus domenus (CORS).

## Sprendimai
- Žemėlapis piešiamas pačių (D3 + Natural Earth), be tile serverių. Veikia offline, jokio API rakto.
- Viskas sudėta į vieną `index.html` failą, kad lengva būtų įdėti į APK assets.
- Šalys be šaltinių (BY, RU, KGD) paslėptos iš UI.
- Pavojaus tipas (`kind`) atskirtas nuo lygio (`level`): karas ir stichija gali būti tą pačią dieną.

## Kiti žingsniai
1. Patikrinti feed URL iš telefono (lt72.lt RSS, 112.lv, kriis.ee, gov.pl/rcb)
2. `collector/collector.py`: parseriai šalims + MeteoAlarm CAP
3. Regionų lygis: Natural Earth admin_1 jau yra `map.topo.json` (sluoksnis `r`)
4. APK karkasas
