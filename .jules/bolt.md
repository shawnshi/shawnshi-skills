## 2026-05-23 - Avoid pandas iterrows
**Learning:** Using `df.iterrows()` inside dictionary comprehensions or loops instantiates new Series objects for every row, which generates massive overhead.
**Action:** For dictionary comprehensions, use vectorized iterations like `zip(df['key_col'], df['val_col'])`. For general row iteration loops, prefer `df.itertuples()` to yield lightweight namedtuples.
