# petrel

Petrel provides a simple CLI for running OpenAI Codex inside the Apple
container subsystem.

Uses its own folder for Codex state, shared with all containers.

## Installation

Install Petrel using [uv](https://github.com/astral-sh/uv):

```bash
uv tool install https://github.com/tabletcorry/petrel.git
```

This installs the `petrel` command into your uv tools directory.

## Usage

```bash
# Optional: If you don't do this, you will need to setup credentials once in a container.
cp -r ~/.codex ~/.codex-container

# Only required once, or after petrel/codex updates, to build the docker image.
petrel build

# Runs Codex, inside a container, for the current directory.
petrel codex

## Commands

### `codex`
Runs Codex in a container with sensible defaults. The command caches data under
`~/.cache/petrel` to speed up subsequent runs.

Key options include:
- `--name` – container instance name.
- `--persistent-dir` – directory on the host used for persistent Codex data.
- `--dest-dir` – target path for the persistent directory inside the container.
- `--repo-dir` – repository to mount into the container.
- `--image` – container image name.
- `--codex-path` – path to the Codex executable in the container.
- `--shell` – launch a shell instead of Codex.
- `--no-auto-start` – do not automatically start the container subsystem.

Extra arguments after `codex` are passed straight to the Codex command.

### `dockerfile`
Print the rendered Dockerfile template used to build the container. Supply
`--file` to render a custom template.

### `build`
Build the container image from the Dockerfile template. Useful options are:
- `--tag` – image tag to build.
- `--file` – path to a Dockerfile template.
- `--context` – build context directory.
- `--no-auto-start` – do not start the container subsystem automatically.

Petrel checks that the Apple container subsystem is running before executing
commands. If the subsystem is stopped and `--no-auto-start` is not given, Petrel
will attempt to start it for you.
