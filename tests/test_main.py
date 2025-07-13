from __future__ import annotations

import json
import os
import shutil

# ruff: noqa: S101
import subprocess  # noqa: S404 -- used in testing
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

if TYPE_CHECKING:
    from importlib.resources.abc import Traversable

import pytest
from click.testing import CliRunner

import petrel.main as main_module
from petrel.main import (
    ContainerError,
    ensure_container_running,
    get_codex_version,
    main,
    render_template,
)


class DummyCompleted(subprocess.CompletedProcess[str]):
    def __init__(self, stdout: str, returncode: int = 0) -> None:
        super().__init__(args=[], returncode=returncode, stdout=stdout, stderr="")


def test_run_success() -> None:
    cp = main_module._run(["echo", "hello"], check=True, capture_output=True)  # noqa: SLF001
    assert cp.stdout.strip() == "hello"
    assert cp.returncode == 0


def test_run_no_check() -> None:
    cp = main_module._run(["false"], check=False, capture_output=True)  # noqa: SLF001
    assert cp.returncode != 0


def test_run_check_raises() -> None:
    with pytest.raises(subprocess.CalledProcessError):
        main_module._run(["false"], check=True, capture_output=True)  # noqa: SLF001


def test_get_codex_version(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(
        cmd: list[str], check: bool = True, capture_output: bool = False
    ) -> DummyCompleted:
        _ = check, capture_output
        assert cmd == ["codex", "--version"]
        return DummyCompleted(stdout="codex-cli 9.9.9")

    monkeypatch.setattr(main_module, "_run", fake_run)
    assert get_codex_version() == "9.9.9"


def test_ensure_container_running_cli_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(
        _cmd: list[str], check: bool = True, capture_output: bool = False
    ) -> None:
        _ = check, capture_output, _cmd
        raise FileNotFoundError

    monkeypatch.setattr(main_module, "_run", fake_run)
    with pytest.raises(ContainerError) as excinfo:
        ensure_container_running(auto_start=False)
    assert "The 'container' CLI was not found" in str(excinfo.value)


def test_ensure_container_running_already_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(
        _cmd: list[str], check: bool = True, capture_output: bool = False
    ) -> DummyCompleted:
        _ = check, capture_output, _cmd
        return DummyCompleted(stdout="   running\n")

    monkeypatch.setattr(main_module, "_run", fake_run)
    # Should not raise when status contains 'running'
    ensure_container_running(auto_start=False)


def test_ensure_container_running_no_auto_start_when_stopped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(
        _cmd: list[str], check: bool = True, capture_output: bool = True
    ) -> DummyCompleted:
        _ = check, capture_output, _cmd
        return DummyCompleted(stdout="stopped", returncode=1)

    monkeypatch.setattr(main_module, "_run", fake_run)
    with pytest.raises(ContainerError) as excinfo:
        ensure_container_running(auto_start=False)
    assert (
        "Apple container subsystem is not running. Start it with:"
        " container system start" in str(excinfo.value)
    )


def test_ensure_container_running_auto_start_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def fake_run(
        cmd: list[str], check: bool = True, capture_output: bool = False
    ) -> DummyCompleted:
        _ = check, capture_output
        calls.append(cmd)
        if cmd[:3] == ["container", "system", "status"]:
            return DummyCompleted(stdout="stopped", returncode=1)
        if cmd[:3] == ["container", "system", "start"]:
            return DummyCompleted(stdout="")
        pytest.skip(f"Unexpected command: {cmd}")

    monkeypatch.setattr(main_module, "_run", fake_run)
    ensure_container_running(auto_start=True)
    assert ["container", "system", "status"] in calls
    assert ["container", "system", "start"] in calls


def test_ensure_container_running_auto_start_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(
        cmd: list[str], check: bool = True, capture_output: bool = False
    ) -> DummyCompleted:
        _ = check, capture_output
        if cmd[:3] == ["container", "system", "status"]:
            return DummyCompleted(stdout="stopped", returncode=1)
        raise subprocess.CalledProcessError(returncode=1, cmd=cmd)

    monkeypatch.setattr(main_module, "_run", fake_run)
    with pytest.raises(ContainerError) as excinfo:
        ensure_container_running(auto_start=True)
    assert "Failed to start the Apple container subsystem." in str(excinfo.value)


def test_cli_help() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "Usage" in result.output


def test_cli_codex_help() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["codex", "--help"])
    assert result.exit_code == 0
    assert "Run the Codex container" in result.output


