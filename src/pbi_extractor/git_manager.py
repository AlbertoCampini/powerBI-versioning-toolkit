# src/pbi_extractor/git_manager.py

"""Manages Git operations like initializing, committing, and pushing changes."""

import subprocess
from pathlib import Path
from typing import List

from .logger_setup import get_logger
from .config_manager import get_config
from .cli_utils import run_command 

logger = get_logger(__name__)

def _run_git_command_wrapper(git_args: List[str], working_dir: Path, suppress_errors: bool = False) -> subprocess.CompletedProcess[str] | None:
    """Wraps run_command for Git, handling token masking and specific Git errors."""
    config = get_config()
    git_token = config.get("git_token")
    verbose = config.get("verbose", False)

    cmd = ["git"] + git_args

    # Mask the token in the command arguments for logging if it's part of a URL
    logged_cmd_display_parts = []
    for arg in cmd:
        if git_token and git_token in arg and ("http://" in arg or "https://" in arg) and "@" in arg:
            try:
                protocol, rest_with_creds = arg.split("://", 1)
                creds_part, host_and_path = rest_with_creds.split("@", 1)
                user_part, token_part_in_url = creds_part.split(":", 1)
                if token_part_in_url == git_token:
                    logged_cmd_display_parts.append(f"{protocol}://{user_part}:<TOKEN_HIDDEN>@{host_and_path}")
                else:
                    logged_cmd_display_parts.append(arg) # Different token or unexpected format
            except ValueError:
                # Fallback if URL parsing fails, less precise masking
                logged_cmd_display_parts.append(arg.replace(git_token, "<TOKEN_HIDDEN>"))
        else:
            logged_cmd_display_parts.append(arg)
    
    # Log the command with token masked
    logger.info(f"Executing Git command: {' '.join(logged_cmd_display_parts)} in {working_dir}")

    try:
        # Use the generic run_command from cli_utils
        # Note: run_command already logs the command, so the above logging is for the masked version.
        # We might want to prevent run_command from logging if we log here, or make its logging DEBUG level.
        # For now, both will log, one masked, one not (if verbose in run_command is True).
        proc = run_command(cmd, verbose=verbose, cwd=working_dir) # run_command uses its own verbose logic from config
        return proc
    except subprocess.CalledProcessError as e:
        logger.error(f"Git command failed: {' '.join(cmd)}")
        logger.error(f"Git error: {e.stderr}")
        if not suppress_errors:
            raise
        return None # Or return the error object e if preferred
    except FileNotFoundError:
        logger.error("Git command not found. Ensure Git is installed and in PATH.")
        if not suppress_errors:
            raise
        return None

def initialize_git_repository_if_needed(repo_path: Path) -> bool:
    """Initializes a Git repository if .git directory doesn't exist."""
    config = get_config()
    git_config = config.get("git_config", {})
    if not git_config.get("enabled", False):
        logger.info("Git operations are disabled in configuration.")
        return False

    if not repo_path.is_dir():
        logger.info(f"Creating Git repository directory: {repo_path}")
        repo_path.mkdir(parents=True, exist_ok=True)

    dot_git_path = repo_path / ".git"
    if not dot_git_path.exists():
        logger.info(f"Initializing Git repository in {repo_path}...")
        _run_git_command_wrapper(["init"], working_dir=repo_path)
        logger.info("Git repository initialized.")
        return True
    else:
        logger.info(f"Git repository already exists in {repo_path}.")
        return True

def configure_git_remote(repo_path: Path) -> bool:
    """Configures the Git remote repository if not already configured or if URL mismatches."""
    config = get_config()
    git_config = config.get("git_config", {})
    git_token = config.get("git_token")
    git_username = config.get("git_username")

    if not git_config.get("enabled", False):
        return False

    remote_name = git_config.get("remote_name", "origin")
    remote_url = git_config.get("remote_url", "").strip()

    if not remote_url:
        logger.warning("Git remote URL is not configured. Skipping remote setup.")
        return False

    # Construct URL with credentials if available
    if git_username and git_token and remote_url.startswith("https://"):
        protocol, rest_of_url = remote_url.split("://", 1)
        credentialed_url = f"{protocol}://{git_username}:{git_token}@{rest_of_url}"
    else:
        credentialed_url = remote_url

    try:
        # Check if remote exists and what its URL is
        result = _run_git_command_wrapper(["remote", "get-url", remote_name], working_dir=repo_path, suppress_errors=True)
        current_url = result.stdout.strip() if result and result.returncode == 0 else None

        if current_url == credentialed_url or current_url == remote_url: # Check against both, as get-url might not show token
            logger.info(f"Git remote '{remote_name}' is already configured correctly to '{remote_url}'.")
            git_pull_latest(repo_path)  # Pull latest changes
            return True
        elif current_url:
            logger.info(f"Git remote '{remote_name}' URL mismatch. Current: '{current_url}', Desired: '{remote_url}'. Updating...")
            _run_git_command_wrapper(["remote", "set-url", remote_name, credentialed_url], working_dir=repo_path)
        else:
            logger.info(f"Git remote '{remote_name}' not found. Adding remote with URL: {remote_url}")
            _run_git_command_wrapper(["remote", "add", remote_name, credentialed_url], working_dir=repo_path)
        
        logger.info(f"Git remote '{remote_name}' configured to '{remote_url}'.")
        git_pull_latest(repo_path)  # Pull latest changes
        return True
    except Exception as e:
        logger.error(f"Failed to configure Git remote '{remote_name}': {e}")
        return False

