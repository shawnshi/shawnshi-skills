# Bolt's Performance Journal
## 2026-06-09 - [Pandas DataFrame Iteration Overhead]
**Learning:** Using `df.iterrows()` inside dictionary comprehensions (e.g., `{r['date']: r['val'] for _, r in df_pmc.iterrows()}`) creates significant overhead by instantiating new Series objects for every row, making it extremely slow.
**Action:** Use vectorized iterations like `zip(df['key_col'], df['val_col'])` instead, which iterate over underlying NumPy arrays directly and yield a ~30x speedup. For general row iteration, prefer `df.itertuples()`.
