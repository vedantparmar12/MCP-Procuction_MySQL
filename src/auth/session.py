import secrets
import time
import hmac
import hashlib
import json
from typing import Optional, Dict, Any
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
import structlog
from ..config import settings
from ..models import UserProps

logger = structlog.get_logger()

# Session store (in production, use Redis or similar)
_sessions: Dict[str, Dict[str, Any]] = {}


class SessionManager:
    """Manage user sessions with secure cookies"""
    
    def __init__(self):
        self.serializer = URLSafeTimedSerializer(settings.cookie_secret_key)
        self.session_lifetime = settings.session_lifetime_minutes * 60  # Convert to seconds
    
    def create_session(self, user_props: UserProps) -> str:
        """
        Create a new session for the user
        
        Args:
            user_props: User properties from GitHub OAuth
            
        Returns:
            Session ID
        """
        session_id = secrets.token_urlsafe(32)
        
        session_data = {
            "user": {
                "login": user_props.login,
                "name": user_props.name,
                "email": user_props.email,
                "has_write_access": user_props.has_write_access
            },
            "created_at": time.time(),
            "last_accessed": time.time(),
            "access_token": user_props.access_token
        }
        
        _sessions[session_id] = session_data
        
        logger.info(
            "Session created",
            session_id=session_id,
            user=user_props.login
        )
        
        return session_id
    
    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Get session data by ID
        
        Args:
            session_id: Session ID
            
        Returns:
            Session data if valid, None otherwise
        """
        session = _sessions.get(session_id)
        
        if not session:
            return None
        
        # Check if session has expired
        if time.time() - session["created_at"] > self.session_lifetime:
            logger.info("Session expired", session_id=session_id)
            self.destroy_session(session_id)
            return None
        
        # Update last accessed time
        session["last_accessed"] = time.time()
        
        return session
    
    def destroy_session(self, session_id: str) -> None:
        """Destroy a session"""
        if session_id in _sessions:
            logger.info(
                "Session destroyed",
                session_id=session_id,
                user=_sessions[session_id]["user"]["login"]
            )
            del _sessions[session_id]
    
    def create_session_cookie(self, session_id: str) -> str:
        """
        Create a signed session cookie
        
        Args:
            session_id: Session ID
            
        Returns:
            Signed cookie value
        """
        return self.serializer.dumps(session_id)
    
    def parse_session_cookie(self, cookie_value: str) -> Optional[str]:
        """
        Parse and verify a session cookie
        
        Args:
            cookie_value: Signed cookie value
            
        Returns:
            Session ID if valid, None otherwise
        """
        try:
            session_id = self.serializer.loads(
                cookie_value,
                max_age=self.session_lifetime
            )
            return session_id
        except SignatureExpired:
            logger.warning("Session cookie expired")
            return None
        except BadSignature:
            logger.warning("Invalid session cookie signature")
            return None
    
    def get_user_from_cookie(self, cookie_value: str) -> Optional[UserProps]:
        """
        Get user properties from session cookie
        
        Args:
            cookie_value: Signed cookie value
            
        Returns:
            UserProps if valid session, None otherwise
        """
        session_id = self.parse_session_cookie(cookie_value)
        if not session_id:
            return None
        
        session = self.get_session(session_id)
        if not session:
            return None
        
        user_data = session["user"]
        return UserProps(
            login=user_data["login"],
            name=user_data["name"],
            email=user_data["email"],
            access_token=session["access_token"]
        )
    
    def cleanup_expired_sessions(self) -> int:
        """
        Clean up expired sessions
        
        Returns:
            Number of sessions cleaned up
        """
        current_time = time.time()
        expired_sessions = []
        
        for session_id, session in _sessions.items():
            if current_time - session["created_at"] > self.session_lifetime:
                expired_sessions.append(session_id)
        
        for session_id in expired_sessions:
            self.destroy_session(session_id)
        
        if expired_sessions:
            logger.info(
                "Cleaned up expired sessions",
                count=len(expired_sessions)
            )
        
        return len(expired_sessions)


# Global session manager instance
session_manager = SessionManager()


def sign_data(data: str, key: str) -> str:
    """
    Sign data with HMAC for client approval cookies
    Matches the TypeScript implementation
    
    Args:
        data: Data to sign
        key: Secret key
        
    Returns:
        Hex-encoded signature
    """
    signature = hmac.new(
        key.encode(),
        data.encode(),
        hashlib.sha256
    ).digest()
    
    return signature.hex()


def verify_signature(signature_hex: str, data: str, key: str) -> bool:
    """
    Verify HMAC signature
    
    Args:
        signature_hex: Hex-encoded signature
        data: Original data
        key: Secret key
        
    Returns:
        True if signature is valid
    """
    expected_signature = sign_data(data, key)
    return hmac.compare_digest(signature_hex, expected_signature)


def create_approval_cookie(client_id: str, approved: bool = True) -> Dict[str, str]:
    """
    Create a signed cookie for client approval
    Matches the TypeScript implementation
    
    Args:
        client_id: OAuth client ID
        approved: Whether the client is approved
        
    Returns:
        Cookie name and value
    """
    cookie_name = f"mcp_approved_{client_id}"
    
    # Create cookie data
    data = json.dumps({
        "client_id": client_id,
        "approved": approved,
        "timestamp": int(time.time())
    })
    
    # Sign the data
    signature = sign_data(data, settings.cookie_secret_key)
    
    # Combine data and signature
    cookie_value = f"{data}|{signature}"
    
    return {
        "name": cookie_name,
        "value": cookie_value
    }


def verify_approval_cookie(cookie_value: str, client_id: str) -> bool:
    """
    Verify a client approval cookie
    
    Args:
        cookie_value: Cookie value with signature
        client_id: Expected client ID
        
    Returns:
        True if cookie is valid and client is approved
    """
    try:
        # Split data and signature
        parts = cookie_value.split("|")
        if len(parts) != 2:
            return False
        
        data_str, signature = parts
        
        # Verify signature
        if not verify_signature(signature, data_str, settings.cookie_secret_key):
            logger.warning("Invalid approval cookie signature")
            return False
        
        # Parse data
        data = json.loads(data_str)
        
        # Check client ID matches
        if data.get("client_id") != client_id:
            return False
        
        # Check if approved
        return data.get("approved", False)
        
    except Exception as e:
        logger.warning("Failed to verify approval cookie", error=str(e))
        return False