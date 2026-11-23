"""Offline tests for the SQLite loader, using small fake CSVs."""

import pandas as pd
import pytest

from sportsim.mlb import db

SEASON = 2026


@pytest.fixture
def fake_data(tmp_path):
    folder = tmp_path / "mlb" / str(SEASON)
    folder.mkdir(parents=True)

    pd.DataFrame([
        {"team_id": "NYY", "Tm": "New York Yankees", "R": 800, "HR": 230},
        {"team_id": "BOS", "Tm": "Boston Red Sox", "R": 750, "HR": 190},
    ]).to_csv(folder / f"teams_batting_{SEASON}.csv", index=False)

    # Player traded NYY -> BOS appears twice; one lefty (*), one switch hitter (#)
    pd.DataFrame([
        {"team": "NYY", "Rk": 1, "Player": "Aaron Judge", "player_id": "judgeaa01",
         "G": 150, "PA": 650, "AB": 520, "H": 160, "2B": 30, "3B": 1, "HR": 50,
         "BB": 110, "HBP": 10, "SF": 10, "SO": 170, "BA": 0.308, "OPS+": 200},
        {"team": "NYY", "Rk": 2, "Player": "Traded Guy*", "player_id": "tradegu01",
         "G": 60, "PA": 220, "AB": 200, "H": 50, "2B": 10, "3B": 0, "HR": 5,
         "BB": 15, "HBP": 2, "SF": 3, "SO": 40, "BA": 0.250, "OPS+": 95},
        {"team": "BOS", "Rk": 1, "Player": "Traded Guy*", "player_id": "tradegu01",
         "G": 70, "PA": 280, "AB": 250, "H": 75, "2B": 15, "3B": 2, "HR": 10,
         "BB": 25, "HBP": 1, "SF": 4, "SO": 50, "BA": 0.300, "OPS+": 120},
        {"team": "BOS", "Rk": 2, "Player": "Switchy McHitter#", "player_id": "switcmc01",
         "G": 100, "PA": 400, "AB": 360, "H": 90, "2B": 20, "3B": 3, "HR": 12,
         "BB": 30, "HBP": 2, "SF": 3, "SO": 80, "BA": 0.250, "OPS+": 100},
    ]).to_csv(folder / f"players_batting_{SEASON}.csv", index=False)

    pd.DataFrame([
        {"team": "NYY", "Player": "Swingman*", "player_id": "swingma01",
         "W": 4, "L": 3, "G": 20, "GS": 10, "IP": 60.1, "H": 55, "ER": 25, "HR": 8, "BB": 20, "SO": 70},
        {"team": "BOS", "Player": "Swingman*", "player_id": "swingma01",
         "W": 2, "L": 1, "G": 10, "GS": 5, "IP": 30.2, "H": 25, "ER": 10, "HR": 3, "BB": 8, "SO": 35},
    ]).to_csv(folder / f"players_pitching_{SEASON}.csv", index=False)

    return tmp_path / "mlb", tmp_path / "test.db"


def test_clean_column_names():
    assert db.clean_column("2B") == "doubles"
    assert db.clean_column("OPS+") == "ops_plus"
    assert db.clean_column("W-L%") == "win_pct"
    assert db.clean_column("Player") == "name"


def test_innings_math():
    assert db.ip_to_outs(60.1) == 181
    assert db.ip_to_outs(30.2) == 92
    assert db.outs_to_ip(181 + 92) == 91.0          # 60⅓ + 30⅔ = 91


def test_load_season_builds_all_tables(fake_data):
    csv_root, db_path = fake_data
    counts = db.load_season(SEASON, csv_root=csv_root, db_path=db_path)
    assert counts["batting"] == 4                   # one row per player per team
    assert counts["batting_totals"] == 3            # traded player combined
    assert counts["teams"] == 2


def test_traded_player_combined_and_rates_recomputed(fake_data):
    csv_root, db_path = fake_data
    db.load_season(SEASON, csv_root=csv_root, db_path=db_path)
    row = db.query("SELECT * FROM batting_totals WHERE player_id = 'tradegu01'", db_path=db_path).iloc[0]
    assert row["teams"] == "NYY/BOS"
    assert row["hr"] == 15 and row["ab"] == 450 and row["h"] == 125
    assert row["ba"] == round(125 / 450, 3)         # recomputed, not averaged


def test_handedness_from_name_markers(fake_data):
    csv_root, db_path = fake_data
    db.load_season(SEASON, csv_root=csv_root, db_path=db_path)
    p = db.query("SELECT player_id, name, bats, throws FROM players", db_path=db_path).set_index("player_id")
    assert p.loc["tradegu01", "name"] == "Traded Guy"   # marker stripped
    assert p.loc["tradegu01", "bats"] == "L"
    assert p.loc["switcmc01", "bats"] == "S"
    assert p.loc["judgeaa01", "bats"] == "R"
    assert p.loc["swingma01", "throws"] == "L"


def test_pitching_totals(fake_data):
    csv_root, db_path = fake_data
    db.load_season(SEASON, csv_root=csv_root, db_path=db_path)
    row = db.query("SELECT * FROM pitching_totals", db_path=db_path).iloc[0]
    assert row["ip"] == 91.0 and row["er"] == 35
    assert row["era"] == round(9 * 35 / 91, 2)


def test_reloading_a_season_replaces_rows(fake_data):
    csv_root, db_path = fake_data
    db.load_season(SEASON, csv_root=csv_root, db_path=db_path)
    db.load_season(SEASON, csv_root=csv_root, db_path=db_path)
    assert len(db.query("SELECT * FROM batting", db_path=db_path)) == 4
