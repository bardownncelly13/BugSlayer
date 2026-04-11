import json
from collections import defaultdict, deque
def load_json_maybe(s: str):
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return None

def parse_params_list(parameters: str) -> list[str]:
    # Keep simple; just for reporting names
    s = (parameters or "").strip()
    if not (s.startswith("(") and s.endswith(")")):
        return []
    inner = s[1:-1].strip()
    if not inner:
        return []
    parts = [p.strip() for p in inner.split(",") if p.strip()]
    out = []
    for part in parts:
        name = part.split(":", 1)[0].split("=", 1)[0].strip()
        if name:
            toks = [t for t in name.replace("*", " ").replace("&", " ").split() if t]
            out.append(toks[-1])
    return out

def propagate_for_entrypoint(
    entry_record: dict,
    subgraph_record: dict,
    fn_meta: dict,
    vuln_contracts: dict,
    transfer_conf_threshold: float = 0.60,
):
    entry = entry_record["key"]
    vulnerable_keys = set(subgraph_record.get("vulnerableKeys") or [])
    edges = subgraph_record.get("edges") or []
    callsites = subgraph_record.get("callsites") or []

    # adjacency
    succ = defaultdict(list)
    for e in edges:
        succ[e["caller"]].append(e["callee"])

    # callsites by edge
    cs_by_edge = defaultdict(list)
    for cs in callsites:
        if cs.get("id"):
            cs_by_edge[(cs["caller"], cs["callee"])].append(cs)

    # Taint state: function -> tainted callee param indices
    tainted = defaultdict(set)

    # Seed: taint all entrypoint params (conservative)
    entry_params = parse_params_list(fn_meta.get(entry, {}).get("parameters", entry_record.get("parameters","")))
    for i in range(len(entry_params)):
        tainted[entry].add(i)

    # Track uncertainty on edges (missing transfer or low confidence)
    uncertain_edges = set()

    q = deque([entry])
    visited = set([entry])

    while q:
        caller = q.popleft()

        for callee in succ.get(caller, []):
            callee_params = parse_params_list(fn_meta.get(callee, {}).get("parameters", ""))
            new_tainted = set()

            cs_list = cs_by_edge.get((caller, callee), [])
            if not cs_list:
                # If we have an edge but no callsite, we can't do transfer reasoning
                uncertain_edges.add((caller, callee, "no_callsite"))
                # do NOT assume taint-all; mark uncertain instead
                continue

            for cs in cs_list:
                conf = float(cs.get("edge_transfer_confidence", 0.0) or 0.0)
                transfer = load_json_maybe(cs.get("edge_transfer_json", ""))

                if not isinstance(transfer, dict) or "flows" not in transfer:
                    uncertain_edges.add((caller, callee, "no_transfer"))
                    continue

                if conf < transfer_conf_threshold:
                    uncertain_edges.add((caller, callee, f"low_conf:{conf:.2f}"))

                flows = transfer.get("flows") or []
                for f in flows:
                    try:
                        idx = int(f.get("callee_param_index"))
                    except Exception:
                        continue

                    # Determine whether this arg is tainted at this callsite
                    # Default to tainted if missing (conservative)
                    tainted_flag = f.get("tainted")
                    if tainted_flag is None:
                        # backward compat if you still have old "sanitized" bool
                        sanitized = bool(f.get("sanitized", False))
                        tainted_flag = not sanitized
                    tainted_flag = bool(tainted_flag)

                    if not tainted_flag:
                        continue

                    # Optional extra guard: if taint_from doesn't mention anything meaningful, treat uncertain
                    taint_from = f.get("taint_from") or []
                    if not taint_from:
                        uncertain_edges.add((caller, callee, "empty_taint_from"))
                        # still propagate (conservative)
                        new_tainted.add(idx)
                        continue

                    new_tainted.add(idx)

            before = set(tainted.get(callee, set()))
            tainted[callee] |= new_tainted
            if tainted[callee] != before and callee not in visited:
                visited.add(callee)
                q.append(callee)

    findings = []
    for v in vulnerable_keys:
        v_params = parse_params_list(fn_meta.get(v, {}).get("parameters", ""))
        idxs = sorted(list(tainted.get(v, set())))
        contract = vuln_contracts.get(v) or {}
        sink_type = contract.get("sink_type", "other")

        if idxs:
            verdict = "reachable_exploitable"
        else:
            # If there was any uncertainty in the explored subgraph, mark uncertain instead of not_reachable
            verdict = "uncertain" if uncertain_edges else "not_reachable"

        findings.append(
            {
                "entrypoint": entry,
                "vuln": v,
                "sink_type": sink_type,
                "tainted_param_indices": idxs,
                "tainted_param_names": [v_params[i] for i in idxs if i < len(v_params)],
                "verdict": verdict,
                "uncertain_edge_count": len(uncertain_edges),
                "contract": contract,
            }
        )

    return findings