import subprocess
from typing import List, Optional, Dict
import os
import re
import tempfile
import requests
from github import Github
from delta import normalize_repo_relative
from path_utils import normalize_path_for_runtime



def run_git(args: List[str], repo_path: str = ".") -> subprocess.CompletedProcess:
    """
    Run a git command in a given repository path using subprocess.
    """
    return subprocess.run(
        ["git"] + args,
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True
    )


def git_cmd(args: List[str], repo_path: Optional[str] = None) -> subprocess.CompletedProcess:
    """
    Helper function to run a git command, optionally specifying a repo path with -C.
    """
    cmd = ["git"]
    if repo_path:
        cmd += ["-C", repo_path]
    cmd += args
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=True,
    )


def get_repo_info(repo_path: str = ".") -> Dict[str, str]:
    """
    Inspect remote.origin.url and return a dict describing the repository.

    For GitHub:
        {
            "provider": "github",
            "owner": "...",
            "repo": "..."
        }

    For Azure DevOps (dev.azure.com):
        HTTPS: https://dev.azure.com/<org>/<project>/_git/<repo>
        SSH:   git@ssh.dev.azure.com:v3/<org>/<project>/<repo>

        {
            "provider": "azure",
            "host": "dev.azure.com",
            "org": "<org>",
            "project": "<project>",
            "repo": "<repo>"
        }

    (Visual Studio format is partially supported but dev.azure.com is the main case.)
    """
    remote = run_git(
        ["config", "--get", "remote.origin.url"],
        repo_path,
    ).stdout.strip()

    # Azure DevOps: HTTPS (dev.azure.com)
    if "dev.azure.com" in remote:
        # e.g. https://dev.azure.com/org/project/_git/repo
        #      or https://user@dev.azure.com/org/project/_git/repo
        m = re.search(
            r"https://(?:(?P<user>[^@]+)@)?(?P<host>[^/]+)/(?P<org>[^/]+)/(?P<project>[^/]+)/_git/(?P<repo>[^/]+)",
            remote,
        )
        if m:
            return {
                "provider": "azure",
                "host": m.group("host"),
                "org": m.group("org"),
                "project": m.group("project"),
                "repo": m.group("repo"),
            }

    # Azure DevOps: SSH (ssh.dev.azure.com)
    if "ssh.dev.azure.com" in remote:
        # e.g. git@ssh.dev.azure.com:v3/org/project/repo
        m = re.search(
            r"git@ssh\.dev\.azure\.com:v3/(?P<org>[^/]+)/(?P<project>[^/]+)/(?P<repo>[^/]+)",
            remote,
        )
        if m:
            return {
                "provider": "azure",
                "host": "dev.azure.com",
                "org": m.group("org"),
                "project": m.group("project"),
                "repo": m.group("repo"),
            }

    # (Optional) older visualstudio.com style
    if "visualstudio.com" in remote:
        # e.g. https://org.visualstudio.com/project/_git/repo
        m = re.search(
            r"https://(?P<host>[^/]+)/(?P<project>[^/]+)/_git/(?P<repo>[^/]+)",
            remote,
        )
        if m:
            host = m.group("host")          # org.visualstudio.com
            org = host.split(".", 1)[0]     # org
            return {
                "provider": "azure",
                "host": host,
                "org": org,
                "project": m.group("project"),
                "repo": m.group("repo"),
            }

    # Fallback: assume GitHub
    # SSH:  git@github.com:owner/repo.git
    if remote.startswith("git@"):
        m = re.search(r"git@[^:]+:([^/]+)/(.+?)(\.git)?$", remote)
    else:
        # HTTPS: https://github.com/owner/repo.git
        m = re.search(r"https?://[^/]+/([^/]+)/(.+?)(\.git)?$", remote)

    if not m:
        raise ValueError(f"Unable to parse repository from git remote: {remote}")

    owner, repo = m.group(1), m.group(2)
    return {
        "provider": "github",
        "owner": owner,
        "repo": repo,
    }

