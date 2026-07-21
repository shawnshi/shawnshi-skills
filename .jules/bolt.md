## 2026-06-22 - Avoiding pandas iterrows in dictionary comprehensions
**Learning:** Using `df.iterrows()` inside dictionary comprehensions creates significant overhead by instantiating new Series objects for each row, making it extremely slow for large datasets.
**Action:** Use vectorized iterations like `zip(df['key_col'], df['val_col'])` instead, which iterate over underlying NumPy arrays and are significantly faster.
## $(date +%Y-%m-%d) - Avoiding pandas apply with axis=1 for performance
**Learning:** Using `.apply(..., axis=1)` to perform row-by-row computations in Pandas DataFrames is extremely inefficient and slow, acting as a significant performance bottleneck for large datasets compared to using underlying vectorized C/NumPy operations.
**Action:** Replace `df.apply(..., axis=1)` with vectorized column arithmetic and built-in Pandas/NumPy methods (such as `.clip(lower=0)` as a vectorized alternative to `max(0, x)`) to achieve massive performance gains.

## 2026-06-29 - Optimize SpO2 map dictionary creation
**Learning:** Using `to_dict('records')` inside a list comprehension for simple two-column mapping is highly inefficient, creating large overhead by allocating many intermediate dictionaries.
**Action:** Use `dict(zip(df['col1'], df['col2']))` to bypass intermediate list creation and leverage NumPy's underlying contiguous arrays for a ~4.3x speedup.
## 2026-07-07 - Avoiding next() with generator in loops
**Learning:** Using `next()` with a generator expression inside a loop creates an O(N²) performance bottleneck, which is particularly slow for large datasets.
**Action:** Use an O(N) dictionary (hash map) lookup by pre-computing a dictionary before the loop.
## 2026-07-08 - Optimize RHR Baseline Calculation
**Learning:** Computing baseline values by backward scanning `next()` and then filtering the array by checking `!= latest_value` creates both an O(N) performance bottleneck and accidentally discards valid historical records that happen to equal the latest value.
**Action:** Use a single O(N) list comprehension to extract all valid values, then use `[-1]` for the latest and `[:-1]` for the historical baseline to ensure correctness and improve speed.
## 2026-07-11 - Avoiding redundant JSON I/O and O(N^2) lookups
**Learning:** Repeatedly parsing a JSON file and linearly scanning a list within a loop across items leads to severe O(N^2) complexity and I/O bottlenecks.
**Action:** Use an in-memory modification-time-based cache for JSON files loaded in a loop, and pre-compute a dictionary (hash map) to transform O(N) list searches into O(1) lookups.
## 2026-07-14 - Avoiding pandas apply with list comprehensions for string parsing
**Learning:** Using `.apply()` in Pandas with a custom function for string parsing (like converting time strings to seconds) incurs significant overhead because it instantiates a Pandas Series for every row.
**Action:** Replace `.apply()` with Python list comprehensions (`[func(x) for x in df['col']]`) to bypass this overhead and iterate at C-speed in Python, achieving substantial performance gains over `.apply()` and sometimes even over `pd.to_timedelta()`.
## 2026-07-19 - Avoiding sequential outer category fetching for API aggregators
**Learning:** Even if individual network category fetches (like sleep, hrv) use concurrency internally for fetching multiple days, grouping them sequentially at the top level forces sequential blocking on network I/O per category, leading to substantial overhead and poor parallelism.
**Action:** Use a `ThreadPoolExecutor` to dispatch these top-level category requests concurrently, drastically overlapping latency across independent domain models.
## 2026-07-21 - Optimize statistics.mean overhead
**Learning:** Python's built-in `statistics.mean()` is mathematically robust (preventing float precision loss by internally converting to fractions) but has significant overhead for large datasets compared to a simple `sum() / len()` calculation, causing ~80x slower execution in certain contexts.
**Action:** For simple float/integer averages where extreme precision is not required (e.g., temperatures, health metrics), replace `statistics.mean(lst)` with `sum(lst) / len(lst)` for massive speed improvements.
