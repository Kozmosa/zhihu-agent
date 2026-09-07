"""Small CLI boundary: parse options, verify dependencies, then run the server."""

import argparse
import json
import sys
from threading import Event

from zhijing.browser import open_docs_when_ready
from zhijing.startup import check_environment


def valid_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer between 1 and 65535") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ZhiJing Agent server (local access only)")
    parser.add_argument("--port", type=valid_port, default=8000, help="HTTP port (default: 8000)")
    parser.add_argument(
        "--open-browser", action="store_true", help="Open model settings when healthy"
    )
    parser.add_argument(
        "--check", action="store_true", help="Check environment without starting HTTP"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = create_parser().parse_args(argv)
    report = check_environment()
    if args.check:
        print(json.dumps(report, ensure_ascii=True, indent=2))
        return 0 if report["ready"] else 2
    if not report["ready"]:
        for error in report["errors"]:
            print(error, file=sys.stderr)
        print(
            "Run main.py --check for details. Use the project's Python environment.",
            file=sys.stderr,
        )
        return 2

    import uvicorn

    base_url = f"http://127.0.0.1:{args.port}"
    print(f"ZhiJing Agent | Model settings: {base_url}/", flush=True)
    print(f"API documentation: {base_url}/docs", flush=True)
    print(f"Data directory: {report['data_dir']}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    server = uvicorn.Server(
        uvicorn.Config("zhijing.app:create_app", factory=True, host="127.0.0.1", port=args.port)
    )
    stop = Event()
    if args.open_browser:
        open_docs_when_ready(server, base_url, stop)
    try:
        server.run()
    except KeyboardInterrupt:
        return 0
    finally:
        stop.set()
    return 0 if server.started else 1


if __name__ == "__main__":
    raise SystemExit(main())
