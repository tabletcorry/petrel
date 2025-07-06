import subprocess

import pytest
from click.testing import CliRunner

import petrel.main as main_module
from petrel.main import ContainerError, _run, ensure_container_running, main


class DummyCompleted(subprocess.CompletedProcess):
    def __init__(self, stdout: str, returncode: int = 0):
        super().__init__(args=[], returncode=returncode, stdout=stdout, stderr="")


def test_run_success():
    cp = _run(["echo", "hello"], check=True, capture_output=True)
    assert cp.stdout.strip() == "hello"
    assert cp.returncode == 0


def test_run_no_check():
    cp = _run(["false"], check=False, capture_output=True)
    assert cp.returncode != 0


def test_run_check_raises():
    with pytest.raises(subprocess.CalledProcessError):
        _run(["false"], check=True, capture_output=True)


def test_ensure_container_running_cli_not_found(monkeypatch):
    def fake_run(cmd, check=True, capture_output=False):
        raise FileNotFoundError

    monkeypatch.setattr(main_module, "_run", fake_run)
    with pytest.raises(ContainerError) as excinfo:
        ensure_container_running(auto_start=False)
    assert "The 'container' CLI was not found" in str(excinfo.value)


def test_ensure_container_running_already_running(monkeypatch):
    monkeypatch.setattr(
        main_module,
        "_run",
        lambda cmd, check=True, capture_output=False: DummyCompleted(
            stdout="   running\n"
        ),
    )
    # Should not raise when status contains 'running'
    ensure_container_running(auto_start=False)


def test_ensure_container_running_no_auto_start_when_stopped(monkeypatch):
    monkeypatch.setattr(
        main_module,
        "_run",
        lambda cmd, check=True, capture_output=True: DummyCompleted(stdout="stopped"),
    )
    with pytest.raises(ContainerError) as excinfo:
        ensure_container_running(auto_start=False)
    assert (
        "Apple container subsystem is not running. Start it with: container system start"
        in str(excinfo.value)
    )


def test_ensure_container_running_auto_start_success(monkeypatch):
    calls = []

    def fake_run(cmd, check=True, capture_output=False):
        calls.append(cmd)
        if cmd[:3] == ["container", "system", "status"]:
            return DummyCompleted(stdout="stopped")
        if cmd[:3] == ["container", "system", "start"]:
            return DummyCompleted(stdout="")
        pytest.skip(f"Unexpected command: {cmd}")

    monkeypatch.setattr(main_module, "_run", fake_run)
    ensure_container_running(auto_start=True)
    assert ["container", "system", "status"] in calls
    assert ["container", "system", "start"] in calls


def test_ensure_container_running_auto_start_failure(monkeypatch):
    def fake_run(cmd, check=True, capture_output=False):
        if cmd[:3] == ["container", "system", "status"]:
            return DummyCompleted(stdout="stopped")
        raise subprocess.CalledProcessError(returncode=1, cmd=cmd)

    monkeypatch.setattr(main_module, "_run", fake_run)
    with pytest.raises(ContainerError) as excinfo:
        ensure_container_running(auto_start=True)
    assert "Failed to start the Apple container subsystem." in str(excinfo.value)


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "Usage" in result.output


def test_cli_codex_help():
    runner = CliRunner()
    result = runner.invoke(main, ["codex", "--help"])
    assert result.exit_code == 0
    assert "Run the Codex container" in result.output


def test_cli_build_help():
    runner = CliRunner()
    result = runner.invoke(main, ["build", "--help"])
    assert result.exit_code == 0
    assert "Build the container image using the Dockerfile." in result.output


def test_cli_build_error_when_not_running(monkeypatch):
    def fake_ensure(auto_start):
        raise ContainerError("failed to start")

    monkeypatch.setattr(main_module, "ensure_container_running", fake_ensure)
    runner = CliRunner()
    result = runner.invoke(main, ["build"])
    assert result.exit_code == 1
    assert "Error: failed to start" in result.output
