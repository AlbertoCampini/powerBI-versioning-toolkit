# src/pbi_extractor/changelog_manager.py

"""Manages the creation and updating of changelog files."""

from pathlib import Path
from typing import Any, Dict, List

from .logger_setup import get_logger
from .config_manager import get_config
from .file_exporters import generate_diff_markdown # Assuming this can be used for changelog entry

logger = get_logger(__name__)

def update_changelog_file(changelog_path: Path, model_name: str, current_datetime_str: str, diff_data: Dict[str, List[Any]] | None) -> None:
    """Creates or updates the changelog.md file for the model.

    Args:
        changelog_path (Path): The path to the changelog.md file.
        model_name (str): The name of the Power BI model.
        current_datetime_str (str): The current date and time as a string for the entry.
        diff_data (Dict[str, List[Any]] | None): The diff dictionary. If None, indicates no diff was performed or available.
    """
    config = get_config()
    if not config.get("output_elements", {}).get("save_changelog", True):
        logger.info(f"Changelog update is disabled in configuration for {model_name}.")
        return

    logger.info(f"Updating changelog for {model_name} at {changelog_path}...")

    # 1. Prepare the new entry content block
    new_entry_parts: List[str] = []
    new_entry_parts.append(f"## Updated Version at {current_datetime_str}\n")
    # new_entry_parts.append("### Datamodel\n") # This seems redundant if changes are listed below

    if diff_data:
        # Generate diff markdown without the main "# Model Diff Report" header
        diff_md_for_changelog = generate_diff_markdown(diff_data, include_header=False)
        
        if diff_md_for_changelog.strip() and "No changes detected" not in diff_md_for_changelog:
            new_entry_parts.append("### Changes Summary\n")
            new_entry_parts.append(diff_md_for_changelog)
            # Ensure diff_md_for_changelog ends with a blank line for separation
            if not diff_md_for_changelog.endswith("\n\n"):
                if diff_md_for_changelog.endswith("\n"):
                    new_entry_parts.append("\n")
                else:
                    new_entry_parts.append("\n\n")
        else:
            new_entry_parts.append("No significant changes detected in the schema compared to the previous version.\n\n")
    else:
        new_entry_parts.append("Initial version or no comparison data available.\n\n")
    
    new_entry_content = "".join(new_entry_parts)

    # 2. Define the static header for the current model's changelog
    # This header will be at the top of the specific model's changelog file.
    changelog_file_header = (
        f"# 🛠 Changelog - {model_name}\n\n"
        "This changelog tracks changes to the Power BI model schema. "
        "Each entry below summarizes additions and removals of tables, fields, "
        "and relationships as of the timestamped update.\n\n"
    )

    try:
        changelog_path.parent.mkdir(parents=True, exist_ok=True)

        if not changelog_path.exists():
            # For a new file, it's the model-specific header + first entry
            final_content_to_write = changelog_file_header + new_entry_content
            changelog_path.write_text(final_content_to_write, encoding="utf-8")
            logger.info(f"Changelog created for {model_name} with the first entry.")
        else:
            existing_full_content = changelog_path.read_text(encoding="utf-8")
            existing_lines = existing_full_content.splitlines(keepends=True)
            
            # Find where the actual entries start (after the main header)
            first_entry_marker_line_index = -1
            for i, line_content in enumerate(existing_lines):
                if line_content.startswith("## Updated Version at"):
                    first_entry_marker_line_index = i
                    break
            
            current_file_header_part = ""
            previous_entries_part = ""

            if first_entry_marker_line_index != -1:
                # Existing entries found. Content before this is the file's current header.
                current_file_header_part = "".join(existing_lines[:first_entry_marker_line_index])
                previous_entries_part = "".join(existing_lines[first_entry_marker_line_index:])
                
                # Ensure the identified header part is well-formed or use the canonical one if it's empty/whitespace.
                if not current_file_header_part.strip(): 
                     current_file_header_part = changelog_file_header
                elif not current_file_header_part.endswith("\n\n"): # Ensure it ends with a double newline
                    current_file_header_part = current_file_header_part.rstrip() + "\n\n"
            else:
                # No "## Updated Version at" lines found. File might be header-only, empty, or malformed.
                current_file_header_part = existing_full_content
                if not current_file_header_part.strip(): # If existing file is effectively empty
                    current_file_header_part = changelog_file_header 
                else: # Presumed to be a header. Ensure it ends with \n\n.
                    if not current_file_header_part.endswith("\n\n"):
                        current_file_header_part = current_file_header_part.rstrip() + "\n\n"
                # previous_entries_part remains empty as no old entries were identified by marker
            
            # Prepend the new entry before previous entries
            final_content_to_write = current_file_header_part + new_entry_content + previous_entries_part
            changelog_path.write_text(final_content_to_write, encoding="utf-8")
            logger.info(f"Changelog updated for {model_name}.")

    except Exception as e:
        logger.error(f"Failed to update changelog {changelog_path} for model {model_name}: {e}")