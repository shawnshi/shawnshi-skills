## 2026-05-21 - Replace pandas iterrows
**Learning:** Using `df.iterrows()` inside dictionary comprehensions or loops creates significant overhead by instantiating new Series objects for every row.
**Action:** For dictionary comprehensions, use vectorized iterations like `zip(df['key_col'], df['val_col'])`. For general row iteration loops, use `df.itertuples()` to yield lightweight namedtuples.
