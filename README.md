## Current State (Proof of Concept)

This project is currently a **diff-based static analysis proof of concept**.

The system scans **only code changes** (git diffs) rather than entire repositories. This keeps scans fast and focuses results on **new issues introduced by a change**, which is the core design goal.

At this stage:
- Static analysis is implemented via **Semgrep**
- The LLM-based triage and patching logic is **stubbed / evolving**
- The goal is to validate scanner integration and diff-based workflows


## How Scanning Works

Instead of scanning a full repository, the scanner:

1. Compares the current `HEAD` against a base reference (e.g. `origin/main`)
2. Computes the git diff
3. Runs Semgrep with `--git-diff`
4. Reports **only findings that intersect changed lines**

This ensures:
- Faster scans on large repositories
- Lower noise
- Findings correspond directly to the change being reviewed


## Requirements

- Python 3.10+
- Git
- Semgrep

Install Semgrep if needed:

    pip install semgrep


## Running the Scanner

From inside a git repository:

    python main.py --base-ref origin/main

Or explicitly specify a repository path:

    python main.py --repo /path/to/repo --base-ref origin/main

Common alternatives for `--base-ref`:
- main
- develop
- HEAD~1
- Any valid branch, tag, or commit SHA


## What You Should Expect

- Only issues **introduced by the diff** are reported
- Existing issues in unchanged code are ignored
- Runtime is typically seconds, even for large repos
- Output is raw/static for now (LLM integration is upcoming)


## What This Does *Not* Do (Yet)

- Full-repository scans
- Historical vulnerability tracking
- Commit-level attribution
- Automated remediation explanations
- Production-grade patch generation

These are planned next steps once the diff-based scanning pipeline is validated.
