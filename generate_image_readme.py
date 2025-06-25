#!/usr/bin/env python3

import glob
import os
import docker
from datetime import datetime
from jinja2 import Template

AWS_ECR_PUBLIC_ALIAS = "dev1-sg"
AWS_ECR_PUBLIC_REGION = "us-east-1"
AWS_ECR_PUBLIC_REPOSITORY_GROUP = "base"
README_TEMPLATE_PATH = "./templates/image_readme.j2"
SRC_PATH = "./src"

def pull_image(client, image_name):
    print(f"[DEBUG] Pulling image: {image_name}")
    low_level = docker.APIClient()
    try:
        for line in low_level.pull(image_name, stream=True, decode=True):
            if 'status' in line:
                print(f"  [pull] {line['status']}", end='')
                if 'progress' in line:
                    print(f" {line['progress']}")
                else:
                    print()
            elif 'error' in line:
                print(f"[ERROR] Pull error: {line['error']}")
        image = client.images.get(image_name)
        print("[DEBUG] Pull complete")
        return image
    except docker.errors.APIError as e:
        print(f"[ERROR] Failed to pull image {image_name}: {e}")
        raise

def get_arch(client, image):
    arch = client.images.get(image.id).attrs.get("Architecture", "unknown")
    print(f"[DEBUG] Image architecture: {arch}")
    return arch

def run_cmd(client, image, cmd, arch):
    print(f"[DEBUG] Running command '{cmd}' on image '{image}' with arch '{arch}'")
    try:
        output = client.containers.run(image, cmd, remove=True, platform=f"linux/{arch}")
        decoded = output.decode()
        print(f"[DEBUG] Command output:\n{decoded}")
        return decoded
    except docker.errors.ContainerError as e:
        print(f"[ERROR] Container command error:\n{e.stderr.decode() if e.stderr else str(e)}")
        raise
    except docker.errors.APIError as e:
        print(f"[ERROR] Docker API error during command: {e}")
        raise

def parse_kv(output):
    return dict(line.split("=", 1) for line in output.strip().splitlines() if "=" in line)

def get_pkgs(client, image, arch):
    try:
        return run_cmd(client, image, "apk info", arch).splitlines()
    except docker.errors.DockerException:
        try:
            return run_cmd(client, image, "sh -c 'apt list | tail -n +2'", arch).splitlines()
        except docker.errors.DockerException as e:
            print(f"[WARN] Both apk and apt commands failed: {e}")
            return []

def main():
    client = docker.from_env()
    updated_time = datetime.now().astimezone().strftime("%c")

    for dir_path in glob.glob(f"{SRC_PATH}/*/"):
        image_name = os.path.basename(os.path.normpath(dir_path))
        image_uri = f"public.ecr.aws/{AWS_ECR_PUBLIC_ALIAS}/{AWS_ECR_PUBLIC_REPOSITORY_GROUP}/{image_name}"
        readme_path = os.path.join(dir_path, "readme.md")

        print(f"[INFO] Processing image {image_name}")

        try:
            image = pull_image(client, image_uri)
            arch = get_arch(client, image)
            os_release = parse_kv(run_cmd(client, image_uri, "cat /etc/os-release", arch))
            env_vars = run_cmd(client, image_uri, "env", arch).splitlines()
            pkgs = get_pkgs(client, image_uri, arch)
            local_bins = run_cmd(client, image_uri, "ls -1 /usr/local/bin", arch).splitlines()

            with open(README_TEMPLATE_PATH) as f:
                template = Template(f.read(), trim_blocks=True, lstrip_blocks=True)

            output = template.render(
                context={
                    "image": image_uri,
                    "arch": arch,
                    "os_name": os_release.get("NAME"),
                    "os_version_id": os_release.get("VERSION_ID"),
                    "os_id": os_release.get("ID"),
                    "env_vars": env_vars,
                    "pkg_vars": pkgs,
                    "pkg_local": local_bins,
                },
                updated_at=updated_time,
            )

            with open(readme_path, "w") as f:
                f.write(output)

            print(f"[INFO] Wrote readme for {image_name}")

        except Exception as e:
            print(f"[ERROR] Failed processing {image_name}: {e}")

if __name__ == "__main__":
    main()
