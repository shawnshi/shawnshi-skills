## 2024-05-18 - Dictionary lookup optimization in list comprehensions
**Learning:** List comprehensions using `.get()` in both the yield expression and the filter condition result in redundant dictionary lookups (e.g., `[a.get('key') for a in data if a.get('key')]`).
**Action:** Use the walrus operator (`:=`) to assign and filter the value in a single step (e.g., `[val for a in data if (val := a.get('key'))]`), which eliminates the duplicate lookup and improves loop performance.
