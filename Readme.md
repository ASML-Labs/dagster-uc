### Introduction
This is an experimental CLI. It will allow you to manage user code deployments for a dagster instance that's deployed to kubernetes. It can package your code branch into a docker container, upload it to your ACR and update your existing Dagster instance (on kubernetes) to have your user code deployment.
### Pre-requisites
* You must have a valid kubectl config
### Installation
* `pip install dagster-uc`
* Create a configuration file in the root of your repository or in your home directory named `.config_user_code_deployments.yaml`, similar to this example:
```yaml
dev:
  repository_root: ./
  dagster_gui_url: "http://dagster.company.com/"
  docker_root: "."
  dockerfile: "./k8s_deployments/Dockerfile"
  acr: myacr.azurecr.io
  code_path: dagster_pipelines/repo.py
  dagster_version: 1.8.4
  environment: dev
  cicd: false
  limits:
    cpu: 4000m
    memory: 2000Mi
  namespace: my-k8s-namespace
  node: my-k8s-nodepool
  requests:
    cpu: 150m
    memory: 750Mi
  subscription: my-azure-subscription
  acr_subscription: my-azure-subscription
  user_code_deployment_env:
    - name: ON_K8S
      value: 'True'
    - name: ENVIRONMENT
      value: dev
  user_code_deployment_env_secrets:
    - name: my-env-secret
  python_version: "python:3.10-slim"
  kubernetes_context: "my-kubernetes-context"
```
### Usage
* In order to deploy the currently checked out git branch, run `dagster-uc deployment deploy`
* In order to see all possible commands, run `dagster-uc --help`