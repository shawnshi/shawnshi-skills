
## 2026-05-17 - Pandas Row Iteration Overhead
**Learning:** Using `df.iterrows()` inside dictionary comprehensions or large loops creates significant overhead by instantiating new Series objects for every row.
**Action:** Always prefer vectorized iteration with `zip(df['col1'], df['col2'])` for comprehensions, or `df.itertuples()` which yields lightweight namedtuples for general loops.
