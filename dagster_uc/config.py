import os
from dataclasses import dataclass, fields

import yaml

from dagster_uc.initialize_logger import logger


def load_config(environment: str, path: str | None) -> "UserCodeDeploymentsConfig":
    """Loads the configuration file from the local dir or the user's home dir."""
    if path is None:
        paths_to_try = [
            ".config_user_code_deployments.yaml",
            "~/.config_user_code_deployments.yaml",
        ]
        for path_to_try in paths_to_try:
            path_to_try = os.path.expanduser(path_to_try)
            if os.path.exists(path_to_try):
                path = path_to_try
        if path is None:
            raise Exception(
                f"Could not load config file. Tried the following locations: {paths_to_try}\nCurrent folder: {os.getcwd()}\nContents of current folder: {os.listdir(os.getcwd())}\n\n Tip: Place the config file in the same folder you're calling this script from, or your home directory, or specify the path manually using --config-file <path>",
            )
    with open(path) as stream:
        raw_yaml = yaml.safe_load(stream)
        if environment not in raw_yaml:
            raise Exception(
                f"Environment '{environment}' not specified in configuration file at '{path}'",
            )
        data = raw_yaml[environment]
    for field in fields(UserCodeDeploymentsConfig):
        if os.environ.get(field.name.upper(), None) is not None:
            data[field.name] = os.environ[field.name.upper()]
    logger.debug(f"Using configuration:\n {data}")
    return UserCodeDeploymentsConfig(**data)


@dataclass
class UserCodeDeploymentsConfig:
    """This is a data class that holds the configuration parameters necessary
    for running the user code deployment script.
    """

    environment: str
    acr: str
    dockerfile: str
    namespace: str
    subscription: str
    acr_subscription: str
    node: str
    code_path: str
    docker_root: str
    repository_root: str
    dagster_version: str
    user_code_deployment_env_secrets: list[
        dict[str, str]
    ]  # Must be list of dicts with key 'name' like so: [{"name": "sp-credentials"}, {"name": "lakefs-credentials"}]
    user_code_deployment_env: list[
        dict[str, str]
    ]  # Must be list of dicts with keys 'name' and 'value' like so: [{"name": "MY_ENV_VAR", "value": "True"}, ...]
    cicd: bool
    limits: dict[str, str]
    requests: dict[str, str]
    python_version: str
    kubernetes_context: str
    dagster_gui_url: str = ""
    user_deployments_values_yaml: str = "dagster-user-deployments-values.yaml"
    user_code_deployments_configmap_name: str = "dagster-user-deployments-values-yaml"
    dagster_workspace_yaml_configmap_name = "dagster-workspace-yaml"
    verbose: bool = False
    uc_deployment_semaphore_name: str = "dagster-uc-semaphore"
