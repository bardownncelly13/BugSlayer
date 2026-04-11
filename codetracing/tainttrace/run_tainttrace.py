import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO_ROOT))

from neo4j_client import Neo4jClient
from stage0_vuln_contracts import build_contract
from stage1_func_summaries import build_summary
from stage25_edge_transfers import build_edge_transfer
from stage3_propagate_transfers import propagate_for_entrypoint, load_json_maybe

DEFAULT_DEPTH = 50

def run_stage0_contracts(client: Neo4jClient, depth: int, limit: int, overwrite: bool):
    rows = client.fetch_reachable_vulnerable_functions(depth=depth, limit=limit)
    for r in rows:
        if not overwrite:
            existing = client.read(
                "MATCH (f:Function {key:$k}) RETURN coalesce(f.vuln_contract_json,'') AS j",
                k=r["key"],
            )
            if existing and existing[0]["j"]:
                continue
        contract = build_contract(r.get("language"), r.get("vuln_issue"), r.get("vuln_message"), r.get("body"))
        client.set_vuln_contract(r["key"], contract)

def run_stage1_summaries(client: Neo4jClient, depth: int, limit: int, overwrite: bool):
    if overwrite:
        rows = client.fetch_functions_on_any_entry_to_vuln_route(depth=depth, limit=limit)
        for r in rows:
            summary = build_summary(r.get("language"), r.get("parameters"), r.get("body"))
            client.set_func_summary(r["key"], summary)
    else:
        rows = client.fetch_functions_missing_summary(depth=depth, limit=limit)
        for r in rows:
            summary = build_summary(r.get("language"), r.get("parameters"), r.get("body"))
            client.set_func_summary(r["key"], summary)

def run_stage25_transfers(client: Neo4jClient, depth: int, limit: int, overwrite: bool):
    rows = client.fetch_route_callsites_for_transfer(depth=depth, limit=limit, overwrite=overwrite)
    for r in rows:
        transfer = build_edge_transfer(
            r.get("language"),
            r.get("caller_parameters"),
            r.get("caller_body"),
            r.get("callee_parameters"),
            r.get("callee_body"),
            r.get("snippet"),
        )
        conf = float(transfer.get("confidence", 0.0)) if isinstance(transfer, dict) else 0.0
        client.set_callsite_transfer(r["callsite_id"], transfer, conf)

def run_stage3_propagation(client: Neo4jClient, depth: int, out_path: str):
    vuln_rows = client.fetch_reachable_vuln_contracts(depth=depth)
    vuln_contracts = {r["key"]: (load_json_maybe(r.get("vuln_contract_json","")) or {}) for r in vuln_rows}

    fn_rows = client.fetch_functions_on_any_entry_to_vuln_route(depth=depth, limit=500000)
    fn_meta = {r["key"]: r for r in fn_rows}

    entrypoints = client.fetch_entrypoints()

    with open(out_path, "w", encoding="utf-8") as f:
        for e in entrypoints:
            sg_rows = client.fetch_callsites_for_entrypoint_to_any_vuln(e["key"], depth=depth)
            if not sg_rows:
                continue
            sg = sg_rows[0]
            findings = propagate_for_entrypoint(e, sg, fn_meta, vuln_contracts)
            for item in findings:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--depth", type=int, default=DEFAULT_DEPTH)
    ap.add_argument("--limit", type=int, default=2000, help="limit per stage fetch")
    ap.add_argument("--out", default="taint_findings.jsonl")

    ap.add_argument("--contracts", action="store_true")
    ap.add_argument("--summaries", action="store_true")
    ap.add_argument("--transfers", action="store_true")
    ap.add_argument("--propagate", action="store_true")

    ap.add_argument("--overwrite-contracts", action="store_true")
    ap.add_argument("--overwrite-summaries", action="store_true")
    ap.add_argument("--overwrite-transfers", action="store_true")

    args = ap.parse_args()
    run_all = not (args.contracts or args.summaries or args.transfers or args.propagate)

    client = Neo4jClient()
    try:
        if run_all or args.contracts:
            run_stage0_contracts(client, args.depth, args.limit, overwrite=args.overwrite_contracts)
        if run_all or args.summaries:
            run_stage1_summaries(client, args.depth, args.limit, overwrite=args.overwrite_summaries)
        if run_all or args.transfers:
            run_stage25_transfers(client, args.depth, args.limit, overwrite=args.overwrite_transfers)
        if run_all or args.propagate:
            run_stage3_propagation(client, args.depth, args.out)
    finally:
        client.close()

if __name__ == "__main__":
    main()