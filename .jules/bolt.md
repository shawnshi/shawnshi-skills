## 2026-06-12 - Optimize Pandas row iteration in garmin_chart.py
**Learning:** Using `df.iterrows()` inside dictionary comprehensions (e.g., `{r['date']: r['val'] for _, r in df.iterrows()}`) creates significant overhead by instantiating new Series objects for every row.
**Action:** Replace `iterrows()` with vectorized iterations like `zip(df['key_col'], df['val_col'])` when building dictionaries from DataFrames, as it iterates over underlying NumPy arrays directly.
