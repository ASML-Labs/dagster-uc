import os
import subprocess
import sys
from enum import Enum
from subprocess import Popen, TimeoutExpired

from dagster_uc.initialize_logger import logger


class BuildTool(str, Enum):
    """The possible build tools to choose from"""

    docker = "docker"
    buildah = "buildah"
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


def gen_tag(deployment_name: str, acr: str, subscription: str, dagster_version: str) -> str:
    """Identifies the latest tag present in the ACR and increments it by one."""
    import re

    res = run_cli_command(
        f"az acr repository show-tags --repository {deployment_name} -n {acr} --subscription {subscription}",
        ignore_failures=True,
        capture_output=True,
        timeout=5,
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
    tag_list_string = res.stdout.decode("utf-8")
    pattern = r'".*?-(\d+)"'
    tags = re.findall(pattern, tag_list_string)
    logger.debug(f"Found the following image tags for this branch in the acr: {tags}")
    tags_ints = [int(tag) for tag in tags]
    if not len(tags_ints):
        return f"{dagster_version}-0"
    new_tag = f"{dagster_version}-{str(max(tags_ints)+1)}"
    return new_tag


def run_cli_command_streaming(cmd: str, as_user: str = "") -> None:
    """Run the cli command without capturing the output, so it streams to the console."""
    if as_user:
        cmd = f"sudo -u {as_user} {cmd}"
    logger.debug(f"[running command] {cmd}")
    Popen(cmd, stdout=sys.stdout, stderr=sys.stderr, env=os.environ.copy(), shell=True)
