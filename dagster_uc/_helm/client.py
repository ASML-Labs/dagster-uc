from __future__ import annotations

import functools
import pathlib
from typing import Any

from dagster_uc._helm.command import Command
from dagster_uc._helm.models import Chart, ReleaseRevision


def mergeconcat(
    defaults: dict[Any, Any],
    *overrides: dict[Any, Any],
) -> dict[Any, Any]:
    """Deep-merge two or more dictionaries together. Lists are concatenated."""

    def mergeconcat2(defaults, overrides):  # noqa: ANN001, ANN202
        if isinstance(defaults, dict) and isinstance(overrides, dict):
            merged = dict(defaults)
            for key, value in overrides.items():
                if key in defaults:
                    merged[key] = mergeconcat2(defaults[key], value)
                else:
                    merged[key] = value
            return merged
        elif isinstance(defaults, list | tuple) and isinstance(overrides, list | tuple):
            merged = list(defaults)
            merged.extend(overrides)
            return merged
        else:
            return overrides if overrides is not None else defaults

    return functools.reduce(mergeconcat2, overrides, defaults)  # type: ignore


class Client:
    """Entrypoint for interactions with Helm."""

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
        self._command = Command(
            default_timeout=default_timeout,
            executable=executable,
            history_max_revisions=history_max_revisions,
            insecure_skip_tls_verify=insecure_skip_tls_verify,
            kubeconfig=kubeconfig,
            kubecontext=kubecontext,
            unpack_directory=unpack_directory,
        )

    async def get_chart(
        self,
        chart_ref: pathlib.Path | str,
        *,
        devel: bool = False,
        repo: str | None = None,
        version: str | None = None,
    ) -> Chart:
        """Returns the resolved chart for the given ref, repo and version."""
        return Chart(
            self._command,  # type: ignore
            ref=chart_ref,
            repo=repo,
            # Load the metadata for the specified args
            metadata=await self._command.show_chart(
                chart_ref,
                devel=devel,
                repo=repo,
                version=version,
            ),
        )

    async def install_or_upgrade_release(
        self,
        release_name: str,
        chart: Chart,
        *values: dict[str, Any],
        atomic: bool = False,
        cleanup_on_fail: bool = False,
        create_namespace: bool = True,
        description: str | None = None,
        dry_run: bool = False,
        force: bool = False,
        namespace: str | None = None,
        no_hooks: bool = False,
        reset_values: bool = False,
        reuse_values: bool = False,
        skip_crds: bool = False,
        timeout: int | str | None = None,
        wait: bool = False,
        disable_openapi_validation: bool = False,
        skip_schema_validation: bool = False,
    ) -> ReleaseRevision:
        """Install or upgrade the named release using the given chart and values and return
        the new revision.
        """
        return ReleaseRevision._from_status(
            await self._command.install_or_upgrade(
                release_name,
                chart.ref,
                mergeconcat(*values) if values else None,
                atomic=atomic,
                cleanup_on_fail=cleanup_on_fail,
                create_namespace=create_namespace,
                description=description,
                dry_run=dry_run,
                force=force,
                namespace=namespace,
                no_hooks=no_hooks,
                repo=chart.repo,
                reset_values=reset_values,
                reuse_values=reuse_values,
                skip_crds=skip_crds,
                timeout=timeout,
                version=chart.metadata.version,
                wait=wait,
                disable_openapi_validation=disable_openapi_validation,
                skip_schema_validation=skip_schema_validation,
            ),
            self._command,
        )
