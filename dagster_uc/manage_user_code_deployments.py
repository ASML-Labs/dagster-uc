#!/usr/bin/env python3
# ruff: noqa: D103
import contextlib
import logging
import os
import pprint
import subprocess
import time
from typing import Annotated, cast

import kr8s
import typer
from kr8s._objects import APIObject
from kr8s.objects import (
    ConfigMap,
    Pod,
)

from dagster_uc.build_and_push_user_code import build_and_push
from dagster_uc.config import UserCodeDeploymentsConfig, load_config
from dagster_uc.deployment_utils import DagsterUserCodeHandler
from dagster_uc.initialize_logger import logger
from dagster_uc.utils import BuildTool, gen_tag, run_cli_command

app = typer.Typer(invoke_without_command=True)
deployment_app = typer.Typer(
    name="deployment",
    help="Contains various subcommands for managing user code deployments",
)
app.add_typer(deployment_app)
deployment_delete_app = typer.Typer(
    name="delete",
    help="Contains subcommands for deleting one or more user code deployments from the cluster",
)
deployment_app.add_typer(deployment_delete_app)
deployment_check_app = typer.Typer(
    name="check",
    help="Contains subcommands for checking the status of a deployment",
)
deployment_app.add_typer(deployment_check_app)

handler: DagsterUserCodeHandler
config: UserCodeDeploymentsConfig


@app.command("show-config", help="Outputs the configuration that is currently in use")
def show_config():
    """Pretty print the config object"""
    pprint.pprint(config, indent=4)


@app.callback(invoke_without_command=True)
def default(
    ctx: typer.Context,
    environment: str = typer.Option("dev", "--environment", "-e", help="The environment"),
    config_file_path: str = typer.Option(
        None,
        "--config-file",
        "-c",
        help="Path to the config file.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Output DEBUG logging"),
) -> None:
    """This function executes before any other nested cli command is called and loads the configuration object."""
    global logger
    global config
    global handler
    if ctx.invoked_subcommand is None:
        logger.error(
            "No command was provided. Use the parameter --help to see how to use this cli app.",
        )
    else:
        logger.setLevel(logging.DEBUG if verbose else logging.INFO)
        config = load_config(environment, config_file_path)

        if verbose:
            config.verbose = True
        logger.debug(f"Switching kubernetes context to {config.environment}...")
        kr8s_api = cast(
            kr8s.Api,
            kr8s.api(context=f"{config.kubernetes_context}", namespace=config.namespace),
        )
        handler = DagsterUserCodeHandler(config, kr8s_api)
        handler._ensure_dagster_version_match()
        logger.debug(f"Done: Switched kubernetes context to {config.environment}")


def build_push_container(
    deployment_name: str,
    config: UserCodeDeploymentsConfig,
    no_local_check: bool,
    build_with_sudo: bool,
    build_tool: BuildTool,
    tag: str,
) -> None:
    """Builds a docker image for a user-code deployment of the current branch and uploads it to the image registry"""
    if not config.cicd and not no_local_check:
        # Check if repo.py raises any exceptions
        os.environ["LOCAL_RUN"] = "True"
        cmd = f"python3 {os.path.join(config.repository_root, config.code_path)}"
        run_cli_command(cmd, ignore_failures=False)

    handler.update_dagster_workspace_yaml()
    build_and_push(
        config.repository_root,
        config.acr,
        config.acr_subscription,
        config.python_version,
        deployment_name,
        config.dockerfile,
        build_with_sudo,
        build_tool,
        tag,
        deployment_name,
    )


@deployment_app.command(
    name="list",
    help="List user code deployments that are currently active on the cluster",
)
def deployment_list():
    """Outputs a list of currently active deployments"""
    print(
        "\033[1mActive user code deployments\033[0m\n"
        + "\n".join(
            ["* " + d["name"] for d in handler.list_deployments()],
        ),
    )


@deployment_app.command(
    name="revive",
    help="Redeploy an old user-code deployment, without rebuilding and uploading a docker image but instead using the latest existing image from the acr.",
)
def deployment_revive(
    name: Annotated[
        str,
        typer.Option("--name", "-n", help="The name of the deployment to revive."),
    ],
    tag: Annotated[str, typer.Option("--tag", "-t", help="The tag of the deployment to revive.")],
):
    if not handler._check_deployment_exists(
        name,
    ):
        handler.add_user_deployment_to_configmap(
            handler.gen_new_deployment_yaml(name, tag=tag),
        )
        handler.deploy_to_k8s()
        logger.info(f"Deployed {name}")
    else:
        raise Exception(f'Deployment "{name}" already exists')


