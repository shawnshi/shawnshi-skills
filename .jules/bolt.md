## 2024-05-24 - Optimize pandas dictionary comprehensions

**Learning:** Using `df.iterrows()` inside dictionary comprehensions (e.g., `{r['date']: r['val'] for _, r in df.iterrows()}`) creates significant overhead by instantiating new Series objects for each row.

**Action:** Use vectorized iterations like `zip(df['key_col'], df['val_col'])` instead, which iterate over underlying NumPy arrays directly and perform much faster.
