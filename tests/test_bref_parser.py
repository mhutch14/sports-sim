"""Offline tests for the Baseball-Reference parser (no network calls)."""

from sportsim.mlb.scrapers import bref

SAMPLE_PAGE = """
<html><body>
<a href="/teams/NYY/2026.shtml">Yankees</a>
<a href="/teams/ATH/2026.shtml">Athletics</a>

<div><!--
<table id="players_standard_pitching">
  <thead><tr>
    <th data-stat="name_display">Player</th><th data-stat="p_era">ERA</th><th data-stat="p_so">SO</th>
  </tr></thead>
  <tbody>
    <tr><th data-stat="name_display" data-append-csv="colege01"><a href="/players/c/colege01.shtml">Gerrit Cole</a></th>
        <td data-stat="p_era">3.10</td><td data-stat="p_so">200</td></tr>
    <tr class="thead"><th data-stat="name_display">Player</th></tr>
  </tbody>
</table>
--></div>

<table id="players_standard_batting">
  <thead><tr>
    <th data-stat="ranker">Rk</th><th data-stat="name_display">Player</th>
    <th data-stat="b_hr">HR</th><th data-stat="b_avg">BA</th>
  </tr></thead>
  <tbody>
    <tr><th data-stat="ranker">1</th>
        <td data-stat="name_display" data-append-csv="judgeaa01"><a href="/players/j/judgeaa01.shtml">Aaron Judge</a></td>
        <td data-stat="b_hr">50</td><td data-stat="b_avg">.310</td></tr>
    <tr><th data-stat="ranker"></th><td data-stat="name_display">Team Totals</td>
        <td data-stat="b_hr">230</td><td data-stat="b_avg">.250</td></tr>
  </tbody>
</table>
</body></html>
"""


def parse(kind):
    tables = bref.all_tables(SAMPLE_PAGE)
    return bref.to_numbers(bref.drop_summary_rows(bref.table_to_df(bref.pick_table(tables, kind, []))))


def test_finds_tables_hidden_in_comments():
    assert set(bref.all_tables(SAMPLE_PAGE)) == {"players_standard_batting", "players_standard_pitching"}


def test_batting_rows_ids_and_numbers():
    df = parse("batting")
    assert list(df["Player"]) == ["Aaron Judge"]          # Team Totals dropped
    assert df.loc[0, "player_id"] == "judgeaa01"
    assert df.loc[0, "HR"] == 50
    assert abs(df.loc[0, "BA"] - 0.310) < 1e-9


def test_pitching_skips_repeated_header_rows():
    df = parse("pitching")
    assert len(df) == 1
    assert df.loc[0, "player_id"] == "colege01"
    assert df.loc[0, "SO"] == 200
