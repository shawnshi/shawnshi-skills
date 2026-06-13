## 2025-02-18 - Pandas iterrows Overheads in Comprehensions
**Learning:** Using `df.iterrows()` inside dictionary comprehensions (e.g., `{r['date']: r['val'] for _, r in df.iterrows()}`) creates massive overhead due to Pandas instantiating new Series objects for every row, severely degrading performance.
**Action:** Replace `iterrows()` with `zip()` over the underlying Series (e.g., `zip(df['date'], df['val'])`), which is ~28x faster as it leverages fast NumPy iteration.
