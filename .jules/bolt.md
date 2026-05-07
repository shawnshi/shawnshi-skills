## 2026-05-07 - [Optimize SQLite bulk updates]
**Learning:** Always prefer `executemany` over a loop of `execute` statements when performing bulk inserts or updates in SQLite databases within Python.
**Action:** Use `executemany` to reduce overhead and significantly improve performance for large datasets.
