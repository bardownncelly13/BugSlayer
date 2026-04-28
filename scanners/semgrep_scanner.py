import os
from typing import List, Dict, Optional
import subprocess
import json

def _validate_config(config: str) -> None:
    """Reject remote URLs and non-existent paths to prevent arbitrary rule loading."""
    if config.startswith(("http://", "https://", "p/", "r/")):
        raise ValueError(
            f"Remote or registry semgrep config not permitted: {config!r}. "
            "Use a local file path."
        )
    if not os.path.isfile(config):
        raise FileNotFoundError(f"Semgrep config file not found: {config!r}")

def scan_with_semgrep(repo_path: Optional[str] = None, base_ref: str = "origin/main", config: str = r".\rules\owasp_minimal.yml") -> List[Dict]:
    _validate_config(config)
    cmd = ["semgrep", "ci", "--config", config, "--json"]

    env = os.environ.copy()
    env["SEMGREP_BASELINE_REF"] = base_ref

    result = subprocess.run(
        cmd,
        cwd=repo_path,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    # Debug stuff
    # print("Return code:", result.returncode)
    # print("stdout:", result.stdout)
    # print("stderr:", result.stderr)

    if not result.stdout.strip():
        print("No findings found.")
        return []

    # json.loads will fail if there is nothing in the output
    # this is hopefully caught by strip above, this is here in case anything else fails
    try:
        output = json.loads(result.stdout)
    except json.JSONDecodeError:
        print("Failed to parse JSON from Semgrep:")
        print("stdout:", result.stdout)
        print("stderr:", result.stderr)
        return []

    return output.get("results", [])
