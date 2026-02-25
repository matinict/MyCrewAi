#python3 auth_helper.py
#uv run auth_helper.py
import os
import json
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

SCOPES = [
    'https://www.googleapis.com/auth/youtube.upload',
    'https://www.googleapis.com/auth/youtube.force-ssl'
]

def get_creds():
    token_path = 'token.json'
    # Use the specific client secret name seen in your tree
    secret_path = 'client_secret_839331006393-5leiaeau4655bknuge32686ph7476c7a.apps.googleusercontent.com.json'

    creds = None

    # Check if token exists AND is not empty
    if os.path.exists(token_path) and os.path.getsize(token_path) > 0:
        try:
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        except Exception as e:
            print(f"⚠️ Error reading token: {e}. Re-authenticating...")

    # If no valid credentials, run the flow
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("🔄 Refreshing expired token...")
            creds.refresh(Request())
        else:
            print("🔑 Starting new auth flow...")
            flow = InstalledAppFlow.from_client_secrets_file(secret_path, SCOPES)
            # Port 0 finds an available local port automatically
            creds = flow.run_local_server(port=0)

        # Save the token
        with open(token_path, 'w') as token:
            token.write(creds.to_json())
            print(f"✅ Token saved to {token_path}")

    return creds

if __name__ == "__main__":
    get_creds()
    print("🚀 Authentication ready!")
