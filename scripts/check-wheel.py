import json
import os
import re
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

wheels = sorted(Path(sys.argv[1]).glob("*.whl"))
if not wheels:
    raise SystemExit("No wheel found")
with tempfile.TemporaryDirectory(prefix="session-desk-install-") as directory:
    root = Path(directory)
    environment = root / "venv"
    venv.EnvBuilder(with_pip=True).create(environment)
    executable = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    subprocess.run(
        [
            str(executable),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-index",
            "--no-deps",
            str(wheels[-1].resolve()),
        ],
        check=True,
    )
    command_directory = executable.parent
    command = command_directory / (
        "session-desk.exe" if sys.platform == "win32" else "session-desk"
    )
    result = subprocess.run(
        [str(command), "--version"], cwd=root, capture_output=True, text=True, check=True
    )
    if "Session Desk 0.3.0" not in result.stdout:
        raise SystemExit("Installed command did not report the expected application version")
    output = root / "demo.html"
    subprocess.run(
        [str(executable), "-m", "session_desk", "--demo", "--static", "-o", str(output)],
        cwd=root,
        env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
        check=True,
    )
    page = output.read_text(encoding="utf-8")
    match = re.search(r'<script id="app-data" type="application/json">(.*?)</script>', page, re.S)
    if not match or json.loads(match.group(1))["mode"] != "demo":
        raise SystemExit("Installed demo did not produce a valid catalog")
    if 'href="/assets/' in page or 'src="/assets/' in page:
        raise SystemExit("Installed export contains external application assets")
    environment_values = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    environment_values["SESSION_DESK_STATE_DIR"] = str(root / "state")
    launcher = command_directory / (
        "session-desk.exe" if sys.platform == "win32" else "session-desk"
    )
    try:
        subprocess.run(
            [str(launcher), "start", "--demo", "--port", "0"],
            cwd=root,
            env=environment_values,
            check=True,
            timeout=30,
        )
        subprocess.run(
            [str(launcher), "status"], cwd=root, env=environment_values, check=True, timeout=10
        )
    finally:
        subprocess.run(
            [str(launcher), "stop"], cwd=root, env=environment_values, check=True, timeout=30
        )
    print(
        "Installed wheel: commands, packaged UI, standalone demo and detached lifecycle verified."
    )
