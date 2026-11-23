"""
Load scraped Baseball-Reference CSVs into a SQLite database.

    data/mlb/<season>/*.csv  ──►  data/sportsim.db

Tables (every one has a `season` column, so many seasons can live together):

    teams            one row per team per season (team_id, team_name)
    players          one row per player per season (name, bats, throws, teams played for)
    team_batting     team-level batting totals
    team_pitching    team-level pitching totals
    batting          player batting, one row per player per TEAM (traded players have 2+ rows)
    pitching         player pitching, one row per player per TEAM
    batting_totals   player batting, one row per player per SEASON (traded players combined,
                     rate stats recomputed)
    pitching_totals  same for pitching (innings handled as outs, so 6.1 + 2.2 = 9.0)
    rosters          40-man rosters (if scraped with --rosters)

Usage (from the repo root):
    python -m sportsim.mlb.db build                 # load every season found in data/mlb/
    python -m sportsim.mlb.db build --season 2026   # (re)load just one season
    python -m sportsim.mlb.db tables                # list tables and row counts
    python -m sportsim.mlb.db query "SELECT name, hr FROM batting_totals ORDER BY hr DESC LIMIT 10"

From Python:
    from sportsim.mlb import db
    df = db.query("SELECT * FROM pitching_totals WHERE season = 2026 AND ip >= 100")
"""

import argparse
import re
import sqlite3
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data"
CSV_ROOT = DATA_DIR / "mlb"
DB_PATH = DATA_DIR / "sportsim.db"

# CSV file stem (without _<season>) → table name
CSV_TABLES = {
    "teams_batting": "team_batting",
    "teams_pitching": "team_pitching",
    "players_batting": "batting",
    "players_pitching": "pitching",
    "rosters": "rosters",
}

# Baseball-Reference header → database column, for names that don't clean up nicely
SPECIAL_NAMES = {
    "2B": "doubles", "3B": "triples",
    "Player": "name", "Name": "name",
    "Tm": "team_name", "Team": "team_name",
    "W-L%": "win_pct", "SO/W": "so_per_bb", "SO/BB": "so_per_bb",
    "GDP": "gidp", "GIDP": "gidp",
    "B": "bats", "T": "throws",
}

# Counting stats that can simply be added up across teams
BATTING_SUM = ["g", "pa", "ab", "r", "h", "doubles", "triples", "hr", "rbi", "sb", "cs",
               "bb", "so", "tb", "gidp", "hbp", "sh", "sf", "ibb", "war"]
PITCHING_SUM = ["w", "l", "g", "gs", "gf", "cg", "sho", "sv", "h", "r", "er", "hr",
                "bb", "ibb", "so", "hbp", "bk", "wp", "bf", "war"]


# --------------------------------------------------------------------------- #
# Cleaning
# --------------------------------------------------------------------------- #
def clean_column(name: str) -> str:
    """'OPS+' → 'ops_plus', '2B' → 'doubles', 'SO9' → 'so9', 'W-L%' → 'win_pct'."""
    name = str(name).strip()
    if name in SPECIAL_NAMES:
        return SPECIAL_NAMES[name]
    s = name.replace("+", "_plus").replace("%", "_pct").replace("/", "_per_")
    s = re.sub(r"[^0-9A-Za-z]+", "_", s).strip("_").lower()
    if not s:
        s = "col"
    if s[0].isdigit():
        s = "n_" + s
    return s


def clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    out, seen = {}, set()
    for col in df.columns:
        new = clean_column(col)
        base, i = new, 2
        while new in seen:
            new, i = f"{base}_{i}", i + 1
        seen.add(new)
        out[col] = new
    return df.rename(columns=out)


def split_handedness(df: pd.DataFrame, kind: str) -> pd.DataFrame:
    """
    Baseball-Reference marks names: 'Juan Soto*' = left-handed, 'Name#' = switch.
    On batting tables that's how the player bats; on pitching tables, how he throws.
    Strips the marker from the name and stores it in `bats` or `throws`.
    """
    if "name" not in df.columns:
        return df
    df = df.copy()
    names = df["name"].astype(str)
    hand = names.str.extract(r"([*#])\s*$")[0].map({"*": "L", "#": "S"}).fillna("R")
    df["name"] = names.str.replace(r"[*#+]+\s*$", "", regex=True).str.strip()
    col = "bats" if kind == "batting" else "throws"
    if col not in df.columns:
        df[col] = hand
    return df


def ip_to_outs(ip) -> float:
    """Baseball innings notation: 6.1 = 6⅓ innings = 19 outs, 6.2 = 20 outs."""
    if pd.isna(ip):
        return 0
    whole = int(float(ip))
    frac = round((float(ip) - whole) * 10)
    return whole * 3 + frac


