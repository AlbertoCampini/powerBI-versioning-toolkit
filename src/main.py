# src/main.py

"""Main script to run the Power BI model extraction, diffing, and versioning process."""

import sys
from pathlib import Path
from datetime import datetime
import shutil # For copying database.json as old model

# Ensure the src directory is in the Python path for module resolution
# This is often handled by how you run the script (e.g., python -m src.main)
# or by setting PYTHONPATH. For direct execution (python src/main.py),
# this explicit addition might be needed if 'src' is not the CWD.
SCRIPT_DIR_MAIN = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR_MAIN.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SCRIPT_DIR_MAIN) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR_MAIN))

from pbi_extractor.config_manager import load_app_config, get_config
from pbi_extractor.logger_setup import setup_logging, get_logger
from pbi_extractor.pbi_interaction import get_first_pbi_session, extract_model_from_session
from pbi_extractor.metadata_parser import load_model_from_json, collect_metadata_from_model
from pbi_extractor.diff_engine import diff_models
from pbi_extractor.file_exporters import (
    export_metadata_to_csv,
    export_metadata_to_excel,
    save_diff_to_json,
    save_diff_to_markdown,
    save_mermaid_er_diagram,
    save_database_json_copy,
    create_pbix_zip_archive
)
from pbi_extractor.changelog_manager import update_changelog_file
from pbi_extractor.git_manager import (
    initialize_git_repository_if_needed,
    configure_git_remote,
    stage_and_commit_changes,
    push_changes_to_remote,
    get_git_target_dir,
    git_pull_latest
)

# Initialize logger for this main script
# Logging setup will be done after config is loaded

