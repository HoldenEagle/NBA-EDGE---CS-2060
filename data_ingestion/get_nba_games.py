
import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_URL = "https://api.balldontlie.io/v1/games"

def get_games(game_date):
    api_key = os.getenv("BALLDONTLIE_API_KEY")

    if not api_key:
        raise ValueError("Missing BALLDONTLIE_API_KEY environment variable.")

    headers = {
        "Authorization": api_key
    }

    params = {
        "dates[]": game_date,
        "per_page": 100
    }

    response = requests.get(
        API_URL,
        headers=headers,
        params=params,
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


if __name__ == "__main__":
    games = get_games("2026-11-08")

    for game in games:
        print(game)
    
    print(f"\nTotal games found: {len(games)}")
