#!/usr/bin/env python3
"""Nuolatinis surinkėjas GitHub Actions'ui.

GitHub „schedule“ realiai paleidžia darbą retai ir nereguliariai, todėl vienas paleidimas
veikia ~DURATION sekundžių ir kas INTERVAL s perrenka duomenis. alerts.json publikuojamas į
atskirą šaką `data` (vienas commit'as, force-push), kad `main` istorija neaugtų.

Publikuojama, kai pasikeičia turinys arba kas HEARTBEAT s (kad žemėlapis žinotų, jog duomenys gyvi).

    python3 collector/loop.py              # Actions'e (reikia GITHUB_TOKEN, GITHUB_REPOSITORY)
    python3 collector/loop.py --once       # vienas ciklas
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INTERVAL = int(os.environ.get("INTERVAL", 90))
DURATION = int(os.environ.get("DURATION", 55 * 60))
HEARTBEAT = int(os.environ.get("HEARTBEAT", 10 * 60))
BRANCH = "data"
HISTORY_H = 48            # kiek valandų istorijos laikom history.json


def compact(data: dict) -> dict:
    """Istorijai – tik tai, ko reikia žemėlapiui atkurti (be _meta, sutrumpinti tekstai)."""
    out = {}
    for cc, v in data.items():
        if cc.startswith("_"):
            continue
        c = {k: v[k] for k in ("level", "kind", "text", "air", "weather", "regions", "regionsOnly", "src", "url", "time", "dateOnly")
             if k in v and v[k] not in (None, "", False)}
        if c.get("level") in ("white", "none"):
            c.pop("time", None)          # „patikrinta“ laikas kas ciklą kinta – istorijoje nereikalingas
        if c.get("text"):
            c["text"] = c["text"][:240]
        if v.get("items"):
            c["items"] = [{k: a[k] for k in ("level", "kind", "event", "area", "time", "expires", "regions", "src", "url", "dateOnly")
                           if k in a and a[k] not in (None, "", False, [])} for a in v["items"][:10]]
            for a in c["items"]:
                if a.get("area"):
                    a["area"] = a["area"][:160]
        out[cc] = c
    return out


def load_history() -> list:
    """Ankstesnė istorija iš `data` šakos (kad nauji paleidimai jos nepamestų)."""
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not (token and repo):
        return []
    with tempfile.TemporaryDirectory() as d:
        try:
            g = lambda *a: subprocess.run(["git", *a], cwd=d, check=True, capture_output=True, timeout=60)
            g("init", "-q")
            g("fetch", "-q", "--depth", "1", f"https://x-access-token:{token}@github.com/{repo}.git", BRANCH)
            # ukrainealarm talpykla (regionų medis, paskutinis atsakymas, limito laikas) – kad naujas ciklas
            # nelauktų minutės ir nerodytų atsarginio šaltinio
            uc = subprocess.run(["git", "show", "FETCH_HEAD:ua-cache.json"], cwd=d, capture_output=True, timeout=30)
            if uc.returncode == 0:
                Path(os.environ.get("UA_CACHE_DIR", "/tmp"), "ukrainealarm-cache.json").write_bytes(uc.stdout)
            raw = subprocess.run(["git", "show", "FETCH_HEAD:history.json"], cwd=d, capture_output=True, timeout=30)
            return json.loads(raw.stdout.decode("utf-8")).get("snaps", []) if raw.returncode == 0 else []
        except Exception as ex:  # noqa: BLE001
            print("istorijos nepavyko įkelti:", ex)
            return []


def add_snapshot(hist: list, data: dict) -> list:
    from datetime import datetime, timedelta, timezone
    t = data["_meta"]["checked"]
    snap = {"t": t, "d": compact(data)}
    if not hist or hist[-1]["d"] != snap["d"]:
        hist.append(snap)
    cut = (datetime.now(timezone.utc) - timedelta(hours=HISTORY_H)).isoformat()
    old = [h for h in hist if h["t"] < cut]
    hist = ([old[-1]] if old else []) + [h for h in hist if h["t"] >= cut]   # vienas atskaitos taškas prieš langą
    return hist


def collect() -> dict:
    subprocess.run([sys.executable, str(ROOT / "collector/collector.py")], check=True, cwd=ROOT, timeout=180)
    return json.loads((ROOT / "alerts.json").read_text(encoding="utf-8"))


def strip(d: dict) -> dict:
    return {k: v for k, v in d.items() if k != "_meta"}


def publish(data: dict, hist: list | None = None) -> None:
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not (token and repo):
        print("publish: nėra GITHUB_TOKEN / GITHUB_REPOSITORY – praleidžiu")
        return
    with tempfile.TemporaryDirectory() as d:
        Path(d, "alerts.json").write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        files = ["alerts.json"]
        uc = Path(os.environ.get("UA_CACHE_DIR", "/tmp"), "ukrainealarm-cache.json")
        if uc.exists():
            Path(d, "ua-cache.json").write_bytes(uc.read_bytes()); files.append("ua-cache.json")
        if hist is not None:
            Path(d, "history.json").write_text(json.dumps({"hours": HISTORY_H, "snaps": hist}, ensure_ascii=False,
                                                          separators=(",", ":")), encoding="utf-8")
            files.append("history.json")
        g = lambda *a: subprocess.run(["git", *a], cwd=d, check=True, capture_output=True, timeout=60)
        g("init", "-q", "-b", BRANCH)
        g("add", *files)
        g("-c", "user.name=air-alert-bot", "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
          "commit", "-q", "-m", f"alerts {data['_meta']['checked']}")
        g("push", "-q", "-f", f"https://x-access-token:{token}@github.com/{repo}.git", f"HEAD:{BRANCH}")
    print("publish:", data["_meta"]["checked"], {k: v["level"] for k, v in strip(data).items()})


def main() -> int:
    once = "--once" in sys.argv
    t_end = time.time() + DURATION
    last, last_pub = None, 0.0
    hist = load_history()
    print("istorija:", len(hist), "įrašų")
    while True:
        t0 = time.time()
        try:
            data = collect()
            if strip(data) != last or t0 - last_pub >= HEARTBEAT:
                hist = add_snapshot(hist, data)
                publish(data, hist)
                last, last_pub = strip(data), t0
        except Exception as ex:  # noqa: BLE001 – vienas nepavykęs ciklas nestabdo kitų
            print("klaida:", type(ex).__name__, ex)
        if once or time.time() + INTERVAL > t_end:
            return 0
        time.sleep(max(5, INTERVAL - (time.time() - t0)))


if __name__ == "__main__":
    sys.exit(main())
