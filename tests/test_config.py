import pytest

from dagster_uc.config import load_config


@pytest.mark.parametrize(
    ("environment", "expected"),
    [
        (
            "dev",
            {
                "repository_root": ".",
                "environment": "dev",
                "code_path": "example/repo.py",
                "dagster_version": "1.11.16",
                "cicd": False,
                "dagster_gui_url": "http://dagster.dev",
                "verbose": False,
                "use_project_name": True,
                "project_name_override": "",
                "use_latest_chart_version": True,
                "docker_config": {
                    "container_registry": "dagster-uc.dev.acr.io",
                    "dockerfile": "docker/dev.Dockerfile",
                    "docker_root": ".",
                    "docker_env_vars": ["FOO", "FOO='string'"],
                    "image_prefix": "example",
                    "use_az_login": True,
                    "container_registry_chart_path": "helm/dagster/dagster-user-deployments",
                    "build_format": "OCI",
                },
                "helm_config": {
                    "disable_openapi_validation": False,
                    "skip_schema_validation": True,
                    "create_new_namespace": True,
                },
                "kubernetes_config": {
                    "context": "aks-dev",
                    "namespace": "dagster",
                    "node": "cpunode",
                    "image_pull_secrets": [],
                    "user_code_deployment_env_secrets": [{"name": "dagster-storage-secret"}],
                    "user_code_deployment_env": [
                        {"name": "ON_K8S", "value": "1"},
                        {"name": "ENVIRONMENT", "value": "dev"},
                    ],
                    "service_account_annotations": {},
                    "pod_labels": {},
                    "limits": {"cpu": "4000m", "memory": "2000Mi"},
                    "requests": {"cpu": "150m", "memory": "750Mi"},
                },
                "dagster_chart_config": {
                    "deployments_configmap_name": "dagster-user-deployments-values-yaml",
                    "workspace_yaml_configmap_name": "dagster-workspace-yaml",
                    "deployment_semaphore_name": "dagster-uc-semaphore",
                    "release_name": "dagster-user-code",
                },
            },
        ),
        (
            "acc",
            {
                "repository_root": ".",
                "environment": "acc",
                "code_path": "example/repo.py",
                "dagster_version": "1.11.16",
                "cicd": False,
                "dagster_gui_url": "http://dagster.acc",
                "verbose": False,
                "use_project_name": True,
                "project_name_override": "",
                "use_latest_chart_version": True,
                "docker_config": {
                    "container_registry": "dagster-uc.acc.acr.io",
                    "dockerfile": "docker/acc.Dockerfile",
                    "docker_root": ".",
                    "docker_env_vars": ["FOO", "FOO='string'"],
                    "image_prefix": "example",
                    "use_az_login": True,
                    "container_registry_chart_path": "helm/dagster/dagster-user-deployments",
                    "build_format": "OCI",
                },
                "helm_config": {
                    "disable_openapi_validation": False,
                    "skip_schema_validation": True,
                    "create_new_namespace": True,
                },
                "kubernetes_config": {
                    "context": "aks-acc",
                    "namespace": "dagster",
                    "node": "cpunode",
                    "image_pull_secrets": [],
                    "user_code_deployment_env_secrets": [{"name": "dagster-storage-secret"}],
                    "user_code_deployment_env": [
                        {"name": "ON_K8S", "value": "1"},
                        {"name": "ENVIRONMENT", "value": "acc"},
                    ],
                    "service_account_annotations": {},
                    "pod_labels": {},
                    "limits": {"cpu": "4000m", "memory": "2000Mi"},
                    "requests": {"cpu": "150m", "memory": "750Mi"},
                },
                "dagster_chart_config": {
                    "deployments_configmap_name": "dagster-user-deployments-values-yaml",
                    "workspace_yaml_configmap_name": "dagster-workspace-yaml",
                    "deployment_semaphore_name": "dagster-uc-semaphore",
                    "release_name": "dagster-user-code",
                },
            },
        ),
    ],
)
def test_load_config(environment: str, expected: dict):  # noqa
    dev_config = load_config(environment, path="tests/config/.config_user_code_deployments.yaml")

    assert dev_config.model_dump() == expected
