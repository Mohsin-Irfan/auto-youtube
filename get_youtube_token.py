import json
import os
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

def main():
    # Step 1: Download client_secret.json from Google Cloud Console (OAuth 2.0 Client ID for Desktop app)
    # Place it in same folder as this script.
    flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
    creds = flow.run_local_server(port=8080, prompt="consent")
    
    # Print refresh token
    print("\n=== YOUR REFRESH TOKEN (copy this) ===\n")
    print(creds.refresh_token)
    print("\n=== END ===")
    
    # Also save to file for reference
    with open("yt_refresh_token.txt", "w") as f:
        f.write(creds.refresh_token)
    print("Refresh token also saved to yt_refresh_token.txt")

if __name__ == "__main__":
    main()
