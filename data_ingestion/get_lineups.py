
import os
import requests
from dotenv import load_dotenv
LINEUP_STATS_URL = "https://api.balldontlie.io/nba/v1/lineup_stats"


load_dotenv()

API_URL = "https://api.balldontlie.io/v1/games"
LINEUPS_URL = "https://api.balldontlie.io/nba/v1/lineups"
PROJECTED_URL = "https://api.balldontlie.io/nba/v1/projected_lineups"


def get_headers():
    api_key = os.getenv("BALLDONTLIE_API_KEY")

    if not api_key:
        raise ValueError("Missing BALLDONTLIE_API_KEY environment variable.")

    return {"Authorization": api_key}


def get_lineup_stats(player_ids, season, team_id=None):
    params = {
        "player_ids[]": player_ids,
        "seasons[]": season,
        "per_page": 100
    }

    if team_id is not None:
        params["team_ids[]"] = team_id

    all_stats = []

    while True:
        response = requests.get(
            LINEUP_STATS_URL,
            headers=get_headers(),
            params=params,
            timeout=30
        )

        response.raise_for_status()
        result = response.json()

        all_stats.extend(result["data"])

        next_cursor = result["meta"].get("next_cursor")

        if not next_cursor:
            break

        params["cursor"] = next_cursor

    return all_stats


def get_starting_lineups(game_id):
    lineups = get_lineups(game_id)

    starting_lineups = {}

    for player in lineups:
        if not player["starter"]:
            continue

        team = player["team"]["full_name"]

        if team not in starting_lineups:
            starting_lineups[team] = []

        starting_lineups[team].append({
            "player_id": player["player"]["id"],
            "name": (
                player["player"]["first_name"]
                + " "
                + player["player"]["last_name"]
            ),
            "position": player["position"],
            "team_id": player["team"]["id"]
        })

    return starting_lineups


def get_games(game_date):
    response = requests.get(
        API_URL,
        headers=get_headers(),
        params={"dates[]": game_date, "per_page": 100},
        timeout=30
    )

    response.raise_for_status()
    data = response.json()["data"]

    games = []

    for game in data:
        games.append({
            "game_id": game["id"],
            "date": game["date"],
            "status": game["status"],
            "home_team": game["home_team"]["full_name"],
            "away_team": game["visitor_team"]["full_name"]
        })

    return games


def get_lineups(game_id):
    response = requests.get(
        LINEUPS_URL,
        headers=get_headers(),
        params={"game_ids": game_id, "per_page": 100},
        timeout=30
    )

    response.raise_for_status()
    return response.json()["data"]




def get_projected_lineups(game_id):
    response = requests.get(
        PROJECTED_URL,
        headers=get_headers(),
        params={"game_ids[]": game_id, "per_page": 100},
        timeout=30
    )

    response.raise_for_status()
    return response.json()["data"]

from statistics import mean


def calculate_lineup_averages(lineup_games):

    if not lineup_games:
        print("No games found for this lineup.")
        return None

    stat_names = {
        "min": "Minutes",
        "poss": "Possessions",
        "off_rating": "Offensive Rating",
        "def_rating": "Defensive Rating",
        "net_rating": "Net Rating",
        "pace": "Pace"
    }

    averages = {}

    for stat_key, stat_name in stat_names.items():

        values = [
            game["stats"][stat_key]
            for game in lineup_games
            if game["stats"].get(stat_key) is not None
        ]

        averages[stat_name] = mean(values) if values else None

    return averages

def get_all_lineup_stats(season):
    params = {
        "seasons[]": season,
        "per_page": 100
    }

    all_stats = []

    while True:
        response = requests.get(
            LINEUP_STATS_URL,
            headers=get_headers(),
            params=params,
            timeout=30
        )

        response.raise_for_status()
        result = response.json()

        all_stats.extend(result["data"])

        next_cursor = result["meta"].get("next_cursor")

        if next_cursor is None:
            break

        params["cursor"] = next_cursor

    return all_stats

from collections import defaultdict
from statistics import mean


def build_lineup_profiles(all_lineup_games):

    grouped = defaultdict(list)

    for game in all_lineup_games:
        lineup_key = (
            game["team_id"],
            tuple(sorted(game["player_ids"]))
        )

        grouped[lineup_key].append(game)

    profiles = []

    for (team_id, player_ids), games in grouped.items():

        profile = {
            "team_id": team_id,
            "player_ids": list(player_ids),
            "games": games,
            "games_played": len(games)
        }

        stat_keys = {
            "min": "minutes",
            "poss": "possessions",
            "off_rating": "off_rating",
            "def_rating": "def_rating",
            "net_rating": "net_rating",
            "pace": "pace"
        }

        for api_key, profile_key in stat_keys.items():

            values = [
                game["stats"][api_key]
                for game in games
                if game["stats"].get(api_key) is not None
            ]

            profile[profile_key] = (
                mean(values) if values else None
            )

        profiles.append(profile)

    return profiles

