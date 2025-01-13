import os
import re
import subprocess
import sys
from enum import Enum
from subprocess import Popen, TimeoutExpired

import typer

from dagster_uc.log import logger


class BuildTool(str, Enum):
    """The possible build tools to choose from"""

    podman = "podman"
    docker = "docker"
    auto = "auto"


def exception_on_failed_subprocess(res: subprocess.CompletedProcess) -> None:
    """Raises a python exception if the subprocess terminated with exit code > 0"""
    if res.stdout is not None:
        logger.debug(res.stdout.decode("utf-8"))
    if res.returncode != 0:
        if res.stderr is not None:
            logger.error(res.stderr.decode("utf-8"))
        raise Exception("Subprocess failed")


def run_cli_command(
    cmd: str,
    ignore_failures: bool = False,
    input_str: str | None = None,
    capture_output: bool = False,
    timeout: int | None = None,
    shell: bool = True,
) -> subprocess.CompletedProcess | TimeoutExpired:
    """Run the cli command while capturing the output, so its output is not directly shown."""
    logger.debug(f"[running command] {cmd}")
    if input_str == "":
        input_str_bytes = None
    elif input_str is not None:
        input_str_bytes = input_str.encode("utf-8")
    else:
        input_str_bytes = None
    try:
        res = subprocess.run(
            cmd,
            shell=shell,
            check=False,
            env=os.environ.copy(),
            capture_output=capture_output,
            input=input_str_bytes,
            timeout=timeout,
        )
    except TimeoutExpired as timeout_expired:
        return timeout_expired
    if not ignore_failures:
        exception_on_failed_subprocess(res)
    return res


def gen_tag(
    deployment_name: str,
    container_registry: str,
    dagster_version: str,
    use_az_login: bool,
) -> str:
    """Identifies the latest tag present in the ACR and increments it by one."""
    if use_az_login:
        login_registry(container_registry)

    res = run_cli_command(
        f"podman search {os.path.join(container_registry, deployment_name)} --list-tags --format {{{{.Tag}}}} --limit 9999999",
        ignore_failures=True,
        capture_output=True,
        timeout=15,
    )
    if isinstance(res, TimeoutExpired):
        if res.stderr is not None and "Please try running 'az login' again" in res.stderr.decode():
            raise Exception(
                f"{res.stderr.decode()}\n\nAzure cli is likely not logged in. Please try 'az login'",
            )
        else:
            raise res
    if res.stderr is not None and any(
        txt in res.stderr.decode("utf-8").lower() for txt in ["is not found", "does not exist"]
    ):
        return f"{dagster_version}-0"
    elif res.returncode > 0:
        raise Exception(res.stderr)

    tags = re.findall(r".*?-(\d+)", res.stdout.decode("utf-8"))
    logger.debug(
        f"Found the following image tags for this branch in the container registry: {tags}",
    )

    tags_ints = [int(tag) for tag in tags]
    if not len(tags_ints):
        return f"{dagster_version}-0"
    new_tag = f"{dagster_version}-{max(tags_ints) + 1}"
    return new_tag


def run_cli_command_streaming(cmd: str, as_user: str = "") -> None:
    """Run the cli command without capturing the output, so it streams to the console."""
    if as_user:
        cmd = f"sudo -u {as_user} {cmd}"
    logger.debug(f"[running command] {cmd}")
    Popen(cmd, stdout=sys.stdout, stderr=sys.stderr, env=os.environ.copy(), shell=True)


def login_registry(image_registry: str) -> None:
    """Logs into registry with az cli"""
    typer.echo("Logging into acr...")
    cmd = [
        "az",
        "acr",
        "login",
        "--name",
        image_registry,
        "--expose-token",
        "--output",
        "tsv",
        "--query",
        "accessToken",
    ]
    typer.echo(f"\033[1mExecuting\033[0m cmd: {' '.join(cmd)}")
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=False)
    output, error = process.communicate()
    token = output.decode().strip().encode("utf-8")

    cmd = [
        BuildTool.podman.value,
        "login",
        "--username",
        "00000000-0000-0000-0000-000000000000",
        "--password-stdin",
        image_registry,
    ]
    exception_on_failed_subprocess(subprocess.run(cmd, input=token, capture_output=False))


def build_and_push(
    repository_root: str,
    image_registry: str,
    image_name: str,
    dockerfile: str,
    use_sudo: bool,
    tag: str,
    branch_name: str,
    use_az_login: bool,
):
    """Build a docker image and push it to the registry"""
    # We need to work from the root of the repo so docker can access all files
    previous_dir = os.getcwd()
    os.chdir(repository_root)

    cmd = [
        BuildTool.podman.value,
        "build",
        "-f",
        os.path.join(os.getcwd(), dockerfile),
        "-t",
        os.path.join(image_registry, f"{image_name}:{tag}"),
        "--build-arg=BRANCH_NAME=" + branch_name,
        ".",
    ]

    if use_sudo:
        cmd = ["sudo"] + cmd

    exception_on_failed_subprocess(subprocess.run(cmd, capture_output=False))

    if use_az_login:
        login_registry(image_registry=image_registry)

    typer.echo("Pushing image...")
    cmd = [BuildTool.podman.value, "push", os.path.join(image_registry, f"{image_name}:{tag}")]
    if use_sudo:
        cmd = ["sudo"] + cmd
    exception_on_failed_subprocess(subprocess.run(cmd, capture_output=False))
    os.chdir(previous_dir)
