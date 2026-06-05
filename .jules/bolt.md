## 2025-06-05 - Iterrows in list/dict comprehensions
**Learning:** Using `df.iterrows()` inside dictionary or list comprehensions creates significant overhead by instantiating new Series objects for every row, making it notoriously slow for pandas DataFrame iterations.
**Action:** Use vectorized operations like `zip(df['col1'], df['col2'])` instead of `iterrows` for dictionary comprehensions, which iterates directly over underlying numpy arrays and is significantly faster (measured ~30x speedup in dict generation).
