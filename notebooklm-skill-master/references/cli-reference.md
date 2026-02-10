# NotebookLM CLI Reference

**Note**: All commands MUST be prefixed with `python scripts/run.py`.

## 1. Authentication (`auth_manager.py`)
- `status`: Check if currently logged in.
- `setup`: Initial Google login (opens visible browser).
- `clear`: Delete all credentials and cookies.

## 2. Library Management (`notebook_manager.py`)
- `list`: Show all registered notebooks and their IDs.
- `add --url [URL] --name [NAME] --description [DESC] --topics [TAGS]`: Add new.
- `activate --id [ID]`: Set default notebook for future queries.
- `remove --id [ID]`: Delete from local library.

## 3. Querying (`ask_question.py`)
- `--question "..."`: The primary query string.
- `--notebook-id [ID]`: Override default notebook.
- `--notebook-url [URL]`: One-time query to a specific URL.
- `--show-browser`: Open visible window for debugging.

## 4. Maintenance (`cleanup_manager.py`)
- `--confirm`: Clear all temp browser states but keep the library.
