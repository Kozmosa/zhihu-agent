"""Model-independent backend smoke acceptance. Real model calls require --live."""

import argparse
import getpass
import json
import sys
import warnings
from dataclasses import replace
from pathlib import Path

from zhijing.core.config import Settings


def parser():
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument(
        "--provider", choices=("extractive", "ollama", "openai"), default="extractive"
    )
    mode = command.add_mutually_exclusive_group()
    mode.add_argument(
        "--mock", action="store_true", help="Use isolated synthetic localhost responses"
    )
    mode.add_argument(
        "--live", action="store_true", help="Call the explicitly configured real model"
    )
    command.add_argument("--url", help="Model base URL (omitted from reports)")
    command.add_argument("--model", help="Exact provider model ID")
    command.add_argument("--timeout", type=float, help="Per-model-request timeout, 1..1800 seconds")
    command.add_argument("--thinking", choices=("auto", "enabled", "disabled"))
    command.add_argument(
        "--workflow",
        action="store_true",
        help="Also check the durable five-step run and idempotent replay (five extra model calls)",
    )
    command.add_argument(
        "--prompt-key", action="store_true", help="Read an API key with hidden getpass input"
    )
    command.add_argument("--report", type=Path, help="Save the sanitized JSON acceptance report")
    command.add_argument(
        "--work-root", type=Path, help="Parent for temporary isolated application data"
    )
    return command


def main(argv=None):
    command = parser()
    args = command.parse_args(argv)
    if args.provider != "extractive" and not (args.mock or args.live):
        command.error("model providers require an explicit --mock or --live")
    if args.prompt_key and (not args.live or args.provider == "extractive"):
        command.error("--prompt-key requires --live and a model provider")
    if args.thinking and args.provider != "openai":
        command.error("--thinking applies only to --provider openai")
    from .runner import new_report, run_verification

    mode = "live" if args.live else "mock"
    try:
        # Mock/offline checks must not depend on unrelated malformed or secret-bearing env config.
        settings = Settings.from_env() if args.live else Settings(data_dir=Path("."))
        changes = {"model_provider": args.provider}
        if args.provider != "extractive":
            for key in ("url", "model", "timeout"):
                value = getattr(args, key)
                if value is not None:
                    changes[f"{args.provider}_{key}"] = value
            if args.prompt_key:
                # Refuse getpass's echoing fallback when no secure input terminal is available.
                with warnings.catch_warnings():
                    warnings.simplefilter("error", getpass.GetPassWarning)
                    changes[f"{args.provider}_api_key"] = getpass.getpass(
                        "Model API key (not saved): "
                    )
        if args.thinking:
            changes["openai_thinking"] = args.thinking
        report = run_verification(
            replace(settings, **changes),
            mode=mode,
            work_root=args.work_root,
            include_workflow=args.workflow,
        )
    except (Exception, KeyboardInterrupt) as error:
        report = new_report(args.provider, mode)
        report.update(reason="configuration_or_input_error", error_type=type(error).__name__)
    output = json.dumps(report, ensure_ascii=True, indent=2)
    if args.report:
        try:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(output + "\n", encoding="utf-8")
        except OSError:
            print("Could not write verification report; path details omitted.", file=sys.stderr)
            print(output)
            return 2
    print(output)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    raise SystemExit(main())
