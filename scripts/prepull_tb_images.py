"""Pre-pull all Docker images for a TB subset, so image download happens once
and never eats into a timed eval run.

Usage:
    python scripts/prepull_tb_images.py --tb-root ~/terminal-bench-2
    python scripts/prepull_tb_images.py --tb-root ~/terminal-bench-2 --subset fix-git crack-7z-hash
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from harnessforge.eval.tb_adapter import load_subset  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tb-root", type=Path, required=True)
    ap.add_argument("--subset", nargs="*", default=None)
    args = ap.parse_args()

    tasks = load_subset(args.tb_root, args.subset)
    images = sorted({t.docker_image for t in tasks})
    print(f"Pulling {len(images)} images for {len(tasks)} tasks...\n")

    failed = []
    for i, img in enumerate(images, 1):
        print(f"[{i}/{len(images)}] docker pull {img}")
        rc = subprocess.run(["docker", "pull", img]).returncode
        if rc != 0:
            failed.append(img)
            print(f"  !! failed: {img}")

    print("\nDone." if not failed else f"\nDone with {len(failed)} failures:")
    for img in failed:
        print(" -", img)
    print("\nDisk usage:")
    subprocess.run(["docker", "system", "df"])


if __name__ == "__main__":
    main()