def configure_azure_git_auth(repo_path: str = "."):
    """
    For non-interactive environments (CI/Docker), configure 'origin' to embed
    the Azure DevOps PAT in the remote URL so `git push` works without prompts.

    Uses:
        AZURE_DEVOPS_TOKEN  - required
        AZURE_DEVOPS_USER   - optional, defaults to 'azdo'
    """
    info = get_repo_info(repo_path)
    if info["provider"] != "azure":
        # No-op for GitHub or other providers
        return

    token = os.environ.get("AZURE_DEVOPS_TOKEN")
    if not token:
        raise RuntimeError("AZURE_DEVOPS_TOKEN environment variable is required for Azure DevOps")

    user = os.environ.get("AZURE_DEVOPS_USER", "azdo")

    host = info["host"]
    org = info["org"]
    project = info["project"]
    repo_name = info["repo"]

    # Remote format: https://user:token@dev.azure.com/org/project/_git/repo
    authed_url = f"https://{user}:{token}@{host}/{org}/{project}/_git/{repo_name}"

    # Update origin to use the authenticated URL
    run_git(["remote", "set-url", "origin", authed_url], repo_path)

def get_repo_from_git(repo_path: str = "."):
    """
    Backwards-compatible wrapper for old callers that expect (owner, repo)
    for GitHub only.
    """
    info = get_repo_info(repo_path)
    if info["provider"] != "github":
        raise ValueError("get_repo_from_git is only valid for GitHub remotes.")
    return info["owner"], info["repo"]


def get_changed_files(base_ref: str = "origin/main") -> List[str]:
    """
    Get a list of files that have changed compared to a base git reference.
    """
    result = subprocess.run(
        ["git", "diff", "--name-only", base_ref],
        capture_output=True,
        text=True,
        check=True,
    )
    return [f for f in result.stdout.splitlines() if f.strip()]


def _git_ref_exists(repo_path: str, ref: str) -> bool:
    repo_path = normalize_path_for_runtime(repo_path)
    proc = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", ref],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def get_current_branch_name(repo_path: str) -> str:
    """
    Return the current branch name. If HEAD is detached, try origin/HEAD,
    then fall back to main/master when available.
    """
    repo_path = normalize_path_for_runtime(repo_path)
    current = run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo_path).stdout.strip()
    if current and current != "HEAD":
        return current

    # Detached HEAD in CI: use the remote default branch if available.
    try:
        sym = run_git(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], repo_path).stdout.strip()
        if sym.startswith("origin/"):
            return sym.replace("origin/", "", 1)
    except Exception:
        pass

    if _git_ref_exists(repo_path, "main"):
        return "main"
    if _git_ref_exists(repo_path, "master"):
        return "master"
    raise RuntimeError("Unable to determine current/default branch name.")


def resolve_effective_base_ref(repo_path: str, base_ref: str) -> str:
    """
    Resolve a usable diff base ref.

    Preference order:
    1) requested base_ref
    2) local/remote counterpart (origin/main <-> main)
    3) main/master variants
    4) HEAD~1 fallback
    """
    repo_path = normalize_path_for_runtime(repo_path)
    candidates = [base_ref]

    if base_ref.startswith("origin/"):
        local_name = base_ref.replace("origin/", "", 1)
        candidates.append(local_name)
    else:
        candidates.append(f"origin/{base_ref}")

    # main/master fallback variants
    if "main" in base_ref:
        candidates.extend([
            base_ref.replace("main", "master"),
            "main",
            "origin/main",
            "master",
            "origin/master",
        ])
    elif "master" in base_ref:
        candidates.extend([
            base_ref.replace("master", "main"),
            "master",
            "origin/master",
            "main",
            "origin/main",
        ])

    seen = set()
    ordered = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            ordered.append(c)

    for ref in ordered:
        if _git_ref_exists(repo_path, ref):
            return ref

    if _git_ref_exists(repo_path, "HEAD~1"):
        return "HEAD~1"

    raise RuntimeError(
        f"Could not resolve a usable base ref from '{base_ref}' and HEAD~1 is unavailable."
    )


def resolve_pr_base_branch(repo_path: str, effective_base_ref: str) -> str:
    """
    Resolve a branch name suitable for PR target.
    """
    repo_path = normalize_path_for_runtime(repo_path)
    if effective_base_ref == "HEAD~1":
        return get_current_branch_name(repo_path)
    if effective_base_ref.startswith("origin/"):
        return effective_base_ref.replace("origin/", "", 1)
    if effective_base_ref in ("main", "master"):
        return effective_base_ref
    return get_current_branch_name(repo_path)


def get_diff_for_file(path: str, base_ref: str = "origin/main", repo_path: str = ".") -> str:
    """
    Get the git diff for a single file compared to a base reference.

    Args:
        path: Path to the file (repo-relative or absolute under repo).
        base_ref: Git reference to compare against. Default is "origin/main".
        repo_path: Path to the git repository. Default is current directory.

    Returns:
        String containing the diff output.
    """
    path_for_git = normalize_repo_relative(path, repo_path)
    result = run_git(
        ["diff", base_ref, "--", path_for_git],
        repo_path,
    )
    return result.stdout