from math import sqrt
from statistics import pstdev, mean


def find_similar_lineups(
    target_lineup,
    all_profiles,
    top_n=15,
    min_games=3,
    exclude_team_id=None
):

    metrics = ["off_rating", "def_rating", "pace"]

    # Only compare lineups with complete stats and a reasonable sample
    eligible = [
        profile for profile in all_profiles
        if profile["games_played"] >= min_games
        and all(profile[metric] is not None for metric in metrics)
        and profile["team_id"] != exclude_team_id
    ]

    # Calculate league-wide means and standard deviations
    league_means = {
        metric: mean([p[metric] for p in eligible])
        for metric in metrics
    }

    league_stds = {
        metric: pstdev([p[metric] for p in eligible])
        for metric in metrics
    }

    distances = []

    for profile in eligible:

        # Don't compare the target lineup against itself
        if (
            profile["team_id"] == target_lineup["team_id"]
            and set(profile["player_ids"])
            == set(target_lineup["player_ids"])
        ):
            continue

        distance_squared = 0

        for metric in metrics:

            std = league_stds[metric]

            if std == 0:
                continue

            difference = (
                profile[metric] - target_lineup[metric]
            ) / std

            distance_squared += difference ** 2

        distance = sqrt(distance_squared)

        distances.append((distance, profile))

    distances.sort(key=lambda x: x[0])

    return distances[:top_n]

def get_sixers_results_against_profiles(
    sixers_lineup_games,
    all_lineup_games,
    opponent_profiles,
    sixers_team_id
):
    opponent_game_ids = set()

    # Find games in which the opponent lineup appeared
    for profile in opponent_profiles:
        target_players = set(profile["player_ids"])
        target_team = profile["team_id"]

        for game in all_lineup_games:
            if game["team_id"] != target_team:
                continue

            if set(game["player_ids"]) == target_players:
                opponent_game_ids.add(game["game_id"])

    # Keep only the exact Sixers starting-five records
    sixers_results = [
        game for game in sixers_lineup_games
        if game["team_id"] == sixers_team_id
        and game["game_id"] in opponent_game_ids
    ]

    return sixers_results






















if __name__ == "__main__":
    '''
    games = get_games("2026-11-08")

    if not games:
        print("No games found for this date.")
        raise SystemExit

    # Select the first game returned
    game = games[0]

    print(f"\nGAME: {game['away_team']} @ {game['home_team']}")
    print(f"Game ID: {game['game_id']}")
    print(f"Status: {game['status']}")

    # First, try to retrieve actual lineups
    lineups = get_lineups(game["game_id"])

    if lineups:
        print("\nACTUAL LINEUPS")

        for player in lineups:
            name = (
                player["player"]["first_name"]
                + " "
                + player["player"]["last_name"]
            )

            team = player["team"]["full_name"]
            position = player["position"]
            role = "Starter" if player["starter"] else "Bench"

            print(f"{team}: {name} | {position} | {role}")

    else:
        print("\nNo actual lineups available yet.")
        print("Trying projected lineups instead...")

        projected = get_projected_lineups(game["game_id"])

        if not projected:
            print("No projected lineups available either.")

        for team_lineup in projected:
            print(f"\n{team_lineup['status'].upper()}")

            for player in team_lineup["lineup"]:
                name = (
                    player["player"]["first_name"]
                    + " "
                    + player["player"]["last_name"]
                )

                print(f"{player['position']}: {name}")
    '''
    starting_lineups = get_starting_lineups(21718059)
    for team, players in starting_lineups.items():
        print(f"\n{team} STARTING LINEUP")

        for player in players:
            print(
                f"{player['name']} | "
                f"{player['position']} | "
                f"ID: {player['player_id']}"
            )
    
    philly_players = starting_lineups["Philadelphia 76ers"]

    player_ids = [
        player["player_id"]
        for player in philly_players
    ]

    team_id = philly_players[0]["team_id"]

    lineup_games = get_lineup_stats(
    player_ids=player_ids,
    season=2026,
    team_id=team_id
    )

    print(f"Found {len(lineup_games)} games for this lineup.")
    
    lineup_games = [
    game for game in lineup_games
    if set(game["player_ids"]) == set(player_ids)
    ]
    
    averages = calculate_lineup_averages(lineup_games)

    print("\n========== LINEUP SEASON AVERAGES ==========")
    print(f"Games Played Together: {len(lineup_games)}")

    for stat, average in averages.items():
        if average is not None:
            print(f"Average {stat}: {average:.2f}")
            
            
    opponent_team = "Chicago Bulls"

    opponent_players = starting_lineups[opponent_team]

    opponent_player_ids = [
        player["player_id"] for player in opponent_players
    ]

    opponent_team_id = opponent_players[0]["team_id"]
    
    opponent_lineup_games = get_lineup_stats(
    player_ids=opponent_player_ids,
    season=2026,
    team_id=opponent_team_id
    )

    # Make sure we only have the exact five-man combination
    opponent_lineup_games = [
        game for game in opponent_lineup_games
        if set(game["player_ids"]) == set(opponent_player_ids)
    ]

    print(f"{opponent_team} lineup played together in {len(opponent_lineup_games)} games.")
    
    opponent_averages = calculate_lineup_averages(
    opponent_lineup_games
    )
    
    our_averages = calculate_lineup_averages(lineup_games)

    print("\n========== LINEUP MATCHUP COMPARISON ==========")

    print(f"\n{'Metric':<22} {'Philadelphia':>15} {'Chicago':>15}")

    for stat in our_averages:

        our_value = our_averages[stat]
        opponent_value = opponent_averages[stat]

        if our_value is not None and opponent_value is not None:
            print(
                f"{stat:<22} "
                f"{our_value:>15.2f} "
                f"{opponent_value:>15.2f}"
            )

    # 1. Retrieve all NBA lineup records for the season