def outs_to_ip(outs: float) -> float:
    """19 outs → 6.1 (display notation)."""
    return int(outs // 3) + (int(outs) % 3) / 10


def _safe_div(a, b):
    return (a / b).where(b > 0)


# --------------------------------------------------------------------------- #
# Season totals (combine traded players)
# --------------------------------------------------------------------------- #
def batting_totals(batting: pd.DataFrame) -> pd.DataFrame:
    if batting.empty or "player_id" not in batting.columns:
        return pd.DataFrame()
    b = batting[batting["player_id"].notna()].copy()
    sums = [c for c in BATTING_SUM if c in b.columns]
    for c in sums:
        b[c] = pd.to_numeric(b[c], errors="coerce").fillna(0)
    agg = {c: "sum" for c in sums}
    agg.update({"name": "first", "team": lambda t: "/".join(dict.fromkeys(t))})
    for c in ("bats", "age"):
        if c in b.columns:
            agg[c] = "first"
    t = b.groupby(["season", "player_id"], as_index=False).agg(agg)
    t = t.rename(columns={"team": "teams"})
    t["n_teams"] = t["teams"].str.count("/") + 1

    if {"h", "ab"} <= set(t.columns):
        t["ba"] = _safe_div(t["h"], t["ab"]).round(3)
    if {"h", "bb", "hbp", "ab", "sf"} <= set(t.columns):
        t["obp"] = _safe_div(t["h"] + t["bb"] + t["hbp"], t["ab"] + t["bb"] + t["hbp"] + t["sf"]).round(3)
    if {"h", "doubles", "triples", "hr", "ab"} <= set(t.columns):
        tb = t["h"] + t["doubles"] + 2 * t["triples"] + 3 * t["hr"]
        t["slg"] = _safe_div(tb, t["ab"]).round(3)
    if {"obp", "slg"} <= set(t.columns):
        t["ops"] = (t["obp"] + t["slg"]).round(3)
    return t


def pitching_totals(pitching: pd.DataFrame) -> pd.DataFrame:
    if pitching.empty or "player_id" not in pitching.columns:
        return pd.DataFrame()
    p = pitching[pitching["player_id"].notna()].copy()
    sums = [c for c in PITCHING_SUM if c in p.columns]
    for c in sums:
        p[c] = pd.to_numeric(p[c], errors="coerce").fillna(0)
    p["outs"] = p["ip"].apply(ip_to_outs) if "ip" in p.columns else 0
    agg = {c: "sum" for c in sums + ["outs"]}
    agg.update({"name": "first", "team": lambda t: "/".join(dict.fromkeys(t))})
    for c in ("throws", "age"):
        if c in p.columns:
            agg[c] = "first"
    t = p.groupby(["season", "player_id"], as_index=False).agg(agg)
    t = t.rename(columns={"team": "teams"})
    t["n_teams"] = t["teams"].str.count("/") + 1

    t["ip"] = t["outs"].apply(outs_to_ip)       # display notation (6.1 = 6⅓)
    innings = t["outs"] / 3                      # true innings for math
    if "er" in t.columns:
        t["era"] = _safe_div(9 * t["er"], innings).round(2)
    if {"h", "bb"} <= set(t.columns):
        t["whip"] = _safe_div(t["h"] + t["bb"], innings).round(3)
    for stat in ("h", "hr", "bb", "so"):
        if stat in t.columns:
            t[f"{stat}9"] = _safe_div(9 * t[stat], innings).round(1)
    if {"so", "bb"} <= set(t.columns):
        t["so_per_bb"] = _safe_div(t["so"], t["bb"]).round(2)
    return t


def players_table(batting: pd.DataFrame, pitching: pd.DataFrame) -> pd.DataFrame:
    """One row per player per season: name, bats, throws, teams."""
    frames = []
    for df, hand in ((batting, "bats"), (pitching, "throws")):
        if not df.empty and "player_id" in df.columns:
            cols = ["season", "player_id", "name", "team"] + ([hand] if hand in df.columns else [])
            frames.append(df[df["player_id"].notna()][cols])
    if not frames:
        return pd.DataFrame()
    allp = pd.concat(frames, ignore_index=True)
    agg = {"name": "first", "team": lambda t: "/".join(dict.fromkeys(t))}
    for c in ("bats", "throws"):
        if c in allp.columns:
            agg[c] = lambda s: s.dropna().iloc[0] if s.notna().any() else None
    out = allp.groupby(["season", "player_id"], as_index=False).agg(agg)
    return out.rename(columns={"team": "teams"})


def teams_table(team_batting: pd.DataFrame) -> pd.DataFrame:
    if team_batting.empty or "team_id" not in team_batting.columns:
        return pd.DataFrame()
    cols = ["season", "team_id"] + (["team_name"] if "team_name" in team_batting.columns else [])
    return team_batting[team_batting["team_id"].notna()][cols].drop_duplicates()


# --------------------------------------------------------------------------- #
# Writing to SQLite
# --------------------------------------------------------------------------- #
def connect(db_path: Path = None) -> sqlite3.Connection:
    path = Path(db_path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(path)


def write_season(con: sqlite3.Connection, table: str, df: pd.DataFrame, season: int):
    """Replace one season's rows in `table`, adding any new columns first."""
    if df is None or df.empty:
        return 0
    exists = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    if exists:
        have = {r[1] for r in con.execute(f'PRAGMA table_info("{table}")')}
        for col in df.columns:
            if col not in have:
                con.execute(f'ALTER TABLE "{table}" ADD COLUMN "{col}"')
        con.execute(f'DELETE FROM "{table}" WHERE season = ?', (season,))
    df.to_sql(table, con, if_exists="append", index=False)
    return len(df)


def create_indexes(con: sqlite3.Connection):
    for (table,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
        cols = {r[1] for r in con.execute(f'PRAGMA table_info("{table}")')}
        for key in ("player_id", "team", "team_id", "season"):
            if key in cols:
                con.execute(f'CREATE INDEX IF NOT EXISTS "ix_{table}_{key}" ON "{table}" ("{key}")')


def load_season(season: int, csv_root: Path = None, db_path: Path = None) -> dict:
    """Load data/mlb/<season>/*.csv into the database. Returns {table: rows}."""
    folder = Path(csv_root or CSV_ROOT) / str(season)
    if not folder.is_dir():
        raise FileNotFoundError(f"{folder} not found - run the scraper first: "
                                f"python -m sportsim.mlb.scrapers.bref --season {season}")

    frames = {}
    for stem, table in CSV_TABLES.items():
        f = folder / f"{stem}_{season}.csv"
        if not f.exists():
            frames[table] = pd.DataFrame()
            continue
        df = clean_columns(pd.read_csv(f))
        df = df.drop(columns=[c for c in ("rk",) if c in df.columns])
        if table in ("batting", "pitching"):
            df = split_handedness(df, table)
        df.insert(0, "season", season)
        frames[table] = df

    frames["batting_totals"] = batting_totals(frames["batting"])
    frames["pitching_totals"] = pitching_totals(frames["pitching"])
    frames["players"] = players_table(frames["batting"], frames["pitching"])
    frames["teams"] = teams_table(frames["team_batting"])

    counts = {}
    with connect(db_path) as con:
        for table, df in frames.items():
            counts[table] = write_season(con, table, df, season)
        create_indexes(con)
    return counts


def seasons_available(csv_root: Path = None) -> list:
    root = Path(csv_root or CSV_ROOT)
    return sorted(int(p.name) for p in root.glob("*") if p.is_dir() and p.name.isdigit()) if root.exists() else []


def query(sql: str, params=(), db_path: Path = None) -> pd.DataFrame:
    """Run SQL and get a DataFrame back."""
    with connect(db_path) as con:
        return pd.read_sql_query(sql, con, params=params)


def list_tables(db_path: Path = None) -> pd.DataFrame:
    with connect(db_path) as con:
        names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        rows = [(n, con.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0]) for n in names]
    return pd.DataFrame(rows, columns=["table", "rows"])


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="Build / query the Sports Sim SQLite database")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="load scraped CSVs into data/sportsim.db")
    b.add_argument("--season", type=int, help="only this season (default: all found)")
    sub.add_parser("tables", help="list tables and row counts")
    q = sub.add_parser("query", help="run a SQL query")
    q.add_argument("sql")
    args = ap.parse_args()

    if args.cmd == "build":
        seasons = [args.season] if args.season else seasons_available()
        if not seasons:
            sys.exit(f"No seasons in {CSV_ROOT}. Run: python -m sportsim.mlb.scrapers.bref")
        for s in seasons:
            counts = load_season(s)
            print(f"{s}: " + ", ".join(f"{t}={n}" for t, n in counts.items() if n))
        print(f"Database: {DB_PATH.relative_to(REPO_ROOT)}")
    elif args.cmd == "tables":
        print(list_tables().to_string(index=False))
    elif args.cmd == "query":
        with pd.option_context("display.max_rows", 100, "display.width", 200):
            print(query(args.sql).to_string(index=False))


if __name__ == "__main__":
    main()
