import os
import boto3
from datetime import datetime
from botocore.config import Config
from dotenv import load_dotenv
import nbformat as nbf
from jinja2 import Environment, FileSystemLoader

load_dotenv(override=False)

def get_env(key, default=None):
    return os.getenv(key, default)

AWS_ECR_PUBLIC_ALIAS = get_env("AWS_ECR_PUBLIC_ALIAS", "dev1-sg")
AWS_ECR_PUBLIC_REGION = get_env("AWS_ECR_PUBLIC_REGION", "us-east-1")
AWS_ECR_PUBLIC_URI = f"public.ecr.aws/{AWS_ECR_PUBLIC_ALIAS}"
AWS_ECR_PUBLIC_URL = f"https://ecr-public.{AWS_ECR_PUBLIC_REGION}.amazonaws.com"
AWS_ECR_PUBLIC_REPOSITORY_GROUP = get_env("AWS_ECR_PUBLIC_REPOSITORY_GROUP", "base")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
README_TEMPLATE_PATH = get_env("README_TEMPLATE_PATH", os.path.join(BASE_DIR, "../templates/ecr-image-list.j2"))
README_OUTPUT_PATH = get_env("README_OUTPUT_PATH", os.path.join(BASE_DIR, "../ecr-image-list.ipynb"))

def get_ecr_client():
    print(f"[DEBUG] Creating ECR public client for region {AWS_ECR_PUBLIC_REGION}")
    return boto3.Session().client(
        "ecr-public",
        region_name=AWS_ECR_PUBLIC_REGION,
        endpoint_url=AWS_ECR_PUBLIC_URL,
        config=Config(signature_version='v4')
    )

def get_repositories(client, prefix=None):
    repos = []
    print("[DEBUG] Retrieving repositories from ECR public")
    try:
        for page in client.get_paginator("describe_repositories").paginate():
            for repo in page.get("repositories", []):
                if prefix is None or repo["repositoryName"].startswith(prefix):
                    repos.append(repo)
                    print(f"[INFO] Found repository: {repo['repositoryName']}")
    except Exception as e:
        print(f"[ERROR] Failed to list repositories: {e}")
        raise
    print(f"[DEBUG] Total repositories found: {len(repos)}")
    return repos

def get_latest_image_info(client, repository_name):
    print(f"[DEBUG] Getting latest image info for repository: {repository_name}")
    try:
        images = client.describe_images(repositoryName=repository_name).get("imageDetails", [])
        if not images:
            print(f"[WARN] No images found in repository {repository_name}")
            return "<none>", 0

        target_images = [img for img in images if any(t != "latest" for t in img.get("imageTags", []))] or images
        latest_image = max(target_images, key=lambda img: img.get("imagePushedAt", datetime.min))

        tags = latest_image.get("imageTags", [])
        tag = next((t for t in tags if t != "latest"), tags[0] if tags else "<none>")
        size_mb = latest_image.get("imageSizeInBytes", 0) / (1024 ** 2)

        print(f"[INFO] Latest tag: {tag}, Size: {size_mb:.2f} MB")
        return tag, size_mb

    except client.exceptions.RepositoryNotFoundException:
        print(f"[WARN] Repository not found: {repository_name}")
    except Exception as e:
        print(f"[ERROR] Failed to get image info for {repository_name}: {e}")
    return "<none>", 0

def build_markdown(items, updated_at):
    env = Environment(loader=FileSystemLoader(os.path.dirname(README_TEMPLATE_PATH)))
    template = env.get_template(os.path.basename(README_TEMPLATE_PATH))
    return template.render(items=items, updated_at=updated_at, alias=AWS_ECR_PUBLIC_ALIAS)

def main():
    now = datetime.now().astimezone()
    updated_time = f"{now.strftime('%c')} {now.tzname()}"
    print(f"[INFO] Script started at {updated_time}")

    client = get_ecr_client()
    repos = sorted(
        get_repositories(client, prefix=AWS_ECR_PUBLIC_REPOSITORY_GROUP + "/"),
        key=lambda r: r["repositoryName"]
    )

    items = []
    for i, repo in enumerate(repos, 1):
        name = repo["repositoryName"]
        latest_tag, image_size_mb = get_latest_image_info(client, name)
        items.append({
            "number": i,
            "name": name,
            "group": name.split("/")[0] if "/" in name else "-",
            "uri": f"{AWS_ECR_PUBLIC_URI}/{name}",
            "latest_tag": latest_tag,
            "image_size_mb": f"{image_size_mb:.2f}"
        })

    markdown_content = build_markdown(items, updated_time)

    nb = nbf.v4.new_notebook()
    nb.cells.append(nbf.v4.new_markdown_cell(markdown_content))

    with open(README_OUTPUT_PATH, "w", encoding="utf-8") as f:
        nbf.write(nb, f)

    print(f"[INFO] Notebook saved to {README_OUTPUT_PATH}")

if __name__ == "__main__":
    main()
