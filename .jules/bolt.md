## 2026-06-01 - Avoid Pandas iterrows() overhead
**Learning:** Using `df.iterrows()` inside dictionary comprehensions or loops creates significant overhead by instantiating new Series objects for every row.
**Action:** Use vectorized iterations like `zip(df['col1'], df['col2'])` for dictionary comprehensions, and `df.itertuples()` to yield lightweight namedtuples for general row iteration loops.
