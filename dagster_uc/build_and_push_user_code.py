import os
import subprocess

from dagster_uc.utils import BuildTool, exception_on_failed_subprocess


def build_and_push(
    repository_root: str,
    image_registry: str,
    subscription: str,
    base_image: str,
    image_name: str,
    dockerfile: str,
    build_with_sudo: bool,
    build_tool: BuildTool,
    tag: str,
    branch_name: str,
):
    """Build a docker image and push it to the registry"""
    # We need to work from the root of the repo so docker can access all files
    previous_dir = os.getcwd()
    os.chdir(repository_root)

    if build_tool == BuildTool.docker:
        cmd = [
            "docker",
            "build",
            "-f",
            os.path.join(repository_root, dockerfile),
            "-t",
            f"{image_name}:{tag}",
            "--build-arg=BASE_IMAGE=" + base_image,
            "--build-arg=BRANCH_NAME=" + branch_name,
            ".",
        ]

        if build_with_sudo:
            cmd = ["sudo"] + cmd

        exception_on_failed_subprocess(subprocess.run(cmd, capture_output=False))

        cmd = [
            "docker",
            "tag",
            f"{image_name}:{tag}",
            image_registry + f"/{image_name}:{tag}",
        ]
        if build_with_sudo:
            cmd = ["sudo"] + cmd
        exception_on_failed_subprocess(subprocess.run(cmd, capture_output=False))

        print("Logging into acr...")
        cmd = [
            "az",
            "acr",
            "login",
            "--name",
            image_registry,
            "--expose-token",
            "--output",
            "tsv",
            "--query",
            "accessToken",
            "--subscription",
            subscription,
        ]
        if build_with_sudo:
            cmd = ["sudo"] + cmd
        print(f"Executing cmd: {' '.join(cmd)}")
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=False)
        output, error = process.communicate()
        token = output.decode().strip().encode("utf-8")

        cmd = [
            "docker",
            "login",
            "--username",
            "00000000-0000-0000-0000-000000000000",
            "--password-stdin",
            image_registry,
        ]
        if build_with_sudo:
            cmd = ["sudo"] + cmd
        exception_on_failed_subprocess(subprocess.run(cmd, input=token, capture_output=False))

        print("Pushing image...")
        cmd = ["docker", "push", image_registry + f"/{image_name}:{tag}"]
        if build_with_sudo:
            cmd = ["sudo"] + cmd
        exception_on_failed_subprocess(subprocess.run(cmd, capture_output=False))
    elif build_tool == BuildTool.buildah:
        cmd = [
            "buildah",
            "bud",
            "-f",
            os.path.join(repository_root, dockerfile),
            "--isolation=chroot",
            "--layers=true",
            "-t",
            f"{image_name}:{tag}",
            "--build-arg=BASE_IMAGE=" + base_image,
            "--build-arg=BRANCH_NAME=" + branch_name,
            ".",
        ]

        if build_with_sudo:
            cmd = ["sudo"] + cmd

        exception_on_failed_subprocess(subprocess.run(cmd, capture_output=False))

        cmd = [
            "buildah",
            "tag",
            f"{image_name}:{tag}",
            image_registry + f"/{image_name}:{tag}",
        ]

        if build_with_sudo:
            cmd = ["sudo"] + cmd

        exception_on_failed_subprocess(subprocess.run(cmd, capture_output=False))

        print("Logging into acr...")
        cmd = [
            "az",
            "acr",
            "login",
            "--name",
            image_registry,
            "--expose-token",
            "--output",
            "tsv",
            "--query",
            "accessToken",
            "--subscription",
            subscription,
        ]

        if build_with_sudo:
            cmd = ["sudo"] + cmd
        print(f"Executing cmd: {' '.join(cmd)}")
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=False)
        output, error = process.communicate()
        token = output.decode().strip().encode("utf-8")

        cmd = [
            "buildah",
            "login",
            "--username",
            "00000000-0000-0000-0000-000000000000",
            "--password-stdin",
            image_registry,
        ]
        if build_with_sudo:
            cmd = ["sudo"] + cmd
        exception_on_failed_subprocess(subprocess.run(cmd, input=token, capture_output=False))

        print("Pushing image...")
        cmd = ["buildah", "push", image_registry + f"/{image_name}:{tag}"]
        if build_with_sudo:
            cmd = ["sudo"] + cmd
        exception_on_failed_subprocess(subprocess.run(cmd, capture_output=False))
    else:
        raise Exception(f"Unsupported build tool: {build_tool}")
    os.chdir(previous_dir)