@deployment_delete_app.callback(invoke_without_command=True)
def deployment_delete(
    delete_all: Annotated[
        bool,
        typer.Option(
            "--all",
            "-a",
            help="If this is provided, all deployments will be deleted including CI/CD provided deployments.",
        ),
    ] = False,
    name: Annotated[
        str,
        typer.Option(
            "--name",
            "-n",
            help="The name of the deployment to delete. If none is provided, the deployment corresponding to the currently checked out git branch will be deleted.",
        ),
    ] = "",
) -> None:
    if delete_all:
        handler.remove_all_deployments()
        handler.delete_k8s_resources(
            label_selector="app.kubernetes.io/name=dagster-user-deployments",
        )
        handler.delete_k8s_resources(label_selector="app=dagster-user-deployments")
        for item in cast(
            list[APIObject],
            handler.api.get(
                ConfigMap,
                namespace=config.namespace,
                label_selector="app=dagster-user-deployments",
            ),
        ):
            item.delete()  # type: ignore
        handler.delete_k8s_resources(label_selector="dagster/code-location")
        handler.deploy_to_k8s()
        logger.info("Deleted all deployments")
    else:
        if not name:
            name = handler.get_deployment_name(deployment_name_suffix="")
        handler.remove_user_deployment_from_configmap(name)
        handler.delete_k8s_resources_for_user_deployment(
            name,
            delete_deployments=True,
        )
        handler.deploy_to_k8s(reload_dagster=True)
        logger.info(f"Deleted deployment {name}")


@deployment_check_app.callback(invoke_without_command=True)
def check_deployment(
    name: Annotated[
        str,
        typer.Option(
            "--name",
            "-n",
            help="The name of the deployment to check. If not provided, checks deployment corresponding to the current branch.",
        ),
    ] = "",
    timeout: Annotated[
        int,
        typer.Option(
            "--timeout",
            "-t",
            help="The timeout duration in seconds to keep following the logs of user code pod.",
        ),
    ] = 60,
) -> None:
    """This function executes before any other nested cli command is called and loads the configuration object."""
    if not name:
        name = handler.get_deployment_name("")
    if not handler._check_deployment_exists(name):
        logger.warning(
            f"Deployment with name '{name}' does not seem to exist in environment '{config.environment}'. Attempting to proceed with status check anyways.",
        )
    print(f"\033[1mStatus for deployment {name}\033[0m")
    for pod in cast(
        list[Pod],
        handler.api.get(Pod, label_selector=f"deployment={name}", namespace=config.namespace),
    ):
        with contextlib.suppress(Exception):
            for line in pod.logs(pretty=True, follow=True, timeout=timeout):  # type: ignore
                print(line)


def acquire_semaphore(reset_lock: bool = False) -> bool:
    if reset_lock:
        semaphore_list = cast(
            list[APIObject],
            handler.api.get(
                ConfigMap,
                config.uc_deployment_semaphore_name,
                namespace=config.namespace,
            ),
        )
        if len(semaphore_list):
            semaphore_list[0].delete()  # type: ignore

    semaphore_list = cast(
        list[ConfigMap],
        handler.api.get(
            ConfigMap,
            config.uc_deployment_semaphore_name,
            namespace=config.namespace,
        ),
    )
    if len(semaphore_list):
        semaphore = semaphore_list[0]
        if semaphore.data.get("locked") == "true":
            return False

        semaphore.patch({"data": {"locked": "true"}})  # type: ignore
        return True
    else:
        # Create semaphore if it does not exist
        semaphore = ConfigMap(
            {
                "metadata": {
                    "name": config.uc_deployment_semaphore_name,
                    "namespace": config.namespace,
                },
                "data": {"locked": "true"},
            },
        ).create()
        return True


def release_semaphore() -> None:
    try:
        semaphore = cast(
            list[ConfigMap],
            handler.api.get(
                ConfigMap,
                config.uc_deployment_semaphore_name,
                namespace=config.namespace,
            ),
        )[0]
        semaphore.patch({"data": {"locked": "false"}})  # type: ignore
        logger.debug("patched semaphore to locked: false")
    except Exception as e:
        logger.error(f"Failed to release deployment lock: {e}")


