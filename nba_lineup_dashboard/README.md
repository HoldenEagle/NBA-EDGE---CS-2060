# NBA Lineup Matchup Dashboard

A small Flask app that combines the daily games feed, actual/projected starting lineups,
and season lineup statistics from Ball Don't Lie.

## 1. Setup

Use Python 3.10+.

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

macOS/Linux:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Copy `.env.example` to `.env`, then add your Ball Don't Lie API key:

```env
BALLDONTLIE_API_KEY=your_real_key
NBA_SEASON=2026
LINEUP_CACHE_SECONDS=1800
```

`NBA_SEASON=2026` means the 2026-27 NBA season. Update it when the season changes.

## 2. Run

```bash
python app.py
```

Open http://127.0.0.1:5000.

The dashboard defaults to today's date in US Eastern time. You can also select another date.

## 3. What the dashboard shows

For each game, it attempts to show both teams' starting fives. It prefers actual lineups and falls back to projected lineups if actual starters are not available.

For each team it displays:

- The starting five and whether the lineup is actual or projected.
- Season averages for the exact five-player combination, if that combination has historical lineup records.
- The team's historical results in games where the opponent's exact five-man lineup appeared.
- The team's historical results against the 10 statistically closest opponent lineup profiles.

The similarity calculation compares offensive rating, defensive rating and pace after standardizing each metric across eligible profiles.

## 4. Important API/data notes

- The Lineups endpoint is only available from the 2025-26 season onward and only once a game begins.
- Projected lineups can be available before tip-off, but coverage depends on the API.
- Lineup Stats are historical and are documented as becoming available hours to a day after a game finishes. They are not live in-game stats.
- Lineup Stats and Projected Lineups require the appropriate Ball Don't Lie subscription tier. Check your account's endpoint access if you receive a 401/403 response.
- The season-wide lineup-stat response is cached in memory for 30 minutes by default. Restarting the app clears that cache.
- If the API has no lineup for one or both teams, the dashboard displays a waiting message rather than guessing.

## 5. A few implementation details

The API is called once for the day's games, once per game for actual lineups, and when needed once per game for projected lineups. The season-wide lineup-stat records are fetched once and reused for every matchup/team in the request.

The app uses the game date selected in the browser. It does not assume that the machine's UTC date is the NBA-local date.
