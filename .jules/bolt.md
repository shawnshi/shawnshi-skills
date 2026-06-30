## 2026-06-22 - Avoiding pandas iterrows in dictionary comprehensions
**Learning:** Using `df.iterrows()` inside dictionary comprehensions creates significant overhead by instantiating new Series objects for each row, making it extremely slow for large datasets.
**Action:** Use vectorized iterations like `zip(df['key_col'], df['val_col'])` instead, which iterate over underlying NumPy arrays and are significantly faster.
## $(date +%Y-%m-%d) - Avoiding pandas apply with axis=1 for performance
**Learning:** Using `.apply(..., axis=1)` to perform row-by-row computations in Pandas DataFrames is extremely inefficient and slow, acting as a significant performance bottleneck for large datasets compared to using underlying vectorized C/NumPy operations.
**Action:** Replace `df.apply(..., axis=1)` with vectorized column arithmetic and built-in Pandas/NumPy methods (such as `.clip(lower=0)` as a vectorized alternative to `max(0, x)`) to achieve massive performance gains.

## 2026-06-29 - Optimize SpO2 map dictionary creation
**Learning:** Using `to_dict('records')` inside a list comprehension for simple two-column mapping is highly inefficient, creating large overhead by allocating many intermediate dictionaries.
**Action:** Use `dict(zip(df['col1'], df['col2']))` to bypass intermediate list creation and leverage NumPy's underlying contiguous arrays for a ~4.3x speedup.
