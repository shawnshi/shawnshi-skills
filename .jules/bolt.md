## 2024-05-24 - Optimize pandas dictionary comprehensions
**Learning:** Using `df.iterrows()` inside dictionary comprehensions creates significant overhead due to instantiating new Series objects for each row.
**Action:** Use vectorized iterations like `zip(df['key_col'], df['val_col'])` instead, which iterate over underlying NumPy arrays and provide massive speedups.
