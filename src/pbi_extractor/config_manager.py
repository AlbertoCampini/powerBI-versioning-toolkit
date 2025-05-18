# src/pbi_extractor/config_manager.py

"""Manages configuration loading from YAML and .env files."""

import os
from pathlib import Path
import yaml
from dotenv import load_dotenv
from typing import Any, Dict, List, Set, Tuple

# Global config dictionary, to be loaded by load_app_config
APP_CONFIG = {}

def load_app_config(config_path: Path = Path("config.yaml")) -> Dict[str, Any]:
    """Loads configuration from config.yaml and .env, then populates APP_CONFIG."""
    global APP_CONFIG

    # Load .env first to make environment variables available for config.yaml if needed
    load_dotenv()

    if not config_path.is_file():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        config_from_yaml = yaml.safe_load(f)

    # SCRIPT_DIR will be set in the main script or a higher-level module
    # For now, assume it's the parent of the config_path's parent if not otherwise defined
    # This part might need adjustment based on final structure
    script_dir = config_path.resolve().parent
    # Output root management
    custom_root_path_str = config_from_yaml.get("paths", {}).get("custom_output_root", "").strip()
    base_output_root = Path(custom_root_path_str) if custom_root_path_str else script_dir / "out"
    git_target_dir = Path(custom_root_path_str) if custom_root_path_str else None

    APP_CONFIG = {
        "script_dir": script_dir,
        "base_output_root": base_output_root,
        "git_target_dir": git_target_dir,
        "pbi_tools_exe": Path(config_from_yaml.get("paths", {}).get("pbi_tools_exe", "pbi-tools.exe")),
        "extract_mode": config_from_yaml.get("options", {}).get("extract_mode", "Auto"),
        "model_serialization": config_from_yaml.get("options", {}).get("model_serialization", "Raw"),
        "mashup_serialization": config_from_yaml.get("options", {}).get("mashup_serialization", "Default"),
        "verbose": config_from_yaml.get("options", {}).get("verbose", False),
        "output_elements": config_from_yaml.get("output_elements", {}),
        "git_config": config_from_yaml.get("git", {}),
        "granularity_output": config_from_yaml.get("output_elements", {}).get("granularity_output", "%Y%m%d_%H%M%S"),
        "git_username": os.getenv("GIT_USERNAME"),
        "git_token": os.getenv("GIT_TOKEN"),
    }

    # Default values for output_elements if not specified
    default_output_elements = {
        "save_csv": True,
        "save_excel": True,
        "save_json_diff": True,
        "save_markdown_diff": True,
        "save_mermaid_er": True,
        "save_changelog": True,
        "save_database_copy": True,
        "save_pbix_zip": False,
    }
    for key, default_value in default_output_elements.items():
        APP_CONFIG["output_elements"].setdefault(key, default_value)

    # Default values for git_config if not specified
    default_git_config = {
        "enabled": False,
        "remote_url": "",
        "branch": "main",
        "commit_prefix": "[AUTO] PBI model update",
        "remote_name": "origin",
    }
    for key, default_value in default_git_config.items():
        APP_CONFIG["git_config"].setdefault(key, default_value)

    return APP_CONFIG

def get_config() -> Dict[str, Any]:
    """Returns the loaded application configuration."""
    if not APP_CONFIG:
        # Attempt to load with default path if not already loaded.
        # This might be called before explicit loading in some contexts (e.g. module import)
        # Consider if this implicit loading is desired or if an error should be raised.
        # For now, let's assume the main script will call load_app_config().
        raise RuntimeError("Configuration has not been loaded. Call load_app_config() first.")
    return APP_CONFIG