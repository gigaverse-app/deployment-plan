"""Install the built wheel outside the checkout and exercise its public CLI."""

import os
import subprocess
import tempfile
from pathlib import Path

wheel = next(Path("dist").glob("*.whl")).resolve()
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    subprocess.run(["uv", "venv", str(root / "venv")], check=True)
    python = root / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run(["uv", "pip", "install", "--python", str(python), str(wheel)], check=True)
    (root / "actions.yaml").write_text("version: 1\nactions: []\n")
    subprocess.run(
        [str(python), "-m", "deployment_plan", "validate", "--manifest", "actions.yaml"], cwd=root, check=True
    )
    subprocess.run(
        [str(python), "-m", "deployment_plan", "plan", "--manifest", "actions.yaml", "--environment", "production"],
        cwd=root,
        check=True,
    )