all_lineup_games = get_all_lineup_stats(season=2026)

print(f"\nTotal league-wide lineup records: {len(all_lineup_games)}")


# 2. Build season profiles for every unique five-man lineup
all_profiles = build_lineup_profiles(all_lineup_games)

print(f"Unique five-man lineups: {len(all_profiles)}")


# 3. Find Chicago's exact starting lineup profile
bulls_profile = next(
    (
        profile for profile in all_profiles
        if profile["team_id"] == opponent_team_id
        and set(profile["player_ids"]) == set(opponent_player_ids)
    ),
    None
)

if bulls_profile is None:
    raise ValueError("Could not find the Bulls lineup profile.")


# 4. Find the 10 most similar lineups across the league
similar_lineups = find_similar_lineups(
    target_lineup=bulls_profile,
    all_profiles=all_profiles,
    top_n=10,
    min_games=3,
    exclude_team_id=team_id
)


print("\n========== MOST SIMILAR LINEUPS ==========")

for rank, (distance, profile) in enumerate(similar_lineups, start=1):

    print(f"\nRank: {rank}")
    print(f"Team ID: {profile['team_id']}")
    print(f"Player IDs: {profile['player_ids']}")
    print(f"Similarity distance: {distance:.3f}")
    print(f"Offensive Rating: {profile['off_rating']:.2f}")
    print(f"Defensive Rating: {profile['def_rating']:.2f}")
    print(f"Pace: {profile['pace']:.2f}")
    print(f"Games: {profile['games_played']}")


# 5. Philadelphia's performance against the exact Bulls lineup
bulls_results = get_sixers_results_against_profiles(
    sixers_lineup_games=lineup_games,
    all_lineup_games=all_lineup_games,
    opponent_profiles=[bulls_profile],
    sixers_team_id=team_id
)

bulls_averages = calculate_lineup_averages(bulls_results) or {}

# 6. Philadelphia's performance against similar lineups
similar_profiles = [
    profile for distance, profile in similar_lineups
]

similar_results = get_sixers_results_against_profiles(
    sixers_lineup_games=lineup_games,
    all_lineup_games=all_lineup_games,
    opponent_profiles=similar_profiles,
    sixers_team_id=team_id
)

similar_averages = calculate_lineup_averages(similar_results) or {}



# 7. Compare the results
print("\n========== SIXERS PERFORMANCE ==========")

print(f"\nGames against exact Bulls lineup: {len(bulls_results)}")
print(f"Games against similar lineups: {len(similar_results)}")

print(f"\n{'Metric':<22} {'Bulls':>15} {'Similar Lineups':>18}")

for stat in ["Minutes", "Possessions", "Offensive Rating",
             "Defensive Rating", "Net Rating", "Pace"]:

    bulls_value = bulls_averages.get(stat)
    similar_value = similar_averages.get(stat)

    bulls_display = f"{bulls_value:.2f}" if bulls_value is not None else "N/A"
    similar_display = f"{similar_value:.2f}" if similar_value is not None else "N/A"

    print(f"{stat:<25} {bulls_display:>12} {similar_display:>20}")
    