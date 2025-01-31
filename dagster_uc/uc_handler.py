import asyncio
import logging
import re
import subprocess
from collections.abc import Callable
from typing import NamedTuple

import kr8s
import yaml
from kr8s.objects import (
    ConfigMap,
    Deployment,
    Pod,
)
from kr8s.objects import Role as Role
from kr8s.objects import RoleBinding as RoleBinding
from kr8s.objects import Service as Service
from kr8s.objects import ServiceAccount as ServiceAccount
from packaging.version import Version

from dagster_uc.config import UserCodeDeploymentsConfig
from dagster_uc.configmaps import BASE_CONFIGMAP, BASE_CONFIGMAP_DATA
from dagster_uc.log import logger


class DagsterDeployment(NamedTuple):
    """Dagster deployment names"""

    full_name: str
    branch_name: str


class DagsterUserCodeHandler:
    """This the dagster-user code handler for common activities such as updating config maps, listing them and modifying them."""

    def __init__(self, config: UserCodeDeploymentsConfig, kr8s_api: kr8s.Api) -> None:
        self.config = config
        self.api = kr8s_api

    def maybe_create_user_deployments_configmap(self) -> None:
        """Creates a user deployments_configmap if it doesn't exist yet."""
        from copy import deepcopy

        dagster_user_deployments_values_yaml_configmap = deepcopy(BASE_CONFIGMAP)
        dagster_user_deployments_values_yaml_configmap["metadata"]["name"] = (
            self.config.user_code_deployments_configmap_name
        )
        dagster_user_deployments_values_yaml_configmap["data"]["yaml"] = yaml.dump(
            BASE_CONFIGMAP_DATA,
        )
        try:
            self._read_namespaced_config_map(
                self.config.user_code_deployments_configmap_name,
            )
        except kr8s.NotFoundError:
            ConfigMap(
                resource=dagster_user_deployments_values_yaml_configmap,
                namespace=self.config.namespace,
                api=self.api,
            ).create()

    def remove_all_deployments(self) -> None:
        """This function removes in its entirety the values.yaml for dagster's user-code deployment chart from the k8s
        cluster and replaces it with one with an empty deployments array as read
        from dagster_user_deployments_values_yaml_configmap.
        """
        from copy import deepcopy

        dagster_user_deployments_values_yaml_configmap = deepcopy(BASE_CONFIGMAP)
        dagster_user_deployments_values_yaml_configmap["data"]["yaml"] = yaml.dump(
            BASE_CONFIGMAP_DATA,
        )

        configmap = self._read_namespaced_config_map(
            self.config.user_code_deployments_configmap_name,
        )
        configmap.patch(dagster_user_deployments_values_yaml_configmap)

    def list_deployments(
        self,
    ) -> list[dict]:
        """Get the contents of the deployments array from the values.yaml of dagster's user-code deployment chart as it is
        currently stored on k8s.
        """
        config_map = self._read_namespaced_config_map(
            self.config.user_code_deployments_configmap_name,
        )
        current_deployments: list = yaml.safe_load(config_map["data"]["yaml"])["deployments"]
        return current_deployments

    def get_deployment(
        self,
        name: str,
    ) -> dict | None:
        """Return None if the deployment does not exist. Otherwise, return the deployment config."""
        current_deployments = self.list_deployments()
        deployments = list(filter(lambda x: x["name"] == name, current_deployments))
        if len(deployments):
            return deployments[0]
        else:
            return None

    def _check_deployment_exists(
        self,
        name: str,
    ) -> bool:
        """Return True if the deployment exists. This is done by reading the configmap of values.yaml for dagster's
        user-code deployment chart and checking if the deployments array contains this particular deployment_name
        """
        return self.get_deployment(name) is not None

    def update_dagster_workspace_yaml(
        self,
    ) -> None:
        """This function updates dagster's dagster-workspace-yaml configmap to include all currently configured
        deployments. Should be called after adding or removing user-code deployments.
        """
        configmap = self._read_namespaced_config_map(
            self.config.dagster_workspace_yaml_configmap_name,
        )

        last_applied_configuration = (
            configmap["metadata"]
            .get("annotations", {})
            .get("kubectl.kubernetes.io/last-applied-configuration", None)
        )

        def generate_grpc_servers_yaml(servers: list[dict]) -> str:
            data = {"load_from": []}
            for server in servers:
                grpc_server = {
                    "host": server["name"],
                    "port": 3030,
                    "location_name": server["name"].replace(
                        "--",
                        ":",
                    ),  ## We replace the -- separator with `:` for more friendly UI name
                }
                data["load_from"].append({"grpc_server": grpc_server})
            return yaml.dump(data)

        workspaceyaml = generate_grpc_servers_yaml(
            self.list_deployments(),
        )

        new_configmap = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "data": {"workspace.yaml": workspaceyaml},
        }
        new_configmap["metadata"] = {
            "name": self.config.dagster_workspace_yaml_configmap_name,
            "namespace": self.config.namespace,
            "annotations": {
                "kubectl.kubernetes.io/last-applied-configuration": last_applied_configuration,
            },
        }
        configmap.patch(new_configmap)  # type: ignore

    def deploy_to_k8s(
        self,
        reload_dagster: bool = True,
    ) -> None:
        """This will read the values.yaml for dagster's user-code deployment chart as it exists on k8s, and feed it into
        dagster's user-code deployment chart, generating k8s yaml files for user-code deployments. These yamls are
        applied such that the cluster will now reflect the latest version of the user-code deployment configuration.
        """
        from datetime import datetime

        from pyhelm3 import Client
        from pytz import timezone

        tz = timezone("Europe/Amsterdam")

        values_dict = yaml.safe_load(
            self._read_namespaced_config_map(self.config.user_code_deployments_configmap_name)[
                "data"
            ]["yaml"],
        )
        self.update_dagster_workspace_yaml()

        loop = asyncio.new_event_loop()
        helm_client = Client()
        chart = loop.run_until_complete(
            helm_client.get_chart(
                chart_ref="dagster-user-deployments",
                repo="https://dagster-io.github.io/helm",
                version=self.config.dagster_version,
            ),
        )
        helm_templates = [
            *loop.run_until_complete(
                helm_client.template_resources(
                    chart,
                    "dagster",
                    values_dict,
                    namespace=self.config.namespace,
                ),
            ),
        ]

        # Update user code deployments in k8s (akin to kubectl apply -f)
        for obj in helm_templates:
            k8s_obj = eval(obj["kind"])(obj, api=self.api)
            try:
                k8s_obj.patch(obj)
            except kr8s.NotFoundError:
                k8s_obj.create()

        if reload_dagster:
            for deployment_name in ["dagster-daemon", "dagster-dagster-webserver"]:
                deployment = Deployment.get(deployment_name, namespace=self.config.namespace)
                reload_patch = {
                    "spec": {
                        "template": {
                            "metadata": {
                                "annotations": {
                                    "kubectl.kubernetes.io/restartedAt": datetime.now(tz).strftime(
                                        "%Y-%m-%dT%H:%M:%S%z",
                                    ),
                                },
                            },
                        },
                    },
                }
                deployment.patch(reload_patch)

    def delete_k8s_resources_for_user_deployment(
        self,
        label: str,
        delete_deployments: bool = True,
    ) -> None:
        """Deletes all k8s resources related to a specific user code deployment.
        Returns a boolean letting you know if pod was found
        """
        for pod in self.api.get(
            Pod,
            label_selector=f"dagster/code-location={label}",
            field_selector="status.phase=Succeeded",
            namespace=self.config.namespace,
        ):
            logger.info(f"Deleting pod {pod.name}")
            pod.delete()

        if delete_deployments:
            import contextlib

            with contextlib.suppress(kr8s.NotFoundError):
                Deployment.get(
                    namespace=self.config.namespace,
                    label_selector=f"deployment={label}",
                    api=self.api,
                ).delete()
                Deployment.get(
                    namespace=self.config.namespace,
                    label_selector=f"dagster/code-location={label}",
                    api=self.api,
                ).delete()

    def gen_new_deployment_yaml(
        self,
        name: str,
        image_prefix: str | None,
        tag: str,
    ) -> dict:
        """This function generates yaml for a single user-code deployment, which is to be part of the 'deployments' array in the
        values.yaml for dagster's user-code deployments chart.
        """
        import os

        deployment = {
            "name": name,
            "image": {
                "repository": os.path.join(
                    self.config.container_registry,
                    image_prefix or "",
                    name,
                ),
                "tag": tag,
                "pullPolicy": "IfNotPresent",  # Safe, due to versioning of each deployment image
            },
            "dagsterApiGrpcArgs": [
                "-f",
                os.path.join(self.config.docker_root, self.config.code_path),
            ],
            "port": 3030,
            "includeConfigInLaunchedRuns": {"enabled": True},
            "env": self.config.user_code_deployment_env,
            "envConfigMaps": [],
            "envSecrets": self.config.user_code_deployment_env_secrets,
            "annotations": {},
            "nodeSelector": {"agentpool": self.config.node},
            "affinity": {},
            "resources": {
                "limits": self.config.limits,
                "requests": self.config.requests,
            },
            "tolerations": [
                {
                    "key": "agentpool",
                    "operator": "Equal",
                    "value": self.config.node,
                    "effect": "NoSchedule",
                },
            ],
            "podSecurityContext": {},
            "securityContext": {},
            "labels": {},
            "readinessProbe": {
                "enabled": True,
                "periodSeconds": 20,
                "timeoutSeconds": 10,
                "successThreshold": 1,
                "failureThreshold": 3,
            },
            "livenessProbe": {},
            "startupProbe": {"enabled": False},
            "service": {"annotations": {}},
        }
        logger.debug(f"Generated user code deployment:\n{deployment}")
        return deployment

    def _read_namespaced_config_map(
        self,
        name: str,
    ) -> ConfigMap:
        """Read a configmap that exists on the k8s cluster"""
        configmap = ConfigMap.get(name=name, namespace=self.config.namespace, api=self.api)
        return configmap

    def add_user_deployment_to_configmap(
        self,
        new_deployment: dict,
    ) -> None:
        """This function takes a new user-code deployment yaml and adds it to the deployments array
        in the values.yaml of dagster's user-code deployment chart.
        (referring to the values.yaml that is stored in a configmap on k8s.)
        """

        def modify_func(current_deployments: list[dict]) -> list[dict]:
            return current_deployments + [new_deployment]

        self._modify_user_deployments(modify_func)

    def remove_user_deployment_from_configmap(
        self,
        name: str,
    ) -> None:
        """This function removes a user-code deployment yaml from the deployments array
        in the values.yaml of dagster's user-code deployment chart.
        (referring to the values.yaml that is stored in a configmap on k8s.)
        """

        def modify_func(current_deployments: list[dict]) -> list[dict]:
            filtered = list(filter(lambda d: d["name"] != name, current_deployments))
            if len(filtered) == len(current_deployments):
                logger.warning(
                    f'Deployment name "{name}" does not seem to exist in environment "{self.config.environment}". Proceeding to attempt deletion of k8s resources anyways.',
                )
            return filtered

        self._modify_user_deployments(modify_func)

    def _modify_user_deployments(
        self,
        modify_func: Callable[[list[dict]], list[dict]],
    ) -> None:
        """Modifies the deployments array of the values.yaml for Dagster's user-code deployment chart on k8s.

        This function allows for customization of the deployments array by providing a `modify_func` which
        will process the current list of deployments and should return the modified list of deployments.
        This operation is treated as a transaction.

        Args:
            modify_func (Callable[[List[dict]], List[dict]]): A function that takes the current list of
                deployments as input and returns the modified list of deployments.
            config (UserCodeDeploymentsConfig): Config object
        Examples:
            To keep only the first deployment, you can pass the following `modify_func`

            >>> modify_user_deployments(lambda deployment_list: deployment_list[0:1])
        """
        from copy import deepcopy

        configmap = self._read_namespaced_config_map(
            self.config.user_code_deployments_configmap_name,
        )
        last_applied_configuration = (
            configmap["metadata"]
            .get("annotations", {})
            .get("kubectl.kubernetes.io/last-applied-configuration", None)
        )
        current_deployments: list = yaml.safe_load(configmap["data"]["yaml"])["deployments"]

        current_deployments = modify_func(current_deployments)

        depl_list_str = (
            "\n".join([d["name"] for d in current_deployments])
            if len(current_deployments)
            else "No deployments"
        )
        logging.debug(f"List of currently configured deployments:\n{depl_list_str}\n\n")
        new_configmap_data = deepcopy(BASE_CONFIGMAP_DATA)
        new_configmap_data["deployments"] = current_deployments

        new_configmap = deepcopy(BASE_CONFIGMAP)
        new_configmap["data"]["yaml"] = yaml.dump(new_configmap_data)

        new_configmap["metadata"] = {
            "name": self.config.user_code_deployments_configmap_name,
            "namespace": self.config.namespace,
            "annotations": {
                "kubectl.kubernetes.io/last-applied-configuration": last_applied_configuration,
            },
        }
        configmap.patch(new_configmap)

    def get_deployment_name(  # noqa: D102
        self,
        deployment_name_suffix: str | None = None,
        use_project_name: bool = True,
    ) -> DagsterDeployment:
        """Creates a deployment name based on the name of the pyproject.toml and name of git branch"""
        logger.debug("Determining deployment name...")

        project_name = self._get_project_name() if use_project_name else None

        if not self.config.cicd:
            branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"]).decode()
            if deployment_name_suffix:
                branch += deployment_name_suffix
            branch = re.sub(r"[^a-zA-Z0-9]+", "-", branch).strip("-")  # Strips double --
            name = f"{project_name}--{branch}" if project_name is not None else branch
        else:
            branch = self.config.environment
            name = f"{project_name}--{branch}" if project_name is not None else branch

        return DagsterDeployment(
            full_name=name,
            branch_name=branch,
        )

    def _ensure_dagster_version_match(self) -> None:
        """Raises an exception if the cluster version of dagster is different than the local version"""
        logger.debug("Going to read the cluster dagster version...")
        local_dagster_version = Version(self.config.dagster_version)

        ## GETS cluster version from dagster deamon pod
        deamon_pod = Pod.get(
            label_selector="deployment=daemon",
            namespace=self.config.namespace,
            api=self.api,
        )

        ex = deamon_pod.exec(command=["dagster", "--version"])
        output = ex.stdout.decode("ascii")  # type: ignore
        cluster_dagster_version = re.findall("version (.*)", output)

        if len(cluster_dagster_version) != 1:
            raise Exception(
                f"Failed parsing the cluster dagster version, exec response from container `{output}`",
            )
        else:
            cluster_dagster_version = Version(cluster_dagster_version[0])

        logger.debug(f"Cluster dagster version detected to be '{cluster_dagster_version}'")
        if not cluster_dagster_version == local_dagster_version:
            raise Exception(
                f"Dagster version mismatch. Local: {local_dagster_version}, Cluster: {cluster_dagster_version}. Try pulling the latest changes from the develop branch and then rebuilding the local python environment.",
            )

    def check_if_code_pod_exists(self, label: str) -> bool:
        """Checks if the code location pod of specific label is available"""
        running_pods = list(
            self.api.get(
                Pod,
                label_selector=f"deployment={label}",
                namespace=self.config.namespace,
            ),
        )
        return len(running_pods) > 0

    def delete_k8s_resources(self, label_selector: str):
        """Delete all k8s resources with a specified label_selector"""
        for resource in [
            "Pod",
            "ReplicationController",
            "Service",
            "DaemonSet",
            "Deployment",
            "ReplicaSet",
            "StatefulSet",
            "HorizontalPodAutoscaler",
            "CronJob",
            "Job",
        ]:
            for item in self.api.get(
                resource,
                namespace=self.config.namespace,
                label_selector=label_selector,
            ):
                item.delete()

    def acquire_semaphore(self, reset_lock: bool = False) -> bool:
        """Acquires a semaphore by creating a configmap"""
        if reset_lock:
            try:
                semaphore = ConfigMap.get(
                    self.config.uc_deployment_semaphore_name,
                    namespace=self.config.namespace,
                    api=self.api,
                )
                semaphore.delete()
            except kr8s.NotFoundError:
                pass

        try:
            semaphore = ConfigMap.get(
                self.config.uc_deployment_semaphore_name,
                namespace=self.config.namespace,
                api=self.api,
            )
            if semaphore.data.get("locked") == "true":
                return False
            else:
                semaphore.patch({"data": {"locked": "true"}})
                return True
        except kr8s.NotFoundError:
            # Create semaphore if it does not exist
            semaphore = ConfigMap(
                {
                    "metadata": {
                        "name": self.config.uc_deployment_semaphore_name,
                        "namespace": self.config.namespace,
                    },
                    "data": {"locked": "true"},
                },
                api=self.api,
            ).create()
            return True

    def release_semaphore(self) -> None:
        """Releases the semaphore lock"""
        try:
            semaphore = ConfigMap.get(
                self.config.uc_deployment_semaphore_name,
                namespace=self.config.namespace,
                api=self.api,
            )
            semaphore.patch({"data": {"locked": "false"}})
            logger.debug("patched semaphore to locked: false")
        except Exception as e:
            logger.error(f"Failed to release deployment lock: {e}")

    def _get_project_name(self) -> str | None:
        import tomli

        try:
            with open("pyproject.toml", "rb") as fp:
                data = tomli.load(fp)
                return re.sub("[^a-zA-Z0-9-]", "-", data["project"]["name"]).strip("-")
        except FileNotFoundError:
            logger.warning("""
            pyproject.toml not found, no project name will be used.
            Make sure dagster-uc is called in the same directory as the project""")
            return None
