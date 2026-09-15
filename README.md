# MLB Batter vs. Pitcher Matchup Explorer

A Streamlit web app for looking up head-to-head MLB batter vs. pitcher results using current active MLB rosters and Baseball Savant / Statcast data.

## Features

- Only players on current MLB active rosters are shown.
- Separate Batter Team and Pitcher Team filters.
- All Teams option for league-wide searching.
- Current season, previous season, last 2 seasons, last 3 seasons, full Statcast history, or custom dates.
- Plate appearances, at-bats, hits, singles, doubles, triples, home runs, strikeouts, walks, HBP and in-play outs.
- BA, OBP, SLG, OPS, K%, Hit/PA%, and in-play out rate.
- Individual plate-appearance log with final pitch, pitch velocity, exit velocity and launch angle when available.
- CSV download.

## Files

- `app.py` — the website.
- `requirements.txt` — Python packages Streamlit installs.
- `.streamlit/config.toml` — dark visual theme.

## Deploy with GitHub + Streamlit Community Cloud

1. Create a new public GitHub repository, for example `mlb-batter-vs-pitcher`.
2. Upload `app.py`, `requirements.txt`, and the `.streamlit` folder.
3. Commit the files to the `main` branch.
4. Sign in to Streamlit Community Cloud using GitHub.
5. Click **Create app**.
6. Choose the `mlb-batter-vs-pitcher` repository.
7. Set the branch to `main`.
8. Set the main file path to `app.py`.
9. Deploy.
10. Share the resulting `*.streamlit.app` URL.

## Notes

- The app does not store a static roster. It checks MLB's current active rosters and caches them for speed.
- Matchup data is queried only after the user clicks Search matchup.
- Statcast results can occasionally be temporarily unavailable or slow. Retrying later normally resolves a source-side failure.
- For historical ranges, the batter and pitcher may currently be on different teams than they were when a plate appearance occurred. The player filters intentionally use CURRENT active rosters.