def stage_and_commit_changes(repo_path: Path, commit_message: str) -> bool:
    """Stages all changes and commits them."""
    config = get_config()
    git_config = config.get("git_config", {})
    if not git_config.get("enabled", False):
        return False

    # Check if the repo_path is a valid Git repository
    dot_git_path = repo_path / ".git"
    if not dot_git_path.is_dir(): # .git should be a directory
        logger.error(f"Error: {repo_path} is not a Git repository. Missing .git directory. Please initialize it first.")
        return False

    logger.info(f"Staging all changes in {repo_path}...")
    _run_git_command_wrapper(["add", "-A"], working_dir=repo_path)

    # Check if there are changes to commit
    status_result = _run_git_command_wrapper(["status", "--porcelain"], working_dir=repo_path)
    if not status_result or not status_result.stdout.strip():
        logger.info("No changes to commit.")
        return False # Or True, depending on whether "no changes" is a success

    logger.info(f"Committing changes with message: '{commit_message}'...")
    _run_git_command_wrapper(["commit", "-m", commit_message], working_dir=repo_path)
    logger.info("Changes committed.")
    return True

def push_changes_to_remote(repo_path: Path) -> bool:
    """Pushes committed changes to the configured remote and branch."""
    config = get_config()
    git_config = config.get("git_config", {})
    if not git_config.get("enabled", False) or not git_config.get("remote_url", "").strip():
        logger.info("Git push is disabled or remote URL not configured.")
        return False

    remote_name = git_config.get("remote_name", "origin")
    branch_name = git_config.get("branch", "main")

    logger.info(f"Pushing changes to remote '{remote_name}' branch '{branch_name}'...")
    try:
        # Check current branch
        current_branch_proc = _run_git_command_wrapper(["rev-parse", "--abbrev-ref", "HEAD"], working_dir=repo_path)
        if not current_branch_proc or current_branch_proc.stdout.strip() != branch_name:
            logger.info(f"Current branch is '{current_branch_proc.stdout.strip() if current_branch_proc else 'unknown'}'. Checking out '{branch_name}'...")
            # Check if branch exists locally, if not, try to track remote
            try:
                _run_git_command_wrapper(["checkout", branch_name], working_dir=repo_path, suppress_errors=True)
            except subprocess.CalledProcessError:
                logger.info(f"Local branch '{branch_name}' not found. Attempting to create and track from remote '{remote_name}/{branch_name}'.")
                _run_git_command_wrapper(["checkout", "-b", branch_name, f"{remote_name}/{branch_name}"], working_dir=repo_path, suppress_errors=True)
                # If that fails (e.g. remote branch doesn't exist), it will be caught by the push command later.

        _run_git_command_wrapper(["push", "-u", remote_name, branch_name], working_dir=repo_path)
        logger.info("Changes pushed to remote successfully.")
        return True
    except Exception as e:
        logger.error(f"Failed to push changes to remote: {e}")
        return False

def git_pull_latest(repo_path: Path) -> bool:
    """Pulls the latest changes from the configured remote and branch."""
    config = get_config()
    git_config = config.get("git_config", {})
    if not git_config.get("enabled", False) or not git_config.get("remote_url", "").strip():
        logger.info("Git pull is disabled or remote URL not configured.")
        return False

    remote_name = git_config.get("remote_name", "origin")
    branch_name = git_config.get("branch", "main")

    logger.info(f"Pulling latest changes from remote '{remote_name}' branch '{branch_name}' into {repo_path}...")
    try:
        _run_git_command_wrapper(["pull", remote_name, branch_name], working_dir=repo_path)
        logger.info("Successfully pulled latest changes.")
        return True
    except Exception as e:
        logger.error(f"Failed to pull latest changes: {e}")
        return False


def get_git_target_dir() -> Path | None:
    """Returns the configured Git target directory."""
    config = get_config()
    return config.get("git_target_dir")