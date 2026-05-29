## 2026-05-29 - Avoid df.iterrows() in comprehensions
**Learning:** Using `df.iterrows()` inside dictionary comprehensions creates significant overhead by instantiating new Series objects on each iteration.
**Action:** Use vectorized iterations like `zip(df['key_col'], df['val_col'])` instead, which iterate over underlying NumPy arrays directly.
