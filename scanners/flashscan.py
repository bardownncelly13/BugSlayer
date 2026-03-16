import os
import json
import re
from typing import List, Dict, Optional, Tuple
from collections import defaultdict

try:
    from google import genai
except Exception:  # pragma: no cover - optional dependency
    genai = None

from git_utils.git_ops import git_cmd, get_changed_files


def _make_gemini_client() -> "genai.Client":
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not configured")
    if genai is None:
        raise RuntimeError("google.genai package not available")
    return genai.Client(api_key=api_key)


def _extract_json(text: str) -> str:
    """Try to extract a JSON array/object from model text output."""
    # Fast path
    text = text.strip()
    if (text.startswith("[") and text.endswith("]")) or (text.startswith("{") and text.endswith("}")):
        return text

    # Find first { or [ and last matching } or ]
    m = re.search(r"(\[|\{)", text)
    if not m:
        raise ValueError("No JSON found in model output")
    start = m.start()
    # find last brace/bracket
    last_brace = max(text.rfind("}"), text.rfind("]"))
    if last_brace == -1:
        raise ValueError("No JSON end found in model output")
    return text[start : last_brace + 1]


def _parse_response_to_findings(response_text: str, filename: str, line_offset: int = 0) -> List[Dict]:
    """Parse Gemini response (expects JSON array) into normalized findings."""
    try:
        payload = json.loads(response_text)
    except Exception:
        # try to extract JSON substring then load
        payload = json.loads(_extract_json(response_text))

    findings = []
    if isinstance(payload, dict):
        # allow single-object responses
        payload = [payload]

    for item in payload:
        try:
            start = int(item.get("start", item.get("start_line", item.get("line", 0))))
        except Exception:
            start = 0
        try:
            end = int(item.get("end", item.get("end_line", start)))
        except Exception:
            end = start

        findings.append(
            {
                "path": filename,
                "start": {"line": start + line_offset},
                "end": {"line": end + line_offset},
                "issue": item.get("issue") or item.get("type") or item.get("rule") or "possible-vuln",
                "message": item.get("message") or item.get("explanation") or "",
                "severity": item.get("severity") or item.get("risk") or "medium",
                "confidence": float(item.get("confidence", 0.0)) if item.get("confidence") is not None else None,
            }
        )

    return findings


def scan_file_with_gemini(
    filepath: str,
    model: str = "gemini-2.0-flash",
    max_lines_per_chunk: int = 1000,
) -> List[Dict]:
    """Scan a single file with Gemini. Returns a list of findings.

    - Chunks file by lines to keep each request bounded.
    - Each chunk asks the model to return JSON with findings (line numbers are relative
      to the chunk start and adjusted when aggregated).
    """
    client = _make_gemini_client()

    with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()

    findings: List[Dict] = []
    total_lines = len(lines)

    for start_idx in range(0, total_lines, max_lines_per_chunk):
        chunk_lines = lines[start_idx : start_idx + max_lines_per_chunk]
        chunk_text = "\n".join(chunk_lines)

        prompt = (
            "You are a security-focused code reviewer. Carefully analyze the provided code snippet and identify potential security vulnerabilities, insecure patterns, or risky usages.\n"
            "Respond ONLY with valid JSON (no prose, no markdown): an array of objects matching this schema:\n"
            "  - start: integer (1-indexed line number within the snippet)\n"
            "  - end: integer (1-indexed line number within the snippet; may equal start)\n"
            "  - issue: short machine-readable identifier (e.g. \"eval\", \"pickle-load\")\n"
            "  - message: short human-readable explanation\n"
            "  - severity: optional, one of \"low\", \"medium\", \"high\"\n"
            "  - confidence: optional float between 0.0 and 1.0\n"
            "If there are no findings, return an empty array: []\n"
            "Do NOT include any text outside the JSON array and do NOT wrap the JSON in code fences.\n\n"
            f"Filename: {os.path.basename(filepath)}\n"
            "---\n"
            "Source:\n``"
            + chunk_text
            + "\n```"
        )

        resp = client.models.generate_content(model=model, contents=prompt)
        text = getattr(resp, "text", str(resp))

        try:
            parsed = _parse_response_to_findings(text, filepath, line_offset=start_idx)
        except Exception:
            # If parsing fails, skip this chunk but continue scanning others
            parsed = []

        findings.extend(parsed)

    return findings


