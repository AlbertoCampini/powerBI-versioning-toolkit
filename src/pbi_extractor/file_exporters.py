# src/pbi_extractor/file_exporters.py

"""Handles the generation and saving of various output files (CSV, Excel, JSON, Markdown, Mermaid)."""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd
# import xlsxwriter # xlsxwriter will be used by pandas ExcelWriter if installed

from .logger_setup import get_logger
from .config_manager import get_config

logger = get_logger(__name__)


def export_metadata_to_csv(tables_df: pd.DataFrame, fields_df: pd.DataFrame, rels_df: pd.DataFrame, output_dir: Path, model_name: str) -> None:
    """Exports metadata DataFrames to CSV files in the specified directory."""
    config = get_config()
    if not config.get("output_elements", {}).get("save_csv", True):
        logger.info("CSV export is disabled in configuration.")
        return

    logger.info(f"Exporting metadata to CSV files in {output_dir} for model '{model_name}'...")
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        tables_df.to_csv(output_dir / f"{model_name}_tables.csv", index=False, encoding='utf-8-sig')
        fields_df.to_csv(output_dir / f"{model_name}_fields.csv", index=False, encoding='utf-8-sig')
        rels_df.to_csv(output_dir / f"{model_name}_relationships.csv", index=False, encoding='utf-8-sig')
        logger.info("CSV files exported successfully.")
    except Exception as e:
        logger.error(f"Failed to export metadata to CSV: {e}")

def export_metadata_to_excel(tables_df: pd.DataFrame, fields_df: pd.DataFrame, rels_df: pd.DataFrame, output_dir: Path, model_name: str, timestamp: str) -> None:
    """Exports metadata to an Excel file with one sheet per table and one for relationships."""
    config = get_config()
    if not config.get("output_elements", {}).get("save_excel", True):
        logger.info("Excel export is disabled in configuration.")
        return

    excel_file_path = output_dir / f"{model_name}_metadata.xlsx"
    logger.info(f"Exporting metadata to Excel file: {excel_file_path}...")
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        with pd.ExcelWriter(excel_file_path, engine='xlsxwriter') as writer:
            # Sheet for relationships
            if not rels_df.empty:
                rels_df.to_excel(writer, sheet_name="Relationships", index=False)
            else:
                logger.info("No relationships data to write to Excel.")

            # Sheet for tables
            if not tabbles_df.empty:
                tabbles_df.to_excel(writer, sheet_name="Tables", index=False)
            else:
                logger.info("No Tables data to write to Excel.")

            # One sheet for each table with its fields
            if not tables_df.empty and not fields_df.empty:
                for table_name in tables_df["table_name"].unique():
                    fields_for_table = fields_df[fields_df["table"] == table_name]
                    # Sanitize sheet name (Excel limit: max 31 chars, no invalid chars)
                    safe_sheet_name = re.sub(r'[\/*?:[\]]', '_', table_name)[:31]
                    if not fields_for_table.empty:
                        fields_for_table.to_excel(writer, sheet_name=safe_sheet_name, index=False)
                    else:
                        logger.debug(f"No fields data for table '{table_name}' to write to Excel.")
            elif tables_df.empty:
                logger.info("No tables data to process for Excel sheets.")
            elif fields_df.empty:
                logger.info("No fields data to process for Excel sheets.")

        logger.info(f"Excel file exported successfully to {excel_file_path}")
    except Exception as e:
        logger.error(f"Failed to export metadata to Excel: {e}")

def save_diff_to_json(diff_data: Dict[str, List[Any]], output_dir: Path, model_name: str) -> None:
    """Saves the model differences to a JSON file."""
    config = get_config()
    if not config.get("output_elements", {}).get("save_json_diff", True):
        logger.info("JSON diff export is disabled in configuration.")
        return

    if diff_data is None:
        logger.warning("No diff data provided to save_diff_to_json. Skipping JSON diff export.")
        return

    json_file_path = output_dir / f"{model_name}_diff.json"
    logger.info(f"Saving model differences to JSON: {json_file_path}...")
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        with open(json_file_path, "w", encoding="utf-8") as f:
            json.dump(diff_data, f, indent=4, ensure_ascii=False)
        logger.info("JSON diff file saved successfully.")
    except Exception as e:
        logger.error(f"Failed to save JSON diff: {e}")

