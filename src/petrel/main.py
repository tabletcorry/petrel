# ruff: noqa: S606, S404, S603, PLR0913
from __future__ import annotations

import os
import shlex
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


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
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
    "--uv-path",
    default="/home/linuxbrew/.linuxbrew/bin/uv",
    show_default=True,
    help="Path to the 'uv' wrapper binary inside the container.",
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
def main(
    *,
    name: str,
    persistent_dir: Path,
    dest_dir: str,
    repo_dir: Path,
    image: str,
    uv_path: str,
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

    # Construct the base container command.
    container_cmd: list[str] = [
        "container",
        "run",
        "--name",
        name,
        "--rm",
        "-it",
        "--mount",
        f"src={persistent_dir},dst={dest_dir}",
        "-v",
        f"{repo_dir}:/home/linuxbrew/repo",
        image,
    ]

    if shell:
        container_cmd.append("/bin/bash")
    else:
        container_cmd.extend([
            uv_path,
            "run",
            "--isolated",
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


if __name__ == "__main__":
    main()
