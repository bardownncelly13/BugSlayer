import os
import json
import re
from typing import List, Dict, Optional
import subprocess
from collections import defaultdict

try:
    from google import genai
except Exception:
    genai = None

from git_utils.git_ops import git_cmd, get_changed_files


# ------------------------------------------------------------
# Gemini Client
# ------------------------------------------------------------

def _make_gemini_client() -> "genai.Client":
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not configured")

    if genai is None:
        raise RuntimeError("google.genai package not installed")

    return genai.Client(api_key=api_key)


# ------------------------------------------------------------
# JSON Extraction
# ------------------------------------------------------------

def _extract_json(text: str) -> str:

    text = text.strip()

    if text.startswith("[") and text.endswith("]"):
        return text

    m = re.search(r"\[", text)

    if not m:
        raise ValueError("No JSON found")

    start = m.start()
    end = text.rfind("]")

    if end == -1:
        raise ValueError("Invalid JSON")

    return text[start:end + 1]


# ------------------------------------------------------------
# Grep Helpers
# ------------------------------------------------------------

def grep_function(filepath: str, function_name: str):

    if not function_name or function_name == "GLOBAL_SCOPE":
        return None

    name = function_name.split("(")[0]

    pattern = rf"(def|function|func)\s+{name}\b|{name}\s*\("

    try:
        proc = subprocess.run(
            ["grep", "-nEm1", pattern, filepath],
            capture_output=True,
            text=True
        )

        if not proc.stdout:
            return None

        return int(proc.stdout.split(":", 1)[0])

    except Exception:
        return None


def grep_snippet(filepath: str, snippet: str):

    if not snippet:
        return None

    snippet = snippet.strip()

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()

        idx = text.find(snippet)

        if idx == -1:
            return None

        return text[:idx].count("\n") + 1

    except Exception:
        return None

def grep_function_class(filepath: str, function_line: int):

    if not function_line:
        return None

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        for i in range(function_line - 1, -1, -1):

            line = lines[i].strip()

            m = re.match(r"class\s+([A-Za-z0-9_]+)", line)

            if m:
                return m.group(1)

            if line.startswith("def "):
                break

    except Exception:
        return None

    return None

# ------------------------------------------------------------
# Gemini Scan (Per File)
# ------------------------------------------------------------

def scan_file_with_gemini(filepath: str, model: str = "gemini-2.0-flash") -> List[Dict]:

    client = _make_gemini_client()

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            code = f.read()
    except Exception:
        return []

    prompt = f"""
You are a security code auditor.

Analyze the file and find security vulnerabilities.

Return ONLY valid JSON.

Schema:

[
  {{
    "function": "function name exactly as given do not give info about the class it is in this needs to be exact so it can be found with grep example: my_function(arg1, arg2)",
    "function_class": "class name if the function is inside a class otherwise None",
    "snippet": "exact vulnerable code snippet",
    "issue": "short identifier",
    "message": "short explanation",
    "severity": "low|medium|high",
    "confidence": 0.0-1.0
  }}
]

Rules:

- Return the function name containing the vulnerability
- If not inside a function return "GLOBAL_SCOPE"
- snippet must be exact code from the file
- do NOT include line numbers
- do NOT include markdown

Filename:
{os.path.basename(filepath)}

Code:
{code}
"""

    try:

        resp = client.models.generate_content(
            model=model,
            contents=prompt,
        )

        text = getattr(resp, "text", str(resp))

    except Exception:
        return []

    try:
        payload = json.loads(text)
    except Exception:
        try:
            payload = json.loads(_extract_json(text))
        except Exception:
            return []

    if isinstance(payload, dict):
        payload = [payload]

    findings = []

    for item in payload:

        function = item.get("function")
        snippet = item.get("snippet")

        func_line = grep_function(filepath, function)
        snippet_line = grep_snippet(filepath, snippet)
        func_class = item.get("function_class")

        if func_class in ("None", "", "null"):
            func_class = None

        if not func_class:
            func_class = grep_function_class(filepath, func_line)

        findings.append(
            {
                "path": filepath,
                "function": function,
                "function_line": func_line,
                "function_class": func_class,
                "snippet": snippet,
                "snippet_line": snippet_line,
                "issue": item.get("issue"),
                "message": item.get("message"),
                "severity": item.get("severity", "medium"),
                "confidence": item.get("confidence"),
            }
        )

    return findings


