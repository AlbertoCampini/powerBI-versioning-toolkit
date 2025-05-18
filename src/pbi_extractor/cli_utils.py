# src/pbi_extractor/cli_utils.py

"""Command Line Interface (CLI) utility functions."""

import subprocess
import sys
from pathlib import Path
from typing import List, Any, Dict

from .logger_setup import get_logger
# Import get_config after it's defined and loaded to avoid circular dependency issues at import time
# from .config_manager import get_config 

logger = get_logger(__name__)

def run_command(cmd: List[str | Path], verbose: bool | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Runs an external command and handles output/errors.

    Args:
        cmd (List[str  |  Path]): The command and its arguments.
        verbose (bool | None): If True, prints stdout/stderr. If None, uses verbose from config.
        cwd (Path | None): The working directory for the command. Defaults to None (current directory).

    Returns:
        subprocess.CompletedProcess[str]: The result of the command execution.

    Raises:
        subprocess.CalledProcessError: If the command returns a non-zero exit code.
        FileNotFoundError: If the command executable is not found.
    """
    # This import is deferred to runtime to ensure config is loaded.
    from .config_manager import get_config
    config = get_config()

    if verbose is None:
        verbose = config.get("verbose", False)

    cmd_str_list = [str(c) for c in cmd]
    logger.info(f"Executing command: {' '.join(cmd_str_list)}")

    try:
        # Using text=True (universal_newlines=True) and specifying encoding
        proc = subprocess.run(
            cmd_str_list,
            text=True,
            check=True, # Raises CalledProcessError for non-zero exit codes
            capture_output=True, # Captures stdout and stderr
            encoding='utf-8', # Specify encoding for text mode
            cwd=cwd # Pass the working directory
        )
        if proc.stdout and verbose:
            logger.debug(f"Command stdout: {proc.stdout.strip()}")
        if proc.stderr and verbose: # Stderr might contain warnings even on success
            logger.debug(f"Command stderr: {proc.stderr.strip()}")
        return proc
    except subprocess.CalledProcessError as e:
        logger.error(f"Error during command execution: {' '.join(cmd_str_list)}")
        logger.error(f"Return code: {e.returncode}")
        if e.stdout:
            logger.error(f"Stdout: {e.stdout.strip()}")
        if e.stderr:
            logger.error(f"Stderr: {e.stderr.strip()}")
        raise
    except FileNotFoundError:
        logger.error(f"Error: The command '{cmd_str_list[0]}' was not found. Ensure it is installed and in the PATH.")
        raise