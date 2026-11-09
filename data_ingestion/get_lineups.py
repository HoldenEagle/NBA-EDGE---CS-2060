
import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_URL = "https://api.balldontlie.io/v1/games"
LINEUPS_URL = "https://api.balldontlie.io/nba/v1/lineups"
PROJECTED_URL = "https://api.balldontlie.io/nba/v1/projected_lineups"


def get_headers():
    api_key = os.getenv("BALLDONTLIE_API_KEY")

    if not api_key:
        raise ValueError("Missing BALLDONTLIE_API_KEY environment variable.")

    return {"Authorization": api_key}


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


if __name__ == "__main__":
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
