import os
import os.path
import ctypes
import warnings
import json
import sys
import argparse
import tempfile
import shutil
import subprocess

from tree_sitter import Parser, Language

warnings.filterwarnings(
    "ignore",
    message="int argument support is deprecated",
    category=DeprecationWarning,
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
    ".git", ".hg", ".svn",
    "node_modules", "target", "dist", "build",
    ".venv", "venv", "__pycache__",
}

MAX_BYTES = 2_000_000

FUNCTION_NODE_TYPES = {
    "python": ("function_definition",),
    "c": ("function_definition",),
    "cpp": ("function_definition",),
    "rust": ("function_item",),
    "javascript": ("function_declaration", "method_definition", "function", "arrow_function"),
}

# Keep CDLLs alive
_LIBS = {}


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


def load_language(lib_path: str, name: str) -> Language:
    lib = _LIBS.get(lib_path)
    if lib is None:
        lib = ctypes.CDLL(lib_path)
        _LIBS[lib_path] = lib

    fn = getattr(lib, f"tree_sitter_{name}")
    fn.restype = ctypes.c_void_p
    ptr = fn()
    return Language(ptr)


LANGS = {name: load_language(LIB_PATH, name) for name in set(LANG_MAP.values())}

PARSERS = {}
for name, lang in LANGS.items():
    p = Parser()
    p.language = lang
    PARSERS[name] = p


def node_text(node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def extract_functions(tree, source: bytes, rel_path: str, lang_name: str):
    root = tree.root_node
    stack = [(root, None)]
    functions = []

    fn_types = FUNCTION_NODE_TYPES.get(
        lang_name,
        ("function_definition", "function_item", "method_definition"),
    )

    while stack:
        node, current_class = stack.pop()

        # Python class, C++ class
        if node.type in ("class_definition", "class_specifier"):
            name_node = node.child_by_field_name("name")
            if name_node:
                current_class = node_text(name_node, source)

        # Rust impl block
        if lang_name == "rust" and node.type == "impl_item":
            for c in node.children:
                if c.type == "type_identifier":
                    current_class = node_text(c, source)

        if node.type in fn_types:
            name_node = node.child_by_field_name("name")
            param_node = (
                node.child_by_field_name("parameters")
                or node.child_by_field_name("parameter_list")
            )

            if name_node:
                functions.append(
                    {
                        "path": rel_path,  # RELATIVE PATH
                        "language": lang_name,
                        "class": current_class,
                        "function": node_text(name_node, source),
                        "parameters": node_text(param_node, source) if param_node else "",
                        "start_line": node.start_point[0] + 1,
                        "end_line": node.end_point[0] + 1,
                        "body": node_text(node, source),
                    }
                )

        for child in node.children:
            stack.append((child, current_class))

    return functions


def parse_repo(repo_root: str):
    results = []
    errors = 0
    skipped_large = 0

    for root, dirs, files in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

        for file in files:
            ext = os.path.splitext(file)[1]
            if ext not in LANG_MAP:
                continue

            abs_path = os.path.join(root, file)
            rel_path = os.path.relpath(abs_path, repo_root)

            try:
                st = os.stat(abs_path)
                if st.st_size > MAX_BYTES:
                    skipped_large += 1
                    continue

                lang_name = LANG_MAP[ext]
                parser = PARSERS[lang_name]

                with open(abs_path, "rb") as f:
                    source = f.read()

                tree = parser.parse(source)
                results.extend(extract_functions(tree, source, rel_path, lang_name))

            except Exception as e:
                errors += 1
                print(f"ERROR parsing {abs_path}: {e}", file=sys.stderr)

    return results, {"errors": errors, "skipped_large": skipped_large}


def is_git_url(s: str) -> bool:
    return s.startswith(("http://", "https://", "git@", "ssh://")) or s.endswith(".git")


def clone_to_temp(git_url_or_path: str) -> str:
    try:
        from git_utils.git_ops import create_temp_repo
        return create_temp_repo(git_url_or_path)
    except Exception:
        temp_dir = tempfile.mkdtemp(prefix="codetrace_repo_")
        subprocess.run(["git", "clone", git_url_or_path, temp_dir], check=True)
        return temp_dir


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".", help="Local repo path to scan (default: git root if inside a repo)")
    ap.add_argument("--git", default=None, help="Git URL/path to clone+scan (overrides --repo)")
    ap.add_argument("--out", default="-", help="Output JSONL file (default: stdout)")
    args = ap.parse_args()

    temp_dir = None

    if args.git:
        # Clone then scan clone root
        if is_git_url(args.git) or not os.path.isdir(args.git):
            temp_dir = clone_to_temp(args.git)
            repo_root = os.path.abspath(temp_dir)
        else:
            repo_root = os.path.abspath(args.git)
    else:
        # If --repo is '.', scan git root (not just current subdir)
        repo_root = get_git_root(args.repo) if args.repo == "." else os.path.abspath(args.repo)

    data, stats = parse_repo(repo_root)

    out_f = sys.stdout if args.out == "-" else open(args.out, "w", encoding="utf-8")
    try:
        for rec in data:
            print(json.dumps(rec, ensure_ascii=False), file=out_f)
    finally:
        if out_f is not sys.stdout:
            out_f.close()

    print(json.dumps({"_stats": stats, "repo_root": repo_root}, ensure_ascii=False), file=sys.stderr)

    if temp_dir:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()