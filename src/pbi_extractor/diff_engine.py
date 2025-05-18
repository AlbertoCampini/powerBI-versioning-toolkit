# src/pbi_extractor/diff_engine.py

"""Compares two Power BI models and identifies structural differences."""

from typing import Any, Dict, List, Set, Tuple

from .logger_setup import get_logger

logger = get_logger(__name__)

def diff_models(old_model: Dict[str, Any] | None, new_model: Dict[str, Any] | None) -> Dict[str, List[Any]] | None:
    """Compares two model dicts and returns structural differences.

    Args:
        old_model (Dict[str, Any] | None): The old model dictionary (from database.json).
        new_model (Dict[str, Any] | None): The new model dictionary (from database.json).

    Returns:
        Dict[str, List[Any]] | None: A dictionary containing lists of added/removed items,
                                     or None if either model is not provided.
    """
    if old_model is None or new_model is None:
        logger.warning("Cannot diff models: one or both models are missing.")
        return None

    logger.info("Starting model diff process...")

    diff_results: Dict[str, List[Any]] = {
        "tables_added": [],
        "tables_removed": [],
        "fields_added": [],
        "fields_removed": [],
        "relations_added": [],
        "relations_removed": [],
        # TODO: Consider adding modified items as well (e.g., field data type change)
    }

    # Helper to safely get list of items from model
    def _get_items(model_dict: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
        items = model_dict.get(key, [])
        if not isinstance(items, list):
            logger.warning(f"Expected list for key '{key}' in model, got {type(items)}. Treating as empty.")
            return []
        return items

    # 1. Compare Tables
    old_tables_set = {t["name"] for t in _get_items(old_model, "tables") if "name" in t}
    new_tables_set = {t["name"] for t in _get_items(new_model, "tables") if "name" in t}

    diff_results["tables_added"] = sorted(list(new_tables_set - old_tables_set))
    diff_results["tables_removed"] = sorted(list(old_tables_set - new_tables_set))

    # 2. Compare Fields (Columns and Measures)
    def gather_fields_from_model(model_dict: Dict[str, Any]) -> Set[Tuple[str, str]]:
        field_set: Set[Tuple[str, str]] = set()
        for table_data in _get_items(model_dict, "tables"):
            table_name = table_data.get("name")
            if not table_name:
                continue
            for column_data in _get_items(table_data, "columns"):
                if "name" in column_data:
                    field_set.add((table_name, column_data["name"]))
            for measure_data in _get_items(table_data, "measures"):
                if "name" in measure_data:
                    field_set.add((table_name, measure_data["name"]))
        return field_set

    old_fields_set = gather_fields_from_model(old_model)
    new_fields_set = gather_fields_from_model(new_model)

    diff_results["fields_added"] = sorted(list(new_fields_set - old_fields_set))
    diff_results["fields_removed"] = sorted(list(old_fields_set - new_fields_set))

    # 3. Compare Relationships
    def gather_relationships_from_model(model_dict: Dict[str, Any]) -> Set[Tuple[str, str, str, str]]:
        rel_set: Set[Tuple[str, str, str, str]] = set()
        for rel_data in _get_items(model_dict, "relationships"):
            # Ensure all key fields for a relationship's identity are present
            if all(k in rel_data for k in ["fromTable", "fromColumn", "toTable", "toColumn"]):
                rel_set.add((
                    rel_data["fromTable"],
                    rel_data["fromColumn"],
                    rel_data["toTable"],
                    rel_data["toColumn"],
                ))
            else:
                logger.warning(f"Skipping malformed relationship in model: {rel_data}")
        return rel_set

    old_relationships_set = gather_relationships_from_model(old_model)
    new_relationships_set = gather_relationships_from_model(new_model)

    diff_results["relations_added"] = sorted(list(new_relationships_set - old_relationships_set))
    diff_results["relations_removed"] = sorted(list(old_relationships_set - new_relationships_set))

    logger.info("Model diff process completed.")
    logger.debug(f"Diff results: {diff_results}")
    return diff_results