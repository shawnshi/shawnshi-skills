## 2024-05-15 - [Pandas Iteration Bottleneck]
**Learning:** In heavily used data processing scripts (`garmin_chart.py`, `yf.py`), iterating over pandas DataFrames using `iterrows()` introduces massive overhead by instantiating new `Series` objects for every row, blocking the main thread execution unnecessarily for large datasets.
**Action:** Always replace `iterrows()` in dictionary comprehensions with column-specific vectorized `zip()` iterations, and for general loops, replace with `itertuples()` to yield lightweight namedtuples without sacrificing clean dot-notation readability.