def generate_diff_markdown(diff_data: Dict[str, List[Any]], include_header: bool = True) -> str:
    """Generates a Markdown report from model differences."""
    if diff_data is None:
        logger.warning("No diff data provided to generate_diff_markdown. Returning empty string.")
        return "No differences to report or diff data is unavailable.\n"

    md_parts: List[str] = []
    if include_header:
        md_parts.extend(["# Model Diff Report", ""])

    sections = [
        ("tables", "Tables"),
        ("fields", "Fields (Table, Field)"),
        ("relations", "Relationships (FromTbl, FromCol, ToTbl, ToCol)"),
    ]

    has_content = False
    for key_prefix, title in sections:
        added_items = diff_data.get(f"{key_prefix}_added", [])
        removed_items = diff_data.get(f"{key_prefix}_removed", [])

        if not added_items and not removed_items:
            continue
        has_content = True

        md_parts.extend([f"## {title}", ""])
        md_parts.append("| Added | Removed |")
        md_parts.append("|---|---|")

        max_rows = max(len(added_items), len(removed_items))
        for i in range(max_rows):
            added_item_str = ", ".join(added_items[i]) if i < len(added_items) and isinstance(added_items[i], tuple) else (added_items[i] if i < len(added_items) else "")
            removed_item_str = ", ".join(removed_items[i]) if i < len(removed_items) and isinstance(removed_items[i], tuple) else (removed_items[i] if i < len(removed_items) else "")
            md_parts.append(f"| {'✅ ' + str(added_item_str) if added_item_str else ''} | {'❌ ' + str(removed_item_str) if removed_item_str else ''} |")
        md_parts.append("")

    if not has_content and not include_header:
        return "No changes detected in the schema compared to the previous version.\n"
    elif not has_content and include_header:
        md_parts.append("No structural changes detected between the models.")

    return "\n".join(md_parts)

