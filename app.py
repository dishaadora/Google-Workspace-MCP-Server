# -*- coding: utf-8 -*-

import os
import flask
import requests
import base64

import google.oauth2.credentials
import google_auth_oauthlib.flow
import googleapiclient.discovery
import openai
import json

# This variable specifies the name of a file that contains the OAuth 2.0
# information for this application, including its client_id and client_secret.
CLIENT_SECRETS_FILE = "client_secret.json"

# The OAuth 2.0 access scope allows for access to the
# authenticated user's account and requires requests to use an SSL connection.
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly',
          'https://www.googleapis.com/auth/calendar.events'] 
API_SERVICE_NAME = 'drive'
API_VERSION = 'v2'

app = flask.Flask(__name__)
# Note: A secret key is included in the sample so that it works.
# If you use this code in your application, replace this with a truly secret
# key. See https://flask.palletsprojects.com/quickstart/#sessions.
app.secret_key = 'REPLACE ME - this value is here as a placeholder.'

@app.route('/')
def index():
  return print_index_table()

@app.route('/calendar')
def calendar_api_request():
    if 'credentials' not in flask.session:
        return flask.redirect('authorize')

    features = flask.session['features']

    if features['calendar']:
    # User authorized Calendar read permission.
    # Calling the APIs, etc.
        return ('<p>User granted the Google Calendar read permission. '+
                'This sample code does not include code to call Calendar</p>')
    else:
    # User didn't authorize Calendar read permission.
    # Update UX and application accordingly
        return '<p>Calendar feature is not enabled.</p>'

@app.route('/authorize')
def authorize():
  # Create flow instance to manage the OAuth 2.0 Authorization Grant Flow steps.
  flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
      CLIENT_SECRETS_FILE, scopes=SCOPES)

  # The URI created here must exactly match one of the authorized redirect URIs
  # for the OAuth 2.0 client, which you configured in the API Console. If this
  # value doesn't match an authorized URI, you will get a 'redirect_uri_mismatch'
  # error.
  flow.redirect_uri = flask.url_for('oauth2callback', _external=True)

  authorization_url, state = flow.authorization_url(
      # Enable offline access so that you can refresh an access token without
      # re-prompting the user for permission. Recommended for web server apps.
      access_type='offline',
      # Enable incremental authorization. Recommended as a best practice.
      include_granted_scopes='true')

  # Store the state so the callback can verify the auth server response.
  flask.session['state'] = state

  return flask.redirect(authorization_url)

@app.route('/oauth2callback')
def oauth2callback():
  # Specify the state when creating the flow in the callback so that it can
  # verified in the authorization server response.
  state = flask.session['state']

  flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
      CLIENT_SECRETS_FILE, scopes=SCOPES, state=state)
  flow.redirect_uri = flask.url_for('oauth2callback', _external=True)

  # Use the authorization server's response to fetch the OAuth 2.0 tokens.
  authorization_response = flask.request.url
  flow.fetch_token(authorization_response=authorization_response)

  # Store credentials in the session.
  # ACTION ITEM: In a production app, you likely want to save these
  #              credentials in a persistent database instead.
  credentials = flow.credentials
  
  credentials = credentials_to_dict(credentials)
  flask.session['credentials'] = credentials

  # Check which scopes user granted
  features = check_granted_scopes(credentials)
  flask.session['features'] = features
  return flask.redirect('/')
  

@app.route('/revoke')
def revoke():
  if 'credentials' not in flask.session:
    return ('You need to <a href="/authorize">authorize</a> before ' +
            'testing the code to revoke credentials.')

  credentials = google.oauth2.credentials.Credentials(
    **flask.session['credentials'])

  revoke = requests.post('https://oauth2.googleapis.com/revoke',
      params={'token': credentials.token},
      headers = {'content-type': 'application/x-www-form-urlencoded'})

  status_code = getattr(revoke, 'status_code')
  if status_code == 200:
    return('Credentials successfully revoked.' + print_index_table())
  else:
    return('An error occurred.' + print_index_table())

@app.route('/clear')
def clear_credentials():
  if 'credentials' in flask.session:
    del flask.session['credentials']
  return ('Credentials have been cleared.<br><br>' +
          print_index_table())

# Helper function to parse email body
def get_email_body(payload):
    """Recursively search for the plain text part of an email."""
    if 'parts' in payload:
        for part in payload['parts']:
            if part['mimeType'] == 'text/plain':
                return base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
            # Recursive call for nested parts
            body = get_email_body(part)
            if body:
                return body
    elif payload['mimeType'] == 'text/plain':
        return base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8')
    return None

