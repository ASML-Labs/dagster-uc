
# Introduction

This experimental CLI allows you to manage user code deployments for a Dagster instance deployed on Kubernetes. It packages your code branch into a Docker container, uploads it to your container registry, and updates your existing Dagster instance to enable your user code deployment.

# Pre-requisites

* Kubectl with a valid config
* Helm3
* Podman
* Python3.10+
* AZ CLI (if you are on azure)

# Installation

* `pip install dagster-uc`
* Create a configuration file named `.config_user_code_deployments.yaml` in the root of your repository or your home directory. You can also create one by running `dagster-uc init-config -f '.config_user_code_deployments.yaml'`.

```yaml
dev:
  cicd: false
  code_path: dagster_pipelines/repo.py
  image_prefix: 'team-alpha'
  container_registry: myacr.azurecr.io
  dagster_gui_url: null
  dagster_version: 1.8.4
  docker_root: .
  dockerfile: ./Dockerfile
  docker_env_vars:
    - "VAR=SECRET"
    - "RANDOM_VAR_IN_CURRENT_ENV"
  environment: dev
  kubernetes_context: "my-kubernetes-context"
  namespace: dagster-dev
  limits:
    cpu: '2'
    memory: 2Gi
  node: small
  repository_root: .
  requests:
    cpu: '1'
    memory: 1Gi
  use_project_name: true
  use_az_login: false
  user_code_deployment_env:
    - name: ON_K8S
      value: 'True'
    - name: ENVIRONMENT
      value: dev
  user_code_deployment_env_secrets:
    - name: my-env-secret
  user_code_deployments_configmap_name: dagster-user-deployments-values-yaml
  dagster_workspace_yaml_configmap_name: dagster-workspace-yaml
  uc_deployment_semaphore_name: dagster-uc-semaphore
  verbose: false
```

# Instructions

* To deploy the currently checked out Git branch, run `dagster-uc deployment deploy`.
* To see all possible commands, run `dagster-uc --help`

## Environment Configuration

Dagster-uc allows you to have specific user-code deployment configurations per environment. This enables different configurations for your Kubernetes cluster, container registry, resource usage, etc.

The default environment used is `dev`, so you need to have `dev` in your configuration file. Other environment names are up to you. An example structure:

```yaml
dev:
  container_registry: dev-project.azurecr.io
  ...
acc:
  container_registry: acc-project.azurecr.io.
  ...
prd:
  container_registry: prd-project.azurecr.io
  ...
```

Specify the environment with `dagster-uc --environment prd deployment deploy`, or `dagster-uc -e prd deployment deploy` to use the prd config for the deployment.

### Settings defaults

Defaults can be specified for all environments, every key that can be set in the main config can be defined in the defaults. Order of loading config, is defaults -> environment config -> environment variable override.

```yaml
defaults:
  repository_root: "."
  docker_root: "."
  dockerfile: "docker/dev/Dockerfile"
  image_prefix: 'team-alpha'
```

### Overriding Config Settings Through Environment Variables

It's possible to dynamically set different values for fields in one of the environment configurations, while loading the config. This can be achieved through environment variables, examples:

* `export CICD=TRUE`
* `export VERBOSE=TRUE`

## Branches

Dagster-uc deploys a Git branch as a code location to Dagster. When `cicd: true` is set in the config_user_code_deployments.yaml, the deployment name of the code location is derived from the `environment` config variable.

If `cicd: false` the deployment name is derived from the Git branch. The branch name is transformed by replacing non-alphanumeric characters with hyphens and removing any leading or trailing hyphens.

Example: Git branch `feat: my amazing feature` becomes deployment `feat-my-amazing-feature`

### Multiple Deployments of the Same Branch

During deployment, you can provide a `--deployment-name-suffix` to add a suffix to your deployment name. This is useful for testing by deploying the same branch twice with different configurations.

### Multi-Project Deployment in One Dagster Instance

With the `use_project_name` flag in the dagster-uc configuration file, you can prefix the project name to the user-code deployment. The project name is taken from the `pyproject.toml`, so you need to call dagster-uc in the same directory as the `.toml` file.

For example, if the project name in `pyproject.toml` is `my_dummy_project`, the deployment name will be `my-dummy-project--feat-my-amazing-feature`.

> **Important:** Internally the deployment name will use `--` to seperate the project and branch, which is visible on Kubernetes and the container registry. However in the dagster UI it appears as `project:branch`

## Containers

Dagster-uc creates a container image from your existing codebase during deployment.

An example Dockerfile:

```Dockerfile
FROM python:3.11-slim
ARG BRANCH_NAME
ARG DIR="APP"
WORKDIR $DIR
COPY my_project my_project # Contains all code
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --link-mode=copy
ENV PATH="/$DIR/.venv/bin:$PATH"
ENV BRANCH_NAME=${BRANCH_NAME}
```

Set `code_path` in the configuration to the path of the Python executable containing the Dagster definitions. This is used to start the gRPC server. For more details, see the [Dagster K8S docs](https://docs.dagster.io/guides/deploy/deployment-options/kubernetes/deploying-to-kubernetes).

Set `image_prefix` to prefix all the build images. Useful for grouping images under a prefix.

### Versioning

Dagster-uc deploys each image with a version number as a tag. The versioning is done by checking the latest version of that image in the container registry, and then increment by one.

Without this, using the same image tag would cause Dagster to pull the latest image of that tag during existing jobs, potentially causing data inconsistencies.

> **Important:** Use a custom garbage collection policy to remove old branches or keep only the last X tag versions to prevent your container registry from growing too large in size.

### Requirements

Dagster-uc passes a `build-arg=BRANCH_NAME` to the image building step.This is useful because you can script the use of the `BRANCH_NAME` environment variable in your Dagster project code to perform different tasks, such as using a custom IO manager or different secrets. The branch name is either the Git branch or the environment when `cicd` is `true`.

## Kubernetes

Instruct dagster-uc to use the correct `kubernetes_context` that can access your `namespace`. Additionally, configure the pod to use specific compute resource `requests` and `limits`, and set secrets as environment variables using `user_code_deployment_env_secrets` or plain environment variables using `user_code_deployment_env`.