def save_diff_to_markdown(diff_data: Dict[str, List[Any]], output_dir: Path, model_name: str) -> None:
    """Saves the model differences to a Markdown file."""
    config = get_config()
    if not config.get("output_elements", {}).get("save_markdown_diff", True):
        logger.info("Markdown diff export is disabled in configuration.")
        return

    if diff_data is None:
        logger.warning("No diff data provided to save_diff_to_markdown. Skipping Markdown diff export.")
        return

    md_content = generate_diff_markdown(diff_data, include_header=True)
    md_file_path = output_dir / f"{model_name}_diff_report.md"
    logger.info(f"Saving model differences to Markdown: {md_file_path}...")
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        with open(md_file_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        logger.info("Markdown diff report saved successfully.")
    except Exception as e:
        logger.error(f"Failed to save Markdown diff report: {e}")

def generate_mermaid_er_diagram(tables_df: pd.DataFrame, rels_df: pd.DataFrame) -> str:
    """Generates a Mermaid ER diagram string from tables and relationships DataFrames."""
    if tables_df.empty and rels_df.empty:
        logger.info("No tables or relationships data to generate Mermaid ER diagram.")
        return "```mermaid\nerDiagram\n    %% No data available for ER diagram\n```"

    def sanitize_mermaid_id(name: str) -> str:
        """Sanitizes a name for Mermaid ID (alpha-numeric, underscore)."""
        return re.sub(r'[^A-Za-z0-9_]', '_', name)

    def get_cardinality_symbol(cardinality_str: str, is_active: bool) -> str:
        """Maps cardinality string to Mermaid symbol."""
        # Normalize cardinality string: 'many:one', 'one:many', 'one:one', 'many:many'
        # Default to many:one if not perfectly matched or missing
        parts = cardinality_str.lower().split(':')
        if len(parts) == 2:
            from_card, to_card = parts
        else:
            from_card, to_card = "many", "one" # Default

        # Symbol construction based on from -> to direction
        symbol_map = {
            ("one", "many"): "||--o{",
            ("many", "one"): "}o--||",
            ("one", "one"): "||--||",
            ("many", "many"): "}o--o{",
        }
        symbol = symbol_map.get((from_card, to_card), "}o--||") # Default to many-to-one

        return symbol if is_active else symbol.replace("--", "..")

    lines: List[str] = ["erDiagram"]

    # Tables
    if not tables_df.empty:
        for _, row in tables_df.iterrows():
            table_id = sanitize_mermaid_id(row["table_name"])
            # Escape double quotes in table names for the label
            table_label = row["table_name"].replace('"', '#quot;')
            lines.append(f'    {table_id} [label="{table_label}"]') # Using label syntax for clarity
            # TODO: Add columns to table definition if desired
            # Example: JOB {
            #   string job_id PK
            #   string job_title
            # }

    # Relationships
    if not rels_df.empty:
        for _, row in rels_df.iterrows():
            from_table_id = sanitize_mermaid_id(row["from_table"])
            to_table_id = sanitize_mermaid_id(row["to_table"])
            from_column_label = row["from_column"].replace('"', '#quot;')
            to_column_label = row["to_column"].replace('"', '#quot;')
            
            label = f'{from_column_label} → {to_column_label}'
            cardinality = row.get("cardinality", "many:one") # Default if missing
            is_active = row.get("is_active", True)
            symbol = get_cardinality_symbol(cardinality, is_active)

            lines.append(f'    {from_table_id} {symbol} {to_table_id} : "{label}"')

    if len(lines) == 1: # Only erDiagram header
        lines.append("    %% No tables or relationships to display")

    return "```mermaid\n" + "\n".join(lines) + "\n```"

def save_mermaid_er_diagram(tables_df: pd.DataFrame, rels_df: pd.DataFrame, output_dir: Path, model_name: str) -> None:
    """Saves the Mermaid ER diagram to a .md file."""
    config = get_config()
    if not config.get("output_elements", {}).get("save_mermaid_er", True):
        logger.info("Mermaid ER diagram export is disabled in configuration.")
        return

    mermaid_content = generate_mermaid_er_diagram(tables_df, rels_df)
    mermaid_file_path = output_dir / f"{model_name}_ER_diagram.md"
    logger.info(f"Saving Mermaid ER diagram to: {mermaid_file_path}...")
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        with open(mermaid_file_path, "w", encoding="utf-8") as f:
            f.write(mermaid_content)
        logger.info("Mermaid ER diagram saved successfully.")
    except Exception as e:
        logger.error(f"Failed to save Mermaid ER diagram: {e}")

def save_database_json_copy(original_db_json_path: Path, output_dir: Path, model_name: str, timestamp: str) -> None:
    """Saves a timestamped copy of the database.json file."""
    config = get_config()
    if not config.get("output_elements", {}).get("save_database_copy", True):
        logger.info("Database.json copy is disabled in configuration.")
        return

    if not original_db_json_path.exists():
        logger.warning(f"Original database.json not found at {original_db_json_path}. Cannot save a copy.")
        return

    copy_file_path = output_dir / f"{model_name}_database_{timestamp}.json"
    logger.info(f"Saving a copy of database.json to: {copy_file_path}...")
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        # Read and write to handle potential encoding issues and ensure it's a clean copy
        content = original_db_json_path.read_text(encoding='utf-8')
        copy_file_path.write_text(content, encoding='utf-8')
        logger.info("Timestamped database.json copy saved successfully.")
    except Exception as e:
        logger.error(f"Failed to save database.json copy: {e}")


import zipfile # Moved here as it's only used by this function in this module

def create_pbix_zip_archive(pbix_file_path: Path, output_dir: Path, model_name: str, timestamp: str) -> None:
    """Creates a zip archive of the PBIX file."""
    config = get_config()
    if not config.get("output_elements", {}).get("save_pbix_zip", False):
        logger.info("PBIX ZIP archive creation is disabled in configuration.")
        return

    if not pbix_file_path.exists():
        logger.error(f"PBIX file not found at {pbix_file_path}. Cannot create zip archive.")
        return

    zip_file_name = f"{model_name}_{timestamp}.zip"
    zip_file_path = output_dir / zip_file_name

    logger.info(f"Creating PBIX ZIP archive: {zip_file_path} from {pbix_file_path}...")
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_file_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(pbix_file_path, arcname=pbix_file_path.name)
        logger.info(f"PBIX ZIP archive created successfully: {zip_file_path}")
    except Exception as e:
        logger.error(f"Error creating PBIX ZIP archive: {e}")
        # Consider re-raising if this is critical, or just logging if it's optional