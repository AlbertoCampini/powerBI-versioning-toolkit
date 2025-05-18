from __future__ import annotations

"""Extract & diff Power BI model metadata
==========================================
• Loads reference model (database.json)
• Extracts current model from Power BI Desktop (using pbi-tools)
• Compares old vs new structure (tables, fields, relationships)
• Saves CSV, JSON diff, Markdown report, and Mermaid ER (tables+relationships)

Requirements
------------
• Python 3.7+
• pip install pandas
• pbi-tools 1.2+ (https://github.com/pbi-tools/pbi-tools)

Configuration
-------------
Update paths if necessary:
  PBI_TOOLS_EXE      Path to pbi-tools.exe
  OLD_MODEL_PATH     Reference JSON (database.json)
  OUTPUT_ROOT        Root folder for extraction and output

"""
import json
import re
import subprocess  # noqa: S404
import sys
import os # Added for Git operations and path control
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple
import yaml
import xlsxwriter
import pandas as pd
from datetime import datetime # Import datetime
from dotenv import load_dotenv # Added to load environment variables
import zipfile  # Per la creazione dello zip

# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
load_dotenv() # Load variables from .env before accessing os.getenv()

with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)

# Current script directory
SCRIPT_DIR = Path(__file__).parent

# Output root management
custom_root_path_str = config["paths"].get("custom_output_root", "").strip()
# If custom_output_root is specified, BASE_OUTPUT_ROOT is custom_output_root.
# Otherwise, it's SCRIPT_DIR / "out"
BASE_OUTPUT_ROOT = Path(custom_root_path_str) if custom_root_path_str else SCRIPT_DIR / "out"
# The target directory for Git is custom_output_root, if specified, otherwise None.
GIT_TARGET_DIR = Path(custom_root_path_str) if custom_root_path_str else None

# Paths
PBI_TOOLS_EXE = Path(config["paths"]["pbi_tools_exe"])

# Options
EXTRACT_MODE = config["options"].get("extract_mode", "Auto")
MODEL_SERIALIZATION = config["options"].get("model_serialization", "Raw")
MASHUP_SERIALIZATION = config["options"].get("mashup_serialization", "Default")
VERBOSE = config["options"].get("verbose", False)

# Output elements configuration
OUTPUT_ELEMENTS = config.get("output_elements", {})
SAVE_CSV = OUTPUT_ELEMENTS.get("save_csv", True)
SAVE_EXCEL = OUTPUT_ELEMENTS.get("save_excel", True)
SAVE_JSON_DIFF = OUTPUT_ELEMENTS.get("save_json_diff", True)
SAVE_MARKDOWN_DIFF = OUTPUT_ELEMENTS.get("save_markdown_diff", True)
SAVE_MERMAID_ER = OUTPUT_ELEMENTS.get("save_mermaid_er", True)
SAVE_CHANGELOG = OUTPUT_ELEMENTS.get("save_changelog", True)
SAVE_DATABASE_COPY = OUTPUT_ELEMENTS.get("save_database_copy", True)
SAVE_PBIX_ZIP = OUTPUT_ELEMENTS.get("save_pbix_zip", False)

# Git configuration
GIT_CONFIG = config.get("git", {})
GIT_ENABLED = GIT_CONFIG.get("enabled", False)
GIT_REMOTE_URL = GIT_CONFIG.get("remote_url", "").strip()
GIT_BRANCH = GIT_CONFIG.get("branch", "main")
GIT_COMMIT_PREFIX = GIT_CONFIG.get("commit_prefix", "[AUTO] PBI model update")
GIT_REMOTE_NAME = GIT_CONFIG.get("remote_name", "origin")

# Git credentials from .env
GIT_USERNAME = os.getenv("GIT_USERNAME")
GIT_TOKEN = os.getenv("GIT_TOKEN")

# Ensure folders exist
# Folders will be created dynamically based on the PBIX file name

