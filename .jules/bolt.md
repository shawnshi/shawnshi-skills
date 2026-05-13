## 2024-05-14 - Optimize pandas iteration
**Learning:** `df.iterrows()` inside dictionary comprehensions (like `{r['date']: r['val'] for _, r in df.iterrows()}`) creates significant overhead by instantiating new Series objects for every single row.
**Action:** Always prefer iterating over underlying numpy arrays using `zip()` (e.g., `zip(df['date'], df['val'])`) when mapping columns to dictionaries or performing simple row-wise operations in pandas, which avoids Series creation overhead entirely.
