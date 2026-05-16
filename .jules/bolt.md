## 2025-03-08 - Pandas Iteration Overhead
**Learning:** Using df.iterrows() inside comprehensions or loops introduces significant overhead due to Series instantiation for every row.
**Action:** Always prefer zip(df['col1'], df['col2']) for vectorizable iteration or df.itertuples() for row-by-row iteration yielding lightweight namedtuples.
