#!/usr/bin/env python3

import sys
import os
import docker
from datetime import datetime
from jinja2 import Template

AWS_ECR_PUBLIC_ALIAS = "dev1-sg"
AWS_ECR_PUBLIC_REGION = "us-east-1"
AWS_ECR_PUBLIC_REPOSITORY_GROUP = "base"

README_TEMPLATE_PATH = "./templates/image_readme.j2"
SRC_PATH = "./src"

now = datetime.now().astimezone()
updated_time = now.strftime("%c"), now.tzname()

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
        print("[DEBUG] Image pull complete")
        return image
    except docker.errors.APIError as e:
        print(f"[ERROR] Failed to pull image {image_name}: {e}")
        raise

def get_image_architecture(client, image):
    arch = client.images.get(image.id).attrs.get("Architecture", "unknown")
    print(f"[DEBUG] Image architecture: {arch}")
    return arch

def run_container_command(client, image_name, command, arch):
    print(f"[DEBUG] Running command on image '{image_name}' with arch '{arch}': {command}")
    try:
        output = client.containers.run(
            image=image_name,
            command=command,
            remove=True,
            platform=f"linux/{arch}"
        )
        decoded = output.decode("utf-8")
        print(f"[DEBUG] Command output:\n{decoded}")
        return decoded
    except docker.errors.ContainerError as e:
        stderr = e.stderr.decode() if e.stderr else str(e)
        print(f"[ERROR] Container command failed:\n{stderr}")
        raise
    except docker.errors.APIError as e:
        print(f"[ERROR] Docker API error: {e}")
        raise

def parse_key_value_output(output):
    result = {}
    for line in output.strip().splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            result[key] = value.strip('"')
    return result

def run_command_with_fallback(client, image_name, arch):
    try:
        return run_container_command(client, image_name, "apk info", arch).strip().splitlines()
    except (docker.errors.ContainerError, docker.errors.APIError):
        try:
            return run_container_command(client, image_name, "sh -c 'apt list | tail -n +2'", arch).strip().splitlines()
        except (docker.errors.ContainerError, docker.errors.APIError) as e:
            print(f"[WARN] Both apk and apt commands failed for {image_name}: {e}")
            return []

def main():
    if len(sys.argv) != 2:
        print("Usage: python3 run_image_readme.py <image_name>")
        sys.exit(1)

    keyword = sys.argv[1]
    target_dir = os.path.join(SRC_PATH, keyword)

    if not os.path.isdir(target_dir):
        print(f"[ERROR] Directory not found: {target_dir}")
        sys.exit(1)

    client = docker.from_env()

    docker_image_name = keyword
    ecr_public_image_uri = f"public.ecr.aws/{AWS_ECR_PUBLIC_ALIAS}/{AWS_ECR_PUBLIC_REPOSITORY_GROUP}/{docker_image_name}:latest"
    readme_output_path = os.path.join(target_dir, "readme.md")

    try:
        image = pull_image(client, ecr_public_image_uri)
        arch = get_image_architecture(client, image)

        os_release_str = run_container_command(client, ecr_public_image_uri, "cat /etc/os-release", arch)
        os_release_info = parse_key_value_output(os_release_str)

        env_output_str = run_container_command(client, ecr_public_image_uri, "env", arch)
        env_vars = env_output_str.strip().splitlines()

        pkg_vars = run_command_with_fallback(client, ecr_public_image_uri, arch)

        local_output_str = run_container_command(client, ecr_public_image_uri, "ls -1 /usr/local/bin", arch)
        pkg_local = local_output_str.strip().splitlines()

        with open(README_TEMPLATE_PATH) as tpl_file:
            template_content = tpl_file.read()
        template = Template(template_content, trim_blocks=True, lstrip_blocks=True)

        context = {
            "image": ecr_public_image_uri,
            "arch": arch,
            "os_name": os_release_info.get("NAME"),
            "os_version_id": os_release_info.get("VERSION_ID"),
            "os_id": os_release_info.get("ID"),
            "env_vars": env_vars,
            "pkg_vars": pkg_vars,
            "pkg_local": pkg_local,
        }

        output = template.render(context=context, updated_at=updated_time)

        print(f"[INFO] Writing readme to: {readme_output_path}")
        with open(readme_output_path, "w") as f:
            f.write(output)

    except Exception as e:
        print(f"[ERROR] Failed to process {docker_image_name}: {e}")

if __name__ == "__main__":
    main()
