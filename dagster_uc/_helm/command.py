from __future__ import annotations

import asyncio
import json
import logging
import pathlib
import re
import shlex
from typing import Any

import yaml

from dagster_uc._helm.errors import (
    ChartNotFoundError,
    CommandCancelledError,
    Error,
    FailedToRenderChartError,
    HelmConnectionError,
    InvalidResourceError,
    ReleaseNotFoundError,
    ResourceAlreadyExistsError,
)


class SafeLoader(yaml.SafeLoader):
    """We use a custom YAML loader that doesn't bork on plain equals '=' signs.

    It was originally designated with a special meaning, but noone uses it:

        https://github.com/yaml/pyyaml/issues/89
        https://yaml.org/type/value.html
    """

    @staticmethod
    def construct_value(loader, node):  # noqa
        return loader.construct_scalar(node)


SafeLoader.add_constructor("tag:yaml.org,2002:value", SafeLoader.construct_value)


CHART_NOT_FOUND = re.compile(r"chart \"[^\"]+\" (version \"[^\"]+\" )?not found")
CONNECTION_ERROR = re.compile(r"(read: operation timed out|connect: network is unreachable)")


class Command:
    """Class presenting an async interface around the Helm CLI."""

    def __init__(
        self,
        *,
        default_timeout: int | str = "5m",
        executable: str = "helm",
        history_max_revisions: int = 10,
        insecure_skip_tls_verify: bool = False,
        kubeconfig: pathlib.Path | None = None,
        kubecontext: str | None = None,
        unpack_directory: str | None = None,
    ):
        self._logger = logging.getLogger(__name__)
        self._default_timeout = default_timeout
        self._executable = executable
        self._history_max_revisions = history_max_revisions
        self._insecure_skip_tls_verify = insecure_skip_tls_verify
        self._kubeconfig = kubeconfig
        self._kubecontext = kubecontext
        self._unpack_directory = unpack_directory

    def _log_format(self, argument):  # noqa: ANN001, ANN202
        argument = str(argument)
        if argument == "-":
            return "<stdin>"
        elif "\n" in argument:
            return "<multi-line string>"
        else:
            return argument

    async def run(self, command: list[str], input: bytes | None = None) -> bytes:  # noqa: A002
        """Run the given Helm command with the given input as stdin and"""
        command = [self._executable] + command
        if self._kubeconfig:
            command.extend(["--kubeconfig", self._kubeconfig.absolute().as_posix()])
        if self._kubecontext:
            command.extend(["--kube-context", self._kubecontext])
        # The command must be made up of str and bytes, so convert anything that isn't
        shell_formatted_command = shlex.join(
            part if isinstance(part, str | bytes) else str(part) for part in command
        )
        log_formatted_command = shlex.join(self._log_format(part) for part in command)
        self._logger.info("running command: %s", log_formatted_command)
        proc = await asyncio.create_subprocess_shell(
            shell_formatted_command,
            # Only make stdin a pipe if we have input to feed it
            stdin=asyncio.subprocess.PIPE if input is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await proc.communicate(input)
        except asyncio.CancelledError:
            # If the asyncio task is cancelled, terminate the Helm process but let the
            # process handle the termination and exit
            # We occasionally see a ProcessLookupError here if the process finished between
            # us being cancelled and terminating the process, which we ignore as that is our
            # target state anyway
            try:
                proc.terminate()
                _ = await proc.communicate()
            except ProcessLookupError:
                pass
            # Once the process has exited, re-raise the cancelled error
            raise
        if proc.returncode == 0:
            self._logger.info("command succeeded: %s", log_formatted_command)
            return stdout
        else:
            self._logger.warning("command failed: %s", log_formatted_command)
            stderr_str = stderr.decode().lower()
            # Parse some expected errors into specific exceptions
            if "context canceled" in stderr_str:
                error_cls = CommandCancelledError
            # Any error referencing etcd is a connection error
            # This must be before other rules, as it sometimes occurs alonside a not found error
            elif "etcdserver" in stderr_str:
                error_cls = HelmConnectionError
            elif "release: not found" in stderr_str:
                error_cls = ReleaseNotFoundError
            elif "failed to render chart" in stderr_str or "execution error" in stderr_str:
                error_cls = FailedToRenderChartError
            elif "rendered manifests contain a resource that already exists" in stderr_str:
                error_cls = ResourceAlreadyExistsError
            elif "is invalid" in stderr_str:
                error_cls = InvalidResourceError
            elif CHART_NOT_FOUND.search(stderr_str) is not None:
                error_cls = ChartNotFoundError
            elif CONNECTION_ERROR.search(stderr_str) is not None:
                error_cls = HelmConnectionError
            else:
                error_cls = Error
            raise error_cls(proc.returncode, stdout, stderr)

    async def install_or_upgrade(
        self,
        release_name: str,
        chart_ref: pathlib.Path | str,
        values: dict[str, Any] | None = None,
        *,
        atomic: bool = False,
        cleanup_on_fail: bool = False,
        create_namespace: bool = True,
        description: str | None = None,
        devel: bool = False,
        dry_run: bool = False,
        force: bool = False,
        namespace: str | None = None,
        no_hooks: bool = False,
        repo: str | None = None,
        reset_values: bool = False,
        reuse_values: bool = False,
        skip_crds: bool = False,
        timeout: int | str | None = None,
        version: str | None = None,
        wait: bool = False,
        disable_openapi_validation: bool = False,
        skip_schema_validation: bool = False,
    ) -> dict[str, Any]:
        """Installs or upgrades the specified release using the given chart and values."""
        command = [
            "upgrade",
            release_name,
            chart_ref,
            "--history-max",
            self._history_max_revisions,
            "--install",
            "--output",
            "json",
            # Use the default timeout unless an override is specified
            "--timeout",
            timeout if timeout is not None else self._default_timeout,
            # We send the values in on stdin
            "--values",
            "-",
        ]
        if atomic:
            command.append("--atomic")
        if cleanup_on_fail:
            command.append("--cleanup-on-fail")
        if create_namespace:
            command.append("--create-namespace")
        if description:
            command.extend(["--description", description])
        if devel:
            command.append("--devel")
        if dry_run:
            command.append("--dry-run")
        if force:
            command.append("--force")
        if self._insecure_skip_tls_verify:
            command.append("--insecure-skip-tls-verify")
        if namespace:
            command.extend(["--namespace", namespace])
        if no_hooks:
            command.append("--no-hooks")
        if repo:
            command.extend(["--repo", repo])
        if reset_values:
            command.append("--reset-values")
        if reuse_values:
            command.append("--reuse-values")
        if skip_crds:
            command.append("--skip-crds")
        if version:
            command.extend(["--version", version])
        if wait:
            command.extend(["--wait", "--wait-for-jobs"])
        if disable_openapi_validation:
            command.extend(["--disable-openapi-validation"])
        if skip_schema_validation:
            command.extend(["--skip-schema-validation"])
        return json.loads(await self.run(command, json.dumps(values or {}).encode()))

    async def rollback(
        self,
        release_name: str,
        revision: int | None,
        *,
        cleanup_on_fail: bool = False,
        dry_run: bool = False,
        force: bool = False,
        namespace: str | None = None,
        no_hooks: bool = False,
        recreate_pods: bool = False,
        timeout: int | str | None = None,
        wait: bool = False,
    ):
        """Rollback the specified release to the specified revision."""
        command = [
            "rollback",
            release_name,
        ]
        if revision is not None:
            command.append(revision)  # type: ignore
        command.extend(
            [
                "--history-max",
                self._history_max_revisions,
                # Use the default timeout unless an override is specified
                "--timeout",
                timeout if timeout is not None else self._default_timeout,
            ],  # type: ignore
        )
        if cleanup_on_fail:
            command.append("--cleanup-on-fail")
        if dry_run:
            command.append("--dry-run")
        if force:
            command.append("--force")
        if namespace:
            command.extend(["--namespace", namespace])
        if no_hooks:
            command.append("--no-hooks")
        if recreate_pods:
            command.append("--recreate-pods")
        if wait:
            command.extend(["--wait", "--wait-for-jobs"])
        await self.run(command)

    async def show_chart(
        self,
        chart_ref: pathlib.Path | str,
        *,
        devel: bool = False,
        repo: str | None = None,
        version: str | None = None,
    ) -> dict[str, Any]:
        """Returns the contents of Chart.yaml for the specified chart."""
        command = ["show", "chart", chart_ref]
        if devel:
            command.append("--devel")
        if self._insecure_skip_tls_verify:
            command.append("--insecure-skip-tls-verify")
        if repo:
            command.extend(["--repo", repo])
        if version:
            command.extend(["--version", version])
        return yaml.load(await self.run(command), Loader=SafeLoader)

    async def status(  # noqa: ANN201
        self,
        release_name: str,
        *,
        namespace: str | None = None,
        revision: int | None = None,
    ) -> dict[str, Any]:
        """Get the status of the specified release."""
        command = ["status", release_name, "--output", "json"]
        if namespace:
            command.extend(["--namespace", namespace])
        if revision:
            command.extend(["--revision", revision])  # type: ignore
        return json.loads(await self.run(command))

    async def uninstall(
        self,
        release_name: str,
        *,
        dry_run: bool = False,
        keep_history: bool = False,
        namespace: str | None = None,
        no_hooks: bool = False,
        timeout: int | str | None = None,
        wait: bool = False,
    ):
        """Uninstall the specified release."""
        command = [
            "uninstall",
            release_name,
            # Use the default timeout unless an override is specified
            "--timeout",
            timeout if timeout is not None else self._default_timeout,
        ]
        if dry_run:
            command.append("--dry-run")
        if keep_history:
            command.append("--keep-history")
        if namespace:
            command.extend(["--namespace", namespace])
        if no_hooks:
            command.append("--no-hooks")
        if wait:
            command.extend(["--wait"])
        await self.run(command)
