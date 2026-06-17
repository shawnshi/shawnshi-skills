## 2025-02-19 - Pandas iterrows Bottleneck
**Learning:** In `personal-health-analysis/scripts/garmin_chart.py`, creating dictionary comprehensions using `df.iterrows()` to map dates to values creates significant overhead due to Pandas repeatedly instantiating Series objects for each row (~7.25s for 100 iterations on 365 rows).
**Action:** Use vectorized alternatives like `zip(df['key_col'], df['val_col'])` instead of `iterrows()`, which iterate over the underlying NumPy arrays and are dramatically faster (~0.27s, ~27x speedup).
