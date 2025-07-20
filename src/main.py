import asyncio
import os
os.environ['FASTMCP_DISABLE_BANNER'] = '1'
import sys

# CRITICAL: Windows event loop policy MUST be set before any imports that use asyncio
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager

from fastmcp import FastMCP
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
import uvicorn

from .config import settings
from .models import UserProps
from .auth import GitHubOAuth, session_manager, create_approval_cookie
from .database import close_pool, test_connection
from .tools import register_all_tools, cleanup_transactions
from .monitoring import set_user_context, sentry_initialized

import structlog

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer() if settings.log_format == "json" else structlog.dev.ConsoleRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting MySQL MCP Server")
    logger.info(f"Configuration - Host: {settings.mysql_host}, Port: {settings.mysql_port}, Database: {settings.mysql_database}")
    logger.info(f"Event loop policy: {asyncio.get_event_loop_policy()}")
    
    # Test database connection
    try:
        if await test_connection():
            logger.info("Database connection successful")
        else:
            logger.error("Database connection test returned False")
            # Don't exit immediately - let's see the actual error
    except Exception as e:
        logger.error(f"Database connection failed with exception: {e}")
        import traceback
        traceback.print_exc()
        # Still don't exit - let the app start but log the error
    
    if sentry_initialized:
        logger.info("Sentry monitoring enabled")
    else:
        logger.info("Sentry monitoring disabled")
    
    yield
    
    logger.info("Shutting down MySQL MCP Server")
    try:
        await cleanup_transactions()
        await close_pool()
        session_manager.cleanup_expired_sessions()
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")

app = FastAPI(title="MySQL MCP Server OAuth", lifespan=lifespan)

# Add SessionMiddleware BEFORE CORSMiddleware
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.cookie_secret_key,
    same_site="lax",
    https_only=False  # Set to False for local development
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

mcp = FastMCP(
    name=settings.mcp_server_name,
    version=settings.mcp_server_version
)

_mcp_sessions = {}


@app.get("/")
async def root():
    return {
        "name": settings.mcp_server_name,
        "version": settings.mcp_server_version,
        "status": "running",
        "endpoints": {
            "mcp": "/mcp",
            "oauth": "/authorize",
            "health": "/health"
        }
    }


@app.get("/health")
async def health_check():
    try:
        db_healthy = await test_connection()
    except Exception as e:
        logger.error(f"Health check database test failed: {e}")
        db_healthy = False
    
    return {
        "status": "healthy" if db_healthy else "unhealthy",
        "database": "connected" if db_healthy else "disconnected",
        "monitoring": "enabled" if sentry_initialized else "disabled",
        "mysql_host": settings.mysql_host,
        "mysql_database": settings.mysql_database
    }


@app.get("/authorize")
async def authorize(request: Request, redirect_uri: Optional[str] = None):
    import secrets
    state = secrets.token_urlsafe(32)
    
    request.session["oauth_state"] = state
    
    if not redirect_uri:
        redirect_uri = str(request.url_for("callback"))
    
    async with GitHubOAuth() as oauth:
        auth_url = oauth.get_authorization_url(redirect_uri, state)
    
    logger.info("Starting OAuth flow", redirect_uri=redirect_uri)
    
    html = f"""
    <html>
    <head>
        <title>MySQL MCP Server - Authorization</title>
        <style>
            body {{ font-family: Arial, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; }}
            .container {{ border: 1px solid #ddd; border-radius: 8px; padding: 30px; }}
            h1 {{ color: #333; }}
            .info {{ background: #f0f0f0; padding: 15px; border-radius: 4px; margin: 20px 0; }}
            .button {{ background: #0366d6; color: white; padding: 10px 20px; text-decoration: none; 
                      border-radius: 4px; display: inline-block; margin-top: 20px; }}
            .button:hover {{ background: #0256c7; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Authorize MySQL MCP Server</h1>
            <p>This application requests access to your MySQL database through MCP (Model Context Protocol).</p>
            
            <div class="info">
                <strong>This application will be able to:</strong>
                <ul>
                    <li>Read your GitHub profile information</li>
                    <li>Execute database queries based on your permissions</li>
                    <li>Manage database objects if you have write access</li>
                </ul>
            </div>
            
            <p>You will be redirected to GitHub to authenticate.</p>
            
            <a href="{auth_url}" class="button">Continue to GitHub</a>
        </div>
    </body>
    </html>
    """
    
    return HTMLResponse(content=html)


