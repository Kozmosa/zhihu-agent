"""Five-capability smoke test through the formal main.py entry.

--mock uses fixed responses and verifies integration only. --live uses an existing
Ollama-compatible service and does not download a model or persist credentials.
"""

import argparse
import json
import os
import sys
import tempfile
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path

from ollama_testing.cases import exercise
from ollama_testing.mock_server import mock_ollama
from ollama_testing.server import application


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--mock", action="store_true", help="Test HTTP wiring with fixed responses")
    mode.add_argument("--live", action="store_true", help="Test an existing real model endpoint")
    parser.add_argument("--url", default=os.getenv("ZHIJING_OLLAMA_URL", "http://127.0.0.1:11434"))
    parser.add_argument("--model", default=os.getenv("ZHIJING_OLLAMA_MODEL", "qwen3:8b"))
    parser.add_argument("--timeout", type=float, default=120, help="Timeout for each capability")
    parser.add_argument("--report", type=Path, help="Optionally save the JSON report")
    parser.add_argument("--work-root", type=Path, help="Parent for disposable isolated test data")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")
    if args.work_root:
        args.work_root.mkdir(parents=True, exist_ok=True)
    report = {
        "started_at": datetime.now(UTC).isoformat(),
        "mode": "mock" if args.mock else "live",
        "mock_responses": args.mock,
        "live_ollama_api_success_count": 0,
        "live_ollama_api_response_received": False,
        "live_model_validation_passed": False,
        "all_capabilities_passed": False,
        "model_response_measurement": (
            "Counts HTTP 200 capability responses with mode=ollama. Upstream model responses "
            "rejected by application validation may produce 502 and are not counted as successes."
        ),
        "notice": (
            "Fixed model responses verify HTTP integration and validation, not model quality."
            if args.mock
            else "Uses the configured model service; passing is a smoke check, not a quality benchmark."
        ),
        "cases": [],
        "passed": False,
    }
    project = Path(__file__).resolve().parents[1]
    context = mock_ollama() if args.mock else nullcontext((args.url, None))
    try:
        with context as (url, calls):
            with tempfile.TemporaryDirectory(prefix="zhijing-ollama-", dir=args.work_root) as name:
                work = Path(name)
                if args.work_root and not work.resolve().is_relative_to(args.work_root.resolve()):
                    raise ValueError("Unexpected temporary workspace path")
                with application(project, work, url, args.model, args.timeout, args.mock) as client:
                    report["cases"] = exercise(client)
            report["all_capabilities_passed"] = len(report["cases"]) == 5 and all(
                case["passed"] for case in report["cases"]
            )
            report["passed"] = report["all_capabilities_passed"]
            if calls is not None:
                report["model_calls"] = [call["task"] for call in calls]
                report["passed"] = report["passed"] and report["model_calls"] == [
                    "reading",
                    "cards",
                    "facts",
                    "knowledge",
                    "author",
                ]
            else:
                report["live_ollama_api_success_count"] = sum(
                    case.get("http_status") == 200 and case.get("response_mode") == "ollama"
                    for case in report["cases"]
                )
                report["live_ollama_api_response_received"] = (
                    report["live_ollama_api_success_count"] > 0
                )
                report["live_model_validation_passed"] = report["all_capabilities_passed"]
    except Exception as error:
        # Avoid exposing endpoint credentials or upstream response text in reports.
        report["error_type"] = type(error).__name__
    report["finished_at"] = datetime.now(UTC).isoformat()
    output = json.dumps(report, ensure_ascii=True, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    raise SystemExit(main())
