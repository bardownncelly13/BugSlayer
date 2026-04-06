import json
import os
import sys
from neo4j import GraphDatabase
from get_func_by_name import get_function_by_name

NEO4J_URI  = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASS = os.environ.get("NEO4J_PASS", "password")

# Default to parent directory gemini_results.json
DEFAULT_JSON = os.path.join(os.path.dirname(__file__), "..", "gemini_results.json")
INPUT_JSON = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_JSON


def update_function_flags(tx, path, function_name, function_line, parameters="", is_vulnerable=False, is_entry_point=False):
    """Update a Function node with vulnerablefunc and entrypoint flags."""
    fn_key = f"{path}::{function_name}{parameters}::{function_line}"
    
    tx.run(
        """
        MATCH (fn:Function {key: $fn_key})
        SET fn.vulnerablefunc = $is_vulnerable,
            fn.entrypoint = $is_entry_point
        """,
        {
            "fn_key": fn_key,
            "is_vulnerable": is_vulnerable,
            "is_entry_point": is_entry_point,
        },
    )


def process_gemini_results(json_file: str):
    """Parse gemini_results.json and update neo4j with flags."""
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    
    updates = 0
    
    with open(json_file, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    
    with driver.session() as session:
        for file_entry in data:
            path = file_entry.get("path")
            
            # Process vulnerabilities
            for vuln in file_entry.get("vulnerabilities", []):
                function_name = vuln.get("function")
                is_entry_point = vuln.get("is_entry_point", False)
                
                if function_name:
                    # Extract base function name (before opening parenthesis)
                    base_function_name = function_name.split('(')[0].strip()
                    # Use get_function_by_name to find the actual line number and parameters
                    func_info = get_function_by_name(path, base_function_name)
                    if func_info:
                        function_line = func_info["start_line"]
                        parameters = func_info.get("parameters", "")
                        session.execute_write(
                            update_function_flags,
                            path,
                            function_name,
                            function_line,
                            parameters,
                            is_vulnerable=True,
                            is_entry_point=is_entry_point
                        )
                        updates += 1
                        print(f"Updated vulnerability: {path}::{function_name}{parameters}::{function_line} (vulnerable=True, entrypoint={is_entry_point})")
                    else:
                        print(f"Warning: Could not find function {function_name} in {path}")
            
            # Process entry points
            for ep in file_entry.get("entry_points", []):
                function_name = ep.get("function")
                is_entry_point = ep.get("is_entry_point", False)
                
                if function_name:
                    # Extract base function name (before opening parenthesis)
                    base_function_name = function_name.split('(')[0].strip()
                    # Use get_function_by_name to find the actual line number and parameters
                    func_info = get_function_by_name(path, base_function_name)
                    if func_info:
                        function_line = func_info["start_line"]
                        parameters = func_info.get("parameters", "")
                        session.execute_write(
                            update_function_flags,
                            path,
                            function_name,
                            function_line,
                            parameters,
                            is_vulnerable=False,
                            is_entry_point=is_entry_point
                        )
                        updates += 1
                        print(f"Updated entry point: {path}::{function_name}{parameters}::{function_line} (vulnerable=False, entrypoint={is_entry_point})")
                    else:
                        print(f"Warning: Could not find function {function_name} in {path}")
    
    driver.close()
    return updates


def main():
    if not os.path.exists(INPUT_JSON):
        print(f"Error: {INPUT_JSON} not found")
        sys.exit(1)
    
    updates = process_gemini_results(INPUT_JSON)
    print(f"\nTotal updates: {updates}")


if __name__ == "__main__":
    main()
