# Šaltiniai

Nė viena šalis neturi viešo push API oro pavojams. Tikras push yra tik cell broadcast / SMS į telefoną. Žemėlapiui naudojame oficialius **veidrodžius**: puslapius, kuriuose valstybė pati dubliuoja kiekvieną išsiųstą pranešimą. Juos tikriname kas 30–60 s.

Patikrinta 2026-11-03 (paieška). Feed URL dar būtina patikrinti iš telefono, nes debesies aplinka šių svetainių nepasiekia.

## Karas + stichija (oficialūs pranešimų veidrodžiai)

| Šalis | Šaltinis | Kas ten | Pastabos |
|---|---|---|---|
| 🇱🇹 LT | **lt72.lt**, kategorija „Išsiųsti perspėjimo pranešimai“ | PAGD skelbia išsiųstus perspėjimus (oro pavojus, stichija, tarša) | WordPress, tikėtinas RSS `lt72.lt/feed/` arba kategorijos feed. **TODO: patikrinti.** Grandinė: Kariuomenė inicijuoja → PAGD suderina su NKVC → siunčia. |
| 🇱🇻 LV | **112.lv** | Dubliuoja kiekvieną LV-ALERT cell broadcast pranešimą | VUGD. Svetainė perkrova pavojaus metu (2026 m. skirta 660 k€ stiprinimui). |
| 🇪🇪 EE | **kriis.ee** (+ olevalmis.ee) | EE-ALARM pranešimų autentiškumo tikrinimo vieta | Päästeamet / Häirekeskus. Cell broadcast Estijoje iki 2027 m. kovo. |
| 🇫🇮 FI | **Yle Teksti-TV p. 112** | Visi vaaratiedote | Yle API reikia nemokamo `app_id/app_key`. Oro grėsmės funkcija 112 Suomi programėlėje kuriama (SIREN projektas). |
| 🇵🇱 PL | **gov.pl/web/rcb → Komunikaty** | Kiekvienas Alert RCB, įsk. „zagrożenie atakiem z powietrza“ | Taip pat „rosyjski atak powietrzny na terenie Ukrainy“, kai keliami orlaiviai. |

## Orai (mašininiai CAP feed'ai, stabiliausi)

- MeteoAlarm (EUMETNET), Atom + CAP 1.2:
  - `https://feeds.meteoalarm.org/feeds/meteoalarm-legacy-atom-lithuania`
  - `…-latvia`, `…-estonia`, `…-finland`, `…-poland`
- Suomija tiesiogiai, FMI: `https://alerts.fmi.fi/cap/feed/atom_en-GB.xml` (taip pat `atom_fi-FI.xml`, `atom_sv-FI.xml`)

CAP `severity` → mūsų lygis: `Extreme/Severe` (raudona/oranžinė) → `red`; `Moderate` (geltona) → `yellow`.

## Greiti papildomi (naujienos, NE pirminis šaltinis)
lrt.lt, lsm.lv, err.ee, yle.fi. Tinka tik kaip ankstyvas signalas arba „pavojus atšauktas“ patvirtinimui.

## Telefono lygmuo (greičiausias)
Android `NotificationListenerService` gaudo:
- „Belaidžiai nepaprastieji įspėjimai“ (Cell Broadcast Receiver): LT ir LV cell broadcast
- EE-ALARM SMS (siuntėjas `EE-ALARM`, užsienio SIM: +372 5950 0000)
- Alert RCB SMS (siuntėjas `Alert RCB`, PL SIM)
- 112 Suomi, Ole valmis!, Eesti äpp, 112 Latvija programėlių notifikacijas

Ribojimas: gauni tik ten, kur fiziškai yra telefonas.

## Lietuvos oro pavojaus lygiai (žemėlapio spalvos)
| Pranešimas | Lygis |
|---|---|
| ORO PAVOJUS (RAUDONA) | `red` |
| ORO PAVOJUS (RAUDONA), galbūt dronas | `red` |
| TIKĖTINAS ORO PAVOJUS (GELTONA) | `yellow` |
| ORO PAVOJUS (GELTONA PO RAUDONOS) | `yellow` |
| Pavojus atšauktas | `white` |

## Ukraina (sričių lygiu)
| Prioritetas | Šaltinis | Statusas | Raktas |
|---|---|---|---|
| 1 | **api.ukrainealarm.com**: oficiali „Повітряна тривога“ sistema (Mincifra + Ajax), ji valdo ir sirenas | oficialus | prašyti formoje api.ukrainealarm.com → GitHub Secret `UKRAINEALARM_KEY` |
| 2 | **api.alerts.in.ua** `/v1/iot/active_air_raid_alerts_by_oblast.json` | plačiai naudojamas | rašyti api@alerts.in.ua → Secret `ALERTS_IN_UA_TOKEN` |
| 3 | **ubilling.net.ua/aerialalerts/** | NEoficialus agregatorius, be rakto | `cachedat` > 3 h laikomas pasenusiu |

Surinkėjas bando iš eilės ir rašo `UKR.regions = {"UA-63":"red", …}` (ISO 3166-2). Krymas (UA-43) ir Sevastopolis (UA-40) žemėlapyje priskirti Ukrainai.

## Be šaltinių
Baltarusija, Rusija, Karaliaučius: viešų pavojaus sistemų nėra. UI jas paslepia.