# ----------------------------------------------------------------------
# Git Command Helper
# ----------------------------------------------------------------------
def _run_git_command(git_args: List[str], working_dir: Path) -> subprocess.CompletedProcess[str]:
    """Runs a Git command and handles output/errors."""
    cmd = ["git"] + git_args

    # Mask the token in the command arguments for logging
    logged_cmd_display_parts = []
    for arg in cmd:
        if GIT_TOKEN and GIT_TOKEN in arg and ("http://" in arg or "https://" in arg) and "@" in arg:
            try:
                protocol, rest_with_creds = arg.split("://", 1)
                creds_part, host_and_path = rest_with_creds.split("@", 1)
                user_part, token_part_in_url = creds_part.split(":", 1)
                if token_part_in_url == GIT_TOKEN:
                    logged_cmd_display_parts.append(f"{protocol}://{user_part}:<TOKEN_HIDDEN>@{host_and_path}")
                else:
                    logged_cmd_display_parts.append(arg) # Different token or unexpected format
            except ValueError:
                logged_cmd_display_parts.append(arg.replace(GIT_TOKEN, "<TOKEN_HIDDEN>")) # Fallback
        else:
            logged_cmd_display_parts.append(arg)

    print(f"ℹ️ Executing Git: {' '.join(logged_cmd_display_parts)} in {working_dir}")
    try:
        # Use encoding='utf-8' to avoid issues with special characters in commit messages or file names
        proc = subprocess.run(cmd, cwd=working_dir, text=True, check=True, capture_output=True, encoding='utf-8')
        if proc.stdout and VERBOSE:
            print(f"Git stdout: {proc.stdout.strip()}")
        if proc.stderr and VERBOSE: # Even if check=True, stderr might contain warnings
            print(f"Git stderr: {proc.stderr.strip()}")
        return proc
    except subprocess.CalledProcessError as e:
        print(f"❌ Error during Git command execution: {' '.join(cmd)}")
        print(f"Return code: {e.returncode}")
        if e.stdout:
            print(f"Stdout: {e.stdout.strip()}")
        if e.stderr:
            print(f"Stderr: {e.stderr.strip()}")
        raise # Re-raise the exception to stop the current Git operation
    except FileNotFoundError:
        print(f"❌ Error: The 'git' command was not found. Ensure Git is installed and in the PATH.")
        raise

