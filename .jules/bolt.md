
## 2024-05-18 - Dictionary Lookup Optimization in Comprehensions
**Learning:** Redundant dictionary lookups (e.g., `[d.get("key") for d in data if d.get("key")]`) are a common anti-pattern in Python scripts handling JSON/dictionary list data. This requires the Python interpreter to perform the dictionary lookup twice for every matching element.
**Action:** Always use the walrus operator (`:=`) to capture the value during the condition check (`[val for d in data if (val := d.get("key"))]`). In `personal-health-analysis/scripts/garmin_intelligence.py`, this provided a ~12% performance improvement for iterative parsing of health metrics.
