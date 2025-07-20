from fastmcp import FastMCP
from ..models import UserProps
from .basic_tools import register_basic_tools
from .write_tools import register_write_tools  
from .advanced_tools import register_advanced_tools
from .transaction_tools import register_transaction_tools
import structlog

logger = structlog.get_logger()


def register_all_tools(mcp: FastMCP, user_props: UserProps) -> None:
    logger.info(
        "Registering tools for user",
        user=user_props.login,
        has_write_access=user_props.has_write_access
    )
    
    register_basic_tools(mcp)
    logger.info("Basic tools registered")
    
    if user_props.has_write_access:
        register_write_tools(mcp)
        logger.info("Write tools registered")
        
        register_advanced_tools(mcp)
        logger.info("Advanced tools registered")
        
        register_transaction_tools(mcp)
        logger.info("Transaction tools registered")
    else:
        logger.info(
            "User does not have write access, skipping privileged tools",
            user=user_props.login
        )
    
    logger.info("Tool registration complete")