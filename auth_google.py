"""One-time OAuth setup script.

Run this once before starting the bot:

    python auth_google.py

It opens a browser for Google consent covering both Calendar and Tasks,
then writes the resulting credentials to DATA_DIR/token.json.
"""

import os
import sys

from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow

load_dotenv()

DATA_DIR = os.getenv("DATA_DIR", ".")
TOKEN_PATH = os.path.join(DATA_DIR, "token.json")

# Combined scopes so a single consent flow covers both services.
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/tasks",
]


def main() -> None:
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")

    if not client_id or not client_secret:
        print("ERROR: GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set in .env")
        sys.exit(1)

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    print("Opening browser for Google consent...")
    creds = flow.run_local_server(port=0)

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(TOKEN_PATH, "w") as token_file:
        token_file.write(creds.to_json())

    print(f"\nSuccess! Credentials saved to {TOKEN_PATH}")
    print("You can now run the bot with: python bot.py")


if __name__ == "__main__":
    main()
