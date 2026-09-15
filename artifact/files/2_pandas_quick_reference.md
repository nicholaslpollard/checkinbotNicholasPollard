# Pandas quick reference (Week 5)

| Task | Code |
|------|------|
| Load JSON rows | `df = pd.DataFrame(rows)` |
| Load a CSV | `df = pd.read_csv("file.csv")` |
| First rows | `df.head()` |
| Column types | `df.dtypes` |
| Summary stats | `df.describe()` |
| Count per group | `df.groupby("genre").size()` |
| Mean per group | `df.groupby("genre")["rating"].mean()` |
| Filter rows | `df[df["year"] >= 2000]` |
| Sort | `df.sort_values("rating", ascending=False)` |
| Plot | `df.groupby("genre").size().plot(kind="bar")` |
