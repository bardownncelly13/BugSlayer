import subprocess
from typing import List, Optional
import os
import re
import tempfile
from github import Github

def get_repo_from_git(repo_path="."):
    result = run_git(
        ["config", "--get", "remote.origin.url"],
        repo_path
    ).stdout.strip()

    if result.startswith("git@"):
        # git@github.com:owner/repo.git
        match = re.search(r"git@[^:]+:([^/]+)/(.+?)(\.git)?$", result)
    else:
        # https://github.com/owner/repo.git
        match = re.search(r"https?://[^/]+/([^/]+)/(.+?)(\.git)?$", result)

    if not match:
        raise ValueError("Unable to parse repository from git remote")

    owner, repo = match.group(1), match.group(2)
    return owner, repo


def run_git(args: List[str], repo_path: str = ".") -> subprocess.CompletedProcess:
    """
    Run a git command in a given repository path using subprocess.

    Args:
        args: List of git command arguments (e.g., ["status"]).
        repo_path: Path to the git repository. Defaults to current directory.

    Returns:
        subprocess.CompletedProcess object containing stdout, stderr, and returncode.
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

    Args:
        args: List of git command arguments.
        repo_path: Optional path to the git repository. If provided, adds -C <repo_path>.

    Returns:
        subprocess.CompletedProcess object containing stdout, stderr, and returncode.
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


def get_changed_files(base_ref: str = "origin/main") -> List[str]:
    """
    Get a list of files that have changed compared to a base git reference.

    Args:
        base_ref: Git reference to compare against (branch, commit hash, etc.). Default is "origin/main".

    Returns:
        List of file paths (strings) that are different from the base_ref.
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

    Args:
        path: Path to the file.
        base_ref: Git reference to compare against. Default is "origin/main".

    Returns:
        String containing the diff output.
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

    Args:
        repo_path: Path to the git repository.
        branch_name: Name of the new branch to create.
    """

    run_git(["checkout", "-b", branch_name], repo_path)


def apply_patch(repo_path, file_path, old, new):
    path = os.path.join(repo_path, file_path)

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    print(content)
    
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

    Args:
        repo_path: Path to the git repository.
        files: List of file paths to stage.
    """
    run_git(["add"] + files, repo_path)


def commit_changes(repo_path: str, message: str, author: Optional[str] = None):
    """
    Commit staged changes with a commit message and optional author.

    Args:
        repo_path: Path to the git repository.
        message: Commit message.
        author: Optional author string in the form "Name <email>". If None, uses default git committer.
    """
    cmd = ["commit", "-m", message]
    if author:
        cmd += ["--author", author]
    run_git(cmd, repo_path)


def push_branch(repo_path: str, branch_name: str):
    """
    Push a branch to the remote repository and set upstream tracking.

    Args:
        repo_path: Path to the git repository.
        branch_name: Name of the branch to push.
    """
    run_git(["push", "--set-upstream", "origin", branch_name], repo_path)

def create_pr(repo_path, head, base, title, body):
    owner, repo_name = get_repo_from_git(repo_path)
    full_name = f"{owner}/{repo_name}"

    g = Github(os.environ["GITHUB_TOKEN"])
    repo = g.get_repo(full_name)

    # for b in repo.get_branches():
    #     print(b.name)
    
    # print(f"Current base is {base}")

    return repo.create_pull(
        title=title,
        body=body,
        head=head,
        base=base,
    )


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
    original_branch = run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo_path).stdout.strip()
    try:
        base_branch_name = f"llm-fix/{finding['check_id']}-{file.replace('/', '-')}"
        branch_name = _generate_unique_branch_name(repo_path, base_branch_name)
        commit_message = f"fix(security): {finding['extra'].get('message', '')}"

        files_changed = [file]

        # print("=== Dry Run ===")
        # print("Branch:", branch_name)
        # print("Commit message:", commit_message)
        # print("Files changed:", files_changed)
        # print("Risk level:", patch.risk)
        # print("Old snippet:\n", patch.old)
        # print("New snippet:\n", patch.new)
        # print("================\n")

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
    # finally:
    #     run_git(["checkout", original_branch], repo_path)

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