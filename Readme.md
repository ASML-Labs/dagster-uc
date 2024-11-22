
# Introduction

This is an experimental CLI. It will allow you to manage user code deployments for a dagster instance that's deployed to kubernetes. It can package your code branch into a docker container, upload it to your ACR and update your existing Dagster instance (on kubernetes) to have your user code deployment.

# Pre-requisites

* Kubectl + valid kubectl config
* Helm3
* Podman
* Python3.10+
* AZ CLI (if you are on azure)

# Installation

* `pip install dagster-uc`
* Create a configuration file in the root of your repository or in your home directory named `.config_user_code_deployments.yaml`, similar to this example. You can also create one by doing `dagster-uc init-config -f '.config_user_code_deployments.yaml'`

```yaml
dev:
  cicd: false
  code_path: dagster_pipelines/repo.py
  container_registry: myacr.azurecr.io
  dagster_gui_url: null
  dagster_version: 1.8.4
  docker_root: .
  dockerfile: ./Dockerfile
  environment: dev
  image_prefix: 'team-alpha'
  kubernetes_context: "my-kubernetes-context"
  limits:
    cpu: '2'
    memory: 2Gi
  namespace: .
  node: small
  repository_root: .
  requests:
    cpu: '1'
    memory: 1Gi
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

# Usage

* In order to deploy the currently checked out git branch, run `dagster-uc deployment deploy`
* In order to see all possible commands, run `dagster-uc --help`
