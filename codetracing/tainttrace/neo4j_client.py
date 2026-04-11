import os
import json
from neo4j import GraphDatabase

NEO4J_URI  = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASS", "password")


class Neo4jClient:
    def __init__(self):
        self.driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))

    def close(self):
        self.driver.close()

    def read(self, cypher: str, **params):
        with self.driver.session() as s:
            return [r.data() for r in s.run(cypher, params)]

    def write(self, cypher: str, **params):
        with self.driver.session() as s:
            s.execute_write(lambda tx: tx.run(cypher, params).consume())

    # ---------- Stage 0: reachable vulnerable functions (override contracts) ----------
    def fetch_route_callsites_for_transfer(self, depth=50, limit=2000, overwrite=False):
        """
        CallSites on some entrypoint->vuln route with RESOLVES_TO.
        If overwrite=False, only those missing edge_transfer_json.
        """
        depth = int(depth)
        where = "" if overwrite else "WHERE cs.edge_transfer_json IS NULL OR cs.edge_transfer_json = ''"

        q = f"""
        MATCH p = (e:Function {{entrypoint:true}})-[:CALLS*1..{depth}]->(:Function {{vulnerablefunc:true}})
        UNWIND relationships(p) AS r
        WITH DISTINCT startNode(r) AS caller, endNode(r) AS callee
        MATCH (caller)-[:HAS_CALLSITE]->(cs:CallSite)-[:RESOLVES_TO]->(callee)
        {where}
        RETURN DISTINCT
        cs.id AS callsite_id,
        coalesce(cs.language,"") AS language,
        cs.snippet AS snippet,
        caller.key AS caller_key,
        coalesce(caller.parameters,"") AS caller_parameters,
        coalesce(caller.body,"") AS caller_body,
        callee.key AS callee_key,
        coalesce(callee.parameters,"") AS callee_parameters,
        coalesce(callee.body,"") AS callee_body,
        coalesce(cs.edge_transfer_json,"") AS edge_transfer_json,
        coalesce(cs.edge_transfer_confidence,0.0) AS edge_transfer_confidence
        LIMIT $limit
        """
        return self.read(q, limit=limit)

    def set_callsite_transfer(self, callsite_id: str, transfer: dict, confidence: float):
        self.write(
            """
            MATCH (cs:CallSite {id:$id})
            SET cs.edge_transfer_json = $json,
                cs.edge_transfer_confidence = $conf
            """,
            id=callsite_id,
            json=json.dumps(transfer, ensure_ascii=False),
            conf=confidence,
        )
    def fetch_reachable_vulnerable_functions(self, depth=50, limit=5000):
        depth = int(depth)
        q = f"""
        MATCH p = (e:Function {{entrypoint:true}})-[:CALLS*1..{depth}]->(v:Function {{vulnerablefunc:true}})
        WITH DISTINCT v
        RETURN v.key AS key, v.language AS language, v.body AS body,
               v.vuln_issue AS vuln_issue, v.vuln_message AS vuln_message
        LIMIT $limit
        """
        return self.read(q, limit=limit)

    def set_vuln_contract(self, key: str, contract: dict):
        self.write(
            """
            MATCH (f:Function {key:$key})
            SET f.vuln_contract_json = $json
            """,
            key=key,
            json=json.dumps(contract, ensure_ascii=False),
        )

    # ---------- Stage 1: function summaries on routes (missing or overwrite) ----------

    def fetch_functions_on_any_entry_to_vuln_route(self, depth=50, limit=50000):
        depth = int(depth)
        q = f"""
        MATCH p = (e:Function {{entrypoint:true}})-[:CALLS*1..{depth}]->(:Function {{vulnerablefunc:true}})
        UNWIND nodes(p) AS n
        WITH DISTINCT n
        WHERE n:Function
        RETURN n.key AS key, n.language AS language, n.body AS body, n.parameters AS parameters,
               coalesce(n.func_summary_json,"") AS func_summary_json
        LIMIT $limit
        """
        return self.read(q, limit=limit)

    def fetch_functions_missing_summary(self, depth=50, limit=5000):
        depth = int(depth)
        q = f"""
        MATCH p = (e:Function {{entrypoint:true}})-[:CALLS*1..{depth}]->(:Function {{vulnerablefunc:true}})
        UNWIND nodes(p) AS n
        WITH DISTINCT n
        WHERE n:Function AND (n.func_summary_json IS NULL OR n.func_summary_json = "")
        RETURN n.key AS key, n.language AS language, n.body AS body, n.parameters AS parameters
        LIMIT $limit
        """
        return self.read(q, limit=limit)

    def set_func_summary(self, key: str, summary: dict):
        self.write(
            """
            MATCH (f:Function {key:$key})
            SET f.func_summary_json = $json
            """,
            key=key,
            json=json.dumps(summary, ensure_ascii=False),
        )

    # ---------- Stage 2: arg maps only for callsites on routes (missing or overwrite) ----------

    def fetch_route_callsites_for_argmap(self, depth=50, limit=5000, overwrite=False):
        depth = int(depth)
        where = "" if overwrite else "WHERE cs.arg_map_json IS NULL OR cs.arg_map_json = ''"

        q = f"""
        MATCH p = (e:Function {{entrypoint:true}})-[:CALLS*1..{depth}]->(:Function {{vulnerablefunc:true}})
        UNWIND relationships(p) AS r
        WITH DISTINCT startNode(r) AS caller, endNode(r) AS callee
        MATCH (caller)-[:HAS_CALLSITE]->(cs:CallSite)-[:RESOLVES_TO]->(callee)
        {where}
        RETURN DISTINCT
          cs.id AS callsite_id,
          cs.language AS language,
          cs.snippet AS snippet,
          caller.key AS caller_key,
          caller.parameters AS caller_parameters,
          callee.key AS callee_key,
          callee.parameters AS callee_parameters,
          coalesce(cs.arg_map_json,"") AS arg_map_json,
          coalesce(cs.arg_confidence,0.0) AS arg_confidence
        LIMIT $limit
        """
        return self.read(q, limit=limit)

    def set_callsite_argmap(self, callsite_id: str, argmap: dict, confidence: float):
        self.write(
            """
            MATCH (cs:CallSite {id:$id})
            SET cs.arg_map_json = $json,
                cs.arg_confidence = $conf
            """,
            id=callsite_id,
            json=json.dumps(argmap, ensure_ascii=False),
            conf=confidence,
        )

    # ---------- Stage 3 support ----------

    def fetch_entrypoints(self):
        return self.read(
            """
            MATCH (e:Function) WHERE e.entrypoint = true
            RETURN e.key AS key, e.language AS language, e.parameters AS parameters
            ORDER BY e.key
            """
        )

    def fetch_reachable_vuln_contracts(self, depth=50, limit=50000):
        depth = int(depth)
        q = f"""
        MATCH p = (e:Function {{entrypoint:true}})-[:CALLS*1..{depth}]->(v:Function {{vulnerablefunc:true}})
        WITH DISTINCT v
        RETURN v.key AS key, coalesce(v.vuln_contract_json,"") AS vuln_contract_json
        LIMIT $limit
        """
        return self.read(q, limit=limit)

    def fetch_callsites_for_entrypoint_to_any_vuln(self, entry_key: str, depth=50):
        depth = int(depth)
        q = f"""
        MATCH (e:Function {{key:$entry}})
        OPTIONAL MATCH p = (e)-[:CALLS*1..{depth}]->(v:Function {{vulnerablefunc:true}})
        WITH e, collect(DISTINCT v.key) AS vulnKeys, collect(p) AS ps
        UNWIND ps AS p
        UNWIND relationships(p) AS r
        WITH e, vulnKeys, collect(DISTINCT r) AS rs
        UNWIND rs AS r
        WITH e, vulnKeys, startNode(r) AS caller, endNode(r) AS callee
        OPTIONAL MATCH (caller)-[:HAS_CALLSITE]->(cs:CallSite)-[:RESOLVES_TO]->(callee)
        RETURN
        e.key AS entrypoint,
        vulnKeys AS vulnerableKeys,
        collect(DISTINCT {{caller:caller.key, callee:callee.key}}) AS edges,
        collect(DISTINCT {{
            id: cs.id,
            caller: caller.key,
            callee: callee.key,
            language: cs.language,
            snippet: cs.snippet,
            edge_transfer_json: coalesce(cs.edge_transfer_json,""),
            edge_transfer_confidence: coalesce(cs.edge_transfer_confidence,0.0)
        }}) AS callsites
        """
        return self.read(q, entry=entry_key)