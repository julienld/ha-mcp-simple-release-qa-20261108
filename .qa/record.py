# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Publish non-secret QA job receipts beside their isolated release assets."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import runtime


def main() -> None:
    runtime.context()
    runtime.receipt()
    receipt = json.loads(Path("qa-workflow-receipt.json").read_text(encoding="utf-8"))
    needs = receipt["needs"]
    tag = ""
    if os.environ["GITHUB_REPOSITORY"] == runtime.MIRROR:
        if needs.get("release", {}).get("result") == "success":
            tag = os.environ["GITHUB_REF_NAME"]
    elif needs.get("sync", {}).get("outputs", {}).get("qa_pin"):
        tag = "v" + needs["sync"]["outputs"]["qa_pin"]
    elif needs.get("semantic-release", {}).get("outputs", {}).get("released") == "true":
        tag = "v" + needs["semantic-release"]["outputs"]["version"]
    elif needs.get("prepare", {}).get("outputs", {}).get("release_tag"):
        tag = needs["prepare"]["outputs"]["release_tag"]
    elif needs.get("create-prerelease", {}).get("result") == "success":
        tag = "v" + needs["prepare"]["outputs"]["dev_version"]
    if not tag:
        print("No release produced by this stage; artifact receipt only")
        return
    target = Path(
        f"qa-receipt-{os.environ['GITHUB_RUN_ID']}-{os.environ['GITHUB_RUN_ATTEMPT']}.json"
    )
    shutil.copyfile("qa-workflow-receipt.json", target)
    subprocess.run(
        [
            "gh",
            "release",
            "upload",
            tag,
            str(target),
            "--repo",
            os.environ["GITHUB_REPOSITORY"],
        ],
        check=True,
    )
    print(f"Retained {target} on {tag}")


if __name__ == "__main__":
    main()
