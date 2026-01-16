from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from string import Template
from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    EnvSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from dagster_uc.log import logger

OVERRIDE_CONFIG_FILE_PATH: str | None = None
DEFAULT_CONFIG_FILE_PATH = ".config_user_code_deployments.yaml"


def get_config_file_path() -> str:
    """Gets config file path in this order, manual input from cli -> env var -> default"""
    if OVERRIDE_CONFIG_FILE_PATH is None:
        return os.environ.get("CONFIG_FILE_PATH", DEFAULT_CONFIG_FILE_PATH)
    else:
        return OVERRIDE_CONFIG_FILE_PATH


class KubernetesResource(BaseModel):
    """Kubernetes resources"""

    cpu: str | int
    memory: str | int


class KubernetesSecret(BaseModel):
    """Kubernetes secret"""

    name: str


class KubernetesEnvVar(BaseModel):
    """Kubernetes env var"""

    name: str
    value: str


def deep_merge(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge dict `b` into `a`."""
    result = deepcopy(a)
    for key, value in b.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class EnvParsedYamlConfigSettingsSource(YamlConfigSettingsSource):
    """Yaml Settings Source that parses envVar references before loading. Also selects the env subset based one the environment.
    And merges the defaults in as well.

    ENV VARS need to be configured like this: ${ENV_VAR}

    An example of a valid config.yaml would be:
        ```yaml
        defaults:
            var: "foo"

        dev:
            var: "${env_var}"
        acc:
            var2: "bar"
        ```
    """

    def _read_file(self, file_path: Path) -> dict[str, Any]:
        import json

        data = super()._read_file(file_path)

        environment = os.environ.get("ENVIRONMENT", "dev")

        # get based on environment
        environment_data = data.get(environment)

        if environment_data is None:
            logger.warning("Didn't find environment %s in config yaml", environment)
            environment_data = {}

        defaults_data = data.get("defaults", {})
        combined_data = deep_merge(defaults_data, environment_data)

        data = json.dumps(combined_data)
        data = Template(data).substitute(os.environ)
        return json.loads(data)


class _BaseSettingsWithYamlAndEnv(BaseSettings):
    model_config = SettingsConfigDict(
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(  # noqa: D102
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,  # noqa: ARG003
        env_settings: PydanticBaseSettingsSource,  # noqa: ARG003
        dotenv_settings: PydanticBaseSettingsSource,  # noqa: ARG003
        file_secret_settings: PydanticBaseSettingsSource,  # noqa: ARG003
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            EnvSettingsSource(settings_cls),
            EnvParsedYamlConfigSettingsSource(settings_cls, yaml_file=get_config_file_path()),
        )


class DockerConfiguration(BaseModel):
    """Configuration specific for Docker or Container registry related."""

    container_registry: str
    dockerfile: str
    docker_root: str = Field(default="")
    docker_env_vars: list[str] = Field(default=[])
    image_prefix: str = Field(default="")
    use_az_login: bool = Field(default=True)
    container_registry_chart_path: str | None = Field(default=None)
    build_format: Literal["OCI", "docker"] = "OCI"


class HelmConfiguration(BaseModel):
    """Helm specific configuration"""

    disable_openapi_validation: bool = Field(default=False)
    skip_schema_validation: bool = Field(default=False)
    create_new_namespace: bool = Field(default=True)


class KubernetesConfiguration(BaseModel):
    """Kubernetes specific configuration."""

    context: str
    namespace: str
    node: str
    image_pull_secrets: list[KubernetesSecret] = Field(default=[])
    user_code_deployment_env_secrets: list[KubernetesSecret] = Field(default=[])
    user_code_deployment_env: list[KubernetesEnvVar] = Field(default=[])
    limits: KubernetesResource | None = Field(default=None)
    requests: KubernetesResource | None = Field(default=None)
    service_account_annotations: dict = Field(default={})
    pod_labels: dict = Field(default={})


class DagsterUserCodeChartConfiguration(BaseModel):
    """User code chart configuration"""

    deployments_configmap_name: str = "dagster-user-deployments-values-yaml"
    workspace_yaml_configmap_name: str = "dagster-workspace-yaml"
    deployment_semaphore_name: str = "dagster-uc-semaphore"
    release_name: str = "dagster-user-code"


class DagsterUserCodeConfiguration(_BaseSettingsWithYamlAndEnv):
    """Dagster User Code configuration"""

    # Environment/code config
    repository_root: str = Field(default="")
    environment: str
    code_path: str
    dagster_version: str
    cicd: bool = Field(default=False)
    dagster_gui_url: str | None = Field(default=None)
    verbose: bool = Field(default=False)
    use_project_name: bool = Field(default=True)
    project_name_override: str = Field(default="")
    use_latest_chart_version: bool = False

    docker_config: DockerConfiguration = Field(default_factory=DockerConfiguration, alias="docker")  # type: ignore
    helm_config: HelmConfiguration = Field(default_factory=HelmConfiguration, alias="helm")
    kubernetes_config: KubernetesConfiguration = Field(
        default_factory=KubernetesConfiguration,  # type: ignore
        alias="kubernetes",
    )
    dagster_chart_config: DagsterUserCodeChartConfiguration = Field(
        default_factory=DagsterUserCodeChartConfiguration,
        alias="chart",
    )


def load_config(environment: str, path: str | None = None) -> DagsterUserCodeConfiguration:
    """Loads the configuration file from the local dir or the user's home dir."""
    os.environ["ENVIRONMENT"] = environment
    global OVERRIDE_CONFIG_FILE_PATH
    if path is not None:
        OVERRIDE_CONFIG_FILE_PATH = path

    return DagsterUserCodeConfiguration()  # type: ignore