def gemini_scan(
    repo_path: str = ".",
    files: Optional[List[str]] = None,
    base_ref: Optional[str] = None,
    head_ref: Optional[str] = None,
) -> Dict[str, List[Dict]]:
    """High-level Gemini scan helper.

    - If `files` provided, scan those files (paths relative to repo_path).
    - If `base_ref` and `head_ref` supplied, scan files changed between those refs.
    - If `base_ref` supplied (but no head_ref), fall back to `git diff --name-only base_ref`.
    - Otherwise scan all .py files under repo_path.

    Returns findings grouped by filename.
    """
    # Resolve files list
    targets: List[str] = []
    if files:
        targets = [os.path.join(repo_path, f) if not os.path.isabs(f) else f for f in files]

    elif base_ref and head_ref:
        # Mirror semgrep behavior: use git diff between base_ref..head_ref to get changed files
        try:
            proc = git_cmd(["diff", "--name-only", f"{base_ref}..{head_ref}"], repo_path)
            changed = [l.strip() for l in (proc.stdout or "").splitlines() if l.strip()]
            targets = [os.path.join(repo_path, f) if not os.path.isabs(f) else f for f in changed]
        except Exception:
            targets = []

    elif base_ref:
        # Backward-compatible fallback
        try:
            changed = get_changed_files(base_ref)
            targets = [os.path.join(repo_path, f) if not os.path.isabs(f) else f for f in changed]
        except Exception:
            targets = []

    if not targets:
        # Walk repo for .py files
        for root, _, filenames in os.walk(repo_path):
            for fn in filenames:
                if fn.endswith(".py"):
                    targets.append(os.path.join(root, fn))

    grouped: Dict[str, List[Dict]] = defaultdict(list)

    for t in targets:
        if not os.path.exists(t):
            continue
        try:
            file_findings = scan_file_with_gemini(t)
        except Exception:
            # If external API fails for a file, skip it and continue
            continue
        if file_findings:
            grouped[t].extend(file_findings)

    return dict(grouped)


def print_gemini_findings(findings: Dict[str, List[Dict]]) -> None:
    if not findings:
        print("Gemini: No findings")
        return

    print("\n=== Gemini Security Scan Results ===\n")
    for file_idx, (file, file_findings) in enumerate(findings.items(), 1):
        print(f"File {file_idx} - {file}:")
        for vuln_idx, f in enumerate(file_findings, 1):
            start = f.get("start", {}).get("line")
            end = f.get("end", {}).get("line")
            issue = f.get("issue")
            msg = f.get("message")
            sev = f.get("severity")
            conf = f.get("confidence")
            print(f"  Vulnerability {vuln_idx}")
            print(f"    Issue: {issue}")
            print(f"    Lines: {start}-{end}")
            print(f"    Message: {msg}")
            print(f"    Severity: {sev}")
            if conf is not None:
                print(f"    Confidence: {conf:.2f}")
        print()


def gemini_findings_to_json(findings: Dict[str, List[Dict]]) -> str:
    """Convert findings to JSON format with numbered vulnerabilities."""
    output = []
    for file_idx, (file, file_findings) in enumerate(findings.items(), 1):
        file_entry = {
            "file_number": file_idx,
            "path": file,
            "vulnerabilities": []
        }
        for vuln_idx, f in enumerate(file_findings, 1):
            vuln_entry = {
                "vulnerability_number": vuln_idx,
                "start_line": f.get("start", {}).get("line"),
                "end_line": f.get("end", {}).get("line"),
                "issue": f.get("issue"),
                "message": f.get("message"),
                "severity": f.get("severity"),
                "confidence": f.get("confidence")
            }
            file_entry["vulnerabilities"].append(vuln_entry)
        output.append(file_entry)
    return json.dumps(output, indent=2)
