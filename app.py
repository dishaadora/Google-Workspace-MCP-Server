import base64
import os
import sys
from typing import Dict, Any, AsyncIterator, Optional
from contextlib import asynccontextmanager

import google.oauth2.credentials
import googleapiclient.discovery
from google.auth.transport.requests import Request
from googleapiclient.errors import HttpError

from mcp.server.fastmcp import FastMCP, Context
from config import SCOPES

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_PATH = os.path.join(SCRIPT_DIR, 'token.json')

# --- Lifespan Management for Credentials ---

@asynccontextmanager
async def credential_manager(server: FastMCP) -> AsyncIterator[Dict[str, Any]]:
    """
    Manages loading and refreshing Google API credentials on server startup.
    """
    creds = None
    if not os.path.exists(TOKEN_PATH):
        print(f"ERROR: Token file '{TOKEN_PATH}' not found.", file=sys.stderr)
        print("Please run 'python get_credentials.py' first to authorize the application.", file=sys.stderr)
        # Yield an empty context and let tool calls fail gracefully
        yield {"creds": None}
        return

    print(f"Loading credentials from {TOKEN_PATH}", file=sys.stderr)
    creds = google.oauth2.credentials.Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if creds and creds.expired and creds.refresh_token:
        print("Credentials expired. Refreshing...", file=sys.stderr)
        try:
            creds.refresh(Request())
            # Re-save the refreshed token
            with open(TOKEN_PATH, 'w') as token_file:
                token_file.write(creds.to_json())
            print("Token refreshed and saved.", file=sys.stderr)
        except Exception as e:
            print(f"ERROR: Failed to refresh token: {e}", file=sys.stderr)
            creds = None # Mark credentials as invalid
            
    # Make credentials available to all tool handlers via context
    yield {"creds": creds}
    print("Server shutting down.", file=sys.stderr)



# Initialize the server with the lifespan manager
server = FastMCP(
    "GsuiteMCPServer", 
    title="Gsuite MCP Server",
    lifespan=credential_manager
)

def get_creds_from_context(ctx: Context) -> google.oauth2.credentials.Credentials:
    """Helper to get credentials from the context and handle errors."""
    creds = ctx.request_context.lifespan_context.get("creds")
    if not creds or not creds.valid:
        raise Exception(
            "Google API credentials are not available or invalid. "
            "Please run 'python get_credentials.py' to authenticate."
        )
    return creds

def get_email_body(payload: Dict[str, Any]) -> Optional[str]:
    """Cerca ricorsivamente la parte di testo 'text/plain' di un'email."""
    if 'parts' in payload:
        for part in payload['parts']:
            if part['mimeType'] == 'text/plain' and 'data' in part['body']:
                return base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
            body = get_email_body(part)
            if body:
                return body
    elif payload['mimeType'] == 'text/plain' and 'data' in payload['body']:
        return base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8')
    return None

@server.tool()
def read_latest_gmail_email(ctx: Context) -> Dict[str, str]:
    creds = get_creds_from_context(ctx)
    try:
        gmail_service = googleapiclient.discovery.build('gmail', 'v1', credentials=creds)
        messages_list = gmail_service.users().messages().list(userId='me', maxResults=1).execute()
        
        if not messages_list.get('messages'):
            raise AppError("Email not found.", status_code=404)
        
        msg_id = messages_list['messages'][0]['id']
        message = gmail_service.users().messages().get(userId='me', id=msg_id, format='full').execute()
        
        email_body = get_email_body(message['payload'])
        if not email_body:
            raise AppError("Impossible finding body in the last mail.")
            
        return {'snippet': message.get('snippet', ''), 'body': email_body}
    except HttpError as e:
        raise AppError(f"API Gmail error: {e.reason}", status_code=e.status_code)

@server.tool()
def create_calendar_event(event_details: Dict[str, Any], email_snippet: str, ctx: Context) -> Dict[str, Any]:
    creds = get_creds_from_context(ctx)
    event_body = {
        'summary': event_details['summary'],
        'description': event_details.get('description', f'Created from email.\nSnippet: {email_snippet}'),
        'start': {'dateTime': event_details['start_time'], 'timeZone': 'Europe/Rome'},
        'end': {'dateTime': event_details['end_time'], 'timeZone': 'Europe/Rome'},
    }
    try:
        calendar_service = googleapiclient.discovery.build('calendar', 'v3', credentials=creds)
        created_event = calendar_service.events().insert(calendarId='primary', body=event_body).execute()
        return created_event
    except HttpError as e:
        raise AppError(f"API Calendar error: {e.reason}", status_code=e.status_code)


if __name__ == "__main__":
    server.run()