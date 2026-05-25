
## 2026-05-25 - Pandas DataFrame Iteration Optimization
**Learning:** Using `df.iterrows()` inside dictionary comprehensions or loops creates significant overhead by instantiating new Series objects for each row.
**Action:** Use vectorized `zip(df['col1'], df['col2'])` for dictionary comprehensions and `df.itertuples()` for row iterations to yield lightweight namedtuples, significantly improving performance.
