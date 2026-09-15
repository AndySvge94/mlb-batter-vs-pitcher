from __future__ import annotations

from datetime import date, datetime
from io import StringIO

import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="MLB Batter vs Pitcher", page_icon="⚾", layout="wide")

MLB_API = "https://statsapi.mlb.com/api/v1"
SAVANT_CSV = "https://baseballsavant.mlb.com/statcast_search/csv"

# Fallback list used only if MLB's teams endpoint is temporarily unavailable.
FALLBACK_TEAMS = {
    108: "Los Angeles Angels", 109: "Arizona Diamondbacks", 110: "Baltimore Orioles",
    111: "Boston Red Sox", 112: "Chicago Cubs", 113: "Cincinnati Reds",
    114: "Cleveland Guardians", 115: "Colorado Rockies", 116: "Detroit Tigers",
    117: "Houston Astros", 118: "Kansas City Royals", 119: "Los Angeles Dodgers",
    120: "Washington Nationals", 121: "New York Mets", 133: "Athletics",
    134: "Pittsburgh Pirates", 135: "San Diego Padres", 136: "Seattle Mariners",
    137: "San Francisco Giants", 138: "St. Louis Cardinals", 139: "Tampa Bay Rays",
    140: "Texas Rangers", 141: "Toronto Blue Jays", 142: "Minnesota Twins",
    143: "Philadelphia Phillies", 144: "Atlanta Braves", 145: "Chicago White Sox",
    146: "Miami Marlins", 147: "New York Yankees", 158: "Milwaukee Brewers",
}

HIT_EVENTS = {"single", "double", "triple", "home_run"}
STRIKEOUT_EVENTS = {"strikeout", "strikeout_double_play"}
WALK_EVENTS = {"walk", "intent_walk", "intentional_walk"}
HBP_EVENTS = {"hit_by_pitch"}
SAC_EVENTS = {"sac_fly", "sac_bunt", "sac_fly_double_play"}
IN_PLAY_OUT_EVENTS = {
    "field_out", "force_out", "grounded_into_double_play", "fielders_choice_out",
    "double_play", "triple_play", "sac_fly", "sac_bunt", "sac_fly_double_play",
}
AB_EXCLUSIONS = WALK_EVENTS | HBP_EVENTS | SAC_EVENTS | {"catcher_interf"}

EVENT_LABELS = {
    "single": "Single", "double": "Double", "triple": "Triple", "home_run": "Home Run",
    "strikeout": "Strikeout", "strikeout_double_play": "Strikeout / Double Play",
    "walk": "Walk", "intent_walk": "Intentional Walk", "intentional_walk": "Intentional Walk",
    "hit_by_pitch": "Hit By Pitch", "field_out": "Field Out", "force_out": "Force Out",
    "grounded_into_double_play": "Grounded Into Double Play", "fielders_choice_out": "Fielder's Choice Out",
    "fielders_choice": "Fielder's Choice", "double_play": "Double Play", "triple_play": "Triple Play",
    "sac_fly": "Sacrifice Fly", "sac_bunt": "Sacrifice Bunt", "sac_fly_double_play": "Sac Fly Double Play",
    "field_error": "Reached On Error", "catcher_interf": "Catcher Interference",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; MLB-BvP-Stats/1.0)",
    "Accept": "text/csv,application/json,text/plain,*/*",
}


def _get_json(url: str, params: dict | None = None) -> dict:
    response = requests.get(url, params=params, headers=HEADERS, timeout=25)
    response.raise_for_status()
    return response.json()


@st.cache_data(ttl=21600, show_spinner=False)
def get_teams() -> pd.DataFrame:
    try:
        payload = _get_json(f"{MLB_API}/teams", {"sportId": 1, "activeStatus": "Y"})
        teams = [
            {"team_id": int(t["id"]), "team": t["name"], "abbreviation": t.get("abbreviation", "")}
            for t in payload.get("teams", [])
            if t.get("id")
        ]
        if len(teams) >= 25:
            return pd.DataFrame(teams).sort_values("team").reset_index(drop=True)
    except Exception:
        pass
    return pd.DataFrame(
        [{"team_id": tid, "team": name, "abbreviation": ""} for tid, name in FALLBACK_TEAMS.items()]
    ).sort_values("team").reset_index(drop=True)