# ------------------------------------------------------------
# Repo Scan
# ------------------------------------------------------------

def gemini_scan(
    repo_path: str = ".",
    files: Optional[List[str]] = None,
    base_ref: Optional[str] = None,
    head_ref: Optional[str] = None,
) -> Dict[str, List[Dict]]:

    targets: List[str] = []

    if files:

        targets = [
            os.path.join(repo_path, f) if not os.path.isabs(f) else f
            for f in files
        ]

    elif base_ref and head_ref:

        try:

            proc = git_cmd(
                ["diff", "--name-only", f"{base_ref}..{head_ref}"],
                repo_path,
            )

            changed = [
                l.strip()
                for l in (proc.stdout or "").splitlines()
                if l.strip()
            ]

            targets = [
                os.path.join(repo_path, f) if not os.path.isabs(f) else f
                for f in changed
            ]

        except Exception:
            targets = []

    elif base_ref:

        try:

            changed = get_changed_files(base_ref)

            targets = [
                os.path.join(repo_path, f) if not os.path.isabs(f) else f
                for f in changed
            ]

        except Exception:
            targets = []

    if not targets:

        for root, _, filenames in os.walk(repo_path):

            for fn in filenames:

                if fn.endswith(
                    (
                        ".py",".js",".ts",".java",".go",".rs",".cpp",".c",
                        ".cs",".php",".rb",".swift",".kt",".scala",".lua",
                        ".hs",".sh",".dart",".m",".mm",".zig",".nim"
                    )
                ):
                    targets.append(os.path.join(root, fn))

    grouped: Dict[str, List[Dict]] = defaultdict(list)

    for t in targets:

        if not os.path.exists(t):
            continue

        try:
            file_findings = scan_file_with_gemini(t)
        except Exception:
            continue

        if file_findings:
            grouped[t].extend(file_findings)

    return dict(grouped)


# ------------------------------------------------------------
# Pretty Print
# ------------------------------------------------------------

def print_gemini_findings(findings: Dict[str, List[Dict]]):

    if not findings:
        print("Gemini: No findings")
        return

    print("\n=== Gemini Security Scan Results ===\n")

    for file_idx, (file, file_findings) in enumerate(findings.items(), 1):

        print(f"File {file_idx} - {file}")

        for vuln_idx, f in enumerate(file_findings, 1):

            print(f"  Vulnerability {vuln_idx}")
            print(f"    Function: {f.get('function')}")
            print(f"    Function Line: {f.get('function_line')}")
            print(f"    Function Class: {f.get('function_class')}")
            print(f"    Snippet: {f.get('snippet')}")
            print(f"    Snippet Line: {f.get('snippet_line')}")
            print(f"    Issue: {f.get('issue')}")
            print(f"    Message: {f.get('message')}")
            print(f"    Severity: {f.get('severity')}")

            conf = f.get("confidence")

            if conf is not None:
                print(f"    Confidence: {conf}")

        print()


# ------------------------------------------------------------
# JSON Export
# ------------------------------------------------------------

def gemini_findings_to_json(findings: Dict[str, List[Dict]]) -> str:

    output = []

    for file_idx, (file, file_findings) in enumerate(findings.items(), 1):

        file_entry = {
            "file_number": file_idx,
            "path": file,
            "vulnerabilities": [],
        }

        for vuln_idx, f in enumerate(file_findings, 1):

            vuln_entry = {
                "vulnerability_number": vuln_idx,
                "function": f.get("function"),
                "function_line": f.get("function_line"),
                "function_class": f.get("function_class"),
                "snippet": f.get("snippet"),
                "snippet_line": f.get("snippet_line"),
                "issue": f.get("issue"),
                "message": f.get("message"),
                "severity": f.get("severity"),
                "confidence": f.get("confidence"),
            }

            file_entry["vulnerabilities"].append(vuln_entry)

        output.append(file_entry)

    return json.dumps(output, indent=2)