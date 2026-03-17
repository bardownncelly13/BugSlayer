import os
os.environ["CFLAGS"] = "-std=c11"

from tree_sitter import Language

Language.build_library(
    "build/my-languages.so",
    [
        "tree-sitter-python",
        "tree-sitter-c",
        "tree-sitter-cpp",
        "tree-sitter-rust",
        "tree-sitter-go",
        "tree-sitter-java",
        "tree-sitter-javascript",
    ],
)