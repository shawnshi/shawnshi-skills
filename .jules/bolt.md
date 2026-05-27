## 2026-05-27 - Pandas iterrows() overhead in Dictionary Comprehensions
**Learning:** Using `df.iterrows()` inside dictionary comprehensions creates massive overhead (~23x slower) because it instantiates a new Pandas Series object for every single row.
**Action:** Always use vectorized iterations like `zip(df['key_col'], df['val_col'])` to iterate directly over underlying NumPy arrays when building mappings from DataFrames.