def create_branch(repo_path: str, branch_name: str):
    """
    Create a new git branch from the currently checked-out branch (HEAD).
    """
    run_git(["checkout", "-b", branch_name], repo_path)


def _normalize_whitespace_for_anchor(s: str, tab_size: int = 4) -> str:
    """Expand tabs to spaces so anchor matching is insensitive to tab vs space indentation."""
    return s.replace("\t", " " * tab_size)


def _find_anchor_ignoring_leading_indent(content: str, old: str):
    """
    Find `old` in `content` when the file has leading indentation (tabs/spaces)
    before the snippet that the LLM did not include. Matches at line boundaries:
    at each line start we skip whitespace, then require the line(s) to match old.
    Returns (start, end) in content (the code span only; indentation to the left
    is preserved when we replace with new), or (-1, -1) if not found.
    """
    lines_old = old.splitlines()
    if not lines_old:
        return -1, -1

    pos = 0
    while pos < len(content):
        start_line = pos
        # Skip leading whitespace on this line (tabs and spaces)
        while pos < len(content) and content[pos] in " \t":
            pos += 1
        match_start = pos
        # Try to match all lines of old from here
        ok = True
        for i, line_old in enumerate(lines_old):
            if i > 0:
                if pos >= len(content) or content[pos] != "\n":
                    ok = False
                    break
                pos += 1
                while pos < len(content) and content[pos] in " \t":
                    pos += 1
            if pos + len(line_old) > len(content):
                ok = False
                break
            if content[pos : pos + len(line_old)] != line_old:
                ok = False
                break
            pos += len(line_old)
        if ok:
            return match_start, pos
        # Advance to next line start
        pos = content.find("\n", start_line)
        if pos == -1:
            break
        pos += 1
    return -1, -1


def _find_anchor_with_whitespace_flex(content: str, old: str, tab_size: int = 4):
    """
    Find the first occurrence of `old` in `content`, using exact match first,
    then tab-normalized match, then match ignoring leading indentation per line
    (so LLM snippet without tabs/spaces matches file lines that have them).
    Returns (start, end) in original content, or (-1, -1) if not found.
    """
    pos = content.find(old)
    if pos != -1:
        return pos, pos + len(old)

    # Try: file has tabs, LLM has spaces (or vice versa) – normalize both
    content_n = _normalize_whitespace_for_anchor(content, tab_size)
    old_n = _normalize_whitespace_for_anchor(old, tab_size)
    pos_n = content_n.find(old_n)
    if pos_n != -1:
        n_to_c = []
        content_pos = 0
        for c in content:
            n = tab_size if c == "\t" else 1
            for _ in range(n):
                n_to_c.append(content_pos)
            content_pos += 1
        n_to_c.append(content_pos)
        end_n = pos_n + len(old_n)
        start_content = n_to_c[pos_n]
        end_content = n_to_c[end_n] if end_n < len(n_to_c) else len(content)
        return start_content, end_content

    # Try: LLM gave snippet without leading indent; file has indent (tab/space) before it
    return _find_anchor_ignoring_leading_indent(content, old)


