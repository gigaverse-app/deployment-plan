"""Publish tested release files without replacing an existing distribution."""

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

tag = os.environ["RELEASE_TAG"]
release = json.loads(subprocess.check_output(["gh", "release", "view", tag, "--json", "assets"], text=True))
existing = {asset["name"] for asset in release["assets"]}
for distribution in sorted([*Path("dist").glob("*.whl"), *Path("dist").glob("*.tar.gz")]):
    if distribution.name in existing:
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(
                ["gh", "release", "download", tag, "--pattern", distribution.name, "--dir", directory], check=True
            )
            saved = Path(directory) / distribution.name
            if hashlib.sha256(saved.read_bytes()).digest() != hashlib.sha256(distribution.read_bytes()).digest():
                raise SystemExit(f"Refusing to replace immutable release asset: {distribution.name}")
    else:
        subprocess.run(["gh", "release", "upload", tag, str(distribution)], check=True)
