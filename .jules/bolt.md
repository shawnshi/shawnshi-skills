## 2024-05-19 - [SQLite Bulk Updates]
**Learning:** Python-to-SQLite overhead from calling execute() repeatedly in a loop is significant.
**Action:** When performing bulk updates or inserts, collect the parameters in a list and use executemany().
