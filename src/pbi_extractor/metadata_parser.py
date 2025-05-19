# src/pbi_extractor/metadata_parser.py

"""Parses the Power BI model (database.json) and collects metadata."""

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

from .logger_setup import get_logger

logger = get_logger(__name__)

def load_model_from_json(file_path: Path) -> Dict[str, Any] | None:
    """Loads the model from a database.json file.

    Args:
        file_path (Path): Path to the database.json file.

    Returns:
        Dict[str, Any] | None: The 'model' dictionary from the JSON, or None if loading fails.
    """
    logger.info(f"Loading model from {file_path}...")
    if not file_path.exists():
        logger.error(f"Model file not found: {file_path}")
        return None
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
        model = data.get("model")
        if model is None:
            logger.warning(f"'model' key not found in {file_path}. File might be malformed or not a PBI model JSON.")
            return None
        logger.info(f"Model loaded successfully from {file_path}.")
        return model
    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode JSON from {file_path}: {e}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred while loading model from {file_path}: {e}")
        return None

def collect_metadata_from_model(
    model_data: Dict[str, Any]
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Extracts DataFrames for tables, fields, and relationships from model data.

    Args:
        model_data (Dict[str, Any]): The 'model' dictionary from database.json.

    Returns:
        Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]: DataFrames for tables, fields, and relationships.
    """
    logger.info("Collecting metadata from model data...")
    tables_list: List[Dict[str, Any]] = []
    fields_list: List[Dict[str, Any]] = []
    relationships_list: List[Dict[str, Any]] = []

    if not isinstance(model_data, dict):
        logger.warning("Invalid model_data format: expected a dictionary.")
        return pd.DataFrame(tables_list), pd.DataFrame(fields_list), pd.DataFrame(relationships_list)

    for tbl in model_data.get("tables", []):
        tables_list.append({
            "table_name": tbl.get("name", "UnknownTable"),
            "is_hidden": tbl.get("isHidden", False),
            "description": tbl.get("description", ""),
        })
        for col in tbl.get("columns", []):
            fields_list.append({
                "table": tbl.get("name", "UnknownTable"),
                "object_name": col.get("name", "UnknownColumn"),
                "object_type": "calculated column" if col.get("type") else "column" , # If type field exists the object is calculated column otherwise it is column
                "data_type": col.get("dataType"),
                "is_hidden": col.get("isHidden", False),
                "description": col.get("description", ""),
                "expression": col.get("expression",""), # Expression is relevant field only for DAX for calculated columns
            })
        for meas in tbl.get("measures", []):
            fields_list.append({
                "table": tbl.get("name", "UnknownTable"),
                "object_name": meas.get("name", "UnknownMeasure"),
                "object_type": "measure",
                "data_type": None,  # Measures don't have a fixed data type in the same way columns do
                "is_hidden": meas.get("isHidden", False),
                "description": meas.get("description", ""),
                "expression": meas.get("expression", ""),
            })

    for rel in model_data.get("relationships", []):
        from_card = rel.get("fromCardinality", "many")
        to_card = rel.get("toCardinality", "one")
        cardinality = f"{from_card.lower()}:{to_card.lower()}"

        relationships_list.append({
            "from_table": rel.get("fromTable", "UnknownFromTable"),
            "from_column": rel.get("fromColumn", "UnknownFromColumn"),
            "to_table": rel.get("toTable", "UnknownToTable"),
            "to_column": rel.get("toColumn", "UnknownToColumn"),
            "cardinality": cardinality,
            "cross_filtering_behavior": rel.get("crossFilteringBehavior", "singleDirection"),
            "is_active": rel.get("isActive", True),
        })

    tables_df = pd.DataFrame(tables_list)
    fields_df = pd.DataFrame(fields_list)
    rels_df = pd.DataFrame(relationships_list)

    logger.info(f"Metadata collection complete. Found {len(tables_df)} tables, {len(fields_df)} fields, {len(rels_df)} relationships.")
    return tables_df, fields_df, rels_df