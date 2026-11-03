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


def collect() -> dict:
    subprocess.run([sys.executable, str(ROOT / "collector/collector.py")], check=True, cwd=ROOT, timeout=180)
    return json.loads((ROOT / "alerts.json").read_text(encoding="utf-8"))


def strip(d: dict) -> dict:
    return {k: v for k, v in d.items() if k != "_meta"}


def publish(data: dict) -> None:
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not (token and repo):
        print("publish: nėra GITHUB_TOKEN / GITHUB_REPOSITORY – praleidžiu")
        return
    with tempfile.TemporaryDirectory() as d:
        Path(d, "alerts.json").write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        g = lambda *a: subprocess.run(["git", *a], cwd=d, check=True, capture_output=True, timeout=60)
        g("init", "-q", "-b", BRANCH)
        g("add", "alerts.json")
        g("-c", "user.name=air-alert-bot", "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
          "commit", "-q", "-m", f"alerts {data['_meta']['checked']}")
        g("push", "-q", "-f", f"https://x-access-token:{token}@github.com/{repo}.git", f"HEAD:{BRANCH}")
    print("publish:", data["_meta"]["checked"], {k: v["level"] for k, v in strip(data).items()})


def main() -> int:
    once = "--once" in sys.argv
    t_end = time.time() + DURATION
    last, last_pub = None, 0.0
    while True:
        t0 = time.time()
        try:
            data = collect()
            if strip(data) != last or t0 - last_pub >= HEARTBEAT:
                publish(data)
                last, last_pub = strip(data), t0
        except Exception as ex:  # noqa: BLE001 – vienas nepavykęs ciklas nestabdo kitų
            print("klaida:", type(ex).__name__, ex)
        if once or time.time() + INTERVAL > t_end:
            return 0
        time.sleep(max(5, INTERVAL - (time.time() - t0)))


if __name__ == "__main__":
    sys.exit(main())
