# Changelog

Newest first. Add a line here whenever you finish something worth remembering.

## 2026-11-23
- Added SQLite database (`sportsim.mlb.db`): loads scraped CSVs into `data/sportsim.db`, combines traded players into season totals with recomputed rate stats, extracts bats/throws, CLI for build / tables / query. See docs/DATABASE.md.
- Project set up: package layout, docs, tests, GitHub Actions.
- Added Baseball-Reference scraper (`sportsim.mlb.scrapers.bref`): team batting/pitching, player batting/pitching, optional 40-man rosters. Rate-limited to 15 requests/min with a local page cache.
