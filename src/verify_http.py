"""Verify the formal application entry with isolated data from a source checkout."""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.dont_write_bytecode = True
PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "scripts"))

from reporting.http_runner import run_http  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-root", type=Path, required=True)
    args = parser.parse_args()
    work = args.work_root.resolve() / datetime.now(UTC).strftime("http-%Y%m%d-%H%M%S-%f")
    work.mkdir(parents=True)
    evidence = work / "evidence"
    evidence.mkdir()
    cases = run_http(PROJECT, evidence, work, sys.executable)
    passed = all(case["status"] == "通过" for case in cases)
    report = {"passed": passed, "cases": cases}
    (work / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {"passed": passed, "case_count": len(cases), "report": str(work / "report.json")}
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
