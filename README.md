# Power BI Model Extractor & Versioning Tool

## Overview

This project provides a Python-based solution to extract the structure of a Power BI model (`.pbix`) using [pbi-tools](https://github.com/pbi-tools/pbi-tools). It generates comprehensive metadata in various formats (CSV, Excel, JSON diff, Markdown diff, Mermaid ER diagrams), and optionally manages version control through automated Git operations.

The primary goal is to automate the tracking of model changes, streamline technical documentation, and facilitate collaboration by maintaining a versioned history of the Power BI model's schema.

---

## Features

*   **Model Extraction**: Leverages `pbi-tools` to extract model metadata from an active Power BI Desktop session.
*   **Metadata Generation**: Produces detailed information about tables, columns, measures, and relationships.
*   **Multiple Output Formats**:
    *   CSV files for easy data analysis.
    *   Excel reports consolidating all metadata.
    *   JSON diff files highlighting changes between model versions.
    *   Markdown reports summarizing these differences.
    *   Mermaid syntax for Entity-Relationship (ER) diagrams.
*   **Changelog**: Automatically updates a changelog for each model, tracking its evolution.
*   **Backup**: Saves timestamped copies of the raw `database.json` model and the `.pbix` file (as a ZIP archive).
*   **Git Integration (Optional)**:
    *   Initializes a Git repository in the output directory.
    *   Configures remote repository (supports token-based authentication via `.env`).
    *   Automatically stages, commits, and pushes changes to the specified branch.
*   **Configuration**: Highly configurable via `config.yaml` for paths, extraction options, output elements, and Git settings.
*   **Logging**: Provides detailed logging for troubleshooting and monitoring.

---

## Prerequisites

*   **Python** >= 3.10.
*   **pbi-tools**: Version 1.0.0-beta.7 or newer. Ensure `pbi-tools.exe` is accessible. ([Download from pbi-tools releases](https://github.com/pbi-tools/pbi-tools/releases)).
*   **Git**: Must be installed and accessible in the system's `PATH` if Git integration is enabled.

---

## Installation

1.  **Clone the Repository**:
    ```bash
    git clone <repository_url>
    cd PBI-VCS # Or your project directory name
    ```

2.  **Install Dependencies**:
    It's highly recommended to use a virtual environment:
    ```bash
    python -m venv .venv
    # Activate the virtual environment
    # On Windows:
    .venv\Scripts\activate
    # On macOS/Linux:
    # source .venv/bin/activate

    pip install -r requirements.txt
    ```

3.  **Configuration**:
    *   Copy `config.example.yaml` to `config.yaml` and customize it.
    *   Copy `.env.example` to `.env` and provide your Git credentials if using Git integration with a private repository.

    See the [Configuration Details](#configuration-details) section below.

---

## How to Use

1.  **Open Power BI Desktop**: Load the `.pbix` file whose model you want to extract and analyze.
2.  **Run the Script**:
    Navigate to the project's root directory in your terminal (where `src/` and `config.yaml` are located) and execute:
    ```bash
    python src/main.py
    ```
3.  **Check Outputs**: Output files will be generated in the directory specified by `custom_output_root` in `config.yaml`. If `custom_output_root` is not set, outputs will be in a folder named `out/` within your project directory. Each PBIX model will have its own subfolder within this output directory.
4.  **Git Operations (if enabled)**: If Git integration is active, the script will attempt to commit and push the changes to your configured remote repository.

---

## Project Structure

```
.PBI-VCS/
├── .vscode/                # VSCode settings (optional)
├── src/
│   ├── pbi_extractor/      # Core logic for extraction, parsing, diffing, exporting
│   │   ├── __init__.py
│   │   ├── changelog_manager.py
│   │   ├── cli_utils.py
│   │   ├── config_manager.py
│   │   ├── diff_engine.py
│   │   ├── file_exporters.py
│   │   ├── git_manager.py
│   │   ├── logger_setup.py
│   │   ├── metadata_parser.py
│   │   └── pbi_interaction.py
│   ├── __init__.py
│   └── main.py             # Main script entry point
├── .env                    # Git credentials (GIT_USERNAME, GIT_TOKEN)
├── .env.example            # Example for .env file
├── .gitignore              # Specifies intentionally untracked files
├── config.yaml             # Main configuration for paths, options, and outputs
├── config.example.yaml     # Example for config.yaml
├── extractor.py            # (Old script - will be removed after refactoring)
├── LICENSE                 # Project's license information
├── README.md               # This file
└── requirements.txt        # Python dependencies
```

---

## Configuration Details

### `config.yaml`

This file controls the behavior of the script. Key sections:

| Section           | Parameter              | Description                                                                                                | Example                                                                    |
| ----------------- | ---------------------- | ---------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| `paths`           | `pbi_tools_exe`        | **Required.** Full path to the `pbi-tools.exe` executable.                                                 | `C:/apps/pbi-tools/pbi-tools.exe` or `/usr/local/bin/pbi-tools.exe`        |
|                   | `custom_output_root`   | Optional. Root directory for all outputs. If empty, defaults to `PROJECT_ROOT/out/`.                       | `D:/PBI_Exports`                                                           |
| `options`         | `extract_mode`         | `pbi-tools` extraction mode (`Auto`, `Full`, `Basic`). `Auto` is recommended.                              | `Auto`                                                                     |
|                   | `model_serialization`  | `pbi-tools` model serialization format (`Raw`, `Default`). `Raw` is often preferred for detailed diffs.    | `Raw`                                                                      |
|                   | `mashup_serialization` | `pbi-tools` mashup (Power Query) serialization (`Default`, `Full`).                                        | `Default`                                                                  |
|                   | `verbose`              | Enable detailed console logging (`true`/`false`). Sets log level to DEBUG if true.                         | `false`                                                                    |
| `output_elements` | `save_csv`             | Save metadata (tables, fields, relationships) as CSV files.                                                | `true`                                                                     |
|                   | `save_excel`           | Save consolidated metadata into an Excel file.                                                             | `true`                                                                     |
|                   | `save_json_diff`       | Save structural differences between the current and previous model in JSON format.                         | `true`                                                                     |
|                   | `save_markdown_diff`   | Save a human-readable summary of model differences in Markdown format.                                     | `true`                                                                     |
|                   | `save_mermaid_er`      | Save an Entity-Relationship diagram in Mermaid syntax (can be rendered by Markdown viewers).               | `true`                                                                     |
|                   | `save_changelog`       | Create/update a `CHANGELOG.md` file for the processed model, summarizing changes.                          | `true`                                                                     |
|                   | `save_database_copy`   | Save a timestamped copy of the extracted `database.json` file.                                             | `true`                                                                     |
|                   | `save_pbix_zip`        | Save a timestamped ZIP archive of the original `.pbix` file.                                               | `false`                                                                    |
|                   | `granularity_output`        | Format `string` for granularity timestamped output files                                               | `%Y%m%d`
| `git`             | `enabled`              | Enable Git versioning features (`true`/`false`).                                                           | `false`                                                                    |
|                   | `remote_url`           | URL of the remote Git repository (e.g., GitHub, GitLab). Required if `enabled` is `true`.                  | `https://github.com/your_username/your_pbi_models_repo.git`                |
|                   | `branch`               | Target branch for commits and pushes (e.g., `main`, `master`).                                             | `main`                                                                     |
|                   | `commit_prefix`        | Prefix for automated commit messages.                                                                      | `[AUTO] PBI Model Sync`                                                    |
|                   | `remote_name`          | Name of the Git remote (usually `origin`).                                                                 | `origin`                                                                   |

### `.env`

This file stores sensitive credentials and should **not** be committed to your repository. Ensure it's listed in your `.gitignore` file.

| Variable       | Description                                                                 | Example                           |
| -------------- | --------------------------------------------------------------------------- | --------------------------------- |
| `GIT_USERNAME` | Username for Git authentication (often used with HTTPS PATs).               | `your-git-username`               |
| `GIT_TOKEN`    | Personal Access Token (PAT) for Git services like GitHub, GitLab, Azure DevOps. | `ghp_YourGitHubPersonalAccessToken` |

If `GIT_USERNAME` and `GIT_TOKEN` are provided and `git.remote_url` is an HTTPS URL, the script will attempt to use these for authentication when pushing to the remote repository.

---


## Troubleshooting

*   **`pbi-tools` not found**: Ensure the `pbi_tools_exe` path in `config.yaml` is correct and that `pbi-tools` is installed and executable.
*   **No Power BI Session Found**: Make sure Power BI Desktop is running and the target `.pbix` file is open before running the script.
*   **Git Authentication Errors**: If using Git integration with a private repository, verify your `GIT_USERNAME` and `GIT_TOKEN` in the `.env` file are correct and have the necessary permissions.
*   **File Path Issues on Windows**: Use forward slashes (`/`) or double backslashes (`\\`) for paths in `config.yaml` to avoid issues with escape characters.
*   **Check Logs**: The script generates log files (by default in `[output_root]/[model_name]/logs/`). Review these logs for detailed error messages.

---

## Contributing

Contributions, issues, and feature requests are welcome. Please open an issue or submit a pull request to the repository.

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
