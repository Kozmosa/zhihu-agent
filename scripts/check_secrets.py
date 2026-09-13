#!/usr/bin/env python3
"""Offline credential guard for Git objects, with no secret values in diagnostics.

Run before committing with ``python scripts/check_secrets.py --staged``.
CI runs without --staged to inspect HEAD. Working-tree edits cannot hide staged
credentials. This is a deliberately small guard, not a complete secret detector.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, order=True)
class Finding:
    path: str
    line: int
    rule: str


# Exact file AND exact synthetic value. Adding a new test must not exempt other
# files, new credentials, or a sensitive filename from the guard.
TEST_VALUES = {
    "tests/test_provider_verification.py": {
        "sk-" + "do-not-report-very-secret",
        "sk-" + "environment-secret",
    },
    "tests/test_local_model_config.py": {"test-secret"},
    "tests/test_model_security.py": {"synthetic-transport-audit-only"},
    "tests/test_model_settings.py": {"key\\nheader", "非法测试key"},
    "tests/test_runs.py": {"never-store-this"},
    "tests/test_settings_ui.py": {
        "synthetic-secret-do-not-echo", "synthetic-secret-do-not-echo\\n",
    },
    "tests/test_zhihu_web_routes.py": {"fixture-official"},
}

PLACEHOLDERS = {
    "", "example", "placeholder", "replace-me", "replace_me", "changeme",
    "your_api_key", "your_access_secret", "your_client_secret", "your_api_token",
    "your_key_here", "<api_key>", "<access_secret>", "<your_api_key>", "...", "{}",
    "api key", "access secret", "client secret", "api token",
}
REFERENCE = re.compile(
    r"(?:\$\{[^\r\n]+\}|\$\([A-Za-z_][\w:]*\)|\$(?:env:)?[A-Za-z_]\w*"
    r"|\{[A-Za-z_]\w*\}|%[A-Za-z_]\w*%|![A-Za-z_]\w*!)\Z"
)
TOKEN_RULES = (
    ("api_token", re.compile(r"(?<![\w-])sk-[A-Za-z0-9_-]{20,}(?![\w-])")),
    ("github_token", re.compile(r"(?<!\w)gh[pousr]_[A-Za-z0-9]{36,}(?!\w)")),
    ("github_token", re.compile(r"(?<!\w)github_pat_[A-Za-z0-9_]{20,}(?!\w)")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----")),
)
FIELD = r"[A-Za-z_][\w-]*(?:api[_-]?key|access[_-]?secret|client[_-]?secret|api[_-]?token)|api[_-]?key|access[_-]?secret|client[_-]?secret|api[_-]?token"
QUOTED_ASSIGNMENT = re.compile(
    rf"(?<![\w-])(?:[\"']?(?:{FIELD})[\"']?)\s*[:=]\s*"
    r"(?P<quote>[\"'])(?P<value>[^\r\n]*?)(?P=quote)", re.IGNORECASE
)
TRIPLE_ASSIGNMENT = re.compile(
    rf"(?<![\w-])(?:[\"']?(?:{FIELD})[\"']?)\s*[:=]\s*"
    r"(?P<quote>\"\"\"|''')(?P<value>[\s\S]*?)(?:(?P=quote)|\Z)",
    re.IGNORECASE,
)
PLAIN_ASSIGNMENT = re.compile(
    rf"^\s*(?:export\s+)?(?:{FIELD})\s*[:=]\s*(?P<value>[^\r\n#]+?)\s*(?:#.*)?$",
    re.IGNORECASE,
)
CMD_ASSIGNMENT = re.compile(
    rf"^\s*@?set\s+(?P<outer>\")?(?:{FIELD})\s*=\s*(?P<value>[^\r\n]*?)\s*$",
    re.IGNORECASE,
)


def _allowed(path: str, value: str) -> bool:
    return (
        value.lower() in PLACEHOLDERS
        or REFERENCE.fullmatch(value) is not None
        or value in TEST_VALUES.get(path, ())
    )


def _filename_rule(path: str) -> str | None:
    # Git uses forward slashes. Reject path aliases instead of normalizing them
    # into an allowlisted fixture path.
    if path.startswith("/") or "\\" in path or any(p in {"", ".", ".."} for p in path.split("/")):
        return "invalid_git_path"
    name = path.rsplit("/", 1)[-1].lower()
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return "environment_file"
    if name in {"model-config.json", "model-config.dpapi.json"} or (
        name.startswith(".model-config-") and name.endswith(".tmp")
    ):
        return "local_model_credentials"
    if re.search(r"\.(?:pem|key|p12|pfx|jks|keystore)$", name):
        return "private_key_file"
    if re.search(r"\.(?:db|sqlite|sqlite3)(?:-(?:wal|shm|journal))?$", name):
        return "local_database"
    if name in {"cookies", "cookie", "login data", "web data", "local state", ".netrc", "_netrc", ".npmrc"}:
        return "local_credentials_file"
    if re.search(r"(?:^|[._-])cookies?(?:[._-].*)?\.(?:json|txt|csv|jsonl|dat|bak)$", name):
        return "browser_cookie_export"
    return None


def scan_blob(path: str, data: bytes) -> list[Finding]:
    filename_rule = _filename_rule(path)
    if filename_rule:
        return [Finding(path, 1, filename_rule)]
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        contents = data.decode("utf-16", errors="replace")
    else:
        contents = data.decode("utf-8-sig", errors="replace")
    findings: set[Finding] = set()
    for match in TRIPLE_ASSIGNMENT.finditer(contents):
        if not _allowed(path, match["value"].strip()):
            findings.add(Finding(path, contents.count("\n", 0, match.start()) + 1, "credential_literal"))
    for number, line in enumerate(contents.splitlines(), 1):
        for rule, pattern in TOKEN_RULES:
            if any(not _allowed(path, match.group()) for match in pattern.finditer(line)):
                findings.add(Finding(path, number, rule))
        for match in QUOTED_ASSIGNMENT.finditer(line):
            if not _allowed(path, match["value"]):
                findings.add(Finding(path, number, "credential_literal"))
        if path.lower().endswith((".yml", ".yaml", ".env")) or path.rsplit("/", 1)[-1].lower() == ".env.example":
            match = PLAIN_ASSIGNMENT.match(line)
            if match and not _allowed(path, match["value"].strip().strip("\"'")):
                findings.add(Finding(path, number, "credential_literal"))
        match = CMD_ASSIGNMENT.match(line)
        if match:
            value = match["value"]
            if match["outer"] and value.endswith('"'):
                value = value[:-1]
            if not _allowed(path, value.strip().strip("\"'")):
                findings.add(Finding(path, number, "credential_literal"))
    return sorted(findings)


def _git(root: Path, *args: str, input_data: bytes | None = None) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *args], input=input_data, capture_output=True, check=False
    )
    if result.returncode:
        # Git's stderr can contain user-controlled filenames or remote URLs.
        raise RuntimeError("Cannot read the requested Git snapshot.")
    return result.stdout


def scan_repository(root: Path, *, staged: bool = False) -> list[Finding]:
    records = _git(root, "ls-files", "--stage", "-z") if staged else _git(
        root, "ls-tree", "-r", "-z", "HEAD"
    )
    findings: list[Finding] = []
    objects: list[tuple[str, str]] = []
    for record in records.split(b"\0"):
        if not record:
            continue
        metadata, encoded_path = record.split(b"\t", 1)
        parts = metadata.decode("ascii").split()
        path = encoded_path.decode("utf-8", errors="replace")
        if staged:
            _, oid, stage = parts
            if stage != "0":
                raise RuntimeError("Resolve merge conflicts before scanning the Git index.")
        else:
            _, kind, oid = parts
            if kind != "blob":
                # Submodules are not covered by a scan of this repository.
                findings.append(Finding(path, 1, "unscanned_gitlink"))
                continue
        if parts[0] == "160000":
            findings.append(Finding(path, 1, "unscanned_gitlink"))
            continue
        objects.append((path, oid))
    if objects:
        batch = io.BytesIO(_git(
            root, "cat-file", "--batch",
            input_data="".join(oid + "\n" for _, oid in objects).encode("ascii"),
        ))
        for path, oid in objects:
            header = batch.readline().decode("ascii").split()
            if len(header) != 3 or header[:2] != [oid, "blob"]:
                raise RuntimeError("Cannot read the requested Git object.")
            size = int(header[2])
            data = batch.read(size)
            if len(data) != size or batch.read(1) != b"\n":
                raise RuntimeError("Incomplete Git object.")
            findings.extend(scan_blob(path, data))
    return sorted(set(findings))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true", help="Scan the complete Git index, not working-tree files")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Repository directory (default: current directory)")
    args = parser.parse_args(argv)
    try:
        findings = scan_repository(args.repo, staged=args.staged)
    except (RuntimeError, OSError, ValueError):
        print("Secret scan could not inspect the Git snapshot; refusing to pass.", file=sys.stderr)
        return 2
    if findings:
        for finding in findings:
            # JSON quoting prevents terminal control characters in file paths.
            print(f"{json.dumps(finding.path, ensure_ascii=True)}:{finding.line}: {finding.rule}")
        return 1
    print("Secret scan passed for Git index." if args.staged else "Secret scan passed for HEAD.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
