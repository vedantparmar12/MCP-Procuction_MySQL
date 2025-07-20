from fastmcp import FastMCP
from ..models import (
    ExecuteDatabaseRequest,
    create_success_response,
    create_error_response
)
from ..database import (
    validate_sql_query,
    is_write_operation,
    with_database,
    execute_query,
    validate_params,
    extract_table_names
)
import structlog
import json

logger = structlog.get_logger()


def register_write_tools(mcp: FastMCP) -> None:
    """Register write operation tools for privileged users"""
    
    @mcp.tool(
        name="execute_database",
        description="Execute write operations (INSERT, UPDATE, DELETE) or DDL statements (CREATE, ALTER, DROP). Requires write permissions."
    )
    async def execute_database(request: ExecuteDatabaseRequest):
        """Execute write operations on the database"""
        try:
            # Validate SQL
            validation = validate_sql_query(request.sql)
            if not validation.is_valid:
                return create_error_response(f"Invalid SQL query: {validation.error}")
            
            # Validate parameters if provided
            if request.params:
                params_valid, params_error = validate_params(request.params)
                if not params_valid:
                    return create_error_response(f"Invalid parameters: {params_error}")
            
            # Log the operation
            tables = extract_table_names(request.sql)
            logger.info(
                "Executing write operation",
                operation_type=validation.operation_type,
                tables=tables,
                has_params=bool(request.params)
            )
            
            async def operation():
                # Execute the query
                result = await execute_query(
                    request.sql,
                    params=request.params,
                    fetch_all=False,
                    return_cursor=True
                )
                
                if not result.success:
                    raise Exception(result.error)
                
                return {
                    "rows_affected": result.rows_affected,
                    "last_insert_id": result.data.get("lastrowid") if result.data else None,
                    "duration_ms": result.duration_ms
                }
            
            result = await with_database(operation)
            
            # Format response based on operation type
            operation_type = validation.operation_type or "unknown"
            
            response_text = f"**Operation Completed Successfully**\n\n"
            response_text += f"Operation Type: {operation_type.upper()}\n"
            
            if tables:
                response_text += f"Tables Affected: {', '.join(tables)}\n"
            
            response_text += f"Rows Affected: {result['rows_affected']}\n"
            
            if result['last_insert_id'] is not None and operation_type == "write":
                response_text += f"Last Insert ID: {result['last_insert_id']}\n"
            
            response_text += f"Execution Time: {result['duration_ms']:.2f}ms\n"
            
            # Add helpful notes based on operation
            if operation_type == "ddl":
                response_text += "\n**Note:** DDL operations are auto-committed and cannot be rolled back."
            elif operation_type == "write":
                response_text += "\n**Note:** Use `manage_transaction` to control transaction boundaries for multiple operations."
            
            return create_success_response(response_text)
            
        except Exception as e:
            logger.error("Write operation failed", error=str(e))
            return create_error_response(f"Write operation failed: {str(e)}")