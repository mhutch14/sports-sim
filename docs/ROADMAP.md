# Roadmap

```mermaid
flowchart LR
    P1[1 - Scrape data] --> P2[2 - SQLite database] --> P3[3 - Key stats / ratings] --> P4[4 - Sim engine] --> P5["5 - main.py to run sims"]
    style P1 fill:#9f9,stroke:#333
    style P2 fill:#9f9,stroke:#333
```

## Phase 1: Data ✅
- [x] Baseball-Reference scraper: team + player season stats
- [x] 40-man rosters (`--rosters`)
- [ ] MLB Stats API client for live rosters / depth charts / transactions
- [x] Combine traded players' rows by `player_id` (in the database)
- [ ] Platoon splits (stats vs LHP / RHP)

## Phase 2: Database (SQLite, free and built into Python) ✅
- [x] Load the scraped CSVs into `data/sportsim.db` (tables: teams, players, batting, pitching, rosters)
- [x] `player_id` / `team` as keys so tables join cleanly
- [x] One command to rebuild the database after each scrape (`python -m sportsim.mlb.db build`)
- [x] Season totals with traded players combined (`batting_totals`, `pitching_totals`)
- [x] Handedness (bats / throws) from Baseball-Reference name markers

## Phase 3: Which stats matter (ratings)
- [ ] Turn season stats into per-plate-appearance outcome rates (K, BB, HBP, 1B, 2B, 3B, HR, out)
- [ ] Regress small samples toward league average
- [ ] Park factors

## Phase 4: Simulation engine
- [ ] Batter-vs-pitcher matchup model (e.g. log5 / odds-ratio)
- [ ] Base-running & out logic, innings, extras
- [ ] Lineups and starting pitcher / bullpen usage
- [ ] Box score output

- [ ] Monte Carlo: run a matchup N times → win probability, score distribution
- [ ] Full schedule → standings projections

## Phase 5: `main.py` to run simulations
- [ ] e.g. `python main.py --home NYY --away BOS --games 1000`
- [ ] Print box score / win probability summary

## Later: Other sports
- [ ] Reuse the same layout: `sportsim/<sport>/scrapers`, `sportsim/<sport>/sim`
