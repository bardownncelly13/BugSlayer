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

# Tree-sitter imports for function extraction (optional)
TREE_SITTER_AVAILABLE = False
try:
    from tree_sitter import Parser, Language
    import ctypes
    TREE_SITTER_AVAILABLE = True
except ImportError:
    pass

from llm.gemini_client import gemini_text

# Tree-sitter imports for function extraction (optional)
TREE_SITTER_AVAILABLE = False
try:
    from tree_sitter import Parser, Language
    import ctypes
    TREE_SITTER_AVAILABLE = True
except ImportError:
    pass

# Tree-sitter setup for function extraction
if TREE_SITTER_AVAILABLE:
    LIB_PATH = os.path.join(os.path.dirname(__file__), "..", "codetracing", "parsers", "build", "my-languages.so")

    LANG_MAP = {
        ".py": "python",
        ".js": "javascript",
        ".rs": "rust",
        ".c": "c",
        ".h": "c",
        ".cpp": "cpp",
        ".hpp": "cpp",
    }

    FUNCTION_NODE_TYPES = {
        "python": ("function_definition",),
        "c": ("function_definition",),
        "cpp": ("function_definition",),
        "rust": ("function_item",),
        "javascript": ("function_declaration", "method_definition", "function", "arrow_function"),
    }

    _LIBS = {}
    def load_language(lib_path: str, name: str) -> Language:
        lib = _LIBS.get(lib_path)
        if lib is None:
            lib = ctypes.CDLL(lib_path)
            _LIBS[lib_path] = lib

        fn = getattr(lib, f"tree_sitter_{name}")
        fn.restype = ctypes.c_void_p
        return Language(fn())

    LANGS = {name: load_language(LIB_PATH, name) for name in set(LANG_MAP.values())}
    PARSERS = {}
    for name, lang in LANGS.items():
        p = Parser()
        p.language = lang
        PARSERS[name] = p

    def node_text(node, source: bytes) -> str:
        return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")

    def extract_functions_from_file(filepath: str) -> List[Dict]:
        """Extract all functions from a file using tree-sitter."""
        if not TREE_SITTER_AVAILABLE:
            return []

        try:
            with open(filepath, "rb") as f:
                source = f.read()
        except Exception:
            return []

        ext = os.path.splitext(filepath)[1].lower()
        lang_name = LANG_MAP.get(ext)
        if not lang_name:
            return []

        parser = PARSERS.get(lang_name)
        if not parser:
            return []

        try:
            tree = parser.parse(source)
            root = tree.root_node
            stack = [(root, None)]
            functions = []
            fn_types = FUNCTION_NODE_TYPES.get(lang_name, ("function_definition",))

            while stack:
                node, parent_class = stack.pop()

                # class context (python/cpp)
                current_class = parent_class
                if node.type in ("class_definition", "class_specifier"):
                    name_node = node.child_by_field_name("name")
                    if name_node:
                        current_class = node_text(name_node, source)

                if node.type in fn_types:
                    name_node = node.child_by_field_name("name")

                    # C/C++: name often nested under declarator
                    if name_node is None and lang_name in ("c", "cpp"):
                        decl = node.child_by_field_name("declarator")
                        name_node = _find_first_identifier(decl) if decl else None

                    if name_node:
                        func_name = node_text(name_node, source)
                        start_line = node.start_point[0] + 1

                        param_node = (
                            node.child_by_field_name("parameters")
                            or node.child_by_field_name("parameter_list")
                        )
                        parameters = node_text(param_node, source) if param_node else ""

                        functions.append(
                            {
                                "name": func_name,
                                "line": start_line,
                                "parameters": parameters,
                                "class": current_class,
                            }
                        )

                for child in reversed(node.children):
                    stack.append((child, current_class))

            return functions
        except Exception:
            return []

# Tree-sitter imports for function extraction
try:
    from tree_sitter import Parser, Language
    import ctypes
    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False

# Tree-sitter setup for function extraction (run after imports)
if TREE_SITTER_AVAILABLE and not PARSERS:
    try:
        LIB_PATH = os.path.join(os.path.dirname(__file__), "..", "codetracing", "parsers", "build", "my-languages.so")
        LANGS = {name: load_language(LIB_PATH, name) for name in set(LANG_MAP.values())}
        PARSERS = {}
        for name, lang in LANGS.items():
            p = Parser()
            p.language = lang
            PARSERS[name] = p
    except Exception:
        TREE_SITTER_AVAILABLE = False


