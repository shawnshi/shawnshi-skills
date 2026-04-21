## 2024-04-21 - Optimizing Python comprehensions with Walrus Operator
**Learning:** Found a common pattern of `[d.get("key") for d in data if d.get("key")]` which performs the dictionary lookup `get("key")` twice per item.
**Action:** Use the walrus operator `:=` in the conditional part `[val for d in data if (val := d.get("key"))]` to capture the result of the lookup, saving O(n) method calls per comprehension.