def apply_patch(repo_path, file_path, replacements):
    """
    Apply one or more (old, new) replacements to a file.
    replacements: list of (old_str, new_str) tuples. Applied in reverse order
    by position so that earlier edits do not shift indices for later ones.
    Anchor matching normalizes tabs to spaces so LLM output (often spaces)
    matches files that use tabs for indentation.
    """
    path = os.path.join(repo_path, file_path)
    pairs = list(replacements)
    if not pairs:
        raise ValueError("apply_patch: replacements list is empty")

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Find start/end in content for each "old" (exact or tab-normalized match)
    positions = []
    for i, (old, new) in enumerate(pairs):
        start, end = _find_anchor_with_whitespace_flex(content, old)
        if start == -1:
            raise ValueError(
                f"Patch anchor not found in {file_path} (replacement {i + 1}/{len(pairs)})"
            )
        new_adjusted = new

        # Heuristic: if we're replacing a *single* line with *multiple* lines, and the
        # LLM omitted the original leading indentation in `old`, then prefix the
        # indentation from the matched location to subsequent `new` lines.
        #
        # This avoids cases like:
        #   file: "    foo();"
        #   old:  "foo();"
        #   new:  "foo();\nbar();"
        # where `bar();` would otherwise become unindented.
        if "\n" in new and "\n" not in old:
            if old and old[0] not in " \t":
                line_start = content.rfind("\n", 0, start) + 1
                indent = content[line_start:start]
                if indent:
                    new_lines = new.split("\n")
                    for j in range(1, len(new_lines)):
                        nl = new_lines[j]
                        # Don't indent already-indented lines or empty lines.
                        if nl and nl[0] not in " \t":
                            new_lines[j] = indent + nl
                    new_adjusted = "\n".join(new_lines)

        # Store (start, end, new) so we can replace content[start:end] with new
        positions.append((start, end, new_adjusted))

    # Apply in reverse order by position so offsets stay valid
    positions.sort(key=lambda x: x[0], reverse=True)
    for start, end, new in positions:
        content = content[:start] + new + content[end:]

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def stage_files(repo_path: str, files: List[str]):
    """
    Stage a list of files for commit.
    """
    run_git(["add"] + files, repo_path)


def commit_changes(repo_path: str, message: str, author: Optional[str] = None):
    """
    Commit staged changes with a commit message and optional author.
    """
    cmd = ["commit", "-m", message]
    if author:
        cmd += ["--author", author]
    run_git(cmd, repo_path)


def push_branch(repo_path: str, branch_name: str):
    """
    Push a branch to the remote repository and set upstream tracking.
    """
    run_git(["push", "--set-upstream", "origin", branch_name], repo_path)


def create_pr(repo_path, head, base, title, body):
    """
    Create a pull request for either GitHub or Azure DevOps,
    depending on the remote.
    """
    info = get_repo_info(repo_path)

    # GitHub path 
    if info["provider"] == "github":
        g = Github(os.environ["GITHUB_TOKEN"])
        full_name = f"{info['owner']}/{info['repo']}"
        repo = g.get_repo(full_name)

        return repo.create_pull(
            title=title,
            body=body,
            head=head,
            base=base,
        )

    # Azure DevOps path
    if info["provider"] == "azure":
        token = os.environ.get("AZURE_DEVOPS_TOKEN")
        if not token:
            raise RuntimeError("AZURE_DEVOPS_TOKEN environment variable is not set")

        host = info["host"]        
        org = info["org"]
        project = info["project"]
        repo_name = info["repo"]

        # Azure DevOps REST API endpoint for creating a PR by repo name
        # POST https://dev.azure.com/{org}/{project}/_apis/git/repositories/{repo}/pullrequests?api-version=7.1-preview.1
        url = f"https://{host}/{org}/{project}/_apis/git/repositories/{repo_name}/pullrequests"
        params = {"api-version": "7.1-preview.1"}

        payload = {
            "sourceRefName": f"refs/heads/{head}",
            "targetRefName": f"refs/heads/{base}",
            "title": title,
            "description": body,
        }

        # PAT via Basic auth: username can be empty, PAT is the password
        resp = requests.post(url, json=payload, params=params, auth=("", token))
        resp.raise_for_status()
        return resp.json()

    raise ValueError(f"Unsupported provider in repo info: {info}")



def _generate_unique_branch_name(repo_path, base_name):
    # Make sure remote branch list is current
    run_git(["fetch", "--prune"], repo_path)

    # Local branches
    local = run_git(["branch", "--format=%(refname:short)"], repo_path).stdout.splitlines()
    local_branches = {b.strip() for b in local}

    # Remote branches (cleaner format)
    remote = run_git(["branch", "-r", "--format=%(refname:short)"], repo_path).stdout.splitlines()

    # Remove origin/ prefix cleanly
    remote_branches = {
        b.replace("origin/", "", 1).strip()
        for b in remote
        if "->" not in b  # skip HEAD pointer line
    }

    existing = local_branches.union(remote_branches)
    # print(f"Existing Branches: {existing}")

    if base_name not in existing:
        return base_name

    counter = 1
    while True:
        candidate = f"{base_name}-{counter}"
        if candidate not in existing:
            return candidate
        counter += 1


