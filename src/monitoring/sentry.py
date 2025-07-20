import functools
from typing import Optional, Dict, Any, Callable
import structlog
from ..config import settings

logger = structlog.get_logger()

# Sentry SDK is optional
try:
    import sentry_sdk
    from sentry_sdk.integrations.asyncio import AsyncioIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration
    SENTRY_AVAILABLE = True
except ImportError:
    SENTRY_AVAILABLE = False
    logger.warning("Sentry SDK not installed. Monitoring features disabled.")


def init_sentry() -> bool:
    """
    Initialize Sentry if DSN is configured
    
    Returns:
        True if Sentry was initialized, False otherwise
    """
    if not SENTRY_AVAILABLE:
        return False
    
    if not settings.sentry_dsn:
        logger.info("Sentry DSN not configured, skipping initialization")
        return False
    
    try:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.environment,
            traces_sample_rate=1.0,  # 100% sampling to match TypeScript
            integrations=[
                AsyncioIntegration(),
                LoggingIntegration(
                    level=None,  # Capture all levels
                    event_level=None  # Don't capture logs as events
                )
            ],
            before_send=before_send_filter,
            attach_stacktrace=True,
            send_default_pii=False  # Don't send PII by default
        )
        
        logger.info(
            "Sentry initialized successfully",
            environment=settings.environment
        )
        return True
        
    except Exception as e:
        logger.error("Failed to initialize Sentry", error=str(e))
        return False


def before_send_filter(event: Dict[str, Any], hint: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Filter sensitive data before sending to Sentry
    
    Args:
        event: Sentry event data
        hint: Additional context
        
    Returns:
        Filtered event or None to drop
    """
    # Remove sensitive data from the event
    if "request" in event:
        request = event["request"]
        
        # Remove authorization headers
        if "headers" in request:
            headers = request["headers"]
            sensitive_headers = ["authorization", "cookie", "x-api-key"]
            for header in sensitive_headers:
                if header in headers:
                    headers[header] = "[REDACTED]"
        
        # Remove sensitive query parameters
        if "query_string" in request:
            # Parse and filter query string if needed
            pass
    
    # Remove database passwords from error messages
    if "exception" in event:
        for exception in event["exception"].get("values", []):
            if "value" in exception:
                value = exception["value"]
                # Redact passwords and connection strings
                import re
                value = re.sub(r'password["\']?\s*[:=]\s*["\']?[^"\'\s]+', 'password=***', value, flags=re.IGNORECASE)
                value = re.sub(r'mysql://[^@]+@', 'mysql://***@', value)
                exception["value"] = value
    
    return event


def set_user_context(user_props) -> None:
    """
    Set user context for Sentry
    
    Args:
        user_props: UserProps object with user information
    """
    if SENTRY_AVAILABLE and sentry_sdk.Hub.current.client:
        sentry_sdk.set_user({
            "username": user_props.login,
            "email": user_props.email
        })


def capture_exception(error: Exception, **kwargs) -> Optional[str]:
    """
    Capture an exception to Sentry
    
    Args:
        error: Exception to capture
        **kwargs: Additional context
        
    Returns:
        Event ID if sent to Sentry, None otherwise
    """
    if SENTRY_AVAILABLE and sentry_sdk.Hub.current.client:
        with sentry_sdk.push_scope() as scope:
            # Add additional context
            for key, value in kwargs.items():
                scope.set_context(key, value)
            
            return sentry_sdk.capture_exception(error)
    
    return None


def trace_mcp_tool(tool_name: str):
    """
    Decorator to trace MCP tool execution with Sentry
    
    Args:
        tool_name: Name of the MCP tool
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            if SENTRY_AVAILABLE and sentry_sdk.Hub.current.client:
                # Extract parameters for tracing
                attributes = {
                    "mcp.tool.name": tool_name,
                }
                
                # Add request parameters as attributes
                if args and hasattr(args[0], "__dict__"):
                    request_data = args[0].__dict__
                    for key, value in request_data.items():
                        if not key.startswith("_") and isinstance(value, (str, int, float, bool)):
                            attributes[f"mcp.tool.param.{key}"] = value
                
                with sentry_sdk.start_transaction(
                    op="mcp.tool",
                    name=f"mcp.tool/{tool_name}",
                    custom_sampling_context=attributes
                ) as transaction:
                    transaction.set_tag("mcp.tool.name", tool_name)
                    
                    try:
                        result = await func(*args, **kwargs)
                        transaction.set_status("ok")
                        return result
                    except Exception as e:
                        transaction.set_status("internal_error")
                        raise
            else:
                # No Sentry, just execute the function
                return await func(*args, **kwargs)
        
        return wrapper
    return decorator


def handle_error(error: Exception, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Handle an error with Sentry integration
    Returns a user-friendly error response with event ID
    
    Args:
        error: The exception that occurred
        context: Additional context for the error
        
    Returns:
        Error response dict with event ID if available
    """
    # Capture to Sentry
    event_id = None
    if context:
        event_id = capture_exception(error, **context)
    else:
        event_id = capture_exception(error)
    
    # Create user-friendly error message
    error_response = {
        "error": str(error),
        "type": type(error).__name__
    }
    
    if event_id:
        error_response["event_id"] = event_id
        error_response["message"] = f"An error occurred. Event ID: {event_id}"
    
    return error_response


# Initialize Sentry on module import
sentry_initialized = init_sentry()