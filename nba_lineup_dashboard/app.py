import os
import time
from collections import defaultdict
from datetime import datetime
from math import sqrt
from statistics import mean, pstdev
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv
from flask import Flask, render_template, request

load_dotenv()

GAMES_URL = "https://api.balldontlie.io/v1/games"
TEAMS_URL = "https://api.balldontlie.io/v1/teams"
PLAYERS_URL = "https://api.balldontlie.io/nba/v1/players"
LINEUPS_URL = "https://api.balldontlie.io/nba/v1/lineups"
PROJECTED_URL = "https://api.balldontlie.io/nba/v1/projected_lineups"
LINEUP_STATS_URL = "https://api.balldontlie.io/nba/v1/lineup_stats"
INJURIES_URL = "https://api.balldontlie.io/v1/player_injuries"

SEASONS = (2025, 2026)
CACHE_SECONDS = int(os.getenv("LINEUP_CACHE_SECONDS", "1800"))
LOCAL_TZ = ZoneInfo("America/New_York")

app = Flask(__name__)
session = requests.Session()
_stats_cache = {"created": 0, "seasons": None, "data": None}
_reference_cache = {"created": 0, "players": {}, "teams": {}}


def get_headers():
    api_key = os.getenv("BALLDONTLIE_API_KEY")
    if not api_key:
        raise RuntimeError("Missing BALLDONTLIE_API_KEY in your .env file.")
    return {"Authorization": api_key}


def api_get(url, params=None):
    response = session.get(url, headers=get_headers(), params=params or {}, timeout=30)
    response.raise_for_status()
    return response.json()


def get_all_pages(url, params):
    all_rows = []
    page_params = dict(params)
    while True:
        payload = api_get(url, page_params)
        all_rows.extend(payload.get("data", []))
        next_cursor = payload.get("meta", {}).get("next_cursor")
        if next_cursor is None:
            break
        page_params["cursor"] = next_cursor
    return all_rows


def get_games(game_date):
    rows = get_all_pages(GAMES_URL, {"dates[]": game_date, "per_page": 100})
    return [{
        "game_id": game["id"],
        "date": game.get("date", game_date),
        "status": game.get("status", "Status unavailable"),
        "home_team": game["home_team"]["full_name"],
        "away_team": game["visitor_team"]["full_name"],
        "home_team_id": game["home_team"]["id"],
        "away_team_id": game["visitor_team"]["id"],
    } for game in rows]


def get_actual_lineups(game_id):
    return get_all_pages(LINEUPS_URL, {"game_ids": game_id, "per_page": 100})


def get_projected_lineups(game_id):
    return get_all_pages(PROJECTED_URL, {"game_ids[]": game_id, "per_page": 100})


def get_team_injuries(team_ids):
    """Retrieve current injury reports for the specified teams."""
    rows = []

    for team_id in team_ids:
        team_rows = get_all_pages(
            INJURIES_URL,
            {
                "team_ids[]": team_id,
                "per_page": 100
            }
        )
        rows.extend(team_rows)

    injuries_by_team = defaultdict(list)

    for row in rows:
        player = row.get("player") or {}
        team_id = player.get("team_id")

        if not team_id:
            continue

        injuries_by_team[team_id].append({
            "name": (
                f'{player.get("first_name", "")} '
                f'{player.get("last_name", "")}'
            ).strip(),
            "position": player.get("position") or "—",
            "status": row.get("status") or "Unknown",
            "description": row.get("description") or "No description available.",
            "return_date": row.get("return_date") or "Not specified",
        })

    return injuries_by_team

