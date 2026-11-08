# /// script
# requires-python = ">=3.13"
# dependencies = ["PyYAML==6.0.3"]
# ///
"""Replay the product publication step against disposable releases in the QA source."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import yaml

SOURCE = "julienld/ha-mcp-simple-release-qa-20261108"
FORK = "julienld/ha-mcp-dev"


def command(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(args, check=False, capture_output=True, text=True)
    if check and result.returncode:
        token = os.environ.get("GH_TOKEN", "")
        error = result.stderr.replace(token, "[redacted]") if token else result.stderr
        raise RuntimeError(f"{args[:2]} failed ({result.returncode}): {error}")
    return result


def api(path: str) -> object:
    return json.loads(command("gh", "api", path).stdout)


def release(tag: str) -> dict:
    return json.loads(
        command(
            "gh",
            "release",
            "view",
            tag,
            "--repo",
            SOURCE,
            "--json",
            "databaseId,isDraft,assets",
        ).stdout
    )


def render(product: str) -> None:
    import prepare

    root = Path(__file__).resolve().parents[4] / SOURCE.split("/")[1]
    assert root.is_dir()
    target = root / ".qa/guard_proof.py"
    target.write_bytes(Path(__file__).read_bytes())
    shutil.copyfile(
        Path(__file__).with_suffix(".py.lock"), target.with_suffix(".py.lock")
    )
    prepare.helpers.save(
        root / ".github/workflows/qa-publish-guard.yml",
        {
            "name": "QA publication guard proof",
            "on": {
                "push": {
                    "branches": ["master"],
                    "paths": [".github/workflows/qa-publish-guard.yml"],
                },
                "workflow_dispatch": {},
            },
            "permissions": {"contents": "write"},
            "jobs": {
                "proof": {
                    "if": "${{ github.repository == '"
                    + SOURCE
                    + "' && github.event_name == 'workflow_dispatch' && vars.QA_ARMED == 'false' }}",
                    "runs-on": "ubuntu-latest",
                    "timeout-minutes": 10,
                    "steps": [
                        {
                            "uses": prepare.helpers.CHECKOUT,
                            "with": {"persist-credentials": False, "fetch-depth": 0},
                        },
                        {"uses": prepare.helpers.UV, "with": {"version": "0.13.4"}},
                        {
                            "run": "uv run -s .qa/guard_proof.py run --product-sha "
                            + product,
                            "env": {
                                "GH_TOKEN": "${{ github.token }}",
                                "QA_ARMED": "${{ vars.QA_ARMED }}",
                            },
                        },
                        {
                            "uses": prepare.helpers.UPLOAD,
                            "if": "${{ always() }}",
                            "with": {
                                "name": "publication-guard-proof",
                                "path": "guard-proof.json",
                                "retention-days": 30,
                            },
                        },
                    ],
                }
            },
        },
    )
    print(root)


def run(product: str) -> None:
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("GITHUB_REPOSITORY") != SOURCE
        or os.environ.get("QA_ARMED") != "false"
    ):
        raise ValueError("Only the disarmed QA source may execute this proof")
    workflow = api(
        f"repos/{FORK}/contents/.github/workflows/release-publish.yml?ref={product}"
    )
    text = base64.b64decode(workflow["content"]).decode()
    steps = yaml.safe_load(text)["jobs"]["publish_pypi"]["steps"]
    body = next(
        step["run"] for step in steps if step.get("name") == "Publish GitHub release"
    )
    assert json.loads(Path("hacs.json").read_text())["zip_release"] is True
    original = api(f"repos/{SOURCE}/git/ref/tags/stable")["object"]["sha"]
    command("git", "fetch", "--no-tags", "origin", original)
    head = command("git", "rev-parse", "HEAD").stdout.strip()
    tag = "qa-publish-guard-" + os.environ["GITHUB_RUN_ID"]
    remote = f"https://x-access-token:{os.environ['GH_TOKEN']}@github.com/{SOURCE}.git"
    result = {
        "product_sha": product,
        "run": f"https://github.com/{SOURCE}/actions/runs/{os.environ['GITHUB_RUN_ID']}",
        "step_sha256": hashlib.sha256(body.encode()).hexdigest(),
        "original_stable": original,
        "fixture_tag": tag,
        "passed": False,
    }
    created = False
    try:
        command("git", "tag", tag, head)
        command("git", "push", remote, f"refs/tags/{tag}")
        command(
            "gh",
            "release",
            "create",
            tag,
            "--repo",
            SOURCE,
            "--verify-tag",
            "--draft",
            "--prerelease",
            "--title",
            "QA publication guard fixture",
            "--notes",
            "Disposable fixture; not an installation source.",
        )
        created = True
        before = release(tag)
        env = {**os.environ, "TAG": tag}
        missing = subprocess.run(
            ["bash", "-e", "-c", body],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert missing.returncode != 0
        assert release(tag)["isDraft"] is True
        assert api(f"repos/{SOURCE}/git/ref/tags/stable")["object"]["sha"] == original
        result["missing_asset"] = {
            "returncode": missing.returncode,
            "draft": True,
            "stable_unchanged": True,
        }
        archive = Path("proof-download")
        archive.mkdir()
        command(
            "gh",
            "release",
            "download",
            "v9.2.0",
            "--repo",
            SOURCE,
            "--pattern",
            "ha_mcp_tools.zip",
            "--dir",
            str(archive),
        )
        command(
            "gh",
            "release",
            "upload",
            tag,
            str(archive / "ha_mcp_tools.zip"),
            "--repo",
            SOURCE,
        )
        uploaded = release(tag)
        asset_id = next(
            asset["id"]
            for asset in uploaded["assets"]
            if asset["name"] == "ha_mcp_tools.zip"
        )
        for _ in range(2):
            published = subprocess.run(
                ["bash", "-e", "-c", body],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            token = os.environ["GH_TOKEN"]
            assert published.returncode == 0, published.stderr.replace(
                token, "[redacted]"
            )
            current = release(tag)
            assert (
                current["databaseId"] == before["databaseId"]
                and current["isDraft"] is False
            )
            assert (
                next(
                    asset["id"]
                    for asset in current["assets"]
                    if asset["name"] == "ha_mcp_tools.zip"
                )
                == asset_id
            )
            assert api(f"repos/{SOURCE}/git/ref/tags/stable")["object"]["sha"] == head
        result["recovery_and_retry"] = {
            "same_release_id": before["databaseId"],
            "same_asset_id": asset_id,
            "public": True,
            "stable_commit": head,
            "repeated_successfully": True,
        }
        result["passed"] = True
    finally:
        command("git", "push", "--force", remote, f"{original}:refs/tags/stable")
        result["stable_restored"] = (
            api(f"repos/{SOURCE}/git/ref/tags/stable")["object"]["sha"] == original
        )
        if created:
            command(
                "gh",
                "release",
                "delete",
                tag,
                "--repo",
                SOURCE,
                "--cleanup-tag",
                "--yes",
            )
        Path("guard-proof.json").write_text(json.dumps(result, indent=2) + "\n")
    assert result["stable_restored"]
    receipt_asset = Path("qa-publish-guard-" + os.environ["GITHUB_RUN_ID"] + ".json")
    shutil.copyfile("guard-proof.json", receipt_asset)
    command(
        "gh",
        "release",
        "upload",
        "v9.2.0",
        str(receipt_asset),
        "--repo",
        SOURCE,
    )
    print(
        json.dumps(
            {"passed": result["passed"], "product_sha": product, "run": result["run"]}
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("render", "run"))
    parser.add_argument("--product-sha", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.product_sha):
        raise ValueError("An immutable product revision is required")
    (render if args.mode == "render" else run)(args.product_sha)


if __name__ == "__main__":
    main()
