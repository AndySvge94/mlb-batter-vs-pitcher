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




@st.cache_data(ttl=3600, show_spinner=False)
def fetch_player_statcast(player_id: int, player_role: str, start_dt: str, end_dt: str) -> pd.DataFrame:
    """Fetch all Statcast pitches for one batter or pitcher in the selected date range."""
    params = {
        "all": "true", "hfPT": "", "hfAB": "", "hfBBT": "", "hfPR": "", "hfZ": "",
        "stadium": "", "hfBBL": "", "hfNewZones": "", "hfGT": "R|PO|", "hfSea": "",
        "hfSit": "", "player_type": player_role, "hfOuts": "", "opponent": "",
        "pitcher_throws": "", "batter_stands": "", "hfSA": "", "team": "", "position": "",
        "hfRO": "", "home_road": "", "hfFlag": "", "metric_1": "", "hfInn": "",
        "min_pitches": 0, "min_results": 0, "group_by": "name", "sort_col": "pitches",
        "player_event_sort": "h_launch_speed", "sort_order": "desc", "min_abs": 0,
        "type": "details", "game_date_gt": start_dt, "game_date_lt": end_dt,
    }
    if player_role == "pitcher":
        params["pitchers_lookup[]"] = int(player_id)
    else:
        params["batters_lookup[]"] = int(player_id)
    response = requests.get(SAVANT_CSV, params=params, headers=HEADERS, timeout=60)
    response.raise_for_status()
    text = response.text.strip()
    if not text or text.lower().startswith("sorry"):
        return pd.DataFrame()
    try:
        return pd.read_csv(StringIO(text))
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def strikeout_by_inning(pa: pd.DataFrame, denominator: str = "PA") -> pd.DataFrame:
    """Return strikeout counts/rates by inning from completed plate appearances."""
    if pa.empty or "inning" not in pa.columns:
        return pd.DataFrame(columns=["Inning", denominator, "Strikeouts", "K Rate"])
    work = pa.copy()
    work["inning_num"] = pd.to_numeric(work["inning"], errors="coerce")
    work = work[work["inning_num"].notna()].copy()
    work["is_k"] = work["event_key"].isin(STRIKEOUT_EVENTS)
    if denominator == "AB":
        work["is_ab"] = ~work["event_key"].isin(AB_EXCLUSIONS)
        grouped = work.groupby("inning_num", as_index=False).agg(
            AB=("is_ab", "sum"), Strikeouts=("is_k", "sum")
        )
        grouped["K Rate"] = grouped.apply(
            lambda r: (r["Strikeouts"] / r["AB"]) if r["AB"] else 0.0, axis=1
        )
    else:
        grouped = work.groupby("inning_num", as_index=False).agg(
            PA=("event_key", "size"), Strikeouts=("is_k", "sum")
        )
        grouped["K Rate"] = grouped.apply(
            lambda r: (r["Strikeouts"] / r["PA"]) if r["PA"] else 0.0, axis=1
        )
    grouped["Inning"] = grouped["inning_num"].astype(int)
    cols = ["Inning", denominator, "Strikeouts", "K Rate"]
    return grouped[cols].sort_values("Inning").reset_index(drop=True)


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


st.title("⚾ MLB Matchup & Strikeout Analyzer")
st.caption("Active MLB players • Batter-vs-pitcher outcomes and player strikeout profiles from Baseball Savant / Statcast")

teams = get_teams()
team_name_to_id = dict(zip(teams["team"], teams["team_id"]))
team_id_to_name = dict(zip(teams["team_id"], teams["team"]))
team_names = ["All Teams"] + teams["team"].tolist()

with st.sidebar:
    st.header("Date Filters")
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

if start_date > end_date:
    st.error("The start date must be before the end date.")
    st.stop()

# Load all current active players once; team filters below simply narrow this cached table.
try:
    with st.spinner("Loading current MLB rosters..."):
        players = get_all_active_players(tuple(int(x) for x in teams["team_id"].tolist()))
except Exception as exc:
    st.error("I couldn't load MLB's active rosters right now. Please refresh and try again.")
    st.caption(str(exc))
    st.stop()

if players.empty:
    st.error("No active MLB roster data was returned. Please refresh and try again.")
    st.stop()

players["team"] = players["team_id"].map(team_id_to_name).fillna("Unknown Team")
all_batters = players[(~players["is_pitcher"]) | players["is_two_way"]].copy().sort_values(["player", "team"])
all_pitchers = players[players["is_pitcher"] | players["is_two_way"]].copy().sort_values(["player", "team"])

matchup_tab, pitcher_k_tab, batter_k_tab = st.tabs([
    "Batter vs Pitcher", "Pitcher K% by Inning", "Batter K% per At-Bat"
])

