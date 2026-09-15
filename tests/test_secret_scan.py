import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_secrets.py"
SPEC = importlib.util.spec_from_file_location("zhijing_secret_scan", SCRIPT)
scanner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = scanner
SPEC.loader.exec_module(scanner)

# Assembled synthetic values ensure these tests never embed deployable tokens.
CANDIDATE = "sk-" + "A1b2C3d4" * 5


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, check=True
    ).stdout


@pytest.fixture
def repository(tmp_path):
    git(tmp_path, "init", "--quiet")
    git(tmp_path, "config", "user.name", "Local Fixture")
    git(tmp_path, "config", "user.email", "fixture@example.invalid")
    git(tmp_path, "config", "core.hooksPath", str(tmp_path / "unused-hooks"))
    git(tmp_path, "config", "commit.gpgsign", "false")
    (tmp_path / "app.py").write_text('api_key = ""\n', encoding="utf-8")
    git(tmp_path, "add", "app.py")
    git(tmp_path, "commit", "--quiet", "-m", "Safe fixture")
    return tmp_path


@pytest.mark.parametrize("path", [
    "data/model-config.json", "data/model-config.dpapi.json", ".model-config-local.tmp",
    ".env", "nested/.env.production", "tls/server.pem", "private.key",
    "cert.p12", "secrets.pfx", "data/sources.sqlite3", "runs.db-wal", "runs.sqlite-shm",
    "browser/Cookies", "browser/Local State", "browser/Login Data", "cookies.txt",
    "zhihu-cookies-export.json", "cookies_2026.csv", "my.cookie.json", "session.cookie.dat",
    "tests/model-config.json", "tests/.env.local", ".netrc", ".npmrc",
])
def test_sensitive_filenames_are_rejected_even_with_empty_content(path):
    assert scanner.scan_blob(path, b"")


@pytest.mark.parametrize("path", [
    ".env.example", "config/.env.example", "tests/test_cookie_parser.py",
    "src/cookie_import.js", "docs/model-config.md", "docs/cookies.md", "config.py",
])
def test_source_documentation_and_empty_environment_example_are_allowed(path):
    assert scanner.scan_blob(path, b"") == []


@pytest.mark.parametrize("value", ["", "YOUR_API_KEY", "<your_api_key>", "${OPENAI_API_KEY}",
                                         "$env:OPENAI_API_KEY", "{CANDIDATE}"])
def test_placeholders_are_allowed(value):
    assert scanner.scan_blob("config.py", f"api_key = {json.dumps(value)}".encode()) == []


def test_runtime_references_and_default_types_are_not_credentials():
    text = '\n'.join([
        'openai_api_key = os.getenv("ZHIJING_OPENAI_API_KEY", "")',
        'api_key: str = ""',
        'access_secret=secret',
        '"api_key": settings.openai_api_key',
    ])
    assert scanner.scan_blob("config.py", text.encode()) == []


@pytest.mark.parametrize("assignment", [
    'api_key = "{}"', "access_secret='{}'", '"ZHIHU_ACCESS_SECRET": "{}"',
    '"openai_api_key": "{}"', 'apiKey: "{}"',
])
def test_literal_sensitive_fields_are_detected_without_special_key_prefix(assignment):
    value = "synthetic-" + "case-literal-value"
    assert any(f.rule == "credential_literal" for f in scanner.scan_blob(
        "config.py", assignment.format(value).encode()
    ))


@pytest.mark.parametrize("prefix", ["sk-", "ghp_", "gho_", "ghu_", "ghs_", "ghr_", "github_pat_"])
def test_known_token_formats_are_detected_in_unrelated_text(prefix):
    assert scanner.scan_blob("README.md", ("token: " + prefix + "A1b2C3d4" * 6).encode())


def test_private_key_block_is_rejected_in_arbitrary_file():
    header = "-----BEGIN " + "OPENSSH PRIVATE KEY-----"
    assert scanner.scan_blob("notes.txt", header.encode())[0].rule == "private_key"


def test_utf16_environment_example_is_scanned():
    field = "ZHIHU_ACCESS_SECRET"
    value = field + "=" + "a1b2c3d4" * 5
    assert scanner.scan_blob(".env.example", value.encode("utf-16"))


def test_environment_and_yaml_plain_values_are_scanned():
    value = "a1b2c3d4" * 5
    assert scanner.scan_blob(".env.example", f"OPENAI_API_KEY={value}\n".encode())
    assert scanner.scan_blob("config.yml", f"api_key: {value}\n".encode())
    assert scanner.scan_blob("config.yml", b"api_key: ${{ secrets.OPENAI_API_KEY }}") == []
    assert scanner.scan_blob(".env.example", b"OPENAI_API_KEY=\n") == []


