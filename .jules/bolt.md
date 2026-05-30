## 2026-05-30 - Optimize Pandas dataframe iteration
**Learning:** Using `df.iterrows()` inside comprehensions and loops creates significant overhead by instantiating new Series objects for each row.
**Action:** Use vectorized iterations like `zip(df['col1'], df['col2'])` for dictionaries, and `df.itertuples()` for row iteration loops to yield lightweight namedtuples.
