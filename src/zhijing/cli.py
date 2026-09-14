"""Small CLI boundary: parse options, verify dependencies, then run the server."""

import argparse
import json
import os
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


def valid_host(value: str) -> str:
    value = value.strip()
    if not value or any(character.isspace() for character in value):
        raise argparse.ArgumentTypeError("host must be a hostname or IP address without spaces")
    return value


def resolve_listen(cli_host: str | None, cli_port: int | None) -> tuple[str, int]:
    """Explicit flags win, then ZHIJING_HOST/ZHIJING_PORT, then platform PORT."""
    try:
        host = cli_host or valid_host(os.getenv("ZHIJING_HOST", "127.0.0.1"))
        port = cli_port if cli_port is not None else valid_port(
            os.getenv("ZHIJING_PORT") or os.getenv("PORT") or "8000"
        )
    except argparse.ArgumentTypeError as exc:
        raise ValueError(str(exc)) from exc
    return host, port


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ZhiJing Agent server (local access only)")
    parser.add_argument("transcript_run_id", nargs="?", help=argparse.SUPPRESS)
    parser.add_argument(
        "--port", type=valid_port, default=None, help="HTTP port (default: ZHIJING_PORT, PORT, 8000)"
    )
    parser.add_argument(
        "--host",
        type=valid_host,
        default=None,
        help="bind address (default: ZHIJING_HOST or 127.0.0.1)",
    )
    parser.add_argument(
        "--open-browser", action="store_true", help="Open model settings when healthy"
    )
    parser.add_argument(
        "--check", action="store_true", help="Check environment without starting HTTP"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = create_parser().parse_args(argv)
    if args.transcript_run_id:
        from zhijing.core.config import Settings
        from zhijing.infrastructure.sqlite_transcript import SQLiteTranscript
        path = Settings().data_dir / "runs.sqlite3"
        for event in SQLiteTranscript(path).list(args.transcript_run_id):
            print(json.dumps(event, ensure_ascii=False))
        return 0
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

    try:
        host, port = resolve_listen(args.host, args.port)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    base_url = f"http://127.0.0.1:{port}"
    print(f"ZhiJing Agent | Model settings: {base_url}/", flush=True)
    print(f"API documentation: {base_url}/docs", flush=True)
    print(f"Data directory: {report['data_dir']}", flush=True)
    if host not in {"127.0.0.1", "localhost", "::1"}:
        print(f"Listening on {host}:{port}.", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    server = uvicorn.Server(
        uvicorn.Config("zhijing.app:create_app", factory=True, host=host, port=port)
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
