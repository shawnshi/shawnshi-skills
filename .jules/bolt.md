## 2025-02-12 - Pandas iterrows() overhead
**Learning:** For pandas DataFrames, `df.iterrows()` inside dictionary comprehensions (e.g., `{r['date']: r['val'] for _, r in df.iterrows()}`) creates significant overhead by instantiating new Series objects for every row.
**Action:** Use vectorized iterations like `zip(df['key_col'], df['val_col'])` instead, which iterate over underlying NumPy arrays directly.
