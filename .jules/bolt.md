## 2024-05-14 - Optimize pandas iterrows
**Learning:** `df.iterrows()` inside dictionary comprehensions creates significant overhead by instantiating new Series objects for every row. Vectorized iterations like `zip(df['key'], df['value'])` are much faster since they iterate over the underlying NumPy arrays directly.
**Action:** Replace `iterrows()` with `zip()` for dictionary mapping loops over pandas DataFrames.
