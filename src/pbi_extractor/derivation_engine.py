# src/pbi_extractor/derivation_engine.py

"""Builds and navigates derivation trees for measures and calculated columns."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Set, Tuple

import pandas as pd

from .logger_setup import get_logger
from .metadata_parser import normalize_expression

logger = get_logger(__name__)

_QUALIFIED_REF_PATTERN = re.compile(r"(?:'((?:[^']|'')+)'|([A-Za-z0-9_\.]+))\[([^\]]+)\]")
_UNQUALIFIED_REF_PATTERN = re.compile(r"\[([^\]]+)\]")
_STRING_LITERAL_PATTERN = re.compile(r'"(?:[^"]|"")*"')


def _canonical_object_id(table_name: str, object_name: str) -> str:
    return f"{table_name}[{object_name}]"


def _node_label(table_name: str, object_name: str) -> str:
    return f"{table_name}.{object_name}"


def _strip_string_literals(expression: str) -> str:
    return _STRING_LITERAL_PATTERN.sub(" ", expression)


def _extract_references(expression: str) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """Extracts qualified and unqualified DAX references from an expression."""
    if not expression:
        return [], []

    sanitized_expression = _strip_string_literals(expression)
    qualified_refs: List[Dict[str, str]] = []
    qualified_spans: List[Tuple[int, int]] = []

    for match in _QUALIFIED_REF_PATTERN.finditer(sanitized_expression):
        table_name = (match.group(1) or match.group(2) or "").replace("''", "'").strip()
        object_name = (match.group(3) or "").strip()
        if table_name and object_name:
            qualified_refs.append({
                "table": table_name,
                "name": object_name,
                "raw_reference": match.group(0).strip(),
            })
            qualified_spans.append(match.span())

    mask = [True] * len(sanitized_expression)
    for start, end in qualified_spans:
        for i in range(start, end):
            mask[i] = False

    unqualified_source = "".join(
        ch if mask[idx] else " " for idx, ch in enumerate(sanitized_expression)
    )
    unqualified_refs: List[Dict[str, str]] = []
    for match in _UNQUALIFIED_REF_PATTERN.finditer(unqualified_source):
        object_name = (match.group(1) or "").strip()
        if object_name:
            unqualified_refs.append({
                "name": object_name,
                "raw_reference": match.group(0).strip(),
            })

    return qualified_refs, unqualified_refs


def _resolve_qualified_reference(
    ref_table: str,
    ref_name: str,
    measures_by_table: Dict[str, Dict[str, str]],
    columns_by_table: Dict[str, Dict[str, str]],
) -> str | None:
    table_key = ref_table.casefold()
    name_key = ref_name.casefold()

    measure_id = measures_by_table.get(table_key, {}).get(name_key)
    if measure_id:
        return measure_id

    return columns_by_table.get(table_key, {}).get(name_key)


def _resolve_unqualified_reference(
    owner_kind: str,
    owner_table: str,
    ref_name: str,
    measure_name_index: Dict[str, List[str]],
    columns_by_table: Dict[str, Dict[str, str]],
) -> str | None:
    name_key = ref_name.casefold()
    owner_table_key = owner_table.casefold()
    candidate_measures = measure_name_index.get(name_key, [])
    owner_table_columns = columns_by_table.get(owner_table_key, {})

    if owner_kind == "measure":
        if len(candidate_measures) == 1:
            return candidate_measures[0]
        return owner_table_columns.get(name_key)

    # Calculated columns: prioritize same-table columns and then global unique measure.
    same_table_column = owner_table_columns.get(name_key)
    if same_table_column:
        return same_table_column
    if len(candidate_measures) == 1:
        return candidate_measures[0]
    return None


def _tree_node_stub(node_data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": node_data["object_id"],
        "table": node_data["table"],
        "name": node_data["name"],
        "kind": node_data["kind"],
        "is_hidden": node_data["is_hidden"],
        "children": [],
        "is_terminal": True,
    }


def _build_tree_node(
    node_id: str,
    nodes: Dict[str, Dict[str, Any]],
    dependencies: Dict[str, List[str]],
    max_depth: int,
    depth: int,
    recursion_stack: List[str],
) -> Dict[str, Any]:
    node_data = nodes[node_id]
    tree_node = _tree_node_stub(node_data)

    if node_id in recursion_stack:
        cycle_start_index = recursion_stack.index(node_id)
        cycle_path = recursion_stack[cycle_start_index:] + [node_id]
        tree_node["has_cycle"] = True
        tree_node["cycle_path"] = cycle_path
        return tree_node

    if depth >= max_depth:
        tree_node["max_depth_reached"] = True
        return tree_node

    next_stack = recursion_stack + [node_id]
    child_ids = dependencies.get(node_id, [])
    children: List[Dict[str, Any]] = []
    for child_id in child_ids:
        child_node = _build_tree_node(
            node_id=child_id,
            nodes=nodes,
            dependencies=dependencies,
            max_depth=max_depth,
            depth=depth + 1,
            recursion_stack=next_stack,
        )
        children.append(child_node)

    tree_node["children"] = children
    tree_node["is_terminal"] = len(children) == 0
    return tree_node


def build_derivation_graph(
    model_data: Dict[str, Any],
    fields_df: pd.DataFrame,
    include_hidden: bool = True,
    include_calculated_columns: bool = True,
) -> Dict[str, Any]:
    """Builds derivation graph from model metadata."""
    _ = model_data  # Reserved for future structured dependencies (dependsOn).

    nodes: Dict[str, Dict[str, Any]] = {}
    dependencies: Dict[str, Set[str]] = {}
    unresolved_references: List[Dict[str, str]] = []
    unresolved_seen: Set[Tuple[str, str, str, str]] = set()

    measures_by_table: Dict[str, Dict[str, str]] = {}
    columns_by_table: Dict[str, Dict[str, str]] = {}
    measure_name_index: Dict[str, List[str]] = {}

    if fields_df.empty:
        logger.warning("No fields found. Derivation graph will be empty.")
        return {
            "nodes": {},
            "edges": [],
            "dependencies": {},
            "dependents": {},
            "measure_nodes": [],
            "measure_name_index": {},
            "unresolved_references": [],
            "meta": {
                "include_hidden": include_hidden,
                "include_calculated_columns": include_calculated_columns,
            },
        }

    for _, row in fields_df.iterrows():
        table_name = str(row.get("table", "")).strip()
        object_name = str(row.get("object_name", "")).strip()
        object_type = str(row.get("object_type", "")).strip().lower()
        is_hidden = bool(row.get("is_hidden", False))
        if not table_name or not object_name:
            continue
        if not include_hidden and is_hidden:
            continue

        if object_type == "measure":
            kind = "measure"
        elif object_type == "calculated column":
            kind = "calculated_column"
        else:
            kind = "column"

        if kind == "calculated_column" and not include_calculated_columns:
            continue

        object_id = str(row.get("object_id") or _canonical_object_id(table_name, object_name))
        expression = normalize_expression(row.get("expression"))
        if kind == "column":
            expression = ""

        nodes[object_id] = {
            "object_id": object_id,
            "table": table_name,
            "name": object_name,
            "label": _node_label(table_name, object_name),
            "kind": kind,
            "is_hidden": is_hidden,
            "expression": expression,
        }

        table_key = table_name.casefold()
        name_key = object_name.casefold()

        if kind == "measure":
            measures_by_table.setdefault(table_key, {})[name_key] = object_id
            measure_name_index.setdefault(name_key, []).append(object_id)
        else:
            columns_by_table.setdefault(table_key, {})[name_key] = object_id

    for node_id, node in nodes.items():
        if node["kind"] not in {"measure", "calculated_column"} or not node["expression"]:
            continue

        dependencies.setdefault(node_id, set())
        expression = node["expression"]
        qualified_refs, unqualified_refs = _extract_references(expression)

        for ref in qualified_refs:
            target_id = _resolve_qualified_reference(
                ref_table=ref["table"],
                ref_name=ref["name"],
                measures_by_table=measures_by_table,
                columns_by_table=columns_by_table,
            )
            if target_id and target_id in nodes:
                dependencies[node_id].add(target_id)
            else:
                unresolved_key = (node_id, ref["table"], ref["name"], "qualified")
                if unresolved_key not in unresolved_seen:
                    unresolved_seen.add(unresolved_key)
                    unresolved_references.append({
                        "owner": node_id,
                        "owner_kind": node["kind"],
                        "reference_type": "qualified",
                        "reference_table": ref["table"],
                        "reference_name": ref["name"],
                        "raw_reference": ref["raw_reference"],
                    })

        for ref in unqualified_refs:
            target_id = _resolve_unqualified_reference(
                owner_kind=node["kind"],
                owner_table=node["table"],
                ref_name=ref["name"],
                measure_name_index=measure_name_index,
                columns_by_table=columns_by_table,
            )
            if target_id and target_id in nodes:
                dependencies[node_id].add(target_id)
            else:
                unresolved_key = (node_id, "", ref["name"], "unqualified")
                if unresolved_key not in unresolved_seen:
                    unresolved_seen.add(unresolved_key)
                    unresolved_references.append({
                        "owner": node_id,
                        "owner_kind": node["kind"],
                        "reference_type": "unqualified",
                        "reference_table": "",
                        "reference_name": ref["name"],
                        "raw_reference": ref["raw_reference"],
                    })

    edges: List[Dict[str, str]] = []
    dependents: Dict[str, Set[str]] = {node_id: set() for node_id in nodes}
    normalized_dependencies: Dict[str, List[str]] = {}
    for source_id, targets in dependencies.items():
        sorted_targets = sorted(targets)
        normalized_dependencies[source_id] = sorted_targets
        for target_id in sorted_targets:
            edges.append({"from": source_id, "to": target_id})
            dependents.setdefault(target_id, set()).add(source_id)

    for node_id in nodes:
        normalized_dependencies.setdefault(node_id, [])
        dependents.setdefault(node_id, set())

    measure_nodes = sorted(
        node_id for node_id, node in nodes.items() if node["kind"] == "measure"
    )
    normalized_measure_name_index = {
        name: sorted(ids) for name, ids in measure_name_index.items()
    }
    normalized_dependents = {
        node_id: sorted(source_ids) for node_id, source_ids in dependents.items()
    }

    return {
        "nodes": nodes,
        "edges": sorted(edges, key=lambda item: (item["from"], item["to"])),
        "dependencies": normalized_dependencies,
        "dependents": normalized_dependents,
        "measure_nodes": measure_nodes,
        "measure_name_index": normalized_measure_name_index,
        "unresolved_references": sorted(
            unresolved_references,
            key=lambda item: (item["owner"], item["reference_type"], item["reference_table"], item["reference_name"]),
        ),
        "meta": {
            "include_hidden": include_hidden,
            "include_calculated_columns": include_calculated_columns,
        },
    }


def select_derivation_roots(
    graph: Dict[str, Any],
    root_scope: str,
    configured_roots: List[str],
) -> List[str]:
    """Selects root measures according to the configured scope."""
    nodes = graph.get("nodes", {})
    measure_nodes = graph.get("measure_nodes", [])
    dependencies = graph.get("dependencies", {})

    if not measure_nodes:
        return []

    root_scope_normalized = (root_scope or "auto").strip().lower()
    if root_scope_normalized == "all_measures":
        return sorted(measure_nodes)

    if root_scope_normalized == "configured":
        selected: Set[str] = set()
        measure_name_index = graph.get("measure_name_index", {})
        for raw_root in configured_roots or []:
            candidate = str(raw_root or "").strip()
            if not candidate:
                continue
            if candidate in nodes and nodes[candidate]["kind"] == "measure":
                selected.add(candidate)
                continue
            candidate_key = candidate.casefold()
            candidate_ids = measure_name_index.get(candidate_key, [])
            if len(candidate_ids) == 1:
                selected.add(candidate_ids[0])
        if selected:
            return sorted(selected)
        logger.warning("Configured derivation roots are empty or invalid. Falling back to auto roots.")
        root_scope_normalized = "auto"

    if root_scope_normalized == "auto":
        measure_in_degree: Dict[str, int] = {measure_id: 0 for measure_id in measure_nodes}
        for source_id in measure_nodes:
            for target_id in dependencies.get(source_id, []):
                if target_id in measure_in_degree:
                    measure_in_degree[target_id] += 1

        auto_roots = sorted(
            measure_id for measure_id, in_degree in measure_in_degree.items() if in_degree == 0
        )
        return auto_roots or sorted(measure_nodes)

    logger.warning(f"Unknown root_scope '{root_scope}'. Falling back to auto roots.")
    return select_derivation_roots(graph=graph, root_scope="auto", configured_roots=[])


def build_measure_derivation_forest(
    graph: Dict[str, Any],
    roots: List[str],
    max_depth: int = 50,
) -> Dict[str, Any]:
    """Builds one derivation tree per root measure."""
    nodes = graph.get("nodes", {})
    dependencies = graph.get("dependencies", {})

    normalized_max_depth = max(1, int(max_depth))
    measure_derivations: Dict[str, Dict[str, Any]] = {}
    for root_id in roots:
        root_node = nodes.get(root_id)
        if not root_node or root_node.get("kind") != "measure":
            continue
        measure_derivations[root_id] = _build_tree_node(
            node_id=root_id,
            nodes=nodes,
            dependencies=dependencies,
            max_depth=normalized_max_depth,
            depth=0,
            recursion_stack=[],
        )

    return {
        "max_depth": normalized_max_depth,
        "measure_derivations": measure_derivations,
    }


def build_derivation_rows(
    measure_derivations: Dict[str, Dict[str, Any]],
    nodes: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Flattens derivation trees to tabular rows."""
    rows: List[Dict[str, Any]] = []

    def walk(
        root_label: str,
        parent_node: Dict[str, Any],
        path_labels: List[str],
        level: int,
    ) -> None:
        children = parent_node.get("children", [])
        for child in children:
            child_label = _node_label(child["table"], child["name"])
            child_children = child.get("children", [])
            is_terminal = (
                len(child_children) == 0
                or bool(child.get("has_cycle"))
                or bool(child.get("max_depth_reached"))
            )
            row_path = path_labels + [child_label]
            rows.append({
                "root_measure": root_label,
                "level": level,
                "parent": _node_label(parent_node["table"], parent_node["name"]),
                "parent_kind": parent_node["kind"],
                "child": child_label,
                "child_kind": child["kind"],
                "is_terminal": is_terminal,
                "path": " -> ".join(row_path),
            })
            walk(
                root_label=root_label,
                parent_node=child,
                path_labels=row_path,
                level=level + 1,
            )

    for root_id, root_tree in sorted(measure_derivations.items()):
        root_node = nodes.get(root_id)
        if not root_node:
            continue
        root_label = _node_label(root_node["table"], root_node["name"])
        root_is_terminal = len(root_tree.get("children", [])) == 0
        rows.append({
            "root_measure": root_label,
            "level": 0,
            "parent": "",
            "parent_kind": "",
            "child": root_label,
            "child_kind": root_node["kind"],
            "is_terminal": root_is_terminal,
            "path": root_label,
        })
        walk(
            root_label=root_label,
            parent_node=root_tree,
            path_labels=[root_label],
            level=1,
        )

    return rows


def build_derivation_output_payload(
    model_name: str,
    root_scope: str,
    roots: List[str],
    graph: Dict[str, Any],
    forest: Dict[str, Any],
) -> Dict[str, Any]:
    """Builds the final payload used by exporters."""
    nodes = graph.get("nodes", {})
    edges = graph.get("edges", [])
    measure_derivations = forest.get("measure_derivations", {})

    serialized_nodes = [
        {
            "object_id": node_id,
            "table": node_data["table"],
            "name": node_data["name"],
            "kind": node_data["kind"],
            "is_hidden": node_data["is_hidden"],
            "expression": node_data["expression"] if node_data["kind"] != "column" else "",
        }
        for node_id, node_data in sorted(nodes.items(), key=lambda item: item[0])
    ]

    derivation_rows = build_derivation_rows(
        measure_derivations=measure_derivations,
        nodes=nodes,
    )

    return {
        "model_name": model_name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "root_scope": root_scope,
        "roots": roots,
        "nodes": serialized_nodes,
        "edges": edges,
        "measure_derivations": measure_derivations,
        "unresolved_references": graph.get("unresolved_references", []),
        "table_rows": derivation_rows,
        "max_depth": forest.get("max_depth"),
    }