with matchup_tab:
    st.subheader("Batter vs. Pitcher")
    cteam1, cteam2 = st.columns(2)
    with cteam1:
        batter_team = st.selectbox("Batter team", team_names, index=0, key="match_batter_team")
    with cteam2:
        pitcher_team = st.selectbox("Pitcher team", team_names, index=0, key="match_pitcher_team")

    batter_pool = all_batters.copy()
    pitcher_pool = all_pitchers.copy()
    if batter_team != "All Teams":
        batter_pool = batter_pool[batter_pool["team_id"] == int(team_name_to_id[batter_team])]
    if pitcher_team != "All Teams":
        pitcher_pool = pitcher_pool[pitcher_pool["team_id"] == int(team_name_to_id[pitcher_team])]

    left, right = st.columns(2)
    with left:
        batter_idx = st.selectbox(
            "Batter", batter_pool.index.tolist(), key="match_batter",
            format_func=lambda i: f"{batter_pool.loc[i, 'player']} — {batter_pool.loc[i, 'team']} ({batter_pool.loc[i, 'position']})",
        )
    with right:
        pitcher_idx = st.selectbox(
            "Pitcher", pitcher_pool.index.tolist(), key="match_pitcher",
            format_func=lambda i: f"{pitcher_pool.loc[i, 'player']} — {pitcher_pool.loc[i, 'team']} ({pitcher_pool.loc[i, 'position']})",
        )

    batter = batter_pool.loc[batter_idx]
    pitcher = pitcher_pool.loc[pitcher_idx]
    run = st.button("Search matchup", type="primary", use_container_width=True, key="run_matchup")

    if run:
        with st.spinner(f"Searching Statcast: {batter['player']} vs. {pitcher['player']}..."):
            try:
                raw = fetch_matchup(int(batter["player_id"]), int(pitcher["player_id"]), start_date.isoformat(), end_date.isoformat())
            except requests.RequestException as exc:
                st.error("Baseball Savant did not return the matchup data. Try again in a moment.")
                st.caption(str(exc))
                st.stop()
        pa = plate_appearances(raw)
        st.subheader(f"{batter['player']} vs. {pitcher['player']}")
        st.caption(f"{start_date:%b %d, %Y} through {end_date:%b %d, %Y}")
        if pa.empty:
            st.info("No plate appearances were found for this matchup in the selected date range.")
        else:
            s = summarize(pa)
            m1, m2, m3, m4, m5, m6 = st.columns(6)
            m1.metric("Plate Appearances", s["PA"])
            m2.metric("Hits", s["H"])
            m3.metric("Strikeouts", s["SO"])
            m4.metric("K / PA", fmt_rate(s["K%"]))
            m5.metric("In-Play Outs", s["In-play outs"])
            m6.metric("Batting Avg", f"{s['BA']:.3f}")

            t1, t2, t3 = st.tabs(["Outcome Breakdown", "Batting Line", "Plate Appearance Log"])
            with t1:
                outcomes = outcome_table(s)
                display_outcomes = outcomes.copy()
                display_outcomes["Rate"] = display_outcomes["Rate"].map(fmt_rate)
                a, b = st.columns([1, 1.35])
                with a:
                    st.dataframe(display_outcomes, hide_index=True, use_container_width=True)
                with b:
                    st.bar_chart(outcomes.set_index("Outcome")[["Count"]], use_container_width=True)
            with t2:
                line = pd.DataFrame([{
                    "PA": s["PA"], "AB": s["AB"], "H": s["H"], "1B": s["1B"], "2B": s["2B"], "3B": s["3B"],
                    "HR": s["HR"], "SO": s["SO"], "BB": s["BB"], "HBP": s["HBP"],
                    "BA": f"{s['BA']:.3f}", "OBP": f"{s['OBP']:.3f}", "SLG": f"{s['SLG']:.3f}",
                    "OPS": f"{s['OPS']:.3f}", "K/PA": fmt_rate(s["K%"]),
                    "K/AB": fmt_rate((s["SO"] / s["AB"]) if s["AB"] else 0.0),
                    "Hit/PA%": fmt_rate(s["Hit/PA%"]), "In-play out%": fmt_rate(s["In-play out%"]),
                }])
                st.dataframe(line, hide_index=True, use_container_width=True)
            with t3:
                log = pd.DataFrame()
                log["Date"] = pd.to_datetime(pa.get("game_date"), errors="coerce").dt.strftime("%Y-%m-%d")
                log["Matchup"] = pa.apply(lambda r: f"{r.get('away_team', '')} @ {r.get('home_team', '')}".strip(), axis=1)
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
                    "Download plate appearances as CSV", data=log.to_csv(index=False).encode("utf-8"),
                    file_name=f"{batter['player'].replace(' ', '_')}_vs_{pitcher['player'].replace(' ', '_')}.csv",
                    mime="text/csv", use_container_width=True,
                )
    else:
        st.info("Choose a batter and pitcher, then click **Search matchup**.")

