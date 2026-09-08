"""Run model acceptance from a source checkout without installing the package."""

import sys

sys.dont_write_bytecode = True

from zhijing.verification.__main__ import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