@st.cache_data(ttl=3600, show_spinner=False)
def get_active_roster(team_id: int) -> pd.DataFrame:
    """Current active MLB roster. Uses the MLB Stats API's active roster endpoint."""
    payload = _get_json(f"{MLB_API}/teams/{int(team_id)}/roster", {"rosterType": "active"})
    rows = []
    for item in payload.get("roster", []):
        person = item.get("person", {})
        pos = item.get("position", {})
        if not person.get("id"):
            continue
        ptype = str(pos.get("type", ""))
        pname = str(pos.get("name", ""))
        abbr = str(pos.get("abbreviation", ""))
        is_pitcher = ptype.lower() == "pitcher" or pname.lower() == "pitcher" or abbr == "P"
        is_two_way = "two-way" in ptype.lower() or "two-way" in pname.lower() or abbr == "TWP"
        rows.append({
            "player_id": int(person["id"]),
            "player": person.get("fullName", f"Player {person['id']}"),
            "position": abbr or pname,
            "is_pitcher": bool(is_pitcher),
            "is_two_way": bool(is_two_way),
        })
    return pd.DataFrame(rows).sort_values("player").reset_index(drop=True)


@st.cache_data(ttl=1800, show_spinner=False)
def get_all_active_players(team_ids: tuple[int, ...]) -> pd.DataFrame:
    frames = []
    for team_id in team_ids:
        try:
            roster = get_active_roster(team_id).copy()
            roster["team_id"] = int(team_id)
            frames.append(roster)
        except Exception:
            continue
    if not frames:
        return pd.DataFrame(columns=["player_id", "player", "position", "is_pitcher", "is_two_way", "team_id"])
    result = pd.concat(frames, ignore_index=True)
    # Transactions can very briefly create duplicates; keep one entry per MLBAM id.
    return result.drop_duplicates(subset=["player_id"], keep="first").reset_index(drop=True)


def date_range_from_choice(choice: str) -> tuple[date, date]:
    today = date.today()
    y = today.year
    if choice == f"{y} season":
        return date(y, 3, 1), today
    if choice == f"{y - 1} season":
        return date(y - 1, 3, 1), date(y - 1, 11, 15)
    if choice == "Last 2 seasons":
        return date(y - 1, 3, 1), today
    if choice == "Last 3 seasons":
        return date(y - 2, 3, 1), today
    if choice == "Statcast history (2008-present)":
        return date(2008, 1, 1), today
    return date(y, 3, 1), today


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_matchup(batter_id: int, pitcher_id: int, start_dt: str, end_dt: str) -> pd.DataFrame:
    # This mirrors Baseball Savant's detailed Statcast CSV search, while applying BOTH player IDs.
    params = {
        "all": "true", "hfPT": "", "hfAB": "", "hfBBT": "", "hfPR": "", "hfZ": "",
        "stadium": "", "hfBBL": "", "hfNewZones": "", "hfGT": "R|PO|", "hfSea": "",
        "hfSit": "", "player_type": "batter", "hfOuts": "", "opponent": "",
        "pitcher_throws": "", "batter_stands": "", "hfSA": "", "team": "", "position": "",
        "hfRO": "", "home_road": "", "hfFlag": "", "metric_1": "", "hfInn": "",
        "min_pitches": 0, "min_results": 0, "group_by": "name", "sort_col": "pitches",
        "player_event_sort": "h_launch_speed", "sort_order": "desc", "min_abs": 0,
        "type": "details", "game_date_gt": start_dt, "game_date_lt": end_dt,
        "batters_lookup[]": int(batter_id), "pitchers_lookup[]": int(pitcher_id),
    }
    response = requests.get(SAVANT_CSV, params=params, headers=HEADERS, timeout=45)
    response.raise_for_status()
    text = response.text.strip()
    if not text or text.lower().startswith("sorry"):
        return pd.DataFrame()
    try:
        df = pd.read_csv(StringIO(text))
    except pd.errors.EmptyDataError:
        return pd.DataFrame()
    return df


