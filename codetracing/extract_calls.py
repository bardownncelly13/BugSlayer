import os
import os.path
import json
import sys
import ctypes
import warnings
import argparse
import subprocess
import hashlib
from tree_sitter import Parser, Language

warnings.filterwarnings(
    "ignore", message="int argument support is deprecated", category=DeprecationWarning
)

LIB_PATH = os.path.join(os.path.dirname(__file__), "parsers", "build", "my-languages.so")

LANG_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".rs": "rust",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
}

SKIP_DIRS = {
    ".git",
    "node_modules",
    "target",
    "dist",
    "build",
    ".venv",
    "venv",
    "__pycache__",
}

MAX_BYTES = 2_000_000
SNIPPET_RADIUS = 6

# Keep CDLLs alive
_LIBS = {}


def make_callsite_id(caller_key: str, call_line: int, callee_text: str) -> str:
    h = hashlib.sha1(callee_text.encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"{caller_key}::{call_line}::{h}"


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
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


FN_NODES = {
    "python": ("function_definition",),
    "javascript": ("function_declaration", "method_definition"),
    "c": ("function_definition",),
    "cpp": ("function_definition",),
    "rust": ("function_item",),
}

CALL_NODES = {
    "python": ("call",),
    "javascript": ("call_expression", "new_expression"),
    "c": ("call_expression",),
    "cpp": ("call_expression",),
    "rust": ("call_expression", "macro_invocation"),
}


def get_git_root(start_path=".") -> str:
    try:
        out = subprocess.run(
            ["git", "-C", start_path, "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        return out
    except Exception:
        return os.path.abspath(start_path)


def make_snippet(src_bytes: bytes, call_line_1based: int) -> str:
    text = src_bytes.decode("utf-8", errors="replace")
    lines = text.splitlines()
    i = max(call_line_1based - 1, 0)
    lo = max(i - SNIPPET_RADIUS, 0)
    hi = min(i + SNIPPET_RADIUS + 1, len(lines))
    return "\n".join(f"{n+1}: {lines[n]}" for n in range(lo, hi))


def callee_name_from_text(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    for sep in ("::", ".", "->"):
        if sep in s:
            s = s.split(sep)[-1]
    return s.strip().rstrip("(").strip()


def find_first_identifier(node):
    if node is None:
        return None
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type == "identifier":
            return n
        stack.extend(reversed(n.children))
    return None


def c_callee_text(call_node, source: bytes) -> str:
    """
    tree-sitter-c: call_expression has field 'function', which can be:
      - identifier                 foo(...)
      - field_expression           obj.method(...)
      - pointer_expression etc     (*fp)(...)
    We try to return the best text that represents the callee.
    """
    fn = call_node.child_by_field_name("function")
    if fn is None:
        return ""

    # Prefer just the function identifier if possible
    if fn.type == "identifier":
        return node_text(fn, source).strip()

    # obj.method(...) -> prefer the 'field' (method name)
    if fn.type == "field_expression":
        field = fn.child_by_field_name("field")
        if field and field.type == "identifier":
            return node_text(field, source).strip()
        ident = find_first_identifier(fn)
        return node_text(ident, source).strip() if ident else node_text(fn, source).strip()

    # Fallback: find first identifier somewhere inside
    ident = find_first_identifier(fn)
    return node_text(ident, source).strip() if ident else node_text(fn, source).strip()


def iter_calls(tree, source: bytes, rel_path: str, lang: str):
    root = tree.root_node
    stack = [(root, None)]

    while stack:
        node, current_fn = stack.pop()

        # Detect current function (caller)
        if node.type in FN_NODES.get(lang, ()):
            name_node = node.child_by_field_name("name")

            # For C/C++ function_definition name is often nested under declarator
            if name_node is None and lang in ("c", "cpp"):
                decl = node.child_by_field_name("declarator")
                name_node = find_first_identifier(decl) if decl else None

            if name_node:
                caller_name = node_text(name_node, source)
                caller_start_line = node.start_point[0] + 1

                param_node = (
                    node.child_by_field_name("parameters")
                    or node.child_by_field_name("parameter_list")
                )
                parameters = node_text(param_node, source) if param_node else ""

                caller_key = f"{rel_path}::{caller_name}{parameters}::{caller_start_line}"
                current_fn = {
                    "caller_path": rel_path,
                    "caller_name": caller_name,
                    "caller_start_line": caller_start_line,
                    "caller_key": caller_key,
                    "language": lang,
                }

        # Detect call sites
        if current_fn and node.type in CALL_NODES.get(lang, ()):
            if lang in ("c", "cpp"):
                callee_text = c_callee_text(node, source)
            else:
                callee_node = (
                    node.child_by_field_name("function")
                    or node.child_by_field_name("callee")
                    or node.child_by_field_name("name")
                )
                if callee_node is None and node.children:
                    callee_node = node.children[0]
                callee_text = node_text(callee_node, source).strip() if callee_node else ""

            call_line = node.start_point[0] + 1
            callee_name = callee_name_from_text(callee_text)
            callsite_id = make_callsite_id(current_fn["caller_key"], call_line, callee_text)

            yield {
                **current_fn,
                "file": rel_path,
                "call_line": call_line,
                "callee_text": callee_text,
                "callee_name": callee_name,
                "callsite_id": callsite_id,
                "snippet": make_snippet(source, call_line),
            }

        for child in node.children:
            stack.append((child, current_fn))


def run_extract_calls(repo_root: str, out_file: str):
    with open(out_file, "w", encoding="utf-8") as out_f:
        for root, dirs, files in os.walk(repo_root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for file in files:
                ext = os.path.splitext(file)[1]
                if ext not in LANG_MAP:
                    continue
                abs_path = os.path.join(root, file)
                rel_path = os.path.relpath(abs_path, repo_root)
                try:
                    if os.stat(abs_path).st_size > MAX_BYTES:
                        continue
                    lang = LANG_MAP[ext]
                    with open(abs_path, "rb") as f:
                        src = f.read()
                    tree = PARSERS[lang].parse(src)
                    for rec in iter_calls(tree, src, rel_path, lang):
                        print(json.dumps(rec, ensure_ascii=False), file=out_f)
                except Exception:
                    # If you want to debug failures, print the exception here.
                    pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=None, help="Repo path (default: git root)")
    ap.add_argument("--out", default="-", help="JSONL output (default: stdout)")
    args = ap.parse_args()

    repo_root = os.path.abspath(args.repo or get_git_root("."))

    if args.out == "-":
        out_f = sys.stdout
        for root, dirs, files in os.walk(repo_root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for file in files:
                ext = os.path.splitext(file)[1]
                if ext not in LANG_MAP:
                    continue
                abs_path = os.path.join(root, file)
                rel_path = os.path.relpath(abs_path, repo_root)
                try:
                    if os.stat(abs_path).st_size > MAX_BYTES:
                        continue
                    lang = LANG_MAP[ext]
                    with open(abs_path, "rb") as f:
                        src = f.read()
                    tree = PARSERS[lang].parse(src)
                    for rec in iter_calls(tree, src, rel_path, lang):
                        print(json.dumps(rec, ensure_ascii=False), file=out_f)
                except Exception:
                    pass
    else:
        run_extract_calls(repo_root, args.out)


if __name__ == "__main__":
    main()