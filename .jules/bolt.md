## 2024-05-24 - SQLite executemany Performance
**Learning:** In `slide-blocks/setup_paths.py`, replacing iterative `UPDATE` calls with `executemany()` for batch updates provides a measurable performance improvement of approximately 38% for large datasets (e.g., 100,000 rows).
**Action:** Always prefer `executemany` over a loop of `execute` statements when performing bulk inserts or updates in SQLite databases within Python.