def main_workflow():
    """Orchestrates the entire PBI model extraction and processing workflow."""
    # 1. Load Configuration
    print("ℹ️ Phase 1 Loading configuration...", end=" ")
    # Assuming config.yaml is in the project root (parent of src)
    config_file_path = PROJECT_ROOT / "config.yaml"
    try:
        loaded_config = load_app_config(config_file_path)
        # Update script_dir in config to be the actual project root for consistency
        loaded_config['script_dir'] = PROJECT_ROOT
    except FileNotFoundError as e:
        # Fallback logger if config fails before full setup
        print(f"ERROR: Configuration file not found at {config_file_path}. Exiting. Details: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Failed to load configuration. Exiting. Details: {e}", file=sys.stderr)
        sys.exit(1)

    config = get_config() # Get the globally accessible config
    print("✅ Phase 1 Complete")

    # 2. Setup Logging (now that config is loaded)
    print("ℹ️ Phase 2 Setting up logging...", end =" ")
    log_level = config.get("log_level", False)
    # Define a log file path, e.g., in the base_output_root or a dedicated logs folder
    log_file_path = config["base_output_root"] / "logs" / f"pbi_extractor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    try:
        setup_logging(log_level=log_level, log_file=log_file_path)
    except Exception as e:
        print(f"ERROR: Failed to setup logging. Exiting. Details: {e}", file=sys.stderr)
        # Continue without file logging if it fails, console logging should still work if StreamHandler was added.
        # Or exit if file logging is critical.

    logger = get_logger(__name__) # Now get the properly configured logger
    logger.info("Application started. Configuration and logging initialized.")
    logger.debug(f"Full configuration: {config}")

    # --- Git Pre-operations (if enabled and target dir is BASE_OUTPUT_ROOT) ---
    git_repo_path = get_git_target_dir() # This is usually the custom_output_root or BASE_OUTPUT_ROOT
    if not git_repo_path: # If git_target_dir is None (not custom_output_root), use base_output_root
        git_repo_path = config["base_output_root"]
    
    git_enabled = config.get("git_config", {}).get("enabled", False)

    if git_enabled:
        logger.info(f"Git operations enabled. Target directory: {git_repo_path}")
        if not initialize_git_repository_if_needed(git_repo_path):
            logger.error("Failed to initialize Git repository. Git operations might fail.")
            # Decide if to continue or exit
        if not configure_git_remote(git_repo_path):
            logger.warning("Failed to configure Git remote. Pushing may not work.")
    else:
        logger.info("Git operations disabled by configuration.")

    print("✅ Phase 2 Complete")
    # 3. Get Power BI Session
    print("🔍 Phase 3 Getting Power BI session...", end =" ")
    try:
        pbi_session = get_first_pbi_session()
        pbix_file_path = Path(pbi_session["pbix_path"])
        model_name_from_pbix = pbix_file_path.stem
        logger.info(f"Processing PBIX file: {pbix_file_path.name}")
    except RuntimeError as e:
        logger.error(f"Failed to get Power BI session: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"An unexpected error occurred while getting PBI session: {e}", exc_info=True)
        sys.exit(1)

    # Define output directory for the current model based on PBIX name
    # This will be within the BASE_OUTPUT_ROOT
    current_model_output_dir = config["base_output_root"] / model_name_from_pbix
    current_model_output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Output directory for this model: {current_model_output_dir}")

    current_model_output_csv_dir = current_model_output_dir / "csv"
    current_model_output_csv_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Output directory for this model's CSVs: {current_model_output_csv_dir}")

    current_model_output_json_dir = current_model_output_dir / "json"
    current_model_output_json_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Output directory for this model's JSONs: {current_model_output_json_dir}")

    current_model_output_excel_dir = current_model_output_dir / "xlsx"
    current_model_output_excel_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Output directory for this model's Excels: {current_model_output_excel_dir}")
   
 
    # Define paths for old and new model JSONs
    # The "old" model is the database.json from the *previous* run for this PBIX
    old_model_json_path = current_model_output_dir / "database.json" # This becomes the 'old' model for the next run
    # The "new" model will be extracted into a temporary or specific subfolder first
    extraction_target_folder = current_model_output_dir / "_temp_extraction"
    extraction_target_folder.mkdir(parents=True, exist_ok=True)
    print("✅ Phase 3 Complete")

    # 4. Load Old Model (if exists)
    print("⚗️ Phase 4 Loading old model (if exists)...", end=" ")
    old_model_data = None
    if old_model_json_path.exists() and config.get("output_elements", {}).get("save_database_copy", True):
        logger.info(f"Previous model found at: {old_model_json_path}")
        old_model_data = load_model_from_json(old_model_json_path)
        if old_model_data:
            logger.info("Successfully loaded previous model data for comparison.")
        else:
            logger.warning(f"Found previous database.json at {old_model_json_path} but failed to load it. Proceeding without diff.")
    else:
        logger.info(f"No previous model found at {old_model_json_path} or database copy disabled. This will be treated as the first run for diff purposes.")
    print("✅ Phase 4 Complete")

    # 5. Extract New Model
    print("🧪 Phase 5 Extracting new model from PBIX...", end=" ")
    try:
        logger.info(f"Extracting current model from PBIX: {pbix_file_path.name} into {extraction_target_folder}")
        # The extracted database.json will be inside extraction_target_folder/Model/database.json
        extracted_new_model_file_path = extract_model_from_session(pbi_session, extraction_target_folder)
        logger.info(f"New model extracted successfully to: {extracted_new_model_file_path}")
    except FileNotFoundError as e:
        logger.error(f"Extraction failed: database.json not found post-extraction. {e}")
        sys.exit(1)
    except RuntimeError as e:
        logger.error(f"Extraction failed: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"An unexpected error occurred during model extraction: {e}", exc_info=True)
        sys.exit(1)

    # Load the newly extracted model data
    new_model_data = load_model_from_json(extracted_new_model_file_path)
    if not new_model_data:
        logger.error(f"Failed to load the newly extracted model from {extracted_new_model_file_path}. Cannot proceed.")
        # Clean up temp extraction folder if loading fails?
        # shutil.rmtree(extraction_target_folder) 
        sys.exit(1)
    logger.info("Successfully loaded newly extracted model data.")
    print("✅ Phase 5 Complete")

    # 6. Collect Metadata from New Model
    print("🔧 Phase 6 Collecting metadata from new model...", end=" ")
    logger.info("Collecting metadata from the new model...")
    tables_df, fields_df, rels_df = collect_metadata_from_model(new_model_data)
    if tables_df.empty and fields_df.empty and rels_df.empty:
        logger.warning("No metadata (tables, fields, relationships) collected from the new model. Output files might be empty or not generated.")
    else:
        logger.info(f"Metadata collected: {len(tables_df)} tables, {len(fields_df)} fields, {len(rels_df)} relationships.")
    print("✅ Phase 6 Complete")
    
    # 7. Perform Diff (if old model data is available)
    print("🔄 Phase 7 Performing diff (if old model data is available)...", end=" ")
    model_diff_data = None
    if old_model_data and new_model_data:
        logger.info("Performing diff between old and new models...")
        model_diff_data = diff_models(old_model_data, new_model_data)
        if model_diff_data:
            logger.info("Model diff completed.")
            logger.debug(f"Diff results: {model_diff_data}")
        else:
            logger.warning("Diff operation did not return data, though both models were present.")
    elif not old_model_data:
        logger.info("Skipping model diff: No old model data available for comparison.")
    else: # new_model_data must be None if we reach here, which should have exited earlier
        logger.error("Critical error: New model data is not available for diff. This should not happen.")
        sys.exit(1)
    print("✅ Phase 7 Complete")

    # 8. Generate and Save Outputs
    print("💾 Phase 8 Generating and saving outputs...", end=" ")
    # All outputs go into current_model_output_dir
    current_timestamp = datetime.now().strftime(config["granularity_output"])
    logger.info(f"Generating output files for model '{model_name_from_pbix}' with timestamp '{current_timestamp}'...")

    # CSVs
    export_metadata_to_csv(tables_df, fields_df, rels_df, current_model_output_csv_dir, model_name_from_pbix)
    # Excel
    export_metadata_to_excel(tables_df, fields_df, rels_df, current_model_output_excel_dir, model_name_from_pbix, current_timestamp)
    # JSON Diff
    if model_diff_data:
        save_diff_to_json(model_diff_data, current_model_output_json_dir, model_name_from_pbix)
    # Markdown Diff Report
    if model_diff_data:
        save_diff_to_markdown(model_diff_data, current_model_output_dir, model_name_from_pbix)
    # Mermaid ER Diagram
    save_mermaid_er_diagram(tables_df, rels_df, current_model_output_dir, model_name_from_pbix)
    
    # Changelog (specific to this model)
    # The changelog path should be per model, e.g., current_model_output_dir/changelog.md
    model_changelog_path = current_model_output_dir / "CHANGELOG.md"
    update_changelog_file(model_changelog_path, model_name_from_pbix, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), model_diff_data)

    # Save a copy of the PBIX file (zipped)
    create_pbix_zip_archive(pbix_file_path, current_model_output_dir, model_name_from_pbix, current_timestamp)

    # Save a copy of the new database.json for the *next* run (becomes the 'old' model)
    # This should be the *final* step for database.json handling for the current run.
    # The new database.json (which was in _temp_extraction/Model/database.json)
    # needs to be copied to current_model_output_dir/database.json
    final_database_json_path_for_run = current_model_output_dir / "database.json"
    try:
        shutil.copy2(extracted_new_model_file_path, final_database_json_path_for_run)
        logger.info(f"Updated current model state to {final_database_json_path_for_run} for next run.")
    except Exception as e:
        logger.error(f"Failed to copy new database.json to output directory: {e}")

    # Also save a timestamped copy if configured
    save_database_json_copy(final_database_json_path_for_run, current_model_output_json_dir, model_name_from_pbix, current_timestamp)

    # Clean up the temporary extraction folder
    try:
        shutil.rmtree(extraction_target_folder)
        logger.info(f"Cleaned up temporary extraction folder: {extraction_target_folder}")
    except Exception as e:
        logger.warning(f"Could not clean up temporary extraction folder {extraction_target_folder}: {e}")
    print("✅ Phase 8 Complete")

    # --- Git Post-operations (Commit and Push) ---
    if git_enabled:
        print("🚀 Phase 9 GIT operations...",end=" ")
        logger.info(f"Performing Git post-operations for repository: {git_repo_path}")
        # Ensure we are in the correct directory for Git operations if git_repo_path is different from PROJECT_ROOT
        # The _run_git_command_wrapper already takes working_dir
        
        commit_prefix = config.get("git_config", {}).get("commit_prefix", "[AUTO] PBI model update")
        commit_msg = f"{commit_prefix}: {model_name_from_pbix} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        # Before committing, ensure the .git directory is at git_repo_path, not inside model_name_from_pbix subdir
        # This means all changes *within* git_repo_path (including the new model_name_from_pbix folder) will be committed.
        if stage_and_commit_changes(git_repo_path, commit_msg):
            logger.info("Changes staged and committed successfully.")
            if push_changes_to_remote(git_repo_path):
                logger.info("Changes pushed to remote successfully.")
            else:
                logger.warning("Failed to push changes to remote. Commit was local.")
        else:
            logger.info("No changes were staged or committed (either no changes or commit failed).")
        print("✅ Phase 9 Complete")

    logger.info(f"Workflow completed for PBIX: {pbix_file_path.name}")
    print("✅ All operations completed successfully.")
    print("💤 Bye Bye!")

if __name__ == "__main__":
    try:
        main_workflow()
    except SystemExit: # Allow sys.exit() to terminate cleanly
        pass
    except Exception as e:
        # Catch-all for unexpected errors in the main_workflow if not handled internally
        # A more specific logger might be needed if setup_logging hasn't run
        logger_fallback = get_logger(__name__) # Try to get it, might not be fully configured
        if logger_fallback and logger_fallback.hasHandlers():
            logger_fallback.critical(f"An unhandled exception occurred in the main workflow: {e}", exc_info=True)
        else:
            print(f"CRITICAL UNHANDLED ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        logger_final = get_logger(__name__)
        if logger_final and logger_final.hasHandlers():
            logger_final.info("Application shutting down.")
        else:
            print("Application shutting down.", file=sys.stderr)