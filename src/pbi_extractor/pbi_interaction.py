# src/pbi_extractor/pbi_interaction.py

"""Handles interactions with Power BI Desktop, such as finding sessions and extracting models."""

import json
from pathlib import Path
from typing import Dict, List

from .cli_utils import run_command
from .logger_setup import get_logger
from .config_manager import get_config

logger = get_logger(__name__)

def get_first_pbi_session() -> Dict[str, str]:
    """Returns pbix_path and pid of the first open Power BI Desktop session.

    Returns:
        Dict[str, str]: A dictionary containing 'pbix_path' and 'pid'.

    Raises:
        RuntimeError: If pbi-tools info doesn't return JSON or no session is found.
    """
    config = get_config()
    pbi_tools_exe = config["pbi_tools_exe"]
    verbose = config.get("verbose", False)

    logger.info("Searching for Power BI Desktop session…")
    try:
        proc = run_command([pbi_tools_exe, "info"], verbose=verbose)
    except Exception as e:
        logger.error(f"Failed to execute pbi-tools info: {e}")
        raise RuntimeError("Failed to get Power BI session info from pbi-tools.") from e

    raw_output = proc.stdout
    json_start_index = raw_output.find("{")

    if json_start_index < 0:
        logger.error("No JSON found in pbi-tools info output.")
        logger.debug(f"pbi-tools info raw output:\n{raw_output}")
        raise RuntimeError("No JSON found in pbi-tools info output.")

    try:
        info = json.loads(raw_output[json_start_index:])
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON from pbi-tools info: {e}")
        logger.debug(f"pbi-tools info raw output (from json_start_index):\n{raw_output[json_start_index:]}")
        raise RuntimeError("Failed to parse JSON from pbi-tools info.") from e

    sessions = info.get("pbiSessions", [])
    if not sessions:
        logger.warning("No open Power BI Desktop session found by pbi-tools.")
        raise RuntimeError("No open Power BI Desktop session found.")

    # TODO: Manage multiple sessions
    if len(sessions) > 1:
        logger.warning(f"Multiple Power BI sessions found. Using the first one: {sessions[0]}")

    session = sessions[0] # Assuming the first session is the target
    pbix_path = session.get("PbixPath")
    pid = str(session.get("ProcessId"))

    if not pbix_path or not pid:
        logger.error(f"Found session but PbixPath or ProcessId is missing: {session}")
        raise RuntimeError("Found Power BI session but essential details (PbixPath, ProcessId) are missing.")

    logger.info(f"Power BI session found: PBIX='{pbix_path}', PID={pid}")
    return {"pbix_path": pbix_path, "pid": pid}

def extract_model_from_session(session_info: Dict[str, str], extract_folder: Path) -> Path:
    """Extracts the model from the given PBIX session to the specified folder.

    Args:
        session_info (Dict[str, str]): Dictionary with 'pbix_path' and 'pid'.
        extract_folder (Path): The folder where the model will be extracted.

    Returns:
        Path: The path to the extracted 'database.json' file.

    Raises:
        FileNotFoundError: If 'database.json' is not found after extraction.
        RuntimeError: If the extraction command fails.
    """
    config = get_config()
    pbi_tools_exe = config["pbi_tools_exe"]
    extract_mode = config["extract_mode"]
    model_serialization = config["model_serialization"]
    mashup_serialization = config["mashup_serialization"]
    verbose = config.get("verbose", False)

    pbix_path = session_info["pbix_path"]
    pid = session_info["pid"]

    logger.info(f"Starting model extraction for PBIX: {pbix_path} (PID: {pid}) into {extract_folder}")

    # Ensure extract_folder exists
    extract_folder.mkdir(parents=True, exist_ok=True)

    cmd: List[str | Path] = [
        pbi_tools_exe, "extract", pbix_path, pid,
        "-extractFolder", str(extract_folder),
        "-mode", extract_mode,
        "-modelSerialization", model_serialization,
        "-mashupSerialization", mashup_serialization,
    ]

    try:
        run_command(cmd, verbose=verbose)
    except Exception as e:
        logger.error(f"Model extraction failed: {e}")
        raise RuntimeError("Model extraction command failed.") from e

    # Standard path for the model file after pbi-tools extraction
    model_file_path = extract_folder / "Model" / "database.json"

    if not model_file_path.exists():
        logger.error(f"Extracted model file 'database.json' not found at {model_file_path}")
        raise FileNotFoundError(f"Extracted model file 'database.json' not found at {model_file_path}")

    logger.info(f"Model successfully extracted to {model_file_path}")
    return model_file_path