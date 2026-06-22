## 2026-06-22 - Avoiding pandas iterrows in dictionary comprehensions
**Learning:** Using `df.iterrows()` inside dictionary comprehensions creates significant overhead by instantiating new Series objects for each row, making it extremely slow for large datasets.
**Action:** Use vectorized iterations like `zip(df['key_col'], df['val_col'])` instead, which iterate over underlying NumPy arrays and are significantly faster.