def normalize_team_lineups(actual_rows, projected_rows):
    """Prefer actual starters; fill a missing team with its projected five."""
    result = {}

    for row in actual_rows:
        team = row.get("team") or {}
        player = row.get("player") or {}
        team_id = team.get("id")
        if not team_id or not player.get("id") or not row.get("starter"):
            continue
        entry = result.setdefault(team_id, {
            "source": "Actual lineup",
            "status": "Confirmed starters",
            "players": [],
        })
        entry["players"].append({
            "player_id": player["id"],
            "name": f'{player.get("first_name", "")} {player.get("last_name", "")}'.strip(),
            "position": row.get("position") or player.get("position") or "—",
            "starter": True,
        })

    for row in projected_rows:
        team_id = row.get("team_id") or (row.get("team") or {}).get("id")
        if not team_id or len(result.get(team_id, {}).get("players", [])) >= 5:
            continue
        projected_players = []
        for item in row.get("lineup", []):
            player = item.get("player") or {}
            if not player.get("id"):
                continue
            projected_players.append({
                "player_id": player["id"],
                "name": f'{player.get("first_name", "")} {player.get("last_name", "")}'.strip(),
                "position": item.get("position") or "—",
                "starter": True,
            })
        if projected_players:
            result[team_id] = {
                "source": "Projected lineup",
                "status": row.get("status", "Projection"),
                "players": projected_players[:5],
            }

    return result


def get_season_lineup_stats(seasons):
    now = time.time()
    seasons = tuple(seasons)

    if (_stats_cache["data"] is not None
            and _stats_cache["seasons"] == seasons
            and now - _stats_cache["created"] < CACHE_SECONDS):
        return _stats_cache["data"]

    rows = get_all_pages(
        LINEUP_STATS_URL,
        {"seasons[]": list(seasons), "per_page": 100}
    )

    _stats_cache.update(
        created=now,
        seasons=seasons,
        data=rows
    )

    return rows


def get_reference_data(player_ids):
    """Bulk-resolve historical player IDs and team IDs to display names."""
    now = time.time()
    if now - _reference_cache["created"] > CACHE_SECONDS:
        _reference_cache.update(created=now, players={}, teams={})

    missing = set(player_ids) - set(_reference_cache["players"])
    if missing:
        # BDL's players endpoint accepts an array of player_ids[] filters.
        for start in range(0, len(missing), 100):
            chunk = sorted(missing)[start:start + 100]
            params = {"player_ids[]": chunk, "per_page": 100}
            for player in get_all_pages(PLAYERS_URL, params):
                _reference_cache["players"][player["id"]] = (
                    f'{player.get("first_name", "")} {player.get("last_name", "")}'.strip()
                )

    if not _reference_cache["teams"]:
        for team in get_all_pages(TEAMS_URL, {"per_page": 100}):
            _reference_cache["teams"][team["id"]] = team.get("full_name", team.get("name", f'Team {team["id"]}'))

    return _reference_cache["players"], _reference_cache["teams"]


STAT_KEYS = {
    "min": "Minutes",
    "poss": "Possessions",
    "off_rating": "Offensive Rating",
    "def_rating": "Defensive Rating",
    "net_rating": "Net Rating",
    "pace": "Pace",
    "pie": "PIE",
}


def average_stats(lineup_games):
    """Mean per appearance of this exact five-man lineup."""
    result = {}
    for key, label in STAT_KEYS.items():
        values = [
            row.get("stats", {}).get(key)
            for row in lineup_games
            if row.get("stats", {}).get(key) is not None
        ]
        result[label] = round(mean(values), 2) if values else None
    return result


def build_lineup_profiles(all_lineup_games):
    grouped = defaultdict(list)
    for row in all_lineup_games:
        ids = row.get("player_ids") or []
        team_id = row.get("team_id")
        if team_id is not None and ids:
            grouped[(team_id, tuple(sorted(ids)))].append(row)

    profiles = []
    for (team_id, player_ids), games in grouped.items():
        stats = average_stats(games)
        profiles.append({
            "team_id": team_id,
            "player_ids": list(player_ids),
            "games": games,
            "games_played": len(games),
            "off_rating": stats["Offensive Rating"],
            "def_rating": stats["Defensive Rating"],
            "pace": stats["Pace"],
            "pie": stats["PIE"],
            "averages": stats,
            "total_minutes": round(sum(
                row.get("stats", {}).get("min") or 0 for row in games
            ), 2),
        })
    return profiles


