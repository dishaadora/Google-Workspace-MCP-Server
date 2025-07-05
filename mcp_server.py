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
from pydantic import BaseModel, Field
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
    """Recursively finds the 'text/plain' part of an email."""
    if 'parts' in payload:
        for part in payload['parts']:
            if part['mimeType'] == 'text/plain' and 'data' in part['body']:
                return base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
            # Recurse to check nested parts
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
            raise Exception("No emails found.")
        
        msg_id = messages_list['messages'][0]['id']
        message = gmail_service.users().messages().get(userId='me', id=msg_id, format='full').execute()
        
        email_body = get_email_body(message['payload'])
        if not email_body:
            raise Exception("Could not find the body in the last email.")
            
        return {'snippet': message.get('snippet', ''), 'body': email_body}
    except HttpError as e:
        raise Exception(f"API Gmail error (HTTP {e.status_code}): {e.reason}")

class EventDetails(BaseModel):
    summary: str = Field(description="The title or summary of the calendar event.")
    start_time: str = Field(description="The start time of the event in ISO 8601 format (e.g., '2025-07-05T15:00:00').")
    end_time: str = Field(description="The end time of the event in ISO 8601 format (e.g., '2025-07-05T16:00:00').")
    description: Optional[str] = Field(None, description="A detailed description for the event. Can include notes from the source email.")

@server.tool()
def create_calendar_event(event_details: EventDetails, ctx: Context) -> Dict[str, Any]:
    """
    Creates a Google Calendar event from structured event details.
    
    Args:
        event_details: A structured object containing the summary, start time, end time, and description.
    """
    creds = get_creds_from_context(ctx)
    
    # Use the pydantic model directly to build the event body
    event_body = {
        'summary': event_details.summary,
        'description': event_details.description or f'Created from an email automation.',
        'start': {'dateTime': event_details.start_time, 'timeZone': 'Europe/Rome'},
        'end': {'dateTime': event_details.end_time, 'timeZone': 'Europe/Rome'},
    }
    
    try:
        calendar_service = googleapiclient.discovery.build('calendar', 'v3', credentials=creds)
        created_event = calendar_service.events().insert(calendarId='primary', body=event_body).execute()
        return created_event
    except HttpError as e:
        raise Exception(f"API Calendar error (HTTP {e.status_code}): {e.reason}")

if __name__ == "__main__":
    server.run()