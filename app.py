# requirements.txt
"""
Flask==2.3.3
google-auth==2.23.4
google-auth-oauthlib==1.1.0
google-auth-httplib2==0.1.1
google-api-python-client==2.108.0
redis==5.0.1
cryptography==41.0.7
python-dotenv==1.0.0
gunicorn==21.2.0
"""

# .env (example file - create your own with actual values)
"""
GOOGLE_CLIENT_ID=your_client_id_here
GOOGLE_CLIENT_SECRET=your_client_secret_here
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=your_secret_key_here_use_secrets_token_urlsafe_32
FLASK_ENV=production
SESSION_DURATION_HOURS=24
ENCRYPTION_KEY=your_fernet_key_here_use_fernet_generate_key
"""

import os
import json
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple
from functools import wraps

import redis
from flask import Flask, request, jsonify, session, redirect, url_for
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from cryptography.fernet import Fernet
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Redis connection
redis_client = redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379/0'))

# Encryption for sensitive data
cipher_suite = Fernet(os.getenv('ENCRYPTION_KEY').encode())

# Google OAuth configuration
SCOPES = [
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/gmail.readonly'
]

GOOGLE_CLIENT_CONFIG = {
    "web": {
        "client_id": os.getenv('GOOGLE_CLIENT_ID'),
        "client_secret": os.getenv('GOOGLE_CLIENT_SECRET'),
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost:5000/callback"]
    }
}

SESSION_DURATION = timedelta(hours=int(os.getenv('SESSION_DURATION_HOURS', 24)))


class SecurityManager:
    """Handles encryption, hashing, and security operations"""
    
    @staticmethod
    def encrypt_data(data: str) -> str:
        """Encrypt sensitive data before storing"""
        return cipher_suite.encrypt(data.encode()).decode()
    
    @staticmethod
    def decrypt_data(encrypted_data: str) -> str:
        """Decrypt sensitive data after retrieval"""
        return cipher_suite.decrypt(encrypted_data.encode()).decode()
    
    @staticmethod
    def hash_user_id(user_id: str) -> str:
        """Create a hash of user ID for Redis keys"""
        return hashlib.sha256(user_id.encode()).hexdigest()
    
    @staticmethod
    def generate_session_token() -> str:
        """Generate a secure session token"""
        return secrets.token_urlsafe(32)


class RedisManager:
    """Handles Redis operations for caching and session management"""
    
    @staticmethod
    def store_user_credentials(user_id: str, credentials: Credentials) -> bool:
        """Store encrypted user credentials in Redis"""
        try:
            hashed_user_id = SecurityManager.hash_user_id(user_id)
            creds_data = {
                'token': credentials.token,
                'refresh_token': credentials.refresh_token,
                'token_uri': credentials.token_uri,
                'client_id': credentials.client_id,
                'client_secret': credentials.client_secret,
                'scopes': credentials.scopes,
                'expiry': credentials.expiry.isoformat() if credentials.expiry else None
            }
            
            encrypted_creds = SecurityManager.encrypt_data(json.dumps(creds_data))
            redis_client.setex(
                f"user_creds:{hashed_user_id}",
                SESSION_DURATION,
                encrypted_creds
            )
            return True
        except Exception as e:
            app.logger.error(f"Failed to store credentials: {e}")
            return False
    
    @staticmethod
    def get_user_credentials(user_id: str) -> Optional[Credentials]:
        """Retrieve and decrypt user credentials from Redis"""
        try:
            hashed_user_id = SecurityManager.hash_user_id(user_id)
            encrypted_creds = redis_client.get(f"user_creds:{hashed_user_id}")
            
            if not encrypted_creds:
                return None
            
            decrypted_creds = SecurityManager.decrypt_data(encrypted_creds.decode())
            creds_data = json.loads(decrypted_creds)
            
            credentials = Credentials(
                token=creds_data['token'],
                refresh_token=creds_data['refresh_token'],
                token_uri=creds_data['token_uri'],
                client_id=creds_data['client_id'],
                client_secret=creds_data['client_secret'],
                scopes=creds_data['scopes']
            )
            
            if creds_data['expiry']:
                credentials.expiry = datetime.fromisoformat(creds_data['expiry'])
            
            return credentials
        except Exception as e:
            app.logger.error(f"Failed to retrieve credentials: {e}")
            return None
    
    @staticmethod
    def store_session(session_token: str, user_id: str) -> bool:
        """Store session information"""
        try:
            redis_client.setex(
                f"session:{session_token}",
                SESSION_DURATION,
                user_id
            )
            return True
        except Exception as e:
            app.logger.error(f"Failed to store session: {e}")
            return False
    
    @staticmethod
    def get_session_user(session_token: str) -> Optional[str]:
        """Get user ID from session token"""
        try:
            user_id = redis_client.get(f"session:{session_token}")
            return user_id.decode() if user_id else None
        except Exception as e:
            app.logger.error(f"Failed to retrieve session: {e}")
            return None
    
    @staticmethod
    def invalidate_session(session_token: str) -> bool:
        """Invalidate a session"""
        try:
            redis_client.delete(f"session:{session_token}")
            return True
        except Exception as e:
            app.logger.error(f"Failed to invalidate session: {e}")
            return False