def find_similar_lineups(target_profile, profiles, top_n=15, min_games=3,
                         exclude_team_id=None):
    metrics = ["off_rating", "def_rating", "pace", "pie"]
    if not target_profile or any(target_profile.get(metric) is None for metric in metrics):
        return []

    eligible = [
        profile for profile in profiles
        if profile["games_played"] >= min_games
        and all(profile.get(metric) is not None for metric in metrics)
        and profile["team_id"] != exclude_team_id
    ]
    if not eligible:
        return []

    stds = {metric: pstdev([p[metric] for p in eligible]) for metric in metrics}
    distances = []
    for profile in eligible:
        if (profile["team_id"] == target_profile["team_id"]
                and set(profile["player_ids"]) == set(target_profile["player_ids"])):
            continue
        distance_squared = 0
        for metric in metrics:
            if stds[metric]:
                distance_squared += (
                    (profile[metric] - target_profile[metric]) / stds[metric]
                ) ** 2
        distances.append((sqrt(distance_squared), profile))

    distances.sort(key=lambda item: item[0])
    return distances[:top_n]


def find_exact_profile(profiles, team_id, player_ids):
    target = set(player_ids)
    return next((
        profile for profile in profiles
        if profile["team_id"] == team_id and set(profile["player_ids"]) == target
    ), None)


def get_team_results_against_profiles(team_id, all_lineup_games, opponent_profiles):
    opponent_game_ids = {
        row["game_id"]
        for profile in opponent_profiles
        for row in profile["games"]
    }
    return [
        row for row in all_lineup_games
        if row.get("team_id") == team_id and row.get("game_id") in opponent_game_ids
    ]


def aggregate_team_game_stats(lineup_rows):
    """
    Collapse all five-man lineup segments into one record per team-game.
    Rate stats are weighted by possessions; total lineup minutes are summed.
    """
    by_game = defaultdict(list)
    for row in lineup_rows:
        by_game[row["game_id"]].append(row)

    game_rows = []
    for game_id, rows in by_game.items():
        total_poss = sum((r.get("stats", {}).get("poss") or 0) for r in rows)
        total_min = sum((r.get("stats", {}).get("min") or 0) for r in rows)
        stats = {"min": total_min, "poss": total_poss}

        for metric in ("off_rating", "def_rating", "net_rating", "pace", "pie"):
            available = [
                (r.get("stats", {}).get(metric), r.get("stats", {}).get("poss") or 0)
                for r in rows if r.get("stats", {}).get(metric) is not None
            ]
            weight_total = sum(weight for _, weight in available)
            if available and weight_total:
                stats[metric] = sum(value * weight for value, weight in available) / weight_total
            elif available:
                stats[metric] = mean(value for value, _ in available)
            else:
                stats[metric] = None

        game_rows.append({"game_id": game_id, "stats": stats})
    return game_rows


def average_team_game_stats(lineup_rows):
    per_game = aggregate_team_game_stats(lineup_rows)
    return average_stats(per_game), len(per_game)


def analyze_team(team_id, team_name, lineup, opponent_team_id, opponent_lineup,
                 profiles, all_rows, player_names, team_names, injuries):
    player_ids = [p["player_id"] for p in lineup["players"]]
    own_profile = find_exact_profile(profiles, team_id, player_ids)
    own_games = own_profile["games"] if own_profile else []
    own_averages = average_stats(own_games)
    own_total_minutes = own_profile["total_minutes"] if own_profile else 0

    opponent_ids = [p["player_id"] for p in opponent_lineup["players"]]
    opponent_profile = find_exact_profile(profiles, opponent_team_id, opponent_ids)

    exact_results = (
        get_team_results_against_profiles(team_id, all_rows, [opponent_profile])
        if opponent_profile else []
    )
    exact_averages, exact_game_count = average_team_game_stats(exact_results)

    # Fallback: all historical lineup segments for this team in games where
    # the opponent team had any lineup-stat record, regardless of its lineup.
    opponent_game_ids = {
        row["game_id"] for row in all_rows if row.get("team_id") == opponent_team_id
    }
    h2h_rows = [
        row for row in all_rows
        if row.get("team_id") == team_id and row.get("game_id") in opponent_game_ids
    ]
    h2h_averages, h2h_game_count = average_team_game_stats(h2h_rows)
    # Minutes in this table represent the sum of lineup segments across a game,
    # not a useful head-to-head matchup duration. Remove it from this fallback.
    h2h_averages.pop("Minutes", None)

    # First find the 10 closest statistical lineup profiles league-wide.
    similar = (
    find_similar_lineups(opponent_profile, profiles, top_n=15, min_games=3,
                         exclude_team_id=team_id)
    if opponent_profile else []
    )

    # Keep only profiles that actually appeared in a game against this team.
    # Then retain the closest qualifying lineup from each team, up to 5 teams.
    team_game_ids = {
        row["game_id"] for row in all_rows if row.get("team_id") == team_id
    }
    qualifying_similar_lineups = []
    seen_opponent_teams = set()
    similar_game_ids = set()
    similar_lineup_rows = []

    for similarity_rank, (distance, profile) in enumerate(similar, start=1):
        matching_rows = [
            row for row in profile["games"]
            if row.get("game_id") in team_game_ids
        ]
        if not matching_rows or profile["team_id"] in seen_opponent_teams:
            continue

        seen_opponent_teams.add(profile["team_id"])
        matching_game_ids = sorted({row["game_id"] for row in matching_rows})
        similar_game_ids.update(matching_game_ids)
        similar_lineup_rows.extend(matching_rows)

        # Average all statistical values except minutes.
        lineup_averages = average_stats(matching_rows)
        lineup_averages.pop("Minutes", None)

        # Total minutes this exact lineup played against our team.
        total_minutes_against_team = round(
            sum(row.get("stats", {}).get("min") or 0 for row in matching_rows),
            2
        )

        qualifying_similar_lineups.append({
            "similarity_rank": similarity_rank,
            "team_name": team_names.get(
                profile["team_id"], f'Team {profile["team_id"]}'
            ),
            "player_names": [
                player_names.get(pid, f"Player {pid}")
                for pid in profile["player_ids"]
            ],
            "games_played": profile["games_played"],
            "games_in_sample": len(matching_game_ids),
            "total_minutes_against_team": round(
                sum(row.get("stats", {}).get("min") or 0 for row in matching_rows),
                2
            ),
            "distance": round(distance, 3),
        })

        if len(qualifying_similar_lineups) == 5:
            break
    similar_averages = possession_weighted_stats(similar_lineup_rows)
    similar_total_possessions = similar_averages["Possessions"]
    similar_total_minutes = round(
        sum(row.get("stats", {}).get("min") or 0 for row in similar_lineup_rows),
        2
    )
    similar_game_count = len(similar_game_ids)

    return {
        "team_name": team_name,
        "lineup_source": lineup["source"],
        "lineup_status": lineup["status"],
        "players": lineup["players"],
        "lineup_games": len(own_games),
        "lineup_averages": own_averages,
        "lineup_total_minutes": own_total_minutes,
        "lineup_avg_minutes": own_averages.get("Minutes"),
        "opponent_exact_games": exact_game_count,
        "opponent_exact_averages": exact_averages,
        "h2h_games": h2h_game_count,
        "h2h_averages": h2h_averages,
        "show_h2h_fallback": exact_game_count == 0 and h2h_game_count > 0,
        "similar_games": similar_game_count,
        "similar_lineup_count": len(qualifying_similar_lineups),
        "similar_profiles_checked": len(similar),
        "similar_lineup_appearances": qualifying_similar_lineups,
        "similar_lineup_averages": similar_averages,
        "similar_total_possessions": similar_total_possessions,
        "similar_total_minutes": similar_total_minutes,
        "has_historical_profile": own_profile is not None,
        "has_opponent_profile": opponent_profile is not None,
        "injuries": injuries,
    }


def possession_weighted_stats(lineup_rows):
    """
    Calculate combined statistics weighted by possessions.
    Possessions are summed; rate statistics are possession-weighted.
    """
    total_possessions = sum(
        row.get("stats", {}).get("poss") or 0
        for row in lineup_rows
    )

    result = {"Possessions": round(total_possessions, 2)}

    metrics = {
        "off_rating": "Offensive Rating",
        "def_rating": "Defensive Rating",
        "net_rating": "Net Rating",
        "pace": "Pace",
        "pie": "PIE",
    }

    for key, label in metrics.items():
        weighted_values = [
            (
                row.get("stats", {}).get(key),
                row.get("stats", {}).get("poss") or 0
            )
            for row in lineup_rows
            if row.get("stats", {}).get(key) is not None
            and (row.get("stats", {}).get("poss") or 0) > 0
        ]

        weight_total = sum(weight for _, weight in weighted_values)

        result[label] = (
            round(
                sum(value * weight for value, weight in weighted_values)
                / weight_total,
                2
            )
            if weight_total else None
        )

    return result

def build_dashboard_data(game_date):
    games = get_games(game_date)
    if not games:
        return {"date": game_date, "games": [], "message": "No NBA games found for this date."}

    all_rows = get_season_lineup_stats(SEASONS)
    profiles = build_lineup_profiles(all_rows)

    all_player_ids = {
        player_id for row in all_rows for player_id in (row.get("player_ids") or [])
    }
    player_names, team_names = get_reference_data(all_player_ids)
    
    

    dashboard_games = []
    for game in games:
        injuries_by_team = get_team_injuries([
                game["home_team_id"],
                game["away_team_id"]
        ])
        actual = get_actual_lineups(game["game_id"])
        actual_starter_team_ids = {
            (row.get("team") or {}).get("id")
            for row in actual if row.get("starter")
        }
        projected = []
        if (game["home_team_id"] not in actual_starter_team_ids
                or game["away_team_id"] not in actual_starter_team_ids):
            projected = get_projected_lineups(game["game_id"])

        lineups = normalize_team_lineups(actual, projected)
        home_lineup = lineups.get(game["home_team_id"])
        away_lineup = lineups.get(game["away_team_id"])

        view = {**game, "home": None, "away": None,
                "lineups_available": bool(home_lineup and away_lineup)}
        if view["lineups_available"]:
            view["home"] = analyze_team(
                game["home_team_id"], game["home_team"], home_lineup,
                game["away_team_id"], away_lineup, profiles, all_rows,
                player_names, team_names,
                injuries_by_team.get(game["home_team_id"], [])
            )
            view["away"] = analyze_team(
                game["away_team_id"], game["away_team"], away_lineup,
                game["home_team_id"], home_lineup, profiles, all_rows,
                player_names, team_names,
                injuries_by_team.get(game["away_team_id"], [])
            )
        dashboard_games.append(view)

    return {
        "date": game_date,
        "games": dashboard_games,
        "message": None,
        "seasons": SEASONS,
        "lineup_records": len(all_rows),
    }


@app.route("/")
def index():
    default_date = datetime.now(LOCAL_TZ).date().isoformat()
    game_date = request.args.get("date", default_date)
    try:
        dashboard = build_dashboard_data(game_date)
        return render_template("index.html", dashboard=dashboard, error=None)
    except requests.HTTPError as exc:
        detail = exc.response.text[:500] if exc.response is not None else str(exc)
        return render_template("index.html", dashboard=None,
                               error=f"Ball Don't Lie API error: {detail}"), 502
    except (requests.RequestException, RuntimeError, ValueError, KeyError) as exc:
        return render_template("index.html", dashboard=None, error=str(exc)), 500


if __name__ == "__main__":
    app.run(debug=True)
