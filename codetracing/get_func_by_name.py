import os
import ctypes
import sys
import json
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
_LIBS = {}

# Initialize parsers
PARSERS = {}


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
    if not PARSERS:
        try:
            LANGS = {name: load_language(LIB_PATH, name) for name in set(LANG_MAP.values())}
            for name, lang in LANGS.items():
                p = Parser()
                p.language = lang
                PARSERS[name] = p
        except Exception as e:
            print(f"Error initializing parsers: {e}")


def node_text(node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def get_function_by_name(filepath: str, function_name: str) -> dict:
    """
    Extract a single function from a file by name using tree-sitter.
    Returns dict with path, name, start_line, end_line, body, and fn_key.
    """
    _init_parsers()
    
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
    except Exception:
        return None
    
    tree = parser.parse(source)
    root = tree.root_node
    stack = [(root, None)]
    
    fn_types = FUNCTION_NODE_TYPES.get(lang_name, ("function_definition",))
    
    while stack:
        node, _ = stack.pop()
        
        if node.type in fn_types:
            name_node = node.child_by_field_name("name")
            if name_node:
                node_name = node_text(name_node, source)
                if node_name == function_name:
                    start_line = node.start_point[0] + 1
                    
                    # Extract parameters
                    param_node = (
                        node.child_by_field_name("parameters")
                        or node.child_by_field_name("parameter_list")
                    )
                    parameters = node_text(param_node, source) if param_node else ""
                    
                    fn_key = f"{filepath}::{node_name}{parameters}::{start_line}"
                    return {
                        "path": filepath,
                        "name": node_name,
                        "start_line": start_line,
                        "end_line": node.end_point[0] + 1,
                        "body": node_text(node, source),
                        "parameters": parameters,
                        "fn_key": fn_key
                    }
        
        for child in node.children:
            stack.append((child, None))
    
    return None


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python get_func_by_name.py <filepath> <function_name>")
        print("\nExample:")
        print("  python get_func_by_name.py ../main.py main")
        print("  python get_func_by_name.py scanners/flashscan.py gemini_scan")
        sys.exit(1)
    
    filepath = sys.argv[1]
    function_name = sys.argv[2]
    
    result = get_function_by_name(filepath, function_name)
    if result:
        print(json.dumps(result, indent=2))
    else:
        print(f"Function '{function_name}' not found in {filepath}")
        sys.exit(1)
