## 2026-05-31 - Pandas Iteration Overhead
**Learning:** Using `df.iterrows()` inside comprehensions or loops introduces significant overhead by instantiating new Series objects for every row.
**Action:** Use vectorized operations like `zip(df['col1'], df['col2'])` for comprehensions, and prefer `df.itertuples()` for general row iteration loops.
