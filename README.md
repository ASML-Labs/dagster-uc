# Introduction

This experimental CLI allows you to manage user code deployments for a Dagster instance deployed on Kubernetes. It packages your code branch into a Docker container, uploads it to your container registry, and updates your existing Dagster instance to enable your user code deployment.

# Pre-requisites

* kubectl with a valid config
* Helm 3
* Podman
* Python 3.10+
* Azure CLI (if you are using Azure container registry and `use_az_login`)

# Installation

* Install from PyPI:
  ```
  pip install dagster-uc
  ```

* Create a configuration file named `.config_user_code_deployments.yaml` in the root of your repository or in your home directory.
  You can also create one by running:
  ```
  dagster-uc init-config -f '.config_user_code_deployments.yaml'
  ```

# Configuration (nested structure)

The configuration format is now nested and grouped by concerns (e.g. `docker`, `kubernetes`, `helm`). The top-level keys you will commonly use are:

* `defaults` — values applied to every environment unless overridden.
* Per-environment sections (e.g. `dev`, `acc`, `prd`) — environment-specific overrides.
* `docker` — Docker/build related settings (dockerfile, registry, image prefix, build env vars, etc).
* `kubernetes` — Kubernetes-specific settings (context, namespace, resource requests/limits, env and secret lists).
* `helm` — Helm-related settings (for example, skip schema validation).
* `chart` — chart-specific values you may want to supply into the user-deployments Helm chart.
* `use_latest_chart_version`, `use_project_name`, and `project_name_override` — deployment behavior flags.

Order of loading configuration:
1. `defaults`
2. environment-specific keys (e.g. `dev`)
3. environment variable overrides

Below is an example config that mirrors the new nested structure:

```yaml
defaults:
  repository_root: "."
  code_path: example/repo.py
  dagster_version: 1.11.16
  cicd: false
  use_project_name: True
  use_latest_chart_version: True
  # Docker configuration (grouped under `docker`)
  docker:
    docker_root: "."
    docker_env_vars:
      - FOO
      - FOO='string'
    image_prefix: "example"
    use_az_login: True
    container_registry_chart_path: "helm/dagster/dagster-user-deployments"

  # Helm configuration (grouped under `helm`)
  helm:
    skip_schema_validation: True

  # Kubernetes configuration (grouped under `kubernetes`)
  kubernetes:
    namespace: dagster
    node: cpunode
    requests:
      cpu: 150m
      memory: 750Mi
    limits:
      cpu: 4000m
      memory: 2000Mi
    user_code_deployment_env_secrets:
      - name: dagster-storage-secret

  chart: {}

dev:
  environment: dev
  dagster_gui_url: "http://dagster.dev"

  docker:
    dockerfile: "docker/dev.Dockerfile"
    container_registry: dagster-uc.dev.acr.io

  kubernetes:
    context: "aks-dev"
    user_code_deployment_env:
      - name: ON_K8S
        value: '1'
      - name: ENVIRONMENT
        value: dev

acc:
  environment: acc
  dagster_gui_url: "http://dagster.acc"
  project_name_override: 'example-acc'

  docker:
    dockerfile: "docker/acc.Dockerfile"
    container_registry: dagster-uc.acc.acr.io

  kubernetes:
    context: "aks-acc"
    user_code_deployment_env:
      - name: ON_K8S
        value: '1'
      - name: ENVIRONMENT
        value: acc
```