@deployment_app.command(
    name="deploy",
    help="Deploys the currently checked out git branch to the cluster as a user code deployment",
)
def deployment_deploy(
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help="If this is provided, a full redeploy will always be done, rather than just rebooting user code pods if they already exist in order to trigger a new image pull",
        ),
    ] = False,
    skip_build: bool = typer.Option(
        False,
        "--skip-build",
        "-b",
        help="Image build and push will be skipped",
    ),
    deployment_name_suffix: str = typer.Option(
        "",
        "--deployment-name-suffix",
        "-s",
        help="Suffix to append to the default deployment name (which is based on the git branch name) - useful for doing parallel deployments from the same branch.",
    ),
    deployment_name: str = typer.Option(
        "",
        "--deployment-name",
        "-n",
        help="Overrides the name of the deployment, including any --deployment-name-suffix value",
    ),
    reset_lock: bool = typer.Option(
        False,
        "--reset-lock",
        "-r",
        help="Reset the deployment semaphore of any ongoing other deployments.",
    ),
    no_local_check: Annotated[
        bool,
        typer.Option(
            "--no-local-check",
            "-c",
            help="If this is provided, there will be no local check of repo.py before deployment",
        ),
    ] = False,
    build_with_sudo: Annotated[
        bool,
        typer.Option(
            "--build-with-sudo",
            "-u",
            help="If this is provided, buildah or docker will be called with sudo",
        ),
    ] = False,
    build_tool: Annotated[
        BuildTool,
        typer.Option(
            "--build-tool",
            "-t",
            help="Choose which tool to use for building the image",
            show_choices=True,
        ),
    ] = BuildTool.auto,
):
    def is_command_available(command: str) -> bool:
        try:
            subprocess.run(
                [command, "--version"],
                capture_output=True,
                check=True,  # ruff: ignore
            )
            return True
        except subprocess.CalledProcessError:
            return False
        except FileNotFoundError:
            return False

    count = 0
    while not acquire_semaphore(reset_lock):
        logger.error(
            f"Attempt {count}: Another deployment is in progress. Trying again in 10 seconds. You can force a reset of the deployment lock by using 'dagster-uc deployment deploy --reset-lock'",
        )
        count += 1
        time.sleep(10)

    try:
        logger.debug("Determining build tool...")
        if build_tool == BuildTool.auto:
            if is_command_available(BuildTool.buildah.value):
                build_tool = BuildTool.buildah
            elif is_command_available(BuildTool.docker.value):
                build_tool = BuildTool.docker
            else:
                raise Exception("No suitable build tool is installed on the system")
        logger.debug(f"Using build tool: {build_tool.value}")
        deployment_name = deployment_name or handler.get_deployment_name(
            deployment_name_suffix,
        )
        logger.debug("Determining tag...")
        new_tag = gen_tag(
            deployment_name,
            config.acr,
            config.acr_subscription,
            config.dagster_version,
        )

        print(f"Deploying deployment \033[1m'{deployment_name}:{new_tag}'\033[0m")

        full_redeploy_done = False
        if not skip_build:
            build_push_container(
                deployment_name,
                config,
                no_local_check,
                build_with_sudo,
                build_tool,
                tag=new_tag,
            )

        if not handler._check_deployment_exists(deployment_name):
            logger.info(
                f"Deployment with name '{deployment_name}' does not exist yet in '{config.environment}'. Adding deployment to configmap",
            )
            handler.add_user_deployment_to_configmap(
                handler.gen_new_deployment_yaml(
                    deployment_name,
                    tag=new_tag,
                ),
            )
            handler.deploy_to_k8s()
        else:
            logger.info(
                f"Deployment with name '{deployment_name}' exists in '{config.environment}'. Updating deployment in configmap",
            )
            handler.remove_user_deployment_from_configmap(deployment_name)
            handler.add_user_deployment_to_configmap(
                handler.gen_new_deployment_yaml(
                    deployment_name,
                    tag=new_tag,
                ),
            )
            if config.cicd or force:
                handler.delete_k8s_resources_for_user_deployment(deployment_name)
                handler.deploy_to_k8s()
            elif not handler.check_if_code_pod_exists(label=deployment_name):
                logger.info(
                    "Code deployment present in configmap but pod not found, triggering full deploy...,",
                )
                handler.delete_k8s_resources_for_user_deployment(deployment_name, True)
                handler.deploy_to_k8s()  # Something went wrong - redeploy yamls and reload webserver
            else:
                logger.info(
                    "Code deployment present in configmap and pod found...,",
                )
                handler.delete_k8s_resources_for_user_deployment(deployment_name, False)
                handler.deploy_to_k8s(reload_dagster=False)
    finally:
        release_semaphore()
    if config.dagster_gui_url:
        print(
            f"Your assets: {config.dagster_gui_url.rstrip('/')}/locations/{deployment_name}/assets\033[0m",
        )
    time.sleep(5)
    timeout = 40 if not full_redeploy_done else 240

    while True:
        code_pods = cast(
            list[APIObject],
            handler.api.get(
                Pod,
                label_selector=f"deployment={deployment_name}",
                namespace=config.namespace,
            ),
        )
        if len(code_pods) == 0:
            time.sleep(2)
            continue
        else:
            break

    with contextlib.suppress(Exception):
        for code_pod in code_pods:
            code_pod.wait("condition=Ready", timeout=timeout)  # type: ignore
    check_deployment(deployment_name)


if __name__ == "__main__":
    app()