with pitcher_k_tab:
    st.subheader("Pitcher Strikeout Rate by Inning")
    st.caption("K rate = strikeouts ÷ completed plate appearances faced in that inning.")
    pteam = st.selectbox("Pitcher team", team_names, index=0, key="pk_team")
    ppool = all_pitchers.copy()
    if pteam != "All Teams":
        ppool = ppool[ppool["team_id"] == int(team_name_to_id[pteam])]
    pidx = st.selectbox(
        "Pitcher", ppool.index.tolist(), key="pk_pitcher",
        format_func=lambda i: f"{ppool.loc[i, 'player']} — {ppool.loc[i, 'team']} ({ppool.loc[i, 'position']})",
    )
    psel = ppool.loc[pidx]
    if st.button("Analyze pitcher strikeouts", type="primary", use_container_width=True, key="run_pk"):
        with st.spinner(f"Loading Statcast for {psel['player']}..."):
            try:
                praw = fetch_player_statcast(int(psel["player_id"]), "pitcher", start_date.isoformat(), end_date.isoformat())
            except requests.RequestException as exc:
                st.error("Baseball Savant did not return pitcher data. Try again in a moment.")
                st.caption(str(exc))
                st.stop()
        ppa = plate_appearances(praw)
        if ppa.empty:
            st.info("No completed plate appearances were found for this pitcher in the selected date range.")
        else:
            ps = summarize(ppa)
            c1, c2, c3 = st.columns(3)
            c1.metric("Batters Faced (PA)", ps["PA"])
            c2.metric("Strikeouts", ps["SO"])
            c3.metric("Overall K%", fmt_rate(ps["K%"]))
            inning = strikeout_by_inning(ppa, "PA")
            disp = inning.copy()
            disp["K Rate"] = disp["K Rate"].map(fmt_rate)
            st.dataframe(disp, hide_index=True, use_container_width=True)
            st.bar_chart(inning.set_index("Inning")[["K Rate"]], use_container_width=True)
            st.download_button(
                "Download pitcher K% by inning CSV", data=inning.to_csv(index=False).encode("utf-8"),
                file_name=f"{psel['player'].replace(' ', '_')}_k_rate_by_inning.csv", mime="text/csv", use_container_width=True,
            )

with batter_k_tab:
    st.subheader("Batter Strikeout Rate per At-Bat")
    st.caption("K/AB = strikeouts ÷ official at-bats. Walks, HBP, sacrifice events and catcher interference are excluded from AB.")
    bteam = st.selectbox("Batter team", team_names, index=0, key="bk_team")
    bpool = all_batters.copy()
    if bteam != "All Teams":
        bpool = bpool[bpool["team_id"] == int(team_name_to_id[bteam])]
    bidx = st.selectbox(
        "Batter", bpool.index.tolist(), key="bk_batter",
        format_func=lambda i: f"{bpool.loc[i, 'player']} — {bpool.loc[i, 'team']} ({bpool.loc[i, 'position']})",
    )
    bsel = bpool.loc[bidx]
    if st.button("Analyze batter strikeouts", type="primary", use_container_width=True, key="run_bk"):
        with st.spinner(f"Loading Statcast for {bsel['player']}..."):
            try:
                braw = fetch_player_statcast(int(bsel["player_id"]), "batter", start_date.isoformat(), end_date.isoformat())
            except requests.RequestException as exc:
                st.error("Baseball Savant did not return batter data. Try again in a moment.")
                st.caption(str(exc))
                st.stop()
        bpa = plate_appearances(braw)
        if bpa.empty:
            st.info("No completed plate appearances were found for this batter in the selected date range.")
        else:
            bs = summarize(bpa)
            kab = (bs["SO"] / bs["AB"]) if bs["AB"] else 0.0
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("At-Bats", bs["AB"])
            c2.metric("Strikeouts", bs["SO"])
            c3.metric("K / AB", fmt_rate(kab))
            c4.metric("K / PA", fmt_rate(bs["K%"]))
            inning_b = strikeout_by_inning(bpa, "AB")
            disp_b = inning_b.copy()
            disp_b["K Rate"] = disp_b["K Rate"].map(fmt_rate)
            st.markdown("**K/AB by inning**")
            st.dataframe(disp_b, hide_index=True, use_container_width=True)
            st.bar_chart(inning_b.set_index("Inning")[["K Rate"]], use_container_width=True)
            st.download_button(
                "Download batter K/AB by inning CSV", data=inning_b.to_csv(index=False).encode("utf-8"),
                file_name=f"{bsel['player'].replace(' ', '_')}_k_per_ab_by_inning.csv", mime="text/csv", use_container_width=True,
            )

st.divider()
st.caption("Data source: MLB Stats API for current active rosters; Baseball Savant / Statcast for matchup and strikeout results.")
