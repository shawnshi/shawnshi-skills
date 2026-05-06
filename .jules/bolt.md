## 2024-05-23 - SQLite executemany Performance
**Learning:** In Python, using `executemany` for bulk database operations (inserts, updates) is significantly faster than looping over individual `execute` calls because it minimizes the overhead of repeatedly calling the SQLite C API and passing queries through the Python-C boundary. Our benchmark showed a ~24% to ~30% improvement depending on the dataset size.
**Action:** Always prefer `executemany` over a loop of `execute` statements when performing bulk inserts or updates in SQLite databases within Python.