def test_cli_build_help() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["build", "--help"])
    assert result.exit_code == 0
    assert "Build the container image using the Dockerfile template." in result.output


def test_cli_build_error_when_not_running(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_ensure(auto_start: bool) -> None:
        _ = auto_start
        raise ContainerError("failed to start")

    monkeypatch.setattr(main_module, "ensure_container_running", fake_ensure)
    runner = CliRunner()
    result = runner.invoke(main, ["build"])
    assert result.exit_code == 1
    assert "Error: failed to start" in result.output


def test_render_template_basic(tmp_path: Path) -> None:
    tpl = tmp_path / "Dockerfile.j2"
    tpl.write_text("Hello {{ name }}")
    rendered = render_template(tpl, {"name": "World"})
    assert rendered == "Hello World"


def test_cli_dockerfile_outputs_rendered(tmp_path: Path) -> None:
    tpl = tmp_path / "Dockerfile.j2"
    tpl.write_text("FROM python")
    runner = CliRunner()
    result = runner.invoke(main, ["dockerfile", "--file", str(tpl)])
    assert result.exit_code == 0
    assert result.output.strip() == "FROM python"


def test_cli_dockerfile_default_uses_package_template() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["dockerfile"])
    assert result.exit_code == 0
    assert "FROM debian:latest" in result.output


def test_cli_build_uses_tempfile(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, Any] = {"cmds": []}

    def fake_render(
        path: Path | Traversable, _context: dict[str, str] | None = None
    ) -> str:
        calls["template"] = path
        return "FROM python"

    def fake_run(
        cmd: list[str], check: bool = True, capture_output: bool = False
    ) -> DummyCompleted:
        _ = check, capture_output
        calls["cmds"].append(cmd)
        return DummyCompleted(stdout="")

    monkeypatch.setattr(main_module, "render_template", fake_render)
    monkeypatch.setattr(main_module, "_run", fake_run)

    runner = CliRunner()
    result = runner.invoke(main, ["build", "--context", str(Path.cwd())])
    assert result.exit_code == 0
    build_cmd = next(c for c in calls["cmds"] if c[:2] == ["container", "build"])
    dockerfile_index = build_cmd.index("--file") + 1
    dockerfile_path = Path(build_cmd[dockerfile_index])
    assert not dockerfile_path.exists()
    assert dockerfile_path.name.startswith("tmp")


def test_cli_build_tags_include_version(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, Any] = {"cmds": []}

    def fake_run(
        cmd: list[str], check: bool = True, capture_output: bool = False
    ) -> DummyCompleted:
        _ = check, capture_output
        if cmd[:2] == ["codex", "--version"]:
            return DummyCompleted(stdout="codex-cli 1.2.3")
        if cmd[:3] == ["container", "system", "status"]:
            return DummyCompleted(stdout="running")
        calls["cmds"].append(cmd)
        return DummyCompleted(stdout="")

    monkeypatch.setattr(main_module, "_run", fake_run)
    monkeypatch.setattr(
        main_module, "render_template", lambda *_args, **_kwargs: "FROM python"
    )

    runner = CliRunner()
    result = runner.invoke(
        main, ["build", "--context", str(Path.cwd()), "--tag", "codex"]
    )
    assert result.exit_code == 0
    build_cmd = next(c for c in calls["cmds"] if c[:2] == ["container", "build"])
    assert any(part.startswith("codex:1.2.3") for part in build_cmd)


def test_cli_build_rebuild_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, Any] = {"cmds": []}

    def fake_render(
        path: Path | Traversable, _context: dict[str, str] | None = None
    ) -> str:
        calls["template"] = path
        return "FROM python"

    def fake_run(
        cmd: list[str], check: bool = True, capture_output: bool = False
    ) -> DummyCompleted:
        _ = check, capture_output
        calls["cmds"].append(cmd)
        return DummyCompleted(stdout="")

    monkeypatch.setattr(main_module, "render_template", fake_render)
    monkeypatch.setattr(main_module, "_run", fake_run)

    runner = CliRunner()
    result = runner.invoke(main, ["build", "--context", str(Path.cwd()), "--rebuild"])
    assert result.exit_code == 0
    build_cmd = next(c for c in calls["cmds"] if c[:2] == ["container", "build"])
    assert "--no-cache" in build_cmd


