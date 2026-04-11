import os
import ctypes
import sys
import json
from typing import Any, Dict, List, Optional
from tree_sitter import Parser, Language

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

FUNCTION_NODE_TYPES = {
    "python": ("function_definition",),
    "c": ("function_definition",),
    "cpp": ("function_definition",),
    "rust": ("function_item",),
    "javascript": ("function_declaration", "method_definition", "function", "arrow_function"),
}

# Keep CDLLs alive
_LIBS: Dict[str, Any] = {}

# Initialize parsers
PARSERS: Dict[str, Parser] = {}


def load_language(lib_path: str, name: str) -> Language:
    lib = _LIBS.get(lib_path)
    if lib is None:
        lib = ctypes.CDLL(lib_path)
        _LIBS[lib_path] = lib
    fn = getattr(lib, f"tree_sitter_{name}")
    fn.restype = ctypes.c_void_p
    ptr = fn()
    return Language(ptr)


def _init_parsers():
    """Initialize parsers for all languages."""
    global PARSERS
    if PARSERS:
        return
    try:
        if not os.path.isfile(LIB_PATH):
            return
        langs = {name: load_language(LIB_PATH, name) for name in set(LANG_MAP.values())}
        for name, lang in langs.items():
            p = Parser()
            p.language = lang
            PARSERS[name] = p
    except Exception as e:
        print(f"Error initializing parsers: {e}", file=sys.stderr)
        PARSERS = {}


def node_text(node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def find_first_identifier(node):
    """Walk a subtree and return the first `identifier` node."""
    if node is None:
        return None
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type == "identifier":
            return n
        stack.extend(reversed(n.children))
    return None


def find_first_of_type(node, type_name: str):
    """Walk a subtree and return the first node of type type_name."""
    if node is None:
        return None
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type == type_name:
            return n
        stack.extend(reversed(n.children))
    return None


def _function_dict_from_node(
    node, source: bytes, filepath: str, node_name: str, parameters: str = ""
) -> Dict[str, Any]:
    start_line = node.start_point[0] + 1
    end_line = node.end_point[0] + 1
    parameters = parameters or ""
    return {
        "path": filepath,
        "name": node_name,
        "parameters": parameters,
        "start_line": start_line,
        "end_line": end_line,
        "body": node_text(node, source),
        # NOTE: keep fn_key format consistent with your Neo4j ingest:
        # path::name{parameters}::start_line
        "fn_key": f"{filepath}::{node_name}{parameters}::{start_line}",
    }


def collect_functions_named(filepath: str, function_name: str) -> List[Dict[str, Any]]:
    """
    All tree-sitter function-like nodes whose declared name matches function_name.
    For C/C++ the function name is often nested; we use a subtree fallback.
    """
    _init_parsers()
    ext = os.path.splitext(filepath)[1].lower()
    lang_name = LANG_MAP.get(ext)
    if not lang_name:
        return []
    parser = PARSERS.get(lang_name)
    if not parser:
        return []

    try:
        with open(filepath, "rb") as f:
            source = f.read()
    except OSError:
        return []

    tree = parser.parse(source)
    fn_types = FUNCTION_NODE_TYPES.get(lang_name, ("function_definition",))
    out: List[Dict[str, Any]] = []
    stack = [tree.root_node]

    while stack:
        node = stack.pop()

        if node.type in fn_types:
            name_node = node.child_by_field_name("name")

            # C/C++: name often not directly available; search subtree
            if name_node is None and lang_name in ("c", "cpp"):
                name_node = find_first_identifier(node)

            if name_node:
                node_name = node_text(name_node, source)
                if node_name == function_name:
                    param_node = (
                        node.child_by_field_name("parameters")
                        or node.child_by_field_name("parameter_list")
                    )
                    if not param_node and lang_name in ("c", "cpp"):
                        param_node = find_first_of_type(node, "parameter_list")
                    parameters = node_text(param_node, source) if param_node else ""

                    out.append(
                        _function_dict_from_node(
                            node, source, filepath, node_name, parameters
                        )
                    )

        for child in reversed(node.children):
            stack.append(child)

    out.sort(key=lambda d: (d["start_line"], d["end_line"]))
    return out


def get_function_by_name(
    filepath: str,
    function_name: str,
    target_line: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """
    Extract one function by name. If several matches exist, pass target_line (1-based)
    so the match whose body contains that line wins; if multiple nested matches,
    the innermost (smallest line span) wins.
    """
    matches = collect_functions_named(filepath, function_name)
    if not matches:
        return None

    if target_line is not None:
        containing = [m for m in matches if m["start_line"] <= target_line <= m["end_line"]]
        if len(containing) == 1:
            return containing[0]
        if len(containing) > 1:
            containing.sort(key=lambda m: (m["end_line"] - m["start_line"], -m["start_line"]))
            return containing[0]

    if len(matches) == 1:
        return matches[0]

    # ambiguous without target_line
    return None


def get_enclosing_function_at_line(filepath: str, line_1based: int) -> Optional[Dict[str, Any]]:
    """Innermost function-like node containing line_1based (no name required)."""
    _init_parsers()
    if line_1based is None or line_1based < 1:
        return None

    ext = os.path.splitext(filepath)[1].lower()
    lang_name = LANG_MAP.get(ext)
    if not lang_name:
        return None

    parser = PARSERS.get(lang_name)
    if not parser:
        return None

    try:
        with open(filepath, "rb") as f:
            source = f.read()
    except OSError:
        return None

    tree = parser.parse(source)
    fn_types = FUNCTION_NODE_TYPES.get(lang_name, ("function_definition",))
    candidates: List[tuple] = []

    def visit(node):
        if node.type in fn_types:
            sl = node.start_point[0] + 1
            el = node.end_point[0] + 1
            if sl <= line_1based <= el:
                name_node = node.child_by_field_name("name")
                if name_node is None and lang_name in ("c", "cpp"):
                    name_node = find_first_identifier(node)
                node_name = node_text(name_node, source) if name_node else "<anonymous>"

                param_node = (
                    node.child_by_field_name("parameters")
                    or node.child_by_field_name("parameter_list")
                )
                if not param_node and lang_name in ("c", "cpp"):
                    param_node = find_first_of_type(node, "parameter_list")
                parameters = node_text(param_node, source) if param_node else ""

                span = el - sl
                candidates.append((span, node, node_name, parameters, sl, el))

        for c in node.children:
            visit(c)

    visit(tree.root_node)
    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0])
    _, node, node_name, parameters, sl, el = candidates[0]
    return _function_dict_from_node(node, source, filepath, node_name, parameters)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python get_func_by_name.py <filepath> <function_name> [line]")
        sys.exit(1)

    filepath = sys.argv[1]
    function_name = sys.argv[2]
    line = int(sys.argv[3]) if len(sys.argv) > 3 else None

    result = get_function_by_name(filepath, function_name, target_line=line)
    if result:
        print(json.dumps(result, indent=2))
    else:
        print(f"Function '{function_name}' not found (or ambiguous) in {filepath}")
        sys.exit(1)