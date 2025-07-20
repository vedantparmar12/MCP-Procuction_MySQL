from fastmcp import FastMCP
from ..models import (
    ManageTransactionRequest,
    create_success_response,
    create_error_response
)
from ..database import (
    get_connection,
    TransactionManager
)
import structlog
from typing import Dict, Optional

logger = structlog.get_logger()

# Store active transactions per session/user
# In production, this should be stored in a proper session manager
_active_transactions: Dict[str, TransactionManager] = {}


def register_transaction_tools(mcp: FastMCP) -> None:
    """Register transaction management tools"""
    
    @mcp.tool(
        name="manage_transaction",
        description="Manage database transactions. Actions: begin (start transaction), commit, rollback, savepoint (create savepoint), release_savepoint."
    )
    async def manage_transaction(request: ManageTransactionRequest):
        """Manage database transactions"""
        try:
            # For now, use a simple session ID (in production, use proper session management)
            session_id = "default"  # This should be derived from user context
            
            if request.action == "begin":
                # Check if transaction already exists
                if session_id in _active_transactions:
                    return create_error_response(
                        "A transaction is already active. Please commit or rollback before starting a new one."
                    )
                
                # Start new transaction
                transaction = TransactionManager()
                await transaction.__aenter__()
                _active_transactions[session_id] = transaction
                
                logger.info("Transaction started", session_id=session_id)
                
                return create_success_response(
                    "Transaction started successfully",
                    {
                        "session_id": session_id,
                        "status": "active",
                        "isolation_level": "REPEATABLE READ"  # MySQL default
                    }
                )
            
            # For other actions, we need an active transaction
            if session_id not in _active_transactions:
                return create_error_response(
                    "No active transaction found. Use 'begin' to start a transaction."
                )
            
            transaction = _active_transactions[session_id]
            
            if request.action == "commit":
                try:
                    # Manually commit and cleanup
                    if transaction.conn and not transaction.conn.closed:
                        await transaction.conn.commit()
                    
                    # Clean up
                    await transaction.__aexit__(None, None, None)
                    del _active_transactions[session_id]
                    
                    logger.info("Transaction committed", session_id=session_id)
                    
                    return create_success_response(
                        "Transaction committed successfully",
                        {"session_id": session_id, "status": "committed"}
                    )
                except Exception as e:
                    # Try to clean up even on error
                    try:
                        await transaction.__aexit__(type(e), e, None)
                        del _active_transactions[session_id]
                    except:
                        pass
                    raise
            
            elif request.action == "rollback":
                try:
                    # Manually rollback and cleanup
                    if transaction.conn and not transaction.conn.closed:
                        await transaction.conn.rollback()
                    
                    # Clean up
                    await transaction.__aexit__(Exception("Rollback"), None, None)
                    del _active_transactions[session_id]
                    
                    logger.info("Transaction rolled back", session_id=session_id)
                    
                    return create_success_response(
                        "Transaction rolled back successfully",
                        {"session_id": session_id, "status": "rolled_back"}
                    )
                except Exception as e:
                    # Try to clean up even on error
                    try:
                        del _active_transactions[session_id]
                    except:
                        pass
                    raise
            
            elif request.action == "savepoint":
                if not request.savepoint_name:
                    return create_error_response("Savepoint name is required")
                
                await transaction.create_savepoint(request.savepoint_name)
                
                logger.info(
                    "Savepoint created",
                    session_id=session_id,
                    savepoint=request.savepoint_name
                )
                
                return create_success_response(
                    f"Savepoint '{request.savepoint_name}' created successfully",
                    {
                        "session_id": session_id,
                        "savepoint": request.savepoint_name,
                        "active_savepoints": transaction.savepoints
                    }
                )
            
            elif request.action == "release_savepoint":
                if not request.savepoint_name:
                    return create_error_response("Savepoint name is required")
                
                if request.savepoint_name not in transaction.savepoints:
                    return create_error_response(
                        f"Savepoint '{request.savepoint_name}' not found. "
                        f"Active savepoints: {transaction.savepoints}"
                    )
                
                await transaction.release_savepoint(request.savepoint_name)
                
                logger.info(
                    "Savepoint released",
                    session_id=session_id,
                    savepoint=request.savepoint_name
                )
                
                return create_success_response(
                    f"Savepoint '{request.savepoint_name}' released successfully",
                    {
                        "session_id": session_id,
                        "released_savepoint": request.savepoint_name,
                        "remaining_savepoints": transaction.savepoints
                    }
                )
            
            else:
                return create_error_response(f"Unknown transaction action: {request.action}")
                
        except Exception as e:
            logger.error(f"Transaction {request.action} failed", error=str(e))
            
            # Clean up on error
            if request.action == "begin" and session_id in _active_transactions:
                try:
                    transaction = _active_transactions[session_id]
                    await transaction.__aexit__(type(e), e, None)
                    del _active_transactions[session_id]
                except:
                    pass
            
            return create_error_response(f"Transaction {request.action} failed: {str(e)}")
    
    
    @mcp.tool(
        name="get_transaction_status",
        description="Get the status of the current transaction, including active savepoints."
    )
    async def get_transaction_status():
        """Get current transaction status"""
        try:
            session_id = "default"
            
            if session_id not in _active_transactions:
                return create_success_response(
                    "No active transaction",
                    {"status": "none", "session_id": session_id}
                )
            
            transaction = _active_transactions[session_id]
            
            # Check if connection is still valid
            if not transaction.conn or transaction.conn.closed:
                # Clean up invalid transaction
                del _active_transactions[session_id]
                return create_success_response(
                    "No active transaction",
                    {"status": "none", "session_id": session_id}
                )
            
            return create_success_response(
                "Transaction is active",
                {
                    "status": "active",
                    "session_id": session_id,
                    "savepoints": transaction.savepoints,
                    "connection_id": id(transaction.conn)
                }
            )
            
        except Exception as e:
            logger.error("Failed to get transaction status", error=str(e))
            return create_error_response(f"Failed to get transaction status: {str(e)}")


# Cleanup function for application shutdown
async def cleanup_transactions():
    """Clean up all active transactions on shutdown"""
    for session_id, transaction in list(_active_transactions.items()):
        try:
            logger.warning(
                "Cleaning up abandoned transaction",
                session_id=session_id
            )
            await transaction.__aexit__(Exception("Cleanup"), None, None)
        except Exception as e:
            logger.error(
                "Failed to cleanup transaction",
                session_id=session_id,
                error=str(e)
            )
    _active_transactions.clear()