## 2024-05-24 - [Avoid statistics.mean for simple Python lists]
**Learning:** The Python `statistics.mean` module carries extreme overhead (~64x slower than built-in `sum()/len()`) due to its internal type-checking and precision-preservation loops. When calculating averages over thousands of float values for health metrics, this causes significant aggregation bottlenecks.
**Action:** Use `sum(lst)/len(lst)` instead of `statistics.mean` anywhere precision to the exact fractional margin isn't strictly required, especially in performance-sensitive metric processing pipelines.