Notes on common config keys (now nested):
* `code_path` — path to the Python module that starts your Dagster definitions (used to start the user-code gRPC server).
* `docker.dockerfile` — path to the Dockerfile to build the image.
* `docker.container_registry` — target container registry for the built image (per-environment override).
* `docker.image_prefix` — prefix used when naming images.
* `docker.docker_env_vars` — list of environment variables to pass into the build process.
* `docker.use_az_login` — set to `True` if you need to log in to Azure before pushing images.
* `kubernetes.context` — the kube context to use for deployments in that environment.
* `kubernetes.namespace` — the namespace where Dagster and user deployments live.
* `kubernetes.requests` / `kubernetes.limits` — resource requests and limits for the user code deployment pod.
* `kubernetes.user_code_deployment_env` — a list of name/value env objects to inject into the user-code deployment container.
* `kubernetes.user_code_deployment_env_secrets` — a list of secrets to be mounted/injected as environment variables.
* `helm.skip_schema_validation` — useful for older Helm chart setups or when schema validation causes issues.
* `use_project_name` — when True, the project name from `pyproject.toml` is prefixed to the deployment name.
* `project_name_override` - When set, the project name from `pyproject.toml` is overridden with this value

### Overriding Config with Environment Variables

Environment variables can still be used to override configuration at load time but you need to scaffold them in the yaml using `cicd: ${CICD}`. You can export common flags (for example `CICD=TRUE` or `VERBOSE=TRUE`) to affect behavior — top-level boolean or string fields are typically overridden this way. If you need to override nested values in automation, set the environment variables your automation expects before running the CLI.

# Usage

* Deploy the currently checked out Git branch:
  ```
  dagster-uc deployment deploy
  ```

* See all available commands:
  ```
  dagster-uc --help
  ```

# Branch naming and deployments

* When `cicd: true` is set, the deployment name is derived from the `environment` value.
* When `cicd: false`, the deployment name is derived from the Git branch name. The branch name is normalized by replacing non-alphanumeric characters with hyphens and stripping leading/trailing hyphens.
  Example: `feat: my amazing feature` -> `feat-my-amazing-feature`

* You can deploy the same branch multiple times by supplying `--deployment-name-suffix`, which appends a suffix to the deployment name.

* When `use_project_name` is enabled, the internal deployment name will be prefixed by a project slug derived from your `pyproject.toml`. Internally the prefix separator is `--` so an example name may be `my-project--feat-a`, which appears in the Dagster UI as `project:branch`.

# Building and container behavior

* The build process passes a `BRANCH_NAME` build-arg so your code can behave differently per branch (e.g. selecting secrets, configuration).
* Images are versioned: the CLI will check the registry for existing tags and increment a version to avoid reusing tags that could break running jobs.
* Use a registry lifecycle/garbage-collection policy to keep old images from accumulating.

Example Dockerfile pattern:

```
FROM python:3.11-slim
ARG BRANCH_NAME
ARG DIR="APP"
WORKDIR $DIR
COPY my_project my_project
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --link-mode=copy
ENV PATH="/$DIR/.venv/bin:$PATH"
ENV BRANCH_NAME=${BRANCH_NAME}
```

# Kubernetes / Helm

* Make sure `kubernetes.context` can access the `kubernetes.namespace`.
* Configure `kubernetes.requests` and `kubernetes.limits` for the user-code deployment pod appropriately.
* Pass environment variables via `kubernetes.user_code_deployment_env` and secrets via `kubernetes.user_code_deployment_env_secrets`.
* Helm values and chart overrides can be supplied under `chart` in the config file — these are passed to the user-deployments Helm chart.

# Tips

* Keep a `defaults` section in your config file to reduce duplication between environments.
* Use environment-specific overrides for registry, kube context, and secrets.
* If you use Azure, set `docker.use_az_login: True` and ensure your environment has access to `az` and the appropriate credentials.

# Troubleshooting

* If Helm chart upgrades fail due to schema validation, try setting `helm.skip_schema_validation: True` in your `defaults` or environment override.
* Check that `kubernetes.context` points to the correct cluster and that your kube credentials have permission to modify the target namespace.
* Ensure the `code_path` points to an importable Python module that starts your Dagster definitions.

# Example test config

A small, real example is checked into the repo under `tests/config/.config_user_code_deployments.yaml` and demonstrates the new nested structure used by the CLI tests.