# ----------------------------------------------------------------------
# CLI Helpers
# ----------------------------------------------------------------------
def _run_cli(cmd: List[str | Path]) -> subprocess.CompletedProcess[str]:
    """Runs pbi-tools suppressing stdout/stderr if VERBOSE=False"""
    kwargs: dict[str, Any] = dict(text=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    proc = subprocess.run([str(c) for c in cmd], **kwargs)
    if VERBOSE:
        sys.stdout.write(proc.stdout)
        sys.stderr.write(proc.stderr)
    return proc

# ----------------------------------------------------------------------
# Manage PBI Session
# ----------------------------------------------------------------------
def get_first_pbi_session() -> Dict[str, str]:
    """Returns pbix_path and pid of the first open Power BI Desktop session"""
    print("🔍 Searching for Power BI Desktop session…", end=" ")
    proc = _run_cli([PBI_TOOLS_EXE, "info"])
    raw = proc.stdout
    idx = raw.find("{")
    if idx < 0:
        print("❌")
        raise RuntimeError("No JSON found in pbi-tools info")
    info = json.loads(raw[idx:])
    sessions = info.get("pbiSessions", [])
    if not sessions:
        print("❌")
        raise RuntimeError("No open Power BI session found")
    sess = sessions[0]
    print("✅ session found")
    return {"pbix_path": sess["PbixPath"], "pid": str(sess["ProcessId"])}

def extract_model(session: Dict[str, str], EXTRACT_FOLDER: Path) -> Path:
    """Extracts the model from PBIX and returns the path to database.json"""
    print("🚀 Extracting model…", end=" ")
    cmd = [
        PBI_TOOLS_EXE, "extract", session["pbix_path"], session["pid"],
        "-extractFolder", str(EXTRACT_FOLDER),
        "-mode", EXTRACT_MODE,
        "-modelSerialization", MODEL_SERIALIZATION,
        "-mashupSerialization", MASHUP_SERIALIZATION,
    ]
    _run_cli(cmd)
    model_file = EXTRACT_FOLDER / "Model" / "database.json"
    if not model_file.exists():
        print("❌")
        raise FileNotFoundError(f"Model file not found: {model_file}")
    print(f"✅ model extracted to {model_file}")
    return model_file

# ----------------------------------------------------------------------
# Parsing and metadata collection
# ----------------------------------------------------------------------
def load_model(path: Path) -> Dict[str, Any]:
    """Loads JSON and returns the dict containing 'model'"""
    print(f"📂 Loading model from {path}…", end=" ")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except:
        print("❌ No model found")
        return None
    model = data.get("model", {})
    print("✅ model loaded")
    return model

def collect_metadata(model: Dict[str, Any]) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Extracts DataFrames for tables, fields, and relationships"""
    tables: List[Dict[str, Any]] = []
    fields: List[Dict[str, Any]] = []
    rels: List[Dict[str, Any]] = []

    for tbl in model.get("tables", []):
        tables.append({
            "table_name": tbl["name"],
            "is_hidden": tbl.get("isHidden", False),
            "description": tbl.get("description", ""),
        })
        for col in tbl.get("columns", []):
            fields.append({
                "table": tbl["name"],
                "object_name": col["name"],
                "object_type": "column",
                "is_measure": False,
                "data_type": col.get("dataType"),
                "is_hidden": col.get("isHidden", False),
                "description": col.get("description", ""),
                "expression": None,
            })
        for meas in tbl.get("measures", []):
            fields.append({
                "table": tbl["name"],
                "object_name": meas["name"],
                "object_type": "measure",
                "is_measure": True,
                "data_type": None,
                "is_hidden": meas.get("isHidden", False),
                "description": meas.get("description", ""),
                "expression": meas.get("expression", ""),
            })
   
    for rel in model.get("relationships", []):
        # Cardinality ----------------------------------------------------------
        if "fromCardinality" in rel or "toCardinality" in rel:
                from_card = rel.get("fromCardinality", "many")
                to_card   = rel.get("toCardinality",   "one")
                cardinality = f"{from_card}:{to_card}"
        else:
                cardinality = "many:one"                     # ← default

        # Filter propagation ---------------------------------------------------
        cross_filter = rel.get("crossFilteringBehavior", "singleDirection")

        # Save row ---------------------------------------------------------
        rels.append({
            "from_table":  rel["fromTable"],
            "from_column": rel["fromColumn"],
            "to_table":    rel["toTable"],
            "to_column":   rel["toColumn"],
            "cardinality": cardinality,
            "cross_filtering_behavior": cross_filter,
            "is_active":  rel.get("isActive", True),
        })

       
    return pd.DataFrame(tables), pd.DataFrame(fields), pd.DataFrame(rels)

# ----------------------------------------------------------------------
# Differences between models
# ----------------------------------------------------------------------
def diff_models(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, List[Any]]:
    """Compares two model dicts and returns structural differences"""
    diff = {key: [] for key in (
        "tables_added", "tables_removed",
        "fields_added", "fields_removed",
        "relations_added", "relations_removed",
    )}
    # Tabelle
    old_t = {t["name"] for t in old.get("tables", [])}
    new_t = {t["name"] for t in new.get("tables", [])}
    diff["tables_added"] = sorted(new_t - old_t)
    diff["tables_removed"] = sorted(old_t - new_t)
    # Campi
    def gather_fields(m: Dict[str, Any]) -> Set[Tuple[str, str]]:
        s: Set[Tuple[str, str]] = set()
        for t in m.get("tables", []):
            tbl = t["name"]
            s |= {(tbl, c["name"]) for c in t.get("columns", [])}
            s |= {(tbl, m2["name"]) for m2 in t.get("measures", [])}
        return s
    old_f = gather_fields(old)
    new_f = gather_fields(new)
    diff["fields_added"] = sorted(new_f - old_f)
    diff["fields_removed"] = sorted(old_f - new_f)
    # Relazioni
    def gather_rels(m: Dict[str, Any]) -> Set[Tuple[str, str, str, str]]:
        return {(
            r["fromTable"], r["fromColumn"], r["toTable"], r["toColumn"]
        ) for r in m.get("relationships", [])}
    old_r = gather_rels(old)
    new_r = gather_rels(new)
    diff["relations_added"] = sorted(new_r - old_r)
    diff["relations_removed"] = sorted(old_r - new_r)
    return diff

# ----------------------------------------------------------------------
# Export generation
# ----------------------------------------------------------------------
def diff_to_markdown(diff: Dict[str, List[Any]], include_header: bool = True) -> str:
    """Generates Markdown report with Added/Removed items per concept"""
    md: List[str] = []
    if include_header:
        md.extend(["# Model Diff Report", ""])
    sections = [
        ("tables", "Tables"),
        ("fields", "Fields (Table, Field)"),
        ("relations", "Relationships (FromTbl, FromCol, ToTbl, ToCol)"),
    ]
    for key, title in sections:
        added = diff.get(f"{key}_added", [])
        removed = diff.get(f"{key}_removed", [])
        if not added and not removed:
            continue
        md.extend([f"## {title}", ""])
        md.append("| Added | Removed |")
        md.append("|---|---|")
        rows = max(len(added), len(removed))
        for i in range(rows):
            a =  added[i] if i < len(added) else ""
            r =  removed[i] if i < len(removed) else ""
            if isinstance(a, tuple):
                a = ", ".join(a)
            if isinstance(r, tuple):
                r = ", ".join(r)
            md.append(f"| ✅ {a} | ❌ {r} |")
        md.append("")
    return "\n".join(md)

def model_to_mermaid(tables_df: pd.DataFrame, rels_df: pd.DataFrame) -> str:
    """Generates a Mermaid ER diagram from tables and relationships DataFrames"""
    def cardinality_symbol(cardinality: str, is_active: bool) -> str:
        mapping = {
            "one:many": "||--o{",
            "many:one": "}o--||",
            "one:one": "||--||",
            "many:many": "}o--o{",
        }
        if is_active:
            return mapping.get(cardinality, "||--||")
        else:
            return mapping.get(cardinality, "||--||").replace("--","..")

    def sanitize(name: str) -> str:
        """Sanitizes a name for Mermaid ID (alpha-numeric underscore)"""
        return re.sub(r'[^A-Za-z0-9]', '_', name)

    lines: List[str] = ["```mermaid", "erDiagram"]

    # Tabelle
    for _, row in tables_df.iterrows():
        table_id = sanitize(row["table_name"])
        label = row["table_name"].replace('"', '\\"')
        lines.append(f'{table_id} as "{label}"')

    # Relazioni
    for _, row in rels_df.iterrows():
        frm = sanitize(row["from_table"])
        to = sanitize(row["to_table"])
        frm_col = row["from_column"].replace('"', '\\"')
        to_col = row["to_column"].replace('"', '\\"')
        label = f"{frm_col}→{to_col}"
        symbol = cardinality_symbol(row.get("cardinality", ""),row["is_active"])

        lines.append(f'{frm} {symbol} {to} : "{label}"')

    lines.append("```")
    return "\n".join(lines)

def export_metadata_to_excel(tables_df: pd.DataFrame, fields_df: pd.DataFrame, rels_df: pd.DataFrame, output_path: str) -> None:
    """Exports metadata to an Excel file with one sheet per table and one for relationships."""
    with pd.ExcelWriter(output_path, engine='xlsxwriter') as writer:
        # Initial sheet with relationships
        rels_df.to_excel(writer, sheet_name="Relazioni", index=False)

        # One sheet for each table with its fields
        for table in tables_df["table_name"].unique():
            fields_for_table = fields_df[fields_df["table"] == table]
            sheet_name = table[:31]  # Excel limit: max 31 chars for sheet name
            fields_for_table.to_excel(writer, sheet_name=sheet_name, index=False)


# ----------------------------------------------------------------------
# Changelog generation
# ----------------------------------------------------------------------
def update_changelog(changelog_path: Path, model_name: str, current_date: str, diff: Dict[str, List[Any]] | None) -> None:
    """Creates or updates the changelog.md file for the model."""
    print(f"📝 Updating changelog for {model_name} at {changelog_path}...", end=" ")

    # 1. Prepare the new entry content block
    new_entry_block_parts = []
    new_entry_block_parts.append(f"## Updated Version at {current_date}\n")
    new_entry_block_parts.append("### Datamodel\n")

    if diff:
        diff_md_text = diff_to_markdown(diff, include_header=False)
        if diff_md_text.strip():
            new_entry_block_parts.append("### Changes Summary\n")
            new_entry_block_parts.append(diff_md_text)
            # Ensure diff_md_text ends with a blank line for separation if it doesn't already
            if not diff_md_text.endswith("\n\n"):
                if diff_md_text.endswith("\n"):
                    new_entry_block_parts.append("\n") 
                else: 
                    new_entry_block_parts.append("\n\n")
        else:
            new_entry_block_parts.append("No changes detected in the schema compared to the previous version.\n\n")
    else:
        new_entry_block_parts.append("No diff information available to generate the changelog (previous or new model not found).\n\n")
    
    new_entry_content_str = "".join(new_entry_block_parts)

    # 2. Define the static header for the current model
    header_content_str = (
        f"# 🛠 Changelog - {model_name}\n\n"
        "This changelog tracks daily changes to the Power BI model schema. "
        "Each entry below summarizes additions and removals of tables, fields, "
        "and relationships.\n\n"
    )

    if not changelog_path.exists():
        changelog_path.parent.mkdir(parents=True, exist_ok=True)
        # For a new file, it's header + first entry
        final_write_content = header_content_str + new_entry_content_str
        changelog_path.write_text(final_write_content, encoding="utf-8")
        print("🆕 created,", end=" ")
    else:
        existing_full_content_str = changelog_path.read_text(encoding="utf-8")
        existing_lines = existing_full_content_str.splitlines(keepends=True)
        
        first_entry_line_index = -1
        for i, line_content in enumerate(existing_lines):
            if line_content.startswith("## Updated Version at"):
                first_entry_line_index = i
                break
        
        if first_entry_line_index != -1:
            # Existing entries found. Content before this is the file's current header.
            file_header_part = "".join(existing_lines[:first_entry_line_index])
            
            # Ensure the identified header part is well-formed or use canonical if it's empty/whitespace.
            if not file_header_part.strip(): 
                 file_header_part = header_content_str # Use canonical if existing header part is empty
            elif not file_header_part.endswith("\n\n"): # Ensure it ends with a double newline for separation
                if file_header_part.endswith("\n"):
                    file_header_part += "\n"
                else: 
                    file_header_part += "\n\n"

            previous_entries_part = "".join(existing_lines[first_entry_line_index:])
            final_write_content = file_header_part + new_entry_content_str + previous_entries_part
        else:
            # No "## Updated Version at" lines found. File might be header-only, empty, or malformed.
            file_header_part = existing_full_content_str
            if not file_header_part.strip(): # If existing file is effectively empty
                file_header_part = header_content_str 
            else: # Presumed to be a header. Ensure it ends with \n\n.
                if not file_header_part.endswith("\n\n"):
                    if file_header_part.endswith("\n"):
                        file_header_part += "\n"
                    else:
                        file_header_part += "\n\n"
            
            final_write_content = file_header_part + new_entry_content_str
            
        changelog_path.write_text(final_write_content, encoding="utf-8")
        print("✅ updated.", end=" ")
    
    print() 


def save_pbix_zip_if_enabled(session: Dict[str, str], output_dir: Path):
    if not SAVE_PBIX_ZIP:
        return
    pbix_path = session.get("pbix_path")
    if not pbix_path or not os.path.isfile(pbix_path):
        print("⚠️ PBIX non trovato o non valido, zip non creato.")
        return
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    pbix_name = Path(pbix_path).stem
    zip_name = f"{pbix_name}_{timestamp}.zip"
    zip_path = output_dir / zip_name
    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(pbix_path, arcname=Path(pbix_path).name)
        print(f"✅ PBIX zippato e salvato come {zip_path}")
    except Exception as e:
        print(f"❌ Errore durante la creazione dello zip del PBIX: {e}")

# ----------------------------------------------------------------------
# Main flow
# ----------------------------------------------------------------------
def main() -> None:
    try:
        session = get_first_pbi_session()
        current_date = datetime.now().strftime("%Y-%m-%d") # Ottieni la data corrente

        # Determine model name from PBIX path and create model-specific output folder
        pbix_path = Path(session["pbix_path"])
        model_name = pbix_path.stem  # Get the file name without extension
        OUTPUT_ROOT = BASE_OUTPUT_ROOT / model_name
        OLD_MODEL_PATH = BASE_OUTPUT_ROOT / model_name / "extracted/Model/database.json"

        # Define model-specific paths
        EXTRACT_FOLDER = OUTPUT_ROOT / "extracted"
        CSV_FOLDER = OUTPUT_ROOT / "csv"
        XLSX_FOLDER = OUTPUT_ROOT / "xlsx"
        JSON_FOLDER = OUTPUT_ROOT / "json"  # Nuova cartella per i JSON
        # DIFF_JSON = OUTPUT_ROOT / "diff_report.json" # Vecchio percorso
        DIFF_MD = OUTPUT_ROOT / "diff_report.md"
        MERMAID_MD = OUTPUT_ROOT / "model_er.md"
        CHANGELOG_MD = OUTPUT_ROOT / "changelog.md" # Nuovo percorso per il changelog

        # Ensure model-specific folders exist
        for folder in (EXTRACT_FOLDER, CSV_FOLDER, OUTPUT_ROOT, XLSX_FOLDER, JSON_FOLDER): # Aggiungi JSON_FOLDER
            folder.mkdir(parents=True, exist_ok=True)

        # --- Operazioni Git Iniziali ---
        git_repo_path: Path | None = None # Percorso effettivo del repo Git, se abilitato e valido
        if GIT_ENABLED and GIT_TARGET_DIR:
            git_repo_path = GIT_TARGET_DIR
            print(f"ℹ️ Versionamento Git abilitato per: {git_repo_path}")

            if not git_repo_path.exists():
                print(f"ℹ️ La directory specificata per Git ({git_repo_path}) non esiste. Verrà creata.")
                git_repo_path.mkdir(parents=True, exist_ok=True)
            elif not git_repo_path.is_dir():
                print(f"❌ Errore: Il percorso specificato per Git ({git_repo_path}) esiste ma non è una directory. Versionamento Git saltato.")
                git_repo_path = None # Disabilita Git per questa esecuzione

            if git_repo_path:
                try:
                    # Controlla se è un repository Git, altrimenti inizializza
                    if not (git_repo_path / ".git").is_dir():
                        print(f"ℹ️ La directory {git_repo_path} non è un repository Git. Inizializzazione...")
                        _run_git_command(["init"], working_dir=git_repo_path)
                        print(f"✅ Repository Git inizializzato in {git_repo_path}")
                    else:
                        print(f"ℹ️ Repository Git trovato in {git_repo_path}")

                    # Gestione del remote
                    if GIT_REMOTE_URL: # Questo è l'URL base da config.yaml
                        
                        target_remote_url_for_git = GIT_REMOTE_URL # URL da usare con git, può includere credenziali
                        display_remote_url = GIT_REMOTE_URL # URL da mostrare nei log, sempre mascherato

                        if GIT_USERNAME and GIT_TOKEN and "://" in GIT_REMOTE_URL:
                            protocol, rest_of_url = GIT_REMOTE_URL.split("://", 1)
                            # Rimuove eventuali credenziali esistenti dall'URL base prima di aggiungerne di nuove
                            domain_path_part = rest_of_url.split("@")[-1] 
                            
                            target_remote_url_for_git = f"{protocol}://{GIT_USERNAME}:{GIT_TOKEN}@{domain_path_part}"
                            display_remote_url = f"{protocol}://{GIT_USERNAME}:{GIT_TOKEN}@{domain_path_part}"
                            print(f"ℹ️ URL per Git remote (con autenticazione .env) sarà: {display_remote_url}")
                        else:
                            print(f"ℹ️ Nessun GIT_USERNAME e/o GIT_TOKEN valido trovato in .env, oppure formato GIT_REMOTE_URL non standard.")
                            print(f"ℹ️ URL per Git remote (da config.yaml) sarà: {GIT_REMOTE_URL}")

                        try:
                            remotes_proc = _run_git_command(["remote", "-v"], working_dir=git_repo_path)
                            remotes_output = remotes_proc.stdout.strip()
                            
                            remote_configured_as_target = False
                            existing_remote_name_found = False
                            configured_url_in_git = ""

                            for line in remotes_output.split('\n'):
                                parts = line.split()
                                if len(parts) >= 2 and parts[0] == GIT_REMOTE_NAME:
                                    existing_remote_name_found = True
                                    configured_url_in_git = parts[1]
                                    if configured_url_in_git == target_remote_url_for_git:
                                        remote_configured_as_target = True
                                    break # Trovato il remote con il nome corretto, esamina solo questo
                            
                            if remote_configured_as_target:
                                print(f"ℹ️ Remote '{GIT_REMOTE_NAME}' già configurato correttamente a '{display_remote_url}'.")
                            else:
                                if existing_remote_name_found:
                                    # Maschera il token anche nell'URL esistente, se presente e corrisponde
                                    display_configured_url_in_git = configured_url_in_git
                                    if GIT_TOKEN and GIT_TOKEN in configured_url_in_git and "@" in configured_url_in_git:
                                        try:
                                            proto_cfg, rest_cfg = configured_url_in_git.split("://",1)
                                            creds_cfg, host_path_cfg = rest_cfg.split("@",1)
                                            user_cfg, token_cfg = creds_cfg.split(":",1)
                                            if token_cfg == GIT_TOKEN:
                                                display_configured_url_in_git = f"{proto_cfg}://{user_cfg}:<TOKEN_HIDDEN>@{host_path_cfg}"
                                        except ValueError:
                                            pass # Non fa nulla se il formato non è come atteso
                                    print(f"ℹ️ Remote '{GIT_REMOTE_NAME}' trovato con URL '{display_configured_url_in_git}'. Aggiornamento a '{display_remote_url}'...")
                                    _run_git_command(["remote", "set-url", GIT_REMOTE_NAME, target_remote_url_for_git], working_dir=git_repo_path)
                                else: # Remote non esiste
                                    print(f"ℹ️ Aggiunta remote '{GIT_REMOTE_NAME}' con URL '{display_remote_url}'...")
                                    _run_git_command(["remote", "add", GIT_REMOTE_NAME, target_remote_url_for_git], working_dir=git_repo_path)
                                print(f"✅ Remote '{GIT_REMOTE_NAME}' configurato/aggiornato.")
                            
                            # Pull delle modifiche (userà l'URL configurato nel remote)
                            print(f"ℹ️ Esecuzione git pull da {GIT_REMOTE_NAME} {GIT_BRANCH}...")
                            try:
                                _run_git_command(["pull", GIT_REMOTE_NAME, GIT_BRANCH], working_dir=git_repo_path)
                                print("✅ Git pull completato.")
                            except subprocess.CalledProcessError as e_pull:
                                stderr_lower = e_pull.stderr.lower() if e_pull.stderr else ""
                                if f"couldn't find remote ref {GIT_BRANCH}".lower() in stderr_lower or \
                                   f"no such ref was fetched".lower() in stderr_lower or \
                                   "fatal: couldn't find remote ref".lower() in stderr_lower:
                                    print(f"⚠️ Il branch '{GIT_BRANCH}' non è stato trovato sul remote '{GIT_REMOTE_NAME}'. Se è il primo push per questo branch, è normale. Verrà creato al push.")
                                elif "refusing to merge unrelated histories".lower() in stderr_lower:
                                    print(f"⚠️ Git pull fallito a causa di storie non correlate. Prova ad eseguire 'git pull {GIT_REMOTE_NAME} {GIT_BRANCH} --allow-unrelated-histories' manualmente se sai cosa stai facendo.")
                                    print("ℹ️ Lo script continuerà, ma le modifiche potrebbero non essere basate sull'ultima versione remota.")
                                else:
                                    print(f"❌ Errore durante git pull: {e_pull.stderr.strip() if e_pull.stderr else 'Nessun output di errore specifico.'}")
                                    # Non rilanciare l'eccezione qui per permettere allo script di continuare l'estrazione
                        except Exception as e_remote_setup:
                            print(f"❌ Errore durante la configurazione del remote Git o il pull: {e_remote_setup}")
                            print("ℹ️ Le operazioni Git di pull/push potrebbero non funzionare correttamente.")
                    else:
                        print("ℹ️ Nessun GIT_REMOTE_URL fornito. Le operazioni di pull/push saranno saltate.")
                except Exception as e_git_init_generic:
                    print(f"❌ Errore generico durante l'inizializzazione/configurazione Git: {e_git_init_generic}")
                    print("ℹ️ Versionamento Git potrebbe non funzionare come previsto.")
                    git_repo_path = None # Disabilita ulteriori operazioni Git se l'setup iniziale fallisce
        elif GIT_ENABLED and not GIT_TARGET_DIR:
            print("⚠️ Versionamento Git abilitato ma 'custom_output_root' non è specificato o non è valido in config.yaml. Versionamento Git saltato.")

        old_model = load_model(OLD_MODEL_PATH)
        model_path = extract_model(session, EXTRACT_FOLDER)
        new_model = load_model(model_path)

        # Metadata CSVs
        tables_df, fields_df, rels_df = collect_metadata(new_model)
        if SAVE_CSV:
            tables_df.to_csv(CSV_FOLDER / "tables.csv", index=False)
            fields_df.to_csv(CSV_FOLDER / "fields.csv", index=False)
            rels_df.to_csv(CSV_FOLDER / "relations.csv", index=False)
            print("💾 CSVs saved to", CSV_FOLDER)
        else:
            print("📄 CSV saving skipped by configuration.")

        # Overall XLSX with date
        if SAVE_EXCEL:
            xlsx_filename = f"Datamodel_{current_date}.xlsx"
            export_metadata_to_excel(tables_df, fields_df, rels_df, XLSX_FOLDER / xlsx_filename)
            print(f"💾 XLSX saved to {XLSX_FOLDER / xlsx_filename}")
        else:
            print("📄 Excel saving skipped by configuration.")

        # Diff JSON & Markdown
        if(old_model != None and new_model != None):
            diff = diff_models(old_model, new_model)
            if SAVE_JSON_DIFF:
                diff_json_filename = f"diff_report_{current_date}.json"
                DIFF_JSON_PATH = JSON_FOLDER / diff_json_filename # Nuovo percorso per diff_report.json
                DIFF_JSON_PATH.write_text(json.dumps(diff, indent=2, ensure_ascii=False), encoding="utf-8")
                print(f"💾 JSON Diff report saved to {DIFF_JSON_PATH}")
            else:
                print("📄 JSON Diff report saving skipped by configuration.")
            if SAVE_MARKDOWN_DIFF:
                DIFF_MD.write_text(diff_to_markdown(diff), encoding="utf-8")
                print(f"💾 Markdown Diff report saved to {DIFF_MD}")
            else:
                print("📄 Markdown Diff report saving skipped by configuration.")
        else:
            diff = None # Ensure diff is None if models are not available for changelog
            print("📄 Diff reports skipped due to missing old or new model.")

        # Update changelog
        if SAVE_CHANGELOG:
            update_changelog(CHANGELOG_MD, model_name, current_date, diff)
        else:
            print("📄 Changelog update skipped by configuration.")

        # Copy database.json to JSON_FOLDER with date
        if SAVE_DATABASE_COPY:
            if model_path.exists():
                database_json_copy_filename = f"database_{current_date}.json"
                DATABASE_JSON_COPY_PATH = JSON_FOLDER / database_json_copy_filename
                import shutil # Importa shutil per copiare il file
                shutil.copy2(model_path, DATABASE_JSON_COPY_PATH)
                print(f"💾 Copied database.json to {DATABASE_JSON_COPY_PATH}")
            else:
                print("📄 database.json copy skipped: source file not found.")
        else:
            print("📄 database.json copy skipped by configuration.")

        # Mermaid ER
        if SAVE_MERMAID_ER:
            MERMAID_MD.write_text(model_to_mermaid(tables_df,rels_df), encoding="utf-8")
            print("💾 Mermaid ER saved to", MERMAID_MD)
        else:
            print("📄 Mermaid ER diagram saving skipped by configuration.")

        print("✅ Operation completed successfully.")

        # --- Operazioni Git Finali ---
        if GIT_ENABLED and git_repo_path: # Procede solo se Git è abilitato e il path del repo è valido
            print(f"ℹ️ Esecuzione operazioni Git finali in: {git_repo_path}")
            try:
                # Controlla lo stato prima di 'add' per loggare se ci sono modifiche
                status_proc_before_add = _run_git_command(["status", "--porcelain"], working_dir=git_repo_path)
                if status_proc_before_add.stdout.strip() and VERBOSE:
                    print(f"ℹ️ Modifiche rilevate prima di 'git add .':\n{status_proc_before_add.stdout.strip()}")
                elif not status_proc_before_add.stdout.strip() and VERBOSE:
                    print("ℹ️ Nessuna modifica rilevata da 'git status --porcelain' prima di 'git add .'")

                print("ℹ️ Esecuzione git add . ...")
                _run_git_command(["add", "."], working_dir=git_repo_path)
                print("✅ Git add completato.")

                # Controlla se ci sono modifiche staged per il commit
                # `git diff --staged --quiet` esce con 0 se non c'è nulla, 1 se ci sono modifiche staged
                anything_to_commit = False
                try:
                    _run_git_command(["diff", "--staged", "--quiet"], working_dir=git_repo_path)
                    # Se arriva qui, `git diff --staged --quiet` ha restituito 0 (nessuna modifica staged)
                    print("ℹ️ Nessuna modifica rilevata dopo 'git add .'. Commit saltato.")
                except subprocess.CalledProcessError:
                    # `git diff --staged --quiet` ha restituito un codice diverso da 0, significa che ci sono modifiche staged
                    anything_to_commit = True
                
                if anything_to_commit:
                    commit_message = f"{GIT_COMMIT_PREFIX}: {model_name} - {current_date}"
                    print(f"ℹ️ Creazione commit Git con messaggio: '{commit_message}'")
                    _run_git_command(["commit", "-m", commit_message], working_dir=git_repo_path)
                    print("✅ Commit Git creato.")

                    if GIT_REMOTE_URL:
                        print(f"ℹ️ Esecuzione git push a {GIT_REMOTE_NAME} {GIT_BRANCH}...")
                        try:
                            # Usare -u per impostare l'upstream per il branch la prima volta o se non impostato
                            _run_git_command(["push", "-u", GIT_REMOTE_NAME, GIT_BRANCH], working_dir=git_repo_path)
                            print("✅ Git push completato.")
                        except subprocess.CalledProcessError as e_push:
                            print(f"❌ Errore durante git push: {e_push.stderr.strip() if e_push.stderr else 'Nessun output di errore specifico.'}")
                            print("ℹ️ Potrebbe essere necessario risolvere conflitti o problemi di autenticazione manualmente.")
                    else:
                        print("ℹ️ Nessun GIT_REMOTE_URL configurato. Push saltato.")
                else:
                    # Questo caso è già coperto sopra, ma per chiarezza.
                    # print("ℹ️ Nessuna modifica da committare.")
                    pass

            except subprocess.CalledProcessError as e_git_final:
                # Gli errori specifici dei comandi sono già loggati da _run_git_command
                print(f"❌ Fallimento durante le operazioni Git finali (add/commit/push). Controllare i log sopra.")
            except Exception as e_git_final_generic:
                print(f"❌ Errore generico durante le operazioni Git finali: {e_git_final_generic}")
        elif GIT_ENABLED and not git_repo_path:
             print("⚠️ Versionamento Git abilitato ma il repository non è stato inizializzato o configurato correttamente. Operazioni Git finali saltate.")

    except Exception as exc:
        print(f"❌ Errore generale nello script: {exc}")
        # Considerare se uscire con sys.exit(1) qui o permettere la fine per eventuali cleanup
        # Per ora, manteniamo il comportamento originale di uscire in caso di errore non gestito.
        sys.exit(1)

if __name__ == "__main__":
    main()




