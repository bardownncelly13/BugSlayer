# BugSlayer - End-to-End

[![Setup Guide](https://img.shields.io/badge/Setup%20Guide-BugSlayer-00ff88?style=for-the-badge&logo=github&logoColor=black)](https://morganmcl.github.io/bug-slayer-setup/)

BugSlayer is a diff-aware security remediation pipeline that combines:

- Semgrep findings on changed code
- Neo4j-backed call graph construction
- Taint reachability propagation from entrypoints to vulnerable sinks
- LLM triage and patch generation
- Automated branch/PR creation for valid fixes

The main entrypoint is `main.py`.

## What It Does Today

When you run `main.py`, BugSlayer executes this flow:

1. Builds a call graph for the target repository and reloads Neo4j.
2. Runs Semgrep (diff-aware when possible).
3. Marks vulnerable functions in Neo4j based on Semgrep findings.
4. Optionally runs Gemini-based scanning when `GEMINI_API_KEY` is set.
5. Updates function metadata from Gemini results.
6. Runs tainttrace stages and writes `taint_findings.jsonl`.
7. For each taint finding:
   - Builds context,
   - Runs LLM triage,
   - Attempts validated patch generation in a temp clone,
   - Creates a patch PR on success, or a remediation-report branch on failure.

Exit behavior:

- Exit code `1` when taint findings exist.
- Exit code `0` when no taint findings exist.

## Requirements

- Python 3.10+
- Git
- Docker + Docker Compose (for Neo4j)
- Semgrep CLI available on PATH

Install Python dependencies:

```bash
pip install -r requirements.txt
```

If Semgrep is missing:

```bash
pip install semgrep
```

## Neo4j Setup

BugSlayer manages Neo4j through `codetracing/graphdb/docker-compose.yml`.

- Default Bolt URI: `bolt://127.0.0.1:7687`
- Default Browser URL: `http://localhost:7474`
- Default credentials: `neo4j / password`

The callgraph step performs a destructive reset of graph state (`docker compose down -v` then `up -d`).

## Quick Start

From this repository root:

```bash
python main.py --repo /path/to/target/repo --base-ref origin/main --head-ref HEAD
```

Common options:

- `--repo`: repository to scan (default `.`)
- `--base-ref`: diff base reference (default `origin/main`)
- `--head-ref`: diff head reference (default `HEAD`)
- `--semgrep-config`: custom Semgrep config or comma-separated configs

Notes:

- If diff refs are valid and changed files exist, Semgrep results are filtered to changed lines.
- If no usable diff is available, BugSlayer falls back to a full-repository Semgrep scan.

## Environment Variables

Core runtime:

- `MAX_PATCH_ATTEMPTS` (default `5`)
- `TAINT_FINDINGS_JSONL` (override taint findings input path)

Neo4j:

- `NEO4J_URI` (default `bolt://127.0.0.1:7687`)
- `NEO4J_USER` (default `neo4j`)
- `NEO4J_PASS` (default `password`)
- `NEO4J_SERVICE` (default `neo4j`, used by compose exec)

Gemini scanning / retries:

- `GEMINI_API_KEY` (enables Gemini scan path)
- `GEMINI_MAX_RETRIES`
- `GEMINI_RETRY_BASE_SECONDS`
- `GEMINI_RETRY_MAX_SECONDS`
- `GEMINI_RETRY_VERBOSE`

LLM triage/patch backend (OpenAI-compatible endpoint):

- `TAMUS_AI_CHAT_API_ENDPOINT`
- `TAMUS_AI_CHAT_API_KEY`
- `TAMUS_AI_CHAT_MODEL` (default `protected.Claude Sonnet 4`)

PR creation credentials:

- GitHub: `GITHUB_TOKEN`
- Azure DevOps: `AZURE_DEVOPS_TOKEN` (and optional `AZURE_DEVOPS_USER`)

## Generated Artifacts and Side Effects

Running the pipeline creates or overwrites files in the scanned repository root:

- `funcs.jsonl`
- `calls.jsonl`
- `gemini_results.json` (when Gemini scanner runs)
- `taint_findings.jsonl`

Additional side effects:

- Neo4j data volume is wiped/recreated during callgraph setup.
- Temporary git clones are created for patch validation.
- On successful patch validation, branches/commits/pushes and PR creation are attempted.

Do not run this against repositories or environments where those side effects are unacceptable.

## Standalone Utilities

- `build_CallGraph.sh`: shell workflow for call graph extraction + Neo4j ingest.
- `scanners/gitleaks.py`: run Gitleaks in Docker (`--history` optional).
- `codetracing/tainttrace/run_tainttrace.py`: run taint stages directly.

## Current Limitations

- Patch generation quality depends on LLM output and validator heuristics.
- Validation currently focuses on non-destructive edits and scanner re-checks, not full test-suite execution. We expect test suites would be in parallel pipelines
