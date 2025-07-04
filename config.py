import os
from dotenv import load_dotenv

load_dotenv()

CLIENT_SECRETS_FILE = "desktop_client_secrets.json"

SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/calendar.events'
]

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
