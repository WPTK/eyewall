"""Run the real-input suite against a built eyewall executable and print one results table.

    python scripts/realinput.py --exe dist\\eyewall.exe
    python scripts/realinput.py                       # downloads the latest release asset into an empty directory
    python scripts/realinput.py -k keyboard           # extra arguments go to pytest

The suite is `tests/realinput` (pytest marker `realinput`). It drives the exe on a pseudo-console with the bytes a
terminal sends and reads the screen back through pyte. Results are printed as a table and saved as JSON.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def table(results: dict[str, object]) -> str:
    rows = results["rows"]  # type: ignore[index]
    lines = [f"{'status':6} {'scenario':44} item"]
    for r in rows:  # type: ignore[attr-defined]
        issue = f" {r['issue']}" if r["issue"] else ""
        lines.append(f"{r['status']:6} {r['scenario'][:44]:44} {r['item'][:110]}{issue}")
    counts: dict[str, int] = {}
    for r in rows:  # type: ignore[attr-defined]
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    lines.append("")
    lines.append("artifact: " + json.dumps(results["artifact"]))
    lines.append("items: " + str(len(rows)) + "  " + "  ".join(f"{k}={v}" for k, v in sorted(counts.items())))  # type: ignore[arg-type]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exe", help="the built exe (default: download the latest release asset)")
    ap.add_argument("--results", default=str(ROOT / "realinput-results.json"), help="where to save the JSON table")
    ap.add_argument(
        "--lock", default=os.environ.get("EYEWALL_REAL_LOCK", ""), help="lock directory held during the run"
    )
    args, extra = ap.parse_known_args()

    lock = Path(args.lock) if args.lock else None
    if lock:
        while True:
            try:
                lock.mkdir()
                break
            except FileExistsError:
                time.sleep(5)
    try:
        env = dict(os.environ, EYEWALL_REAL_RESULTS=args.results, PYTHONUTF8="1")
        if args.exe:
            env["EYEWALL_EXE"] = str(Path(args.exe).resolve())
        cmd = [
            sys.executable,
            "-m",
            "pytest",
            "tests/realinput",
            "-m",
            "realinput",
            "-p",
            "no:cacheprovider",
            "-q",
            "--timeout=1500",
            *extra,
        ]
        code = subprocess.run(cmd, cwd=ROOT, env=env, check=False).returncode
    finally:
        if lock:
            lock.rmdir()
    results_path = Path(args.results)
    if results_path.is_file():
        print(table(json.loads(results_path.read_text(encoding="utf-8"))))
        print(f"saved: {results_path}")
    return code


if __name__ == "__main__":
    sys.exit(main())