@app.get("/callback")
async def callback(request: Request, code: Optional[str] = None, state: Optional[str] = None):
    if not code:
        raise HTTPException(status_code=400, detail="Authorization code missing")
    
    session_state = request.session.get("oauth_state")
    if not state or state != session_state:
        raise HTTPException(status_code=400, detail="Invalid state parameter")
    
    try:
        redirect_uri = str(request.url_for("callback"))
        
        async with GitHubOAuth() as oauth:
            access_token = await oauth.exchange_code_for_token(code, redirect_uri)
            user_props = await oauth.get_user_info(access_token)
        
        session_id = session_manager.create_session(user_props)
        set_user_context(user_props)
        
        logger.info(
            "User authenticated successfully",
            user=user_props.login,
            has_write_access=user_props.has_write_access
        )
        
        response = HTMLResponse(content=f"""
        <html>
        <head>
            <title>Authorization Successful</title>
            <style>
                body {{ font-family: Arial, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; }}
                .success {{ color: #28a745; }}
                .info {{ background: #d4edda; padding: 15px; border-radius: 4px; margin: 20px 0; }}
                code {{ background: #f0f0f0; padding: 2px 4px; border-radius: 2px; }}
            </style>
        </head>
        <body>
            <h1 class="success">Authorization Successful!</h1>
            <div class="info">
                <p>Welcome, <strong>{user_props.name}</strong> (@{user_props.login})</p>
                <p>Access Level: <strong>{'Write Access' if user_props.has_write_access else 'Read Only'}</strong></p>
            </div>
            
            <p>You can now use the MCP server. Your session ID is:</p>
            <p><code>{session_id}</code></p>
            
            <p>Configure your MCP client to connect to:</p>
            <p><code>{request.url.scheme}://{request.url.netloc}/mcp</code></p>
        </body>
        </html>
        """)
        
        cookie = session_manager.create_session_cookie(session_id)
        response.set_cookie(
            key="mcp_session",
            value=cookie,
            max_age=settings.session_lifetime_minutes * 60,
            secure=False,  # Set to False for local development
            httponly=True,
            samesite="lax"
        )
        
        approval = create_approval_cookie("mcp_client", True)
        response.set_cookie(
            key=approval["name"],
            value=approval["value"],
            max_age=30 * 24 * 60 * 60,
            secure=False,  # Set to False for local development
            httponly=True
        )
        
        return response
        
    except Exception as e:
        logger.error("OAuth callback failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Authentication failed: {str(e)}")


@app.post("/mcp")
async def mcp_endpoint(request: Request):
    # Check for session cookie first
    session_cookie = request.cookies.get("mcp_session")
    
    # Also check for Authorization header
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        session_cookie = auth_header.replace("Bearer ", "")
    
    if not session_cookie:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    user_props = session_manager.get_user_from_cookie(session_cookie)
    if not user_props:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    
    set_user_context(user_props)
    
    user_key = user_props.login
    if user_key not in _mcp_sessions:
        user_mcp = FastMCP(
            name=settings.mcp_server_name,
            version=settings.mcp_server_version
        )
        
        register_all_tools(user_mcp, user_props)
        _mcp_sessions[user_key] = user_mcp
        
        logger.info(
            "Created MCP session for user",
            user=user_props.login
        )
    
    user_mcp = _mcp_sessions[user_key]
    body = await request.body()
    
    try:
        return {"status": "ok", "message": "MCP endpoint active"}
    except Exception as e:
        logger.error("MCP request failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


def run_server():
    logger.info(
        "Starting MySQL MCP Server",
        host="127.0.0.1",
        port=settings.mcp_server_port
    )
    
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=settings.mcp_server_port,
        log_config={
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                },
            },
            "handlers": {
                "default": {
                    "formatter": "default",
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                },
            },
            "root": {
                "level": settings.log_level,
                "handlers": ["default"],
            },
        }
    )


if __name__ == "__main__":
    # Check if running in MCP mode (stdio)
    if os.environ.get('MCP_MODE') or not sys.stdout.isatty():
        # For MCP/Claude Desktop - use stdio transport
        dev_user = UserProps(
            login="dev_user",
            name="Development User", 
            email="dev@localhost",
            access_token="dev_token"
        )
        
        register_all_tools(mcp, dev_user)
        mcp.run()
    else:
        # For web server mode - start FastAPI
        run_server()