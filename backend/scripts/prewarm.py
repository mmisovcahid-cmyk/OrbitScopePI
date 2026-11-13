"""Download everything a demo of the five challenge targets needs, ahead of time.

The first view of a new field downloads 16-96 cutouts from IRSA (30-90 s, and IRSA sometimes
answers 503). Running this once before a presentation fills the on-disk cache, so every test
target opens immediately. Re-running it is cheap: cached cutouts are reused, and the three
Detection example runs are only computed once.

    cd backend
    python -m scripts.prewarm                    # everything (all detectors, spectra, demo runs)
    python -m scripts.prewarm --targets barnard,wise-0855 --quick

On a Raspberry Pi run it once with internet before an offline demo (deploy/pi/README in docs/RASPBERRY_PI.md).

In Docker the backend does this by itself at startup (PREWARM_ON_STARTUP=true); to run it by hand:
    docker compose exec backend python -m scripts.prewarm
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.prewarm import prewarm  # noqa: E402
from app.services.target_resolver import BUILTIN_TARGETS  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--targets", default="all", help="comma list of ids: " + ", ".join(t["id"] for t in BUILTIN_TARGETS))
    ap.add_argument("--quick", action="store_true", help="only each target's default detector")
    ap.add_argument("--no-photometry", action="store_true", help="skip the spectra / light curves")
    ap.add_argument("--no-demo-runs", action="store_true", help="skip the Detection example runs")
    ap.add_argument("--no-offline", action="store_true", help="skip the Planet X / SBDB offline snapshots")
    args = ap.parse_args()
    ids = None if args.targets == "all" else {x.strip() for x in args.targets.split(",")}
    if ids and not ids & {t["id"] for t in BUILTIN_TARGETS}:
        print("No matching targets. Ids: " + ", ".join(t["id"] for t in BUILTIN_TARGETS))
        return 2
    ok = asyncio.run(prewarm(ids, all_detectors=not args.quick, photometry=not args.no_photometry,
                             demo_runs=not args.no_demo_runs,
                             offline_extras=not args.no_offline, log=lambda m: print(m, flush=True)))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
