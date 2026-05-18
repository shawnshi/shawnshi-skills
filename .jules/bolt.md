## 2026-05-18 - Pandas Iteration Overhead
**Learning:** Using `df.iterrows()` inside dictionary comprehensions or large loops creates significant overhead by instantiating new Series objects for each row. For vectorizable mappings, `zip(df['col1'], df['col2'])` is significantly faster. For general loops, `df.itertuples()` yields lightweight namedtuples and avoids Series creation overhead.
**Action:** Always avoid `df.iterrows()`. Prefer `zip()` for dictionary comprehension mappings and `df.itertuples()` for generic row iterations to improve performance.
