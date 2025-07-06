# ruff: noqa: S606, S404, S603, PLR0913
from __future__ import annotations

import hashlib
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from importlib import resources
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from importlib.resources.abc import Traversable
from pathlib import Path

import click
import jinja2


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


def render_template(
    template_path: Path | Traversable, context: dict[str, str] | None = None
) -> str:
    """Render a Jinja2 template using the provided context or environment."""
    env = jinja2.Environment(autoescape=False)  # noqa: S701
    data = template_path.read_text(encoding="utf-8")
    if context is None:
        context = dict(os.environ)
    template = env.from_string(data)
    return template.render(**context)


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

    # Verify that the container image exists; prompt to build if missing.
    image_check = _run(["container", "images", image], check=False, capture_output=True)
    if image_check.returncode != 0 or not image_check.stdout.strip():
        if click.confirm(
            f"Container image '{image}' not found. Build it now?", default=True
        ):
            # Reuse the build command with default template and context
            build.callback(  # type: ignore[misc]
                tag=image,
                dockerfile_template=None,
                context=Path(),
                no_auto_start=no_auto_start,
            )
        else:
            click.echo(
                click.style(
                    f"Image '{image}' is required but was not built.", fg="red"
                ),
                err=True,
            )
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


@main.command(
    name="dockerfile", context_settings={"help_option_names": ["-h", "--help"]}
)
@click.option(
    "--file",
    "-f",
    "dockerfile_template",
    type=click.Path(path_type=Path, exists=True, file_okay=True, dir_okay=False),
    default=None,
    show_default=False,
    help="Path to the Dockerfile template. Defaults to the built-in template.",
)
def dockerfile_cmd(dockerfile_template: Path | Traversable | None) -> None:
    """Print the rendered Dockerfile template."""
    if dockerfile_template is None:
        dockerfile_template = resources.files(__package__).joinpath("Dockerfile.j2")
    click.echo(render_template(dockerfile_template))


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
    "dockerfile_template",
    type=click.Path(path_type=Path, exists=True, file_okay=True, dir_okay=False),
    default=None,
    show_default=False,
    help="Path to the Dockerfile template. Defaults to the built-in template.",
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
def build(
    tag: str,
    dockerfile_template: Path | Traversable | None,
    context: Path,
    no_auto_start: bool,
) -> None:
    """Build the container image using the Dockerfile template."""
    try:
        ensure_container_running(auto_start=not no_auto_start)
    except ContainerError as exc:
        click.echo(click.style(f"Error: {exc}", fg="red"), err=True)
        sys.exit(1)

    if dockerfile_template is None:
        dockerfile_template = resources.files(__package__).joinpath("Dockerfile.j2")

    rendered = render_template(dockerfile_template)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as tmpfile:
        tmpfile.write(rendered)
        tmpfile_path = Path(tmpfile.name)

    try:
        cmd = [
            "container",
            "build",
            "--tag",
            tag,
            "--file",
            str(tmpfile_path),
            str(context),
        ]
        click.echo(
            click.style("Executing:", fg="green")
            + " "
            + " ".join(map(shlex.quote, cmd))
        )
        _run(cmd)
    finally:
        tmpfile_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
