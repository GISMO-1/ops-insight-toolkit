"""Tool Builder Updater: check GitHub for newer commits and assist with git pull.

README
Purpose: Query GitHub for the latest commit and compare against a local version file to suggest updates.
Inputs/Outputs: Inputs are repo paths and version files; outputs are UpdateCheckResult summaries and git pull status.
Example command: python -m tools.tool_updater --self-check
Self-check: python -m tools.tool_updater --self-check
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


REQUESTS_AVAILABLE = importlib.util.find_spec("requests") is not None
if REQUESTS_AVAILABLE:
    import requests
else:  # pragma: no cover - exercised when requests isn't installed
    requests = None


@dataclass
class UpdateCheckResult:
    status: str
    message: str
    latest_commit: str | None = None
    current_commit: str | None = None
    repo: str | None = None


def default_version_path() -> Path:
    return Path(__file__).resolve().parent / "tool_builder_version.json"


def parse_github_repo(remote_url: str) -> tuple[str, str] | None:
    normalized = remote_url.strip()
    if normalized.startswith("git@github.com:"):
        normalized = normalized.replace("git@github.com:", "https://github.com/")
    if normalized.startswith("https://github.com/"):
        normalized = normalized.removesuffix(".git")
        parts = normalized.split("/")
        if len(parts) >= 5:
            return parts[3], parts[4]
    return None


def get_git_remote(repo_path: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "config", "--get", "remote.origin.url"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def get_git_head(repo_path: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def read_version_file(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    commit = payload.get("commit")
    return commit if isinstance(commit, str) and commit else None


def write_version_file(path: Path, commit: str) -> None:
    path.write_text(json.dumps({"commit": commit}, indent=2), encoding="utf-8")


def fetch_latest_commit(owner: str, repo: str, timeout: float = 5.0) -> tuple[str | None, str | None]:
    if not REQUESTS_AVAILABLE or requests is None:
        return None, "Python package 'requests' is not installed."
    url = f"https://api.github.com/repos/{owner}/{repo}/commits?per_page=1"
    try:
        response = requests.get(url, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - surface network errors
        return None, f"Network error: {exc}"
    if response.status_code != 200:
        return None, f"GitHub API error: {response.status_code}"
    data = response.json()
    if not data:
        return None, "No commits returned from GitHub."
    return data[0].get("sha"), None


def check_for_updates(repo_path: Path, version_path: Path) -> UpdateCheckResult:
    remote_url = get_git_remote(repo_path)
    if not remote_url:
        return UpdateCheckResult(status="unavailable", message="No git remote found.")
    repo_info = parse_github_repo(remote_url)
    if not repo_info:
        return UpdateCheckResult(status="unavailable", message="Remote is not a GitHub repository.")
    owner, repo = repo_info
    latest_commit, error = fetch_latest_commit(owner, repo)
    if error:
        return UpdateCheckResult(status="error", message=error, repo=f"{owner}/{repo}")
    if not latest_commit:
        return UpdateCheckResult(status="error", message="Latest commit could not be determined.", repo=f"{owner}/{repo}")
    current_commit = read_version_file(version_path)
    if not current_commit:
        current_commit = get_git_head(repo_path)
        if current_commit:
            write_version_file(version_path, current_commit)
    if not current_commit:
        return UpdateCheckResult(
            status="error",
            message="Local version could not be determined.",
            latest_commit=latest_commit,
            repo=f"{owner}/{repo}",
        )
    if latest_commit == current_commit:
        return UpdateCheckResult(
            status="up_to_date",
            message="Tool Builder is up to date.",
            latest_commit=latest_commit,
            current_commit=current_commit,
            repo=f"{owner}/{repo}",
        )
    return UpdateCheckResult(
        status="update_available",
        message="New version available.",
        latest_commit=latest_commit,
        current_commit=current_commit,
        repo=f"{owner}/{repo}",
    )


def run_git_pull(repo_path: Path, version_path: Path) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "pull"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return False, f"Unable to run git pull: {exc}"
    if result.returncode != 0:
        stderr = result.stderr.strip() or "git pull failed."
        return False, stderr
    new_commit = get_git_head(repo_path)
    if new_commit:
        write_version_file(version_path, new_commit)
    return True, result.stdout.strip() or "git pull completed."


def self_check() -> tuple[bool, str]:
    sample = parse_github_repo("https://github.com/openai/sample-repo.git")
    if sample != ("openai", "sample-repo"):
        return False, "Repo URL parsing failed."
    temp_path = Path(".tool_builder_version_test.json")
    try:
        write_version_file(temp_path, "abc123")
        if read_version_file(temp_path) != "abc123":
            return False, "Version file round-trip failed."
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return True, "Tool updater self-check passed."


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tool Builder update utilities.")
    parser.add_argument("--self-check", action="store_true", help="Run a quick updater self-check")
    return parser


def main(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv[1:])
    if args.self_check:
        ok, message = self_check()
        print(message)
        return 0 if ok else 1
    print("Run with --self-check for a quick validation.")
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv))
