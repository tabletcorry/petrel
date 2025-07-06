# ruff: noqa: S606, S404, S603, PLR0913
from __future__ import annotations

import hashlib
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import click


class ContainerError(RuntimeError):
    """Raised when the Apple container subsystem or CLI fails."""


def _run(
    cmd: list[str], *, check: bool = True, capture_output: bool = False
) -> subprocess.CompletedProcess[str]:
    """
    Thin wrapper around subprocess.run with sane defaults.

    Args:
        cmd: Command and arguments.
        check: If True, raise on non-zero exit.
        capture_output: If True, capture and return stdout/stderr.

    Returns:
        subprocess.CompletedProcess
    """
    return subprocess.run(cmd, text=True, capture_output=capture_output, check=check)


def ensure_container_running(auto_start: bool = True) -> None:
    """
    Verify that the Apple container subsystem is running and optionally start it.

    Args:
        auto_start: If True, attempt to start the subsystem if it is stopped.

    Raises:
        ContainerError: When the subsystem is not running and cannot be started.
    """
    try:
        status_cp = _run(["container", "system", "status"], capture_output=True)
    except FileNotFoundError as exc:
        raise ContainerError(
            "The 'container' CLI was not found. "
            "Ensure you are running macOS with the new Apple container subsystem."
        ) from exc

    status = status_cp.stdout.strip().lower()
    if "running" in status:
        return

    if not auto_start:
        raise ContainerError(
            "Apple container subsystem is not running. "
            "Start it with: container system start"
        )

    click.echo(
        click.style(
            "Apple container subsystem is not running - starting it now…", fg="yellow"
        )
    )
    try:
        _run(["container", "system", "start"])
    except subprocess.CalledProcessError as exc:
        raise ContainerError("Failed to start the Apple container subsystem.") from exc


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.pass_context
def main(ctx: click.Context) -> None:
    """Petrel CLI entry point."""
    if shutil.which("container") is None:
        click.echo(
            click.style(
                (
                    "The 'container' program was not found. Install it first "
                    "(e.g. `brew install container`)."
                ),
                fg="red",
            ),
            err=True,
        )
        ctx.exit(1)


@main.command(name="codex", context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--name",
    "-n",
    default="codex-test",
    show_default=True,
    help="Name for the running container instance.",
)
@click.option(
    "--persistent-dir",
    type=click.Path(path_type=Path, exists=False),
    default=Path.home() / ".codex-container",
    show_default=lambda: f"{Path.home() / '.codex-container'}",
    help="Host directory to persist Codex data (mounted read-write).",
)
@click.option(
    "--dest-dir",
    default="/home/linuxbrew/.codex",
    show_default=True,
    help="Destination path inside the container for the persistent directory.",
)
@click.option(
    "--repo-dir",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    default=Path.cwd(),
    show_default=lambda: f"{Path.cwd()}",
    help="Path to the local repository to bind-mount inside the container.",
)
@click.option(
    "--image",
    default="codex",
    show_default=True,
    help="Container image name (tag may be appended, e.g. 'codex:latest').",
)
@click.option(
    "--codex-path",
    default="/home/linuxbrew/.linuxbrew/bin/codex",
    show_default=True,
    help="Path to the Codex executable inside the container.",
)
@click.option(
    "--shell/--no-shell",
    default=False,
    help="Launch an interactive shell instead of Codex (debug aid).",
)
@click.option(
    "--no-auto-start",
    is_flag=True,
    help="Do not attempt to auto-start the container subsystem; error instead.",
)
@click.argument("extra", nargs=-1, type=click.UNPROCESSED)
def codex(
    *,
    name: str,
    persistent_dir: Path,
    dest_dir: str,
    repo_dir: Path,
    image: str,
    codex_path: str,
    shell: bool,
    no_auto_start: bool,
    extra: tuple[str, ...],
) -> None:
    """
    Run the Codex container with sensible defaults.

    Any EXTRA arguments are passed verbatim to the container's entry command.
    """
    try:
        ensure_container_running(auto_start=not no_auto_start)
    except ContainerError as exc:
        click.echo(click.style(f"Error: {exc}", fg="red"), err=True)
        sys.exit(1)

    # Ensure the persistent directory exists so `--mount src=…` never errors.
    persistent_dir.mkdir(parents=True, exist_ok=True)

    # Ensure a per-repo cache for Python venv in ~/.cache/petrel/<repo>-<hash>/.venv
    cache_base = Path.home() / ".cache" / "petrel"
    cache_base.mkdir(parents=True, exist_ok=True)
    # Use repo name plus an 8-char hash of its absolute path to avoid collisions
    repo_key = hashlib.sha256(str(repo_dir.resolve()).encode()).hexdigest()[:8]
    repo_cache = cache_base / f"{repo_dir.resolve().name}-{repo_key}"
    repo_cache.mkdir(parents=True, exist_ok=True)
    venv_cache_dir = repo_cache / ".venv"
    venv_cache_dir.mkdir(parents=True, exist_ok=True)

    uv_cache_dir = cache_base / "uv_cache"
    uv_cache_dir.mkdir(parents=True, exist_ok=True)

    # Construct the base container command.
    container_cmd: list[str] = [
        "container",
        "run",
        "--name",
        name,
        "--rm",
        "-it",
        "-v",
        f"{repo_dir}:/home/linuxbrew/repo",
        "--mount",
        f"src={persistent_dir},dst={dest_dir}",
        "--mount",
        f"src={uv_cache_dir},dst=/home/linuxbrew/.uv_cache",
        image,
    ]

    if shell:
        container_cmd.append("/bin/bash")
    else:
        container_cmd.extend([
            codex_path,
            *extra,  # User-supplied passthrough args for Codex
        ])

    click.echo(
        click.style("Executing:", fg="green")
        + " "
        + " ".join(map(shlex.quote, container_cmd))
    )
    # Execute the container; replace current process (no return).
    os.execvp(container_cmd[0], container_cmd)


@main.command(name="build", context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--tag",
    "-t",
    default="codex",
    show_default=True,
    help="Container image tag to build.",
)
@click.option(
    "--file",
    "-f",
    "dockerfile",
    type=click.Path(path_type=Path, exists=True, file_okay=True, dir_okay=False),
    default=Path("Dockerfile"),
    show_default=True,
    help="Path to the Dockerfile.",
)
@click.option(
    "--context",
    default=Path(),
    show_default=True,
    type=click.Path(path_type=Path, exists=True, file_okay=False, dir_okay=True),
    help="Build context directory.",
)
@click.option(
    "--no-auto-start",
    is_flag=True,
    help="Do not attempt to auto-start the container subsystem; error instead.",
)
def build(tag: str, dockerfile: Path, context: Path, no_auto_start: bool) -> None:
    """Build the container image using the Dockerfile."""
    try:
        ensure_container_running(auto_start=not no_auto_start)
    except ContainerError as exc:
        click.echo(click.style(f"Error: {exc}", fg="red"), err=True)
        sys.exit(1)

    cmd = ["container", "build", "--tag", tag, "--file", str(dockerfile), str(context)]
    click.echo(
        click.style("Executing:", fg="green") + " " + " ".join(map(shlex.quote, cmd))
    )
    _run(cmd)


if __name__ == "__main__":
    main()
