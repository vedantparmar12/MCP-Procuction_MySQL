import httpx
from typing import Optional, Dict, Any
from urllib.parse import urlencode
import structlog
from ..config import settings
from ..models import UserProps

logger = structlog.get_logger()

# GitHub OAuth endpoints
GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_API_URL = "https://api.github.com/user"


class GitHubOAuth:
    """Handle GitHub OAuth authentication flow"""
    
    def __init__(self):
        self.client_id = settings.github_client_id
        self.client_secret = settings.github_client_secret
        self.http_client = httpx.AsyncClient()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.http_client.aclose()
    
    def get_authorization_url(self, redirect_uri: str, state: str) -> str:
        """
        Generate GitHub OAuth authorization URL
        
        Args:
            redirect_uri: URL to redirect after authorization
            state: Random state string for CSRF protection
            
        Returns:
            Authorization URL
        """
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "scope": "user:email",
            "state": state
        }
        
        return f"{GITHUB_AUTHORIZE_URL}?{urlencode(params)}"
    
    async def exchange_code_for_token(self, code: str, redirect_uri: str) -> str:
        """
        Exchange authorization code for access token
        
        Args:
            code: Authorization code from GitHub
            redirect_uri: Same redirect URI used in authorization
            
        Returns:
            Access token
            
        Raises:
            Exception: If token exchange fails
        """
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": redirect_uri
        }
        
        headers = {
            "Accept": "application/json"
        }
        
        try:
            response = await self.http_client.post(
                GITHUB_TOKEN_URL,
                data=data,
                headers=headers
            )
            
            response.raise_for_status()
            token_data = response.json()
            
            if "error" in token_data:
                raise Exception(f"GitHub OAuth error: {token_data.get('error_description', token_data['error'])}")
            
            access_token = token_data.get("access_token")
            if not access_token:
                raise Exception("No access token received from GitHub")
            
            logger.info("Successfully exchanged code for token")
            return access_token
            
        except httpx.RequestError as e:
            logger.error("Failed to exchange code for token", error=str(e))
            raise Exception(f"Failed to connect to GitHub: {str(e)}")
        except Exception as e:
            logger.error("Token exchange failed", error=str(e))
            raise
    
    async def get_user_info(self, access_token: str) -> UserProps:
        """
        Get user information from GitHub
        
        Args:
            access_token: GitHub access token
            
        Returns:
            UserProps with user information
            
        Raises:
            Exception: If user info retrieval fails
        """
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json"
        }
        
        try:
            response = await self.http_client.get(
                GITHUB_USER_API_URL,
                headers=headers
            )
            
            response.raise_for_status()
            user_data = response.json()
            
            # Extract user information
            login = user_data.get("login")
            name = user_data.get("name") or login
            email = user_data.get("email") or f"{login}@users.noreply.github.com"
            
            if not login:
                raise Exception("Failed to get GitHub username")
            
            logger.info("Successfully retrieved user info", user=login)
            
            return UserProps(
                login=login,
                name=name,
                email=email,
                access_token=access_token
            )
            
        except httpx.RequestError as e:
            logger.error("Failed to get user info", error=str(e))
            raise Exception(f"Failed to connect to GitHub API: {str(e)}")
        except Exception as e:
            logger.error("User info retrieval failed", error=str(e))
            raise


async def verify_github_token(access_token: str) -> Optional[UserProps]:
    """
    Verify a GitHub access token and get user info
    
    Args:
        access_token: GitHub access token to verify
        
    Returns:
        UserProps if token is valid, None otherwise
    """
    async with GitHubOAuth() as oauth:
        try:
            return await oauth.get_user_info(access_token)
        except Exception as e:
            logger.warning("Token verification failed", error=str(e))
            return None