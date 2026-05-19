## 2026-05-19 - Pandas Iteration Performance
**Learning:** Using `df.iterrows()` inside loops or dictionary comprehensions instantiates expensive Series objects for every row, significantly impacting performance on large datasets.
**Action:** Replace `df.iterrows()` with vectorized approaches like `zip(df['col1'], df['col2'])` for dictionary comprehension lookups, and use `df.itertuples()` for general iteration loops yielding lightweight namedtuples.
