"""Project entry point; works without installation and from any working directory."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(PROJECT_ROOT / "src"))


if __name__ == "__main__":
    from zhijing.cli import main

    raise SystemExit(main())
