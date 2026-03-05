import subprocess
from typing import List, Optional, Dict
import os
import re
import tempfile
import requests
from github import Github



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


def get_diff_for_file(path: str, base_ref: str = "origin/main") -> str:
    """
    Get the git diff for a single file compared to a base reference.
    """
    result = subprocess.run(
        ["git", "diff", base_ref, "--", path],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def create_branch(repo_path: str, branch_name: str):
    """
    Create a new git branch from the currently checked-out branch (HEAD).
    """
    run_git(["checkout", "-b", branch_name], repo_path)


def apply_patch(repo_path, file_path, old, new):
    path = os.path.join(repo_path, file_path)

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # print(content)
    
    if old not in content:
        raise ValueError(
            f"Patch anchor not found in {file_path}"
        )

    updated = content.replace(old, new, 1)

    with open(path, "w", encoding="utf-8") as f:
        f.write(updated)


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


def create_patch_pr(repo_path, finding, file, patch, base_ref):
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
        create_branch(repo_path, branch_name)

        apply_patch(
            repo_path=repo_path,
            file_path=file,
            old=patch.old,
            new=patch.new,
        )

        stage_files(repo_path, files_changed)
        commit_changes(repo_path, commit_message, author="LLM Bot <bot@example.com>")

        #CONFOG AZURE so it doesnt ask for PAT again
        configure_azure_git_auth(repo_path)
        # Push
    #     push_branch(repo_path, branch_name)

    #     # Create PR
    #     head = branch_name
    #     base = base_ref.replace("origin/", "")
    #     title = f"Fix {finding['check_id']} in {file}"
    #     body = f"""
    #     ### Security Fix (Automated) 
        
    #     **Rule:** `{finding['check_id']}`  
    #     **File:** `{file}`  
    #     **Severity:** `{finding.get('extra', {}).get('severity', 'unknown')}`  
    #     **Risk Assessment:** `{patch.risk}`
        
    #     ---
        
    #     ### Patch Summary
    #     This PR applies a minimal, targeted fix to remediate the detected vulnerability.
        
    #     - Exactly one code replacement
    #     - No unrelated logic changed
    #     - Generated automatically by the remediation agent
        
    #     ---
        
    #     ### Review Notes
    #     {"Manual review required." if patch.requires_human else "Low-risk change; manual review optional."}
    # """
    #     # print(f"BASE (This should be a branch name): {base}")
    #     create_pr(repo_path, head, base, title, body)
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