def test_cli_error_when_container_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _cmd: None)
    runner = CliRunner()
    result = runner.invoke(main, ["codex"])
    assert result.exit_code == 1
    assert "brew install container" in result.output


def test_cli_codex_builds_when_image_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(
        cmd: list[str], check: bool = True, capture_output: bool = False
    ) -> DummyCompleted:
        _ = check, capture_output
        calls.append(cmd)
        if cmd[:2] == ["codex", "--version"]:
            return DummyCompleted(stdout="codex-cli 1.0.0")
        if cmd[:3] == ["container", "system", "status"]:
            return DummyCompleted(stdout="running")
        if cmd[:3] == ["container", "images", "inspect"]:
            return DummyCompleted(stdout="", returncode=1)
        if cmd[:2] == ["container", "build"]:
            return DummyCompleted(stdout="")
        raise AssertionError(f"Unexpected command: {cmd}")

    monkeypatch.setattr(main_module, "_run", fake_run)
    monkeypatch.setattr(click, "confirm", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(os, "execvp", lambda _prog, _args: None)

    runner = CliRunner()
    result = runner.invoke(main, ["codex"])
    assert result.exit_code == 0
    assert any(call[:2] == ["container", "build"] for call in calls)


def test_cli_build_applies_missing_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(
        cmd: list[str], check: bool = True, capture_output: bool = False
    ) -> DummyCompleted:
        _ = check, capture_output
        calls.append(cmd)
        if cmd[:2] == ["codex", "--version"]:
            return DummyCompleted(stdout="codex-cli 1.2.3")
        if cmd[:3] == ["container", "system", "status"]:
            return DummyCompleted(stdout="running")
        if cmd[:2] == ["container", "build"]:
            return DummyCompleted(stdout="")
        if cmd[:3] == ["container", "images", "inspect"]:
            tag = cmd[3]
            if tag.endswith("latest"):
                return DummyCompleted(stdout="")
            return DummyCompleted(stdout="", returncode=1)
        if cmd[:3] == ["container", "image", "tag"]:
            return DummyCompleted(stdout="")
        raise AssertionError(f"Unexpected command: {cmd}")

    monkeypatch.setattr(main_module, "_run", fake_run)
    monkeypatch.setattr(
        main_module, "render_template", lambda *_args, **_kwargs: "FROM python"
    )

    runner = CliRunner()
    result = runner.invoke(
        main, ["build", "--context", str(Path.cwd()), "--tag", "codex"]
    )
    assert result.exit_code == 0
    assert ["container", "image", "tag", "codex:latest", "codex:1.2.3"] in calls


def test_cli_build_skips_tag_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(
        cmd: list[str], check: bool = True, capture_output: bool = False
    ) -> DummyCompleted:
        _ = check, capture_output
        calls.append(cmd)
        if cmd[:2] == ["codex", "--version"]:
            return DummyCompleted(stdout="codex-cli 1.2.3")
        if cmd[:3] == ["container", "system", "status"]:
            return DummyCompleted(stdout="running")
        if cmd[:2] == ["container", "build"]:
            return DummyCompleted(stdout="")
        if cmd[:3] == ["container", "images", "inspect"]:
            return DummyCompleted(stdout="")
        if cmd[:3] == ["container", "image", "tag"]:
            return DummyCompleted(stdout="")
        raise AssertionError(f"Unexpected command: {cmd}")

    monkeypatch.setattr(main_module, "_run", fake_run)
    monkeypatch.setattr(
        main_module, "render_template", lambda *_args, **_kwargs: "FROM python"
    )

    runner = CliRunner()
    result = runner.invoke(
        main, ["build", "--context", str(Path.cwd()), "--tag", "codex"]
    )
    assert result.exit_code == 0
    assert not any(call[:3] == ["container", "image", "tag"] for call in calls)


def test_cli_codex_abort_when_image_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(
        cmd: list[str], check: bool = True, capture_output: bool = False
    ) -> DummyCompleted:
        _ = check, capture_output
        if cmd[:2] == ["codex", "--version"]:
            return DummyCompleted(stdout="codex-cli 1.0.0")
        if cmd[:3] == ["container", "system", "status"]:
            return DummyCompleted(stdout="running")
        if cmd[:3] == ["container", "images", "inspect"]:
            return DummyCompleted(stdout="", returncode=1)
        raise AssertionError(f"Unexpected command: {cmd}")

    monkeypatch.setattr(main_module, "_run", fake_run)
    monkeypatch.setattr(click, "confirm", lambda *_args, **_kwargs: False)

    runner = CliRunner()
    result = runner.invoke(main, ["codex"])
    assert result.exit_code == 1


def test_cli_codex_rebuild_for_new_version(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(
        cmd: list[str], check: bool = True, capture_output: bool = False
    ) -> DummyCompleted:
        _ = check, capture_output
        calls.append(cmd)
        if cmd[:2] == ["codex", "--version"]:
            return DummyCompleted(stdout="codex-cli 1.2.3")
        if cmd[:3] == ["container", "system", "status"]:
            return DummyCompleted(stdout="running")
        if cmd[:3] == ["container", "images", "inspect"]:
            if cmd[3].endswith("1.2.3"):
                return DummyCompleted(stdout="", returncode=1)
            return DummyCompleted(stdout="")
        if cmd[:2] == ["container", "build"]:
            return DummyCompleted(stdout="")
        if cmd[:3] == ["container", "image", "tag"]:
            return DummyCompleted(stdout="")
        raise AssertionError(f"Unexpected command: {cmd}")

    monkeypatch.setattr(main_module, "_run", fake_run)
    monkeypatch.setattr(click, "confirm", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(os, "execvp", lambda _prog, _args: None)

    runner = CliRunner()
    result = runner.invoke(main, ["codex"])
    assert result.exit_code == 0
    assert any(call[:2] == ["container", "build"] for call in calls)


def test_cli_codex_skip_rebuild_for_new_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(
        cmd: list[str], check: bool = True, capture_output: bool = False
    ) -> DummyCompleted:
        _ = check, capture_output
        calls.append(cmd)
        if cmd[:2] == ["codex", "--version"]:
            return DummyCompleted(stdout="codex-cli 1.2.3")
        if cmd[:3] == ["container", "system", "status"]:
            return DummyCompleted(stdout="running")
        if cmd[:3] == ["container", "images", "inspect"]:
            if cmd[3].endswith("1.2.3"):
                return DummyCompleted(stdout="", returncode=1)
            return DummyCompleted(stdout="")
        raise AssertionError(f"Unexpected command: {cmd}")

    monkeypatch.setattr(main_module, "_run", fake_run)
    monkeypatch.setattr(click, "confirm", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(os, "execvp", lambda _prog, _args: None)

    runner = CliRunner()
    result = runner.invoke(main, ["codex"])
    assert result.exit_code == 0
    assert not any(call[:2] == ["container", "build"] for call in calls)


def test_cli_codex_prompt_when_latest_outdated(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(
        cmd: list[str], check: bool = True, capture_output: bool = False
    ) -> DummyCompleted:
        _ = check, capture_output
        calls.append(cmd)
        if cmd[:2] == ["codex", "--version"]:
            return DummyCompleted(stdout="codex-cli 1.2.3")
        if cmd[:3] == ["container", "system", "status"]:
            return DummyCompleted(stdout="running")
        if cmd[:3] == ["container", "images", "inspect"]:
            tag = cmd[3]
            if tag.endswith("latest") or tag == "codex":
                data = [{"RepoTags": ["codex:latest", "codex:1.2.0"]}]
                return DummyCompleted(stdout=json.dumps(data))
            if tag.endswith("1.2.3"):
                data = [{"RepoTags": ["codex:1.2.3"]}]
                return DummyCompleted(stdout=json.dumps(data))
        if cmd[:2] == ["container", "build"]:
            return DummyCompleted(stdout="")
        raise AssertionError(f"Unexpected command: {cmd}")

    monkeypatch.setattr(main_module, "_run", fake_run)
    monkeypatch.setattr(click, "confirm", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(os, "execvp", lambda _prog, _args: None)

    runner = CliRunner()
    result = runner.invoke(main, ["codex"])
    assert result.exit_code == 0
    assert any(call[:2] == ["container", "build"] for call in calls)
