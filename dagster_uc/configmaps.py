# This is a k8s yaml for defining a custom configmap with yaml data in it, loaded into a dictionary.
# We will put the values.yaml for dagster's user-code deployment chart inside, and thereby use it to keep track of
# currently deployed user code deployments and their configuration *on the k8s cluster*.
BASE_CONFIGMAP = {
    "apiVersion": "v1",
    "kind": "ConfigMap",
    "data": {"yaml": ""},
    "metadata": {},
}

# This is the data we want to insert into our custom configmap. It's the 'values.yaml' that is to be fed into the
# dagster user-code deployment chart later. This values.yaml starts out with an empty deployment list and is later
# modified and updated to contain all the relevant deployments and credentials.
BASE_CONFIGMAP_DATA = {
    "global": {
        "postgresqlSecretName": "",
        "dagsterHome": "",
        "serviceAccountName": "",
        "celeryConfigSecretName": "",
    },
    "dagsterHome": "/opt/dagster/dagster_home",
    "postgresqlSecretName": "dagster-postgresql-secret",
    "celeryConfigSecretName": "dagster-celery-config-secret",
    "deployments": [],
    "imagePullSecrets": [],
    "serviceAccount": {"create": True, "name": "", "annotations": {}},
    "rbacEnabled": True,
    "extraManifests": [],
}