# ------------------------------------------------------------
# ------------------------------------------------------------


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


def _extract_json_object(text: str) -> str:
    """Extract JSON object from text."""
    text = text.strip()

    if text.startswith("{") and text.endswith("}"):
        return text

    m = re.search(r"\{", text)

    if not m:
        raise ValueError("No JSON object found")

    start = m.start()
    end = text.rfind("}")

    if end == -1:
        raise ValueError("Invalid JSON object")

    return text[start:end + 1]


# ------------------------------------------------------------
# Grep Helpers
# ------------------------------------------------------------

def grep_function(filepath: str, function_name: str):
    if not function_name or function_name == "GLOBAL_SCOPE":
        return None

    name = function_name.split("(")[0].strip()
    if not name:
        return None

    # Match common styles across languages, including C/C++
    pattern = rf"(^\s*(def|function|func)\s+{re.escape(name)}\b)|(^\s*.*\b{re.escape(name)}\s*\()"

    try:
        proc = subprocess.run(
            ["grep", "-nEm1", pattern, filepath],
            capture_output=True,
            text=True,
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

def _find_first_identifier(node):
    if node is None:
        return None
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type == "identifier":
            return n
        stack.extend(reversed(n.children))
    return None
def is_entry_point(filepath: str, function_name: str, function_line: int, code_context: str = "", model: str = "gemini-2.0-flash") -> bool:
    """
    Use Gemini model to determine if a function is an entry point.
    Works for all languages.
    """
    if not function_name or not function_line:
        return False

    try:
        if not code_context:
            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    code_context = f.read()
            except Exception:
                return False

        prompt = f"""Analyze this code and determine if the function '{function_name}' is an entry point.

Entry points are functions that serve as program execution start points, such as:
- main() functions
- Functions called from main blocks (if __name__ == "__main__" in Python)
- Top-level async/module-level calls
- CLI command handlers
- Test runners or bootstrap functions
- Any fucntions that will take input from a user or external system


Return ONLY valid JSON with a single boolean value:

{{
  "is_entry_point": true or false,
  "reason": "brief explanation"
}}

Filename: {os.path.basename(filepath)}

Code:
{code_context}

Target function: {function_name} (at line {function_line})
"""

        try:
            text = gemini_text("", prompt, model=model)
            print(f"DEBUG: Gemini response for {function_name}: {text[:200]}...")
        except Exception as e:
            print(f"DEBUG: Gemini API error for {function_name}: {e}")
            return False

        try:
            payload = json.loads(text)
        except Exception:
            try:
                payload = json.loads(_extract_json_object(text))
            except Exception as e:
                print(f"DEBUG: JSON parse error for {function_name}: {e}, text: {text[:200]}")
                return False

        result = payload.get("is_entry_point", False)
        print(f"DEBUG: is_entry_point for {function_name}: {result}")
        return result

    except Exception:
        return False


def scan_file_for_entry_points(filepath: str, model: str = "gemini-2.0-flash") -> List[Dict]:
    """Scan a file for all functions and identify which are entry points."""
    if not TREE_SITTER_AVAILABLE:
        return []

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            code = f.read()
    except Exception:
        return []

    functions = extract_functions_from_file(filepath)
    entry_points = []

    for func in functions:
        func_name = func["name"]
        func_line = func["line"]
        func_class = func.get("class")

        # Check if this function is an entry point
        is_ep = is_entry_point(filepath, func_name, func_line, code, model)

        if is_ep:
            entry_points.append({
                "path": filepath,
                "function": func_name,
                "function_line": func_line,
                "function_class": func_class,
                "is_entry_point": True,
            })

    return entry_points


# ------------------------------------------------------------
# Gemini Scan (Per File)
# ------------------------------------------------------------

def scan_file_with_gemini(filepath: str, model: str = "gemini-2.0-flash") -> List[Dict]:

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

        text = gemini_text("", prompt, model=model)

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

        entry_point = is_entry_point(filepath, function, func_line, code, model)

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
                "is_entry_point": entry_point,
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
    output_path: Optional[str] = None,
) -> Dict[str, List[Dict]]:

    def _is_scannable_file(name: str) -> bool:
        if not name:
            return False
        if name.endswith(".jsonl"):
            return False
        return name.endswith(
            (
                ".py",
                ".js",
                ".ts",
                ".java",
                ".go",
                ".rs",
                ".cpp",
                ".c",
                ".cs",
                ".php",
                ".rb",
                ".swift",
                ".kt",
                ".scala",
                ".lua",
                ".hs",
                ".sh",
                ".dart",
                ".m",
                ".mm",
                ".zig",
                ".nim",
            )
        )

    def _normalize_target(path: str) -> tuple[str, str]:
        abs_target = path if os.path.isabs(path) else os.path.abspath(os.path.join(repo_path, path))
        rel_target = os.path.relpath(abs_target, repo_path)
        return abs_target, rel_target

    targets: List[str] = []

    if files:

        targets = [
            os.path.join(repo_path, f) if not os.path.isabs(f) else f
            for f in files
            if _is_scannable_file(f)
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
                if _is_scannable_file(f)
            ]

        except Exception:
            targets = []

    elif base_ref:

        try:

            changed = get_changed_files(base_ref)

            targets = [
                os.path.join(repo_path, f) if not os.path.isabs(f) else f
                for f in changed
                if _is_scannable_file(f)
            ]

        except Exception:
            targets = []

    if not targets:

        for root, _, filenames in os.walk(repo_path):

            for fn in filenames:
                if not _is_scannable_file(fn):
                    continue
                targets.append(os.path.join(root, fn))

    grouped: Dict[str, List[Dict]] = defaultdict(list)

    for t in targets:
        abs_t, rel_t = _normalize_target(t)

        if not os.path.exists(abs_t):
            continue

        try:
            file_findings = scan_file_with_gemini(abs_t)
        except Exception:
            continue

        if file_findings:
            grouped[rel_t].extend(file_findings)

        # Always try to scan for entry points if tree-sitter is available
        if TREE_SITTER_AVAILABLE:
            try:
                entry_points = scan_file_for_entry_points(abs_t)
                if entry_points:
                    if rel_t not in grouped:
                        grouped[rel_t] = []
                    grouped[rel_t].extend(entry_points)
            except Exception:
                continue

    findings = dict(grouped)

    if output_path is None:
        output_path = os.path.join(repo_path, "gemini_results.json")

    try:
        with open(output_path, "w", encoding="utf-8") as fh:
            fh.write(gemini_findings_to_json(findings))
    except Exception as e:
        print(f"DEBUG: Failed to write Gemini results to {output_path}: {e}")

    return findings


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

        vuln_count = 0
        ep_count = 0

        for f in file_findings:
            if f.get('is_entry_point') and not f.get('issue'):
                # This is an entry point
                ep_count += 1
                print(f"  Entry Point {ep_count}")
                print(f"    Function: {f.get('function')}")
                print(f"    Function Line: {f.get('function_line')}")
                print(f"    Function Class: {f.get('function_class')}")
                print(f"    Is Entry Point: {f.get('is_entry_point', False)}")
            else:
                # This is a vulnerability
                vuln_count += 1
                print(f"  Vulnerability {vuln_count}")
                print(f"    Function: {f.get('function')}")
                print(f"    Function Line: {f.get('function_line')}")
                print(f"    Function Class: {f.get('function_class')}")
                print(f"    Is Entry Point: {f.get('is_entry_point', False)}")
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
            "entry_points": [],
        }

        vuln_count = 0
        ep_count = 0

        for f in file_findings:
            if f.get('is_entry_point') and not f.get('issue'):
                # This is an entry point
                ep_count += 1
                ep_entry = {
                    "entry_point_number": ep_count,
                    "function": f.get("function"),
                    "function_line": f.get("function_line"),
                    "function_class": f.get("function_class"),
                    "is_entry_point": f.get("is_entry_point", False),
                }
                file_entry["entry_points"].append(ep_entry)
            else:
                # This is a vulnerability
                vuln_count += 1
                vuln_entry = {
                    "vulnerability_number": vuln_count,
                    "function": f.get("function"),
                    "function_line": f.get("function_line"),
                    "function_class": f.get("function_class"),
                    "is_entry_point": f.get("is_entry_point", False),
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