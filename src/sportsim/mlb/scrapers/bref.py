#!/usr/bin/env python3
"""
Baseball-Reference scraper for an MLB simulator.

Pulls, for one season:
  teams_batting_<season>.csv      - team-level batting totals (30 rows)
  teams_pitching_<season>.csv     - team-level pitching totals (30 rows)
  players_batting_<season>.csv    - every player's batting line, tagged with team
  players_pitching_<season>.csv   - every player's pitching line, tagged with team
  rosters_<season>.csv            - (optional, --rosters) each club's 40-man roster

Polite by design:
  * Baseball-Reference allows ~20 requests/minute; going over gets you blocked
    for up to a day. This script waits 4 seconds between requests (15/min).
  * Every page is cached in ./cache, so re-running (e.g. after tweaking the
    parsing) does NOT hit the site again. Use --refresh to re-download.

Usage (from the repo root, after `pip install -e .`):
  python -m sportsim.mlb.scrapers.bref                 # 2026 season (~31 requests, ~2 min)
  python -m sportsim.mlb.scrapers.bref --season 2025
  python -m sportsim.mlb.scrapers.bref --rosters       # also 40-man rosters (+30 requests)

Output goes to data/mlb/<season>/, downloaded pages to data/cache/ (both git-ignored).
"""

import argparse
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup, Comment

BASE = "https://www.baseball-reference.com"
DELAY_SECONDS = 4.0
HEADERS = {
    "User-Agent": "Mozilla/5.0 (personal MLB sim project; low-rate scraper)",
    "Accept-Language": "en-US,en;q=0.9",
}

REPO_ROOT = Path(__file__).resolve().parents[4]
DATA_DIR = REPO_ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
OUT_DIR = DATA_DIR / "mlb"  # season subfolder added in main()
_last_request = 0.0
_session = requests.Session()
_session.headers.update(HEADERS)


# --------------------------------------------------------------------------- #
# Fetching
# --------------------------------------------------------------------------- #
def fetch(url: str, refresh: bool = False) -> str:
    """Download a page (rate-limited) or return it from the local cache."""
    global _last_request
    cache_file = CACHE_DIR / (re.sub(r"[^A-Za-z0-9]+", "_", url.replace(BASE, "")).strip("_") + ".html")
    if cache_file.exists() and not refresh:
        return cache_file.read_text(encoding="utf-8")

    wait = DELAY_SECONDS - (time.time() - _last_request)
    if wait > 0:
        time.sleep(wait)

    print(f"  GET {url}")
    resp = _session.get(url, timeout=30)
    _last_request = time.time()

    if resp.status_code == 429:
        sys.exit("Got HTTP 429 (rate limited). Baseball-Reference blocks for up to a day - "
                 "stop and try again tomorrow. Cached pages are kept.")
    resp.raise_for_status()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(resp.text, encoding="utf-8")
    return resp.text


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
def all_tables(html: str) -> dict:
    """
    Return {table_id: <table> element} for every table on the page.
    Baseball-Reference hides many tables inside HTML comments (they're
    un-commented by JavaScript in the browser), so we parse those too.
    """
    soup = BeautifulSoup(html, "lxml")
    tables = {t.get("id"): t for t in soup.find_all("table") if t.get("id")}
    for c in soup.find_all(string=lambda s: isinstance(s, Comment) and "<table" in s):
        for t in BeautifulSoup(c, "lxml").find_all("table"):
            if t.get("id"):
                tables.setdefault(t["id"], t)
    return tables


def pick_table(tables: dict, must_have: str, prefer: list, avoid=("value", "advanced", "ratio", "extra", "post")):
    """Find the right table even if Baseball-Reference renames table ids."""
    for tid in prefer:
        if tid in tables:
            return tables[tid]
    for tid, t in tables.items():
        low = tid.lower()
        if must_have in low and "standard" in low and not any(a in low for a in avoid):
            return t
    for tid, t in tables.items():
        low = tid.lower()
        if must_have in low and not any(a in low for a in avoid):
            return t
    return None


def table_to_df(table) -> pd.DataFrame:
    """
    Convert a Baseball-Reference <table> to a DataFrame.
    - Column names come from the header row (duplicates get the stat key appended).
    - Adds `player_id` (e.g. 'judgeaa01') / `team_id` when the row links to one,
      which is the key you'll use to join tables and dedupe traded players.
    - Drops repeated mid-table header rows and blank spacer rows.
    """
    header_cells = table.find("thead").find_all("tr")[-1].find_all(["th", "td"])
    key_to_label, used = {}, set()
    for cell in header_cells:
        key = cell.get("data-stat")
        if not key:
            continue
        label = cell.get_text(strip=True) or key
        if label in used:
            label = f"{label}_{key}"
        used.add(label)
        key_to_label[key] = label

    rows = []
    body = table.find("tbody") or table
    for tr in body.find_all("tr"):
        cls = tr.get("class") or []
        if "thead" in cls or "spacer" in cls or "over_header" in cls:
            continue
        row = {}
        for cell in tr.find_all(["th", "td"]):
            key = cell.get("data-stat")
            if not key:
                continue
            row[key_to_label.get(key, key)] = cell.get_text(strip=True)
            pid = cell.get("data-append-csv")
            if pid and "player_id" not in row:
                row["player_id"] = pid
            a = cell.find("a", href=True)
            if a:
                m = re.search(r"/teams/([A-Z]{2,3})/", a["href"])
                if m and "team_id" not in row:
                    row["team_id"] = m.group(1)
                m = re.search(r"/players/\w/(\w+)\.shtml", a["href"])
                if m and "player_id" not in row:
                    row["player_id"] = m.group(1)
        if any(v for v in row.values()):
            rows.append(row)

    return pd.DataFrame(rows)


def to_numbers(df: pd.DataFrame) -> pd.DataFrame:
    """Turn stat columns into numbers where possible (leave names/ids as text)."""
    out = df.copy()
    for col in out.columns:
        converted = pd.to_numeric(out[col].astype(str).str.replace(",", "").str.rstrip("%"), errors="coerce")
        # only convert if most non-empty values are numeric
        nonempty = out[col].astype(str).str.strip().ne("").sum()
        if nonempty and converted.notna().sum() >= 0.8 * nonempty:
            out[col] = converted
    return out


def drop_summary_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Remove 'Team Totals', 'League Average', rank-per-league rows, etc."""
    if df.empty:
        return df
    text = df.fillna("").astype(str).apply(lambda r: " ".join(r.tolist()), axis=1)
    bad = text.str.contains(r"Team Totals|League Average|Rank in|Non-Pitcher Totals|Pitcher Totals", regex=True)
    return df[~bad].reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Scrape steps
# --------------------------------------------------------------------------- #
def scrape_league(season: int, refresh: bool):
    url = f"{BASE}/leagues/majors/{season}.shtml"
    html = fetch(url, refresh)
    tables = all_tables(html)

    bat = pick_table(tables, "batting", ["teams_standard_batting"])
    pit = pick_table(tables, "pitching", ["teams_standard_pitching"])
    teams_bat = to_numbers(drop_summary_rows(table_to_df(bat))) if bat is not None else pd.DataFrame()
    teams_pit = to_numbers(drop_summary_rows(table_to_df(pit))) if pit is not None else pd.DataFrame()

    # Team abbreviations straight from the page links (handles ATH, etc.)
    abbrs = sorted(set(re.findall(rf"/teams/([A-Z]{{2,3}})/{season}\.shtml", html)))
    if not abbrs:
        sys.exit(f"No team links found on {url}. Table ids seen: {list(tables)[:20]}")
    return teams_bat, teams_pit, abbrs, list(tables)


def scrape_team(abbr: str, season: int, refresh: bool):
    html = fetch(f"{BASE}/teams/{abbr}/{season}.shtml", refresh)
    tables = all_tables(html)
    bat = pick_table(tables, "batting", ["players_standard_batting", "team_batting"])
    pit = pick_table(tables, "pitching", ["players_standard_pitching", "team_pitching"])

    def prep(t):
        if t is None:
            return pd.DataFrame()
        df = to_numbers(drop_summary_rows(table_to_df(t)))
        df.insert(0, "team", abbr)
        return df

    return prep(bat), prep(pit), list(tables)


def scrape_roster(abbr: str, season: int, refresh: bool):
    html = fetch(f"{BASE}/teams/{abbr}/{season}-roster.shtml", refresh)
    tables = all_tables(html)
    t = tables.get("the40man") or pick_table(tables, "40man", [], avoid=())
    if t is None:
        return pd.DataFrame()
    df = table_to_df(t)
    df.insert(0, "team", abbr)
    return df


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--rosters", action="store_true", help="also scrape 40-man rosters")
    ap.add_argument("--refresh", action="store_true", help="ignore cache and re-download")
    ap.add_argument("--teams", nargs="*", help="only these team abbreviations, e.g. NYY BOS")
    args = ap.parse_args()

    global OUT_DIR
    s = args.season
    OUT_DIR = OUT_DIR / str(s)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[1/3] League page {s}")
    teams_bat, teams_pit, abbrs, league_ids = scrape_league(s, args.refresh)
    if args.teams:
        abbrs = [a for a in abbrs if a in set(args.teams)]
    teams_bat.to_csv(OUT_DIR / f"teams_batting_{s}.csv", index=False)
    teams_pit.to_csv(OUT_DIR / f"teams_pitching_{s}.csv", index=False)
    print(f"      {len(abbrs)} teams: {' '.join(abbrs)}")

    print(f"[2/3] Team pages ({len(abbrs)} requests, ~{len(abbrs) * DELAY_SECONDS / 60:.0f} min if not cached)")
    bats, pits, seen_ids = [], [], set(league_ids)
    for a in abbrs:
        b, p, ids = scrape_team(a, s, args.refresh)
        bats.append(b); pits.append(p); seen_ids.update(ids)
        print(f"      {a}: {len(b)} hitters, {len(p)} pitchers")
    pd.concat(bats, ignore_index=True).to_csv(OUT_DIR / f"players_batting_{s}.csv", index=False)
    pd.concat(pits, ignore_index=True).to_csv(OUT_DIR / f"players_pitching_{s}.csv", index=False)

    if args.rosters:
        print(f"[3/3] 40-man rosters")
        rosters = [scrape_roster(a, s, args.refresh) for a in abbrs]
        pd.concat(rosters, ignore_index=True).to_csv(OUT_DIR / f"rosters_{s}.csv", index=False)
    else:
        print("[3/3] Skipping rosters (add --rosters to include)")

    # Handy if Baseball-Reference renames a table and something comes back empty
    (OUT_DIR / "table_ids_seen.txt").write_text("\n".join(sorted(seen_ids)))
    print(f"Done. CSVs in {OUT_DIR.relative_to(REPO_ROOT)}/")


if __name__ == "__main__":
    main()
