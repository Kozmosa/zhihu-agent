import json
import subprocess
import sys
from pathlib import Path

import pytest

from zhijing.core.config import Settings
from zhijing.verification.__main__ import main
from zhijing.verification.fixtures import model_response
from zhijing.verification.runner import CAPABILITIES, CheckFailure, check_result, run_verification


@pytest.mark.parametrize("provider", ["extractive", "ollama", "openai"])
def test_independent_capabilities_use_isolated_data_and_report_actual_mode(tmp_path, provider):
    configured_data = tmp_path / "actual-data"
    configured_data.mkdir()
    sentinel = configured_data / "do-not-touch.txt"
    sentinel.write_text("existing user data", encoding="utf-8")
    work = tmp_path / "verification"
    report = run_verification(
        Settings(data_dir=configured_data, model_provider=provider), mode="mock", work_root=work
    )
    assert report["passed"]
    assert [case["capability"] for case in report["cases"]] == list(CAPABILITIES)
    assert all(case["response_mode"] == provider for case in report["cases"])
    assert report["quality_status"] == "not_evaluated"
    assert report["live_model_validation_passed"] is False
    assert report["transport"]["requests"] == (0 if provider == "extractive" else 5)
    assert sentinel.read_text("utf-8") == "existing user data"
    assert list(configured_data.iterdir()) == [sentinel]
    assert list(work.iterdir()) == []


@pytest.mark.parametrize("provider", ["ollama", "openai"])
def test_upstream_http_success_is_distinct_from_evidence_validation_and_continues(
    tmp_path, provider
):
    def invalid_card(prompt):
        result = model_response(prompt)
        if prompt["task"] == "cards":
            result["cards"][0]["evidence_excerpt"] = "Invented evidence absent from the source."
        return result

    report = run_verification(
        Settings(data_dir=tmp_path, model_provider=provider),
        mode="mock",
        work_root=tmp_path,
        responder=invalid_card,
    )
    assert report["passed"] is False
    assert report["admission"] == "rejected"
    failed = report["cases"][1]
    assert failed["capability"] == "cards"
    assert failed["reason"] == "cards_evidence_invalid"
    assert failed["transport"]["http_success_received"] is True
    assert failed["application_validation_passed"] is False
    assert failed["http_status"] == 502
    assert all(case["passed"] for case in report["cases"] if case is not failed)
    assert report["mock_model_calls"] == list(CAPABILITIES)


@pytest.mark.parametrize("provider", ["ollama", "openai"])
def test_transport_rejection_records_response_and_checks_other_capabilities(tmp_path, provider):
    def broken_reading(prompt):
        if prompt["task"] == "reading":
            raise ValueError("sensitive-upstream-text-that-must-not-be-reported")
        return model_response(prompt)

    report = run_verification(
        Settings(data_dir=tmp_path, model_provider=provider),
        mode="mock",
        work_root=tmp_path,
        responder=broken_reading,
    )
    reading = report["cases"][0]
    assert reading["passed"] is False
    assert reading["transport"]["http_response_received"] is True
    assert reading["transport"]["http_success_received"] is False
    assert all(case["passed"] for case in report["cases"][1:])
    assert "sensitive-upstream" not in json.dumps(report)


def test_configuration_rejection_keeps_five_statuses_and_omits_secrets(tmp_path):
    secret = "sk-do-not-report-very-secret"
    report = run_verification(
        Settings(
            data_dir=tmp_path,
            model_provider="openai",
            openai_model="example-model",
            openai_url=f"https://username:{secret}@private.example/v1?key={secret}",
            openai_api_key=secret,
        ),
        mode="live",
        work_root=tmp_path,
    )
    encoded = json.dumps(report)
    assert report["reason"] == "invalid_configuration"
    assert len(report["cases"]) == 5
    assert all(case["status"] == "not_run" for case in report["cases"])
    assert report["transport"]["requests"] == 0
    assert secret not in encoded
    assert "private.example" not in encoded


def test_actual_mode_mismatch_is_not_a_model_success():
    with pytest.raises(CheckFailure, match="unexpected_provider_mode"):
        check_result("author", {"mode": "extractive"}, "openai", "source", {})


@pytest.mark.parametrize("provider", ["extractive", "ollama", "openai"])
def test_optional_workflow_reloads_all_results_and_replay_does_not_call_model(tmp_path, provider):
    report = run_verification(
        Settings(data_dir=tmp_path, model_provider=provider),
        mode="mock",
        work_root=tmp_path,
        include_workflow=True,
    )
    assert report["passed"], report["workflow"]
    workflow = report["workflow"]
    assert workflow["status"] == "passed"
    assert workflow["persisted_result_reloaded"]
    assert workflow["idempotent_replay_without_model_calls"]
    assert len(workflow["steps"]) == 5
    assert report["transport"]["requests"] == (0 if provider == "extractive" else 10)


def test_cli_requires_explicit_model_mode(capsys):
    with pytest.raises(SystemExit) as error:
        main(["--provider", "openai"])
    assert error.value.code == 2
    assert "explicit --mock or --live" in capsys.readouterr().err


def test_cli_help_has_no_import_warnings_or_network():
    result = subprocess.run(
        [sys.executable, "-B", "-m", "zhijing.verification", "--help"],
        cwd=Path(__file__).resolve().parents[1] / "src",
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0
    assert "--prompt-key" in result.stdout
    assert result.stderr == ""


def test_cli_offline_ignores_unrelated_invalid_provider_environment(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ZHIJING_OPENAI_TIMEOUT", "invalid-secret-number")
    monkeypatch.setenv("ZHIJING_OPENAI_API_KEY", "sk-environment-secret")
    output = tmp_path / "report.json"
    code = main(
        [
            "--provider",
            "extractive",
            "--mock",
            "--report",
            str(output),
            "--work-root",
            str(tmp_path / "work"),
        ]
    )
    assert code == 0
    report_text = output.read_text("utf-8")
    assert json.loads(report_text)["passed"]
    assert "secret" not in report_text
    assert "secret" not in capsys.readouterr().out


def test_cli_refuses_echoing_key_input(tmp_path, monkeypatch, capsys):
    import getpass
    import warnings

    def unsafe_getpass(_prompt):
        warnings.warn("Cannot control echo", getpass.GetPassWarning, stacklevel=2)
        raise AssertionError("Must refuse before any echoing input is read")

    monkeypatch.setattr(getpass, "getpass", unsafe_getpass)
    code = main(
        [
            "--provider",
            "openai",
            "--live",
            "--model",
            "example-model",
            "--prompt-key",
            "--work-root",
            str(tmp_path),
        ]
    )
    report = json.loads(capsys.readouterr().out)
    assert code == 1
    assert report["error_type"] == "GetPassWarning"
    assert all(case["status"] == "not_run" for case in report["cases"])