@pytest.mark.parametrize("command", ["set {}={}", 'set "{}={}"', "@SET {}={}", 'set {}="{}"'])
def test_windows_cmd_unquoted_sensitive_values_are_detected(command):
    value = "0123456789abcdef" * 2 + "01234567"
    text = command.format("ZHIHU_ACCESS_SECRET", value)
    findings = scanner.scan_blob("launch.cmd", text.encode())
    assert any(item.rule == "credential_literal" for item in findings)
    assert value not in repr(findings)


@pytest.mark.parametrize("value", ["", "%ZHIHU_ACCESS_SECRET%", "!ZHIHU_ACCESS_SECRET!", "YOUR_ACCESS_SECRET"])
@pytest.mark.parametrize("command", ["set {}={}", 'set "{}={}"'])
def test_windows_cmd_references_and_placeholders_are_allowed(command, value):
    text = command.format("ZHIHU_ACCESS_SECRET", value)
    assert scanner.scan_blob("launch.cmd", text.encode()) == []


def test_non_dot_environment_file_unquoted_value_is_detected():
    field = "ZHIHU_ACCESS_SECRET"
    value = "0123456789abcdef" * 2 + "01234567"
    assert scanner.scan_blob("local.env", f"{field}={value}".encode())
    assert scanner.scan_blob("local.env", f"{field}=${{{field}}}".encode()) == []
    assert scanner.scan_blob("LOCAL.ENV", f"{field}={value}".encode())


@pytest.mark.parametrize("quote", ['"""', "'''"])
@pytest.mark.parametrize("multiline", [False, True])
def test_triple_quoted_sensitive_value_is_not_an_empty_placeholder(quote, multiline):
    value = "0123456789abcdef" * 2 + "01234567"
    if multiline:
        value = "\n" + value + "\n"
    text = f"# Config\napi_key = {quote}{value}{quote}"
    findings = scanner.scan_blob("config.toml", text.encode())
    assert any(item.line == 2 and item.rule == "credential_literal" for item in findings)


@pytest.mark.parametrize("quote", ['"""', "'''"])
@pytest.mark.parametrize("value", ["", "YOUR_API_KEY", "${OPENAI_API_KEY}"])
def test_triple_quoted_placeholders_and_references_are_allowed(quote, value):
    text = f"api_key = {quote}\n{value}\n{quote}"
    assert scanner.scan_blob("config.toml", text.encode()) == []


def test_fixture_allowance_requires_exact_path_and_exact_value():
    fixture_path = "tests/test_provider_verification.py"
    fixture_value = "sk-" + "do-not-report-very-secret"
    assert scanner.scan_blob(fixture_path, fixture_value.encode()) == []
    assert scanner.scan_blob("tests/unrelated.py", fixture_value.encode())
    assert scanner.scan_blob(fixture_path, CANDIDATE.encode())
    for alias in ["./" + fixture_path, "nested/../" + fixture_path,
                  fixture_path.replace("/", "\\"), "/" + fixture_path,
                  "nested/" + fixture_path, "TESTS/test_provider_verification.py"]:
        assert scanner.scan_blob(alias, fixture_value.encode())


def test_index_secret_is_caught_after_working_tree_is_cleaned(repository):
    path = repository / "app.py"
    path.write_text(f'api_key = "{CANDIDATE}"\n', encoding="utf-8")
    git(repository, "add", "app.py")
    path.write_text('api_key = ""\n', encoding="utf-8")
    findings = scanner.scan_repository(repository, staged=True)
    assert findings and {item.path for item in findings} == {"app.py"}
    assert scanner.scan_repository(repository) == []


def test_head_scan_reads_committed_objects_not_working_tree(repository):
    path = repository / "app.py"
    path.write_text(f'api_key = "{CANDIDATE}"\n', encoding="utf-8")
    git(repository, "add", "app.py")
    git(repository, "commit", "--quiet", "-m", "Synthetic unsafe fixture")
    path.write_text('api_key = ""\n', encoding="utf-8")
    assert scanner.scan_repository(repository)


def test_index_scan_checks_unchanged_files_and_honors_staged_deletion(repository):
    path = repository / "private.key"
    path.write_bytes(b"")
    git(repository, "add", "private.key")
    git(repository, "commit", "--quiet", "-m", "Empty prohibited fixture")
    assert any(item.path == "private.key" for item in scanner.scan_repository(repository, staged=True))
    git(repository, "rm", "--cached", "private.key")
    assert scanner.scan_repository(repository, staged=True) == []


def test_command_diagnostics_never_include_credential_content(repository):
    (repository / "app.py").write_text(f'api_key = "{CANDIDATE}"\n', encoding="utf-8")
    git(repository, "add", "app.py")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repository), "--staged"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    assert '"app.py":1: api_token' in result.stdout
    assert CANDIDATE not in result.stdout + result.stderr
    assert "api_key =" not in result.stdout + result.stderr


def test_failed_git_reads_fail_closed_without_echoing_untrusted_path(tmp_path, capsys):
    location = tmp_path / CANDIDATE
    assert scanner.main(["--repo", str(location)]) == 2
    output = capsys.readouterr()
    assert CANDIDATE not in output.out + output.err