def plate_appearances(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty or "events" not in raw.columns:
        return pd.DataFrame()
    df = raw.copy()
    df["events"] = df["events"].astype("string")
    finals = df[df["events"].notna() & (df["events"].str.strip() != "")].copy()
    if finals.empty:
        return finals

    keys = [c for c in ["game_pk", "at_bat_number"] if c in df.columns]
    if len(keys) == 2:
        pitch_counts = df.groupby(keys, dropna=False).size().rename("pitches_in_pa").reset_index()
        finals = finals.merge(pitch_counts, on=keys, how="left")
    else:
        finals["pitches_in_pa"] = pd.NA

    finals["event_key"] = finals["events"].astype(str).str.strip().str.lower()
    finals["result"] = finals["event_key"].map(EVENT_LABELS).fillna(
        finals["event_key"].str.replace("_", " ").str.title()
    )
    return finals


def summarize(pa: pd.DataFrame) -> dict:
    events = pa["event_key"].astype(str) if not pa.empty else pd.Series(dtype=str)
    total_pa = int(len(pa))
    hits = int(events.isin(HIT_EVENTS).sum())
    singles = int((events == "single").sum())
    doubles = int((events == "double").sum())
    triples = int((events == "triple").sum())
    hrs = int((events == "home_run").sum())
    strikeouts = int(events.isin(STRIKEOUT_EVENTS).sum())
    walks = int(events.isin(WALK_EVENTS).sum())
    hbp = int(events.isin(HBP_EVENTS).sum())
    in_play_outs = int(events.isin(IN_PLAY_OUT_EVENTS).sum())
    errors = int((events == "field_error").sum())
    ab = int((~events.isin(AB_EXCLUSIONS)).sum()) if total_pa else 0
    total_bases = singles + 2 * doubles + 3 * triples + 4 * hrs
    ba = hits / ab if ab else 0.0
    obp_denom = ab + walks + hbp + int(events.isin(SAC_EVENTS).sum())
    obp = (hits + walks + hbp) / obp_denom if obp_denom else 0.0
    slg = total_bases / ab if ab else 0.0
    return {
        "PA": total_pa, "AB": ab, "H": hits, "1B": singles, "2B": doubles, "3B": triples,
        "HR": hrs, "SO": strikeouts, "BB": walks, "HBP": hbp,
        "In-play outs": in_play_outs, "ROE": errors, "BA": ba, "OBP": obp, "SLG": slg,
        "OPS": obp + slg, "K%": strikeouts / total_pa if total_pa else 0.0,
        "Hit/PA%": hits / total_pa if total_pa else 0.0,
        "In-play out%": in_play_outs / total_pa if total_pa else 0.0,
    }


def outcome_table(summary: dict) -> pd.DataFrame:
    pa = max(summary["PA"], 1)
    categories = [
        ("Hits", summary["H"]), ("Strikeouts", summary["SO"]),
        ("In-play outs", summary["In-play outs"]), ("Walks", summary["BB"]),
        ("Hit by pitch", summary["HBP"]), ("Reached on error", summary["ROE"]),
    ]
    used = sum(v for _, v in categories)
    other = max(summary["PA"] - used, 0)
    if other:
        categories.append(("Other", other))
    return pd.DataFrame({
        "Outcome": [x[0] for x in categories],
        "Count": [x[1] for x in categories],
        "Rate": [x[1] / pa for x in categories],
    })


def fmt_rate(v: float) -> str:
    return f"{v:.1%}"


st.title("⚾ MLB Batter vs. Pitcher Matchups")
st.caption("Active MLB players • Head-to-head plate appearance outcomes from Baseball Savant / Statcast")

teams = get_teams()
team_name_to_id = dict(zip(teams["team"], teams["team_id"]))
team_id_to_name = dict(zip(teams["team_id"], teams["team"]))
team_names = ["All Teams"] + teams["team"].tolist()

with st.sidebar:
    st.header("Matchup Filters")
    batter_team = st.selectbox("Batter team", team_names, index=0)
    pitcher_team = st.selectbox("Pitcher team", team_names, index=0)
    current_year = date.today().year
    range_options = [
        f"{current_year} season", f"{current_year - 1} season",
        "Last 2 seasons", "Last 3 seasons", "Statcast history (2008-present)", "Custom dates",
    ]
    range_choice = st.selectbox("Date range", range_options, index=0)
    if range_choice == "Custom dates":
        default_start = date(current_year, 3, 1)
        custom_start = st.date_input("Start date", value=default_start, min_value=date(2008, 1, 1), max_value=date.today())
        custom_end = st.date_input("End date", value=date.today(), min_value=date(2008, 1, 1), max_value=date.today())
        start_date, end_date = custom_start, custom_end
    else:
        start_date, end_date = date_range_from_choice(range_choice)
    st.caption("Regular season + postseason Statcast data")

selected_team_ids = set()
if batter_team != "All Teams":
    selected_team_ids.add(int(team_name_to_id[batter_team]))
if pitcher_team != "All Teams":
    selected_team_ids.add(int(team_name_to_id[pitcher_team]))

# For All Teams, collect every active roster. This is cached so normal reruns are fast.
if batter_team == "All Teams" or pitcher_team == "All Teams":
    roster_team_ids = tuple(int(x) for x in teams["team_id"].tolist())
else:
    roster_team_ids = tuple(sorted(selected_team_ids))

try:
    with st.spinner("Loading current MLB rosters..."):
        players = get_all_active_players(roster_team_ids)
except Exception as exc:
    st.error("I couldn't load MLB's active rosters right now. Please refresh and try again.")
    st.caption(str(exc))
    st.stop()

if players.empty:
    st.error("No active MLB roster data was returned. Please refresh and try again.")
    st.stop()

players["team"] = players["team_id"].map(team_id_to_name).fillna("Unknown Team")

batter_pool = players[(~players["is_pitcher"]) | players["is_two_way"]].copy()
pitcher_pool = players[players["is_pitcher"] | players["is_two_way"]].copy()
if batter_team != "All Teams":
    batter_pool = batter_pool[batter_pool["team_id"] == int(team_name_to_id[batter_team])]
if pitcher_team != "All Teams":
    pitcher_pool = pitcher_pool[pitcher_pool["team_id"] == int(team_name_to_id[pitcher_team])]

batter_pool = batter_pool.sort_values(["player", "team"])
pitcher_pool = pitcher_pool.sort_values(["player", "team"])

if batter_pool.empty or pitcher_pool.empty:
    st.warning("That filter produced an empty player list. Try All Teams or another team.")
    st.stop()

left, right = st.columns(2)
with left:
    batter_options = batter_pool.index.tolist()
    batter_idx = st.selectbox(
        "Batter",
        batter_options,
        format_func=lambda i: f"{batter_pool.loc[i, 'player']} — {batter_pool.loc[i, 'team']} ({batter_pool.loc[i, 'position']})",
    )
with right:
    pitcher_options = pitcher_pool.index.tolist()
    pitcher_idx = st.selectbox(
        "Pitcher",
        pitcher_options,
        format_func=lambda i: f"{pitcher_pool.loc[i, 'player']} — {pitcher_pool.loc[i, 'team']} ({pitcher_pool.loc[i, 'position']})",
    )

batter = batter_pool.loc[batter_idx]
pitcher = pitcher_pool.loc[pitcher_idx]

if start_date > end_date:
    st.error("The start date must be before the end date.")
    st.stop()

run = st.button("Search matchup", type="primary", use_container_width=True)

if run:
    with st.spinner(f"Searching Statcast: {batter['player']} vs. {pitcher['player']}..."):
        try:
            raw = fetch_matchup(
                int(batter["player_id"]), int(pitcher["player_id"]),
                start_date.isoformat(), end_date.isoformat(),
            )
        except requests.RequestException as exc:
            st.error("Baseball Savant did not return the matchup data. Try again in a moment.")
            st.caption(str(exc))
            st.stop()

    pa = plate_appearances(raw)
    st.subheader(f"{batter['player']} vs. {pitcher['player']}")
    st.caption(f"{start_date:%b %d, %Y} through {end_date:%b %d, %Y}")

    if pa.empty:
        st.info("No plate appearances were found for this matchup in the selected date range.")
        st.stop()

    s = summarize(pa)

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Plate Appearances", s["PA"])
    m2.metric("Hits", s["H"])
    m3.metric("Strikeouts", s["SO"])
    m4.metric("K Rate", fmt_rate(s["K%"]))
    m5.metric("In-Play Outs", s["In-play outs"])
    m6.metric("Batting Avg", f"{s['BA']:.3f}")

    tab1, tab2, tab3 = st.tabs(["Outcome Breakdown", "Batting Line", "Plate Appearance Log"])

    with tab1:
        outcomes = outcome_table(s)
        display_outcomes = outcomes.copy()
        display_outcomes["Rate"] = display_outcomes["Rate"].map(fmt_rate)
        c1, c2 = st.columns([1, 1.35])
        with c1:
            st.dataframe(display_outcomes, hide_index=True, use_container_width=True)
        with c2:
            chart_df = outcomes.set_index("Outcome")[["Count"]]
            st.bar_chart(chart_df, use_container_width=True)
        st.caption(
            "In-play outs count plate appearances where the ball was put in play and an out was recorded, "
            "including force outs, double plays, sacrifice flies/bunts, and similar Statcast outcomes."
        )

    with tab2:
        line = pd.DataFrame([{
            "PA": s["PA"], "AB": s["AB"], "H": s["H"], "1B": s["1B"], "2B": s["2B"], "3B": s["3B"],
            "HR": s["HR"], "SO": s["SO"], "BB": s["BB"], "HBP": s["HBP"],
            "BA": f"{s['BA']:.3f}", "OBP": f"{s['OBP']:.3f}", "SLG": f"{s['SLG']:.3f}",
            "OPS": f"{s['OPS']:.3f}", "K%": fmt_rate(s["K%"]), "Hit/PA%": fmt_rate(s["Hit/PA%"]),
            "In-play out%": fmt_rate(s["In-play out%"]),
        }])
        st.dataframe(line, hide_index=True, use_container_width=True)

    with tab3:
        log = pd.DataFrame()
        log["Date"] = pd.to_datetime(pa.get("game_date"), errors="coerce").dt.strftime("%Y-%m-%d")
        log["Matchup"] = pa.apply(
            lambda r: f"{r.get('away_team', '')} @ {r.get('home_team', '')}".strip(), axis=1
        )
        log["Inning"] = pa.get("inning", pd.Series(index=pa.index, dtype="object"))
        log["Result"] = pa["result"]
        log["Pitches"] = pa["pitches_in_pa"]
        log["Final Pitch"] = pa.get("pitch_type", pd.Series(index=pa.index, dtype="object"))
        log["Pitch mph"] = pd.to_numeric(pa.get("release_speed", pd.Series(index=pa.index)), errors="coerce").round(1)
        log["Exit Velo"] = pd.to_numeric(pa.get("launch_speed", pd.Series(index=pa.index)), errors="coerce").round(1)
        log["Launch Angle"] = pd.to_numeric(pa.get("launch_angle", pd.Series(index=pa.index)), errors="coerce").round(1)
        log = log.sort_values("Date", ascending=False)
        st.dataframe(log, hide_index=True, use_container_width=True)
        st.download_button(
            "Download plate appearances as CSV",
            data=log.to_csv(index=False).encode("utf-8"),
            file_name=f"{batter['player'].replace(' ', '_')}_vs_{pitcher['player'].replace(' ', '_')}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    with st.expander("How the matchup rates are calculated"):
        st.write(
            "K% = strikeouts / plate appearances. Hit/PA% = hits / plate appearances. "
            "Batting average uses hits / official at-bats, so walks, HBP and sacrifice events are excluded from AB. "
            "The site identifies each completed plate appearance from the final-pitch `events` field in Statcast."
        )
else:
    st.info("Choose a batter and pitcher, then click **Search matchup**.")
    st.markdown(
        "**Tip:** Use the team filters first to make the player lists much shorter. "
        "Set either team to **All Teams** when you want to search the whole league."
    )

st.divider()
st.caption("Data source: MLB Stats API for current active rosters; Baseball Savant / Statcast for matchup results.")
