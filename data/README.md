# data/

Everything in this folder except this file is git-ignored.

```
data/
├── sportsim.db       # SQLite database (python -m sportsim.mlb.db build)
├── cache/            # raw HTML pages, so re-runs don't hit Baseball-Reference again
└── mlb/
    └── 2026/
        ├── teams_batting_2026.csv
        ├── teams_pitching_2026.csv
        ├── players_batting_2026.csv
        ├── players_pitching_2026.csv
        ├── rosters_2026.csv          # only with --rosters
        └── table_ids_seen.txt        # debugging aid if a table comes back empty
```

To fill it: `python -m sportsim.mlb.scrapers.bref` from the repo root.