def create_patch_pr(repo_path, finding, file, patch, pr_base_branch):
    original_branch = run_git(
        ["rev-parse", "--abbrev-ref", "HEAD"],
        repo_path
    ).stdout.strip()

    try:
        base_branch_name = f"llm-fix/{finding['check_id']}-{file.replace('/', '-')}"
        branch_name = _generate_unique_branch_name(repo_path, base_branch_name)
        commit_message = f"fix(security): {finding['extra'].get('message', '')}"

        files_changed = [file]

        # Apply patch locally
        # create_branch(repo_path, branch_name)

        # apply_patch(
        #     repo_path=repo_path,
        #     file_path=file,
        #     replacements=patch.replacements,
        # )

        # stage_files(repo_path, files_changed)
        # commit_changes(repo_path, commit_message, author="LLM Bot <bot@example.com>")

        # # CONFIG AZURE so it doesnt ask for PAT again
        # configure_azure_git_auth(repo_path)
        # # Push
        # push_branch(repo_path, branch_name)

        # Create PR
        head = branch_name
        base = pr_base_branch
        title = f"Fix {finding['check_id']} in {file}"
        body = f"""
        ### Security Fix (Automated) 
        
        **Rule:** `{finding['check_id']}`  
        **File:** `{file}`  
        **Severity:** `{finding.get('extra', {}).get('severity', 'unknown')}`  
        **Risk Assessment:** `{patch.risk}`
        
        ---
        
        ### Patch Summary
        This PR applies a minimal, targeted fix to remediate the detected vulnerability.
        
        - Exactly one code replacement
        - No unrelated logic changed
        - Generated automatically by the remediation agent
        
        ---
        
        ### Review Notes
        {"Manual review required." if patch.requires_human else "Low-risk change; manual review optional."}
    """
        print(f"Creating PR for {file}")
        print(f"Title: {title}")
        print(f"Body: {body}")
        print(f"Head: {head}")
        print(f"Base: {base}")
        # print(f"BASE (This should be a branch name): {base}")
        # create_pr(repo_path, head, base, title, body)
    except Exception as e:
        print(f"create_patch_pr failed with error {e}")
    finally:
        run_git(["checkout", original_branch], repo_path)

    return branch_name


def reset_temp_repo(repo_path):
    run_git(["reset", "--hard"], repo_path)
    run_git(["clean", "-fd"], repo_path)


def create_temp_repo(repo_path: str) -> str:
    temp_dir = tempfile.mkdtemp(prefix="remediation_")

    subprocess.run(
        ["git", "clone", repo_path, temp_dir],
        check=True,
        capture_output=True,
    )

    return temp_dir


if __name__ == "__main__":
    # Lightweight self-tests for apply_patch().
    # Run with: `python git_utils/git_ops.py`

    def run_case(case_name: str, initial: str, replacements, expected: str):
        with tempfile.TemporaryDirectory(prefix="git_ops_test_") as td:
            file_name = "test.txt"
            file_path = os.path.join(td, file_name)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(initial)

            apply_patch(
                repo_path=td,
                file_path=file_name,  # repo-relative path
                replacements=replacements,
            )

            with open(file_path, "r", encoding="utf-8") as f:
                actual = f.read()

            if actual != expected:
                raise AssertionError(
                    f"{case_name} failed.\n"
                    f"Expected:\n{expected!r}\n"
                    f"Actual:\n{actual!r}\n"
                )

    cases = [
        (
            "indent_preserve_1line_old_to_multiline_new",
            "    foo();\n    baz();\n",
            [("foo();", "foo();\nbar();")],
            "    foo();\n    bar();\n    baz();\n",
        ),
        (
            "indent_preserve_when_new_lines_already_indented",
            "    foo();\n    baz();\n",
            [("foo();", "foo();\n    bar();")],
            "    foo();\n    bar();\n    baz();\n",
        ),
        (
            "no_double_indent_when_old_includes_indent",
            "    foo();\n    baz();\n",
            [("    foo();", "    foo();\n    bar();")],
            "    foo();\n    bar();\n    baz();\n",
        ),
        (
            "no_indent_added_when_file_has_no_indent",
            "foo();\n",
            [("foo();", "foo();\nbar();")],
            "foo();\nbar();\n",
        ),
        (
            "tab_indent_preserve",
            "\tfoo();\n\tbaz();\n",
            [("foo();", "foo();\nbar();")],
            "\tfoo();\n\tbar();\n\tbaz();\n",
        ),
    ]

    try:
        for name, initial, replacements, expected in cases:
            run_case(name, initial, replacements, expected)
        print("apply_patch self-tests: OK")
    except Exception as e:
        print(f"apply_patch self-tests: FAIL\n{e}")
        raise