@app.route('/create-event-from-email')
def create_event_from_email():
    if 'credentials' not in flask.session:
        return flask.redirect('authorize')

    credentials = google.oauth2.credentials.Credentials(
        **flask.session['credentials'])
    
    # --- 1. LEGGERE L'ULTIMA MAIL DA GMAIL ---
    try:
        gmail_service = googleapiclient.discovery.build(
            'gmail', 'v1', credentials=credentials)
        
        # Get the ID of the most recent email
        messages = gmail_service.users().messages().list(userId='me', maxResults=1).execute()
        if not messages.get('messages'):
            return "<p>Nessuna email trovata nel tuo account Gmail.</p>"
        
        msg_id = messages['messages'][0]['id']
        
        # Fetch the full email
        message = gmail_service.users().messages().get(userId='me', id=msg_id, format='full').execute()
        
        email_snippet = message['snippet']
        email_body = get_email_body(message['payload'])

        if not email_body:
            return "<p>Impossibile trovare il corpo del testo nell'ultima email.</p>"

    except Exception as e:
        return f"<p>Errore durante la lettura da Gmail: {e}</p>"

    # --- 2. INVIARE L'EMAIL A OPENAI PER L'ANALISI ---
    try:
        openai.api_key = os.getenv("OPENAI_API_KEY")
        if not openai.api_key:
            return "<p>La chiave API di OpenAI non è impostata come variabile d'ambiente (OPENAI_API_KEY).</p>"

        prompt = f"""
        Leggi il seguente testo di un'email e estrai le informazioni per creare un evento di Google Calendar.
        Rispondi ESCLUSIVAMENTE con un oggetto JSON. Il JSON deve avere i seguenti campi: "summary" (titolo dell'evento), 
        "description" (una breve descrizione), "start_time" (in formato ISO 8601, es. '2025-06-28T19:00:00'), 
        "end_time" (in formato ISO 8601, es. '2025-06-28T20:00:00'). Se non riesci a determinare una fine, impostala un'ora dopo l'inizio.
        Se una informazione non è presente, imposta il campo a null.

        Email:
        ---
        {email_body}
        ---
        """

        completion = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that extracts event information and returns only JSON."},
                {"role": "user", "content": prompt}
            ]
        )
        
        response_text = completion.choices[0].message.content
        event_details = json.loads(response_text)

    except Exception as e:
        return f"<p>Errore durante la chiamata a OpenAI o nel parsing del JSON: {e}</p><pre>{response_text}</pre>"

    # --- 3. SCRIVERE L'EVENTO SU GOOGLE CALENDAR ---
    try:
        if not event_details.get('summary') or not event_details.get('start_time'):
            return f"<p>OpenAI non ha estratto informazioni sufficienti per creare un evento.</p><pre>{event_details}</pre>"

        calendar_service = googleapiclient.discovery.build(
            'calendar', 'v3', credentials=credentials)
            
        event_body = {
            'summary': event_details['summary'],
            'description': event_details.get('description', f'Evento creato a partire da un\'email.\n\nSnippet: {email_snippet}'),
            'start': {
                'dateTime': event_details['start_time'],
                'timeZone': 'Europe/Rome', # Puoi renderlo dinamico se necessario
            },
            'end': {
                'dateTime': event_details['end_time'],
                'timeZone': 'Europe/Rome',
            },
        }

        created_event = calendar_service.events().insert(calendarId='primary', body=event_body).execute()
        
        return f"""
            <h2>Evento Creato con Successo!</h2>
            <p><b>Titolo:</b> {created_event['summary']}</p>
            <p><a href='{created_event['htmlLink']}' target='_blank'>Vedi l'evento su Google Calendar</a></p>
        """

    except Exception as e:
        return f"<p>Errore durante la creazione dell'evento su Google Calendar: {e}</p>"

def credentials_to_dict(credentials):
  return {'token': credentials.token,
          'refresh_token': credentials.refresh_token,
          'token_uri': credentials.token_uri,
          'client_id': credentials.client_id,
          'client_secret': credentials.client_secret,
          'granted_scopes': credentials.granted_scopes}

def check_granted_scopes(credentials):
  features = {}
  if 'https://www.googleapis.com/auth/drive.metadata.readonly' in credentials['granted_scopes']:
    features['drive'] = True
  else:
    features['drive'] = False

  if 'https://www.googleapis.com/auth/calendar.readonly' in credentials['granted_scopes']:
    features['calendar'] = True
  else:
    features['calendar'] = False

  return features

def print_index_table():
  return ('<table>' +
          '<tr><td><a href="/test">Test an API request</a></td>' +
          '<td>Submit an API request and see a formatted JSON response. ' +
          '    Go through the authorization flow if there are no stored ' +
          '    credentials for the user.</td></tr>' +
          '<tr><td><a href="/authorize">Test the auth flow directly</a></td>' +
          '<td>Go directly to the authorization flow. If there are stored ' +
          '    credentials, you still might not be prompted to reauthorize ' +
          '    the application.</td></tr>' +
          '<tr><td><a href="/revoke">Revoke current credentials</a></td>' +
          '<td>Revoke the access token associated with the current user ' +
          '    session. After revoking credentials, if you go to the test ' +
          '    page, you should see an <code>invalid_grant</code> error.' +
          '</td></tr>' +
          '<tr><td><a href="/clear">Clear Flask session credentials</a></td>' +
          '<td>Clear the access token currently stored in the user session. ' +
          '    After clearing the token, if you <a href="/test">test the ' +
          '    API request</a> again, you should go back to the auth flow.' +
          '</td></tr>' +
          '<tr><td><a href="/create-event-from-email">Crea Evento da Ultima Email (Gmail -> OpenAI -> Calendar)</a></td>' +
          '<td> Legge l\'ultima email, la invia a OpenAI per estrarre i dettagli di un evento, e lo crea su Google Calendar.' +
                'Richiede i permessi per Gmail e Calendar.</td></tr></table>')

if __name__ == '__main__':
  # When running locally, disable OAuthlib's HTTPs verification.
  # ACTION ITEM for developers:
  #     When running in production *do not* leave this option enabled.
  os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

  # This disables the requested scopes and granted scopes check.
  # If users only grant partial request, the warning would not be thrown.
  os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'

  # Specify a hostname and port that are set as a valid redirect URI
  # for your API project in the Google API Console.
  app.run('localhost', 8080, debug=True)