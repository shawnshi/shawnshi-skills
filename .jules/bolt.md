## 2026-05-24 - Pandas Row Iteration Overhead
**Learning:** Using `df.iterrows()` inside loops or dictionary comprehensions creates significant overhead (up to ~20x slower) because it instantiates new Series objects for every row.
**Action:** Use vectorized iterations like `zip(df['key_col'], df['val_col'])` for dictionary comprehensions, and prefer `df.itertuples()` for general row iteration loops to yield lightweight namedtuples.
