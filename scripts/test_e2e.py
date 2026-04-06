from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_command(args: list[str]) -> None:
    completed = subprocess.run(args, cwd=ROOT, check=True, text=True)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def main() -> None:
    run_command([sys.executable, "run.py", "dry"])
    run_command([sys.executable, "run.py", "test", "--model", "mock/default", "--trials", "1"])


if __name__ == "__main__":
    main()