class GoogleWorkspaceManager:
    """Handles Google Workspace API operations"""
    
    def __init__(self, credentials: Credentials):
        self.credentials = credentials
        self._refresh_credentials_if_needed()
    
    def _refresh_credentials_if_needed(self):
        """Refresh credentials if they're expired"""
        if self.credentials.expired and self.credentials.refresh_token:
            self.credentials.refresh(Request())
    
    def create_calendar_event(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new Google Calendar event"""
        try:
            service = build('calendar', 'v3', credentials=self.credentials)
            
            event = {
                'summary': event_data.get('title', 'New Event'),
                'description': event_data.get('description', ''),
                'start': {
                    'dateTime': event_data['start_datetime'],
                    'timeZone': event_data.get('timezone', 'UTC'),
                },
                'end': {
                    'dateTime': event_data['end_datetime'],
                    'timeZone': event_data.get('timezone', 'UTC'),
                },
                'attendees': [
                    {'email': email} for email in event_data.get('attendees', [])
                ],
                'reminders': {
                    'useDefault': False,
                    'overrides': [
                        {'method': 'email', 'minutes': 24 * 60},
                        {'method': 'popup', 'minutes': 10},
                    ],
                },
            }
            
            if event_data.get('location'):
                event['location'] = event_data['location']
            
            created_event = service.events().insert(
                calendarId='primary',
                body=event,
                sendUpdates='all' if event_data.get('send_notifications', True) else 'none'
            ).execute()
            
            return {
                'success': True,
                'event_id': created_event['id'],
                'event_url': created_event.get('htmlLink'),
                'created': created_event.get('created')
            }
            
        except Exception as e:
            app.logger.error(f"Failed to create calendar event: {e}")
            return {'success': False, 'error': str(e)}


# Authentication decorator
def require_auth(f):
    """Decorator to require authentication for endpoints"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        session_token = request.headers.get('Authorization')
        if not session_token or not session_token.startswith('Bearer '):
            return jsonify({'error': 'Authentication required'}), 401
        
        token = session_token.split(' ')[1]
        user_id = RedisManager.get_session_user(token)
        
        if not user_id:
            return jsonify({'error': 'Invalid or expired session'}), 401
        
        # Add user_id to request context
        request.user_id = user_id
        return f(*args, **kwargs)
    
    return decorated_function


# Data transformation function signatures (to be implemented)
def transform_calendar_data(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Transform input data to Google Calendar event format
    
    Args:
        input_data: Raw input data to be transformed
        
    Returns:
        Dict containing transformed data ready for calendar creation
        
    TODO: Implement transformation logic based on your specific requirements
    """
    pass


def transform_drive_data(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Transform input data for Google Drive operations
    
    Args:
        input_data: Raw input data to be transformed
        
    Returns:
        Dict containing transformed data ready for drive operations
        
    TODO: Implement transformation logic based on your specific requirements
    """
    pass


def transform_gmail_data(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Transform input data for Gmail operations
    
    Args:
        input_data: Raw input data to be transformed
        
    Returns:
        Dict containing transformed data ready for gmail operations
        
    TODO: Implement transformation logic based on your specific requirements
    """
    pass


def validate_calendar_input(input_data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Validate input data for calendar operations
    
    Args:
        input_data: Input data to validate
        
    Returns:
        Tuple of (is_valid, error_message)
        
    TODO: Implement validation logic
    """
    pass


def validate_drive_input(input_data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Validate input data for drive operations
    
    Args:
        input_data: Input data to validate
        
    Returns:
        Tuple of (is_valid, error_message)
        
    TODO: Implement validation logic
    """
    pass


# API Routes

@app.route('/auth/login')
def login():
    """Initiate Google OAuth flow"""
    flow = Flow.from_client_config(
        GOOGLE_CLIENT_CONFIG,
        scopes=SCOPES
    )
    flow.redirect_uri = url_for('callback', _external=True)
    
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent'
    )
    
    session['state'] = state
    return redirect(authorization_url)


@app.route('/callback')
def callback():
    """Handle OAuth callback"""
    if 'state' not in session or request.args.get('state') != session['state']:
        return jsonify({'error': 'Invalid state parameter'}), 400
    
    flow = Flow.from_client_config(
        GOOGLE_CLIENT_CONFIG,
        scopes=SCOPES,
        state=session['state']
    )
    flow.redirect_uri = url_for('callback', _external=True)
    
    try:
        flow.fetch_token(authorization_response=request.url)
        credentials = flow.credentials
        
        # Get user info to create user ID
        service = build('oauth2', 'v2', credentials=credentials)
        user_info = service.userinfo().get().execute()
        user_id = user_info['id']
        
        # Store credentials and create session
        if RedisManager.store_user_credentials(user_id, credentials):
            session_token = SecurityManager.generate_session_token()
            RedisManager.store_session(session_token, user_id)
            
            return jsonify({
                'success': True,
                'session_token': session_token,
                'user_id': user_id,
                'expires_in': int(SESSION_DURATION.total_seconds())
            })
        else:
            return jsonify({'error': 'Failed to store credentials'}), 500
            
    except Exception as e:
        app.logger.error(f"OAuth callback error: {e}")
        return jsonify({'error': 'Authentication failed'}), 400


@app.route('/auth/logout', methods=['POST'])
@require_auth
def logout():
    """Logout and invalidate session"""
    session_token = request.headers.get('Authorization').split(' ')[1]
    
    if RedisManager.invalidate_session(session_token):
        return jsonify({'success': True, 'message': 'Logged out successfully'})
    else:
        return jsonify({'error': 'Failed to logout'}), 500


@app.route('/api/calendar/create', methods=['POST'])
@require_auth
def create_calendar_event():
    """Create a new Google Calendar event"""
    try:
        input_data = request.get_json()
        
        if not input_data:
            return jsonify({'error': 'No data provided'}), 400
        
        # Get user credentials
        credentials = RedisManager.get_user_credentials(request.user_id)
        if not credentials:
            return jsonify({'error': 'User credentials not found'}), 401
        
        # Transform and validate data
        transformed_data = transform_calendar_data(input_data)
        is_valid, error_msg = validate_calendar_input(transformed_data)
        
        if not is_valid:
            return jsonify({'error': f'Invalid input: {error_msg}'}), 400
        
        # Create calendar event
        workspace_manager = GoogleWorkspaceManager(credentials)
        result = workspace_manager.create_calendar_event(transformed_data)
        
        if result['success']:
            # Update stored credentials if they were refreshed
            RedisManager.store_user_credentials(request.user_id, workspace_manager.credentials)
            return jsonify(result), 201
        else:
            return jsonify(result), 400
            
    except Exception as e:
        app.logger.error(f"Error creating calendar event: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/transform/calendar', methods=['POST'])
@require_auth
def transform_calendar_endpoint():
    """Transform input data to calendar format"""
    try:
        input_data = request.get_json()
        
        if not input_data:
            return jsonify({'error': 'No data provided'}), 400
        
        transformed_data = transform_calendar_data(input_data)
        return jsonify({
            'success': True,
            'transformed_data': transformed_data
        })
        
    except Exception as e:
        app.logger.error(f"Error transforming calendar data: {e}")
        return jsonify({'error': 'Transformation failed'}), 500


@app.route('/api/transform/drive', methods=['POST'])
@require_auth
def transform_drive_endpoint():
    """Transform input data to drive format"""
    try:
        input_data = request.get_json()
        
        if not input_data:
            return jsonify({'error': 'No data provided'}), 400
        
        transformed_data = transform_drive_data(input_data)
        return jsonify({
            'success': True,
            'transformed_data': transformed_data
        })
        
    except Exception as e:
        app.logger.error(f"Error transforming drive data: {e}")
        return jsonify({'error': 'Transformation failed'}), 500


@app.route('/api/transform/gmail', methods=['POST'])
@require_auth
def transform_gmail_endpoint():
    """Transform input data to gmail format"""
    try:
        input_data = request.get_json()
        
        if not input_data:
            return jsonify({'error': 'No data provided'}), 400
        
        transformed_data = transform_gmail_data(input_data)
        return jsonify({
            'success': True,
            'transformed_data': transformed_data
        })
        
    except Exception as e:
        app.logger.error(f"Error transforming gmail data: {e}")
        return jsonify({'error': 'Transformation failed'}), 500


@app.route('/api/health')
def health_check():
    """Health check endpoint"""
    try:
        # Test Redis connection
        redis_client.ping()
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.utcnow().isoformat(),
            'services': {
                'redis': 'connected',
                'google_oauth': 'configured'
            }
        })
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'error': str(e)
        }), 500


@app.route('/api/user/info')
@require_auth
def user_info():
    """Get current user information"""
    try:
        credentials = RedisManager.get_user_credentials(request.user_id)
        if not credentials:
            return jsonify({'error': 'User credentials not found'}), 401
        
        service = build('oauth2', 'v2', credentials=credentials)
        user_info = service.userinfo().get().execute()
        
        return jsonify({
            'user_id': request.user_id,
            'email': user_info.get('email'),
            'name': user_info.get('name'),
            'picture': user_info.get('picture')
        })
        
    except Exception as e:
        app.logger.error(f"Error getting user info: {e}")
        return jsonify({'error': 'Failed to get user info'}), 500


@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404


@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500


if __name__ == '__main__':
    # Development server
    app.run(debug=False, host='0.0.0.0', port=5000)

# For production, use gunicorn:
# gunicorn -w 4 -b 0.0.0.0:5000 app:app