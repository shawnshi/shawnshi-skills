## 2024-05-28 - iterrows vs zip/itertuples in pandas
**Learning:** Using `df.iterrows()` inside comprehensions and loops introduces significant overhead (~20x slower for dict comprehensions, ~4x slower for simple loops) in Python because it creates new Series objects for every row.
**Action:** Replace `df.iterrows()` inside dictionary comprehensions with vectorized iterations like `zip(df['col1'], df['col2'])`, and for general loops over DataFrames use `df.itertuples()`.
