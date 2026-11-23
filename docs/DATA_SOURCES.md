# Data sources

## Baseball-Reference (in use)

| | |
|---|---|
| Site | https://www.baseball-reference.com |
| Code | `src/sportsim/mlb/scrapers/bref.py` |
| Rate limit | 20 requests/minute (Sports Reference bot policy). Going over can block you for up to a day. |
| Our setting | 1 request every 4 s (15/min) + local page cache |
| Policies | https://www.sports-reference.com/bot-traffic.html · https://www.sports-reference.com/data_use.html |

**Pages used per season**

| Page | URL pattern | Tables |
|---|---|---|
| League | `/leagues/majors/<season>.shtml` | team standard batting / pitching, list of team abbreviations |
| Team | `/teams/<ABBR>/<season>.shtml` | player standard batting / pitching |
| Roster | `/teams/<ABBR>/<season>-roster.shtml` | 40-man roster (`the40man`) |

**Quirks the scraper handles**
- Many tables are hidden inside HTML comments; the scraper parses those too.
- Table ids get renamed from time to time. The scraper tries known ids first, then falls back to any `*standard*batting` / `*standard*pitching` table. If something comes back empty, check `data/mlb/<season>/table_ids_seen.txt`.
- Repeated header rows and "Team Totals" / "League Average" rows are dropped.

**Why the data isn't in git:** Sports Reference licenses much of its data from third parties and limits redistribution, and this repo is public. Each machine scrapes its own copy into the git-ignored `data/` folder.

## MLB Stats API (planned)

Official, free JSON at `https://statsapi.mlb.com/api/v1/`. Best source for current rosters, depth charts, transactions and schedules. No scraping needed.
