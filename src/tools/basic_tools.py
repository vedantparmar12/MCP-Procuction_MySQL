from fastmcp import FastMCP
from ..models import (
    ListTablesRequest,
    QueryDatabaseRequest,
    DescribeTableRequest,
    create_success_response,
    create_error_response
)
from ..database import (
    validate_sql_query,
    is_write_operation,
    with_database,
    execute_query,
    get_table_list,
    get_table_columns,
    get_table_indexes,
    get_table_foreign_keys,
    sanitize_identifier
)
import structlog
import json

logger = structlog.get_logger()


def register_basic_tools(mcp: FastMCP) -> None:
    """Register basic read-only tools available to all users"""
    
    @mcp.tool(
        name="list_tables",
        description="Get a list of all tables in the database along with their basic information. Use this first to understand the database structure."
    )
    async def list_tables(request: ListTablesRequest):
        """List all tables with their metadata"""
        try:
            logger.info("Listing tables", schema=request.schema)
            
            async def operation():
                # Get table list
                tables = await get_table_list(request.schema)
                
                # Group tables by type
                user_tables = []
                system_tables = []
                views = []
                
                for table in tables:
                    table_info = {
                        "name": table["table_name"],
                        "type": table["table_type"],
                        "engine": table.get("engine"),
                        "rows": table.get("table_rows"),
                        "data_size": table.get("data_length"),
                        "index_size": table.get("index_length"),
                        "created": str(table.get("create_time")) if table.get("create_time") else None,
                        "updated": str(table.get("update_time")) if table.get("update_time") else None
                    }
                    
                    if table["table_type"] == "VIEW":
                        views.append(table_info)
                    elif table["table_schema"] in ["mysql", "information_schema", "performance_schema", "sys"]:
                        system_tables.append(table_info)
                    else:
                        user_tables.append(table_info)
                
                return {
                    "user_tables": user_tables,
                    "views": views,
                    "system_tables": system_tables,
                    "total_count": len(tables)
                }
            
            result = await with_database(operation)
            
            # Format response
            response_text = "**Database Tables and Schema**\n\n"
            
            if result["user_tables"]:
                response_text += f"**User Tables ({len(result['user_tables'])}):**\n```json\n"
                response_text += json.dumps(result["user_tables"], indent=2)
                response_text += "\n```\n\n"
            
            if result["views"]:
                response_text += f"**Views ({len(result['views'])}):**\n```json\n"
                response_text += json.dumps(result["views"], indent=2)
                response_text += "\n```\n\n"
            
            response_text += f"**Total tables found:** {result['total_count']}\n\n"
            response_text += "**Note:** Use `query_database` to run SELECT queries, or `describe_table` to see detailed table structure."
            
            return create_success_response(response_text)
            
        except Exception as e:
            logger.error("Failed to list tables", error=str(e))
            return create_error_response(f"Failed to retrieve database tables: {str(e)}")
    
    
    @mcp.tool(
        name="query_database",
        description="Execute a read-only SQL query (SELECT statements only). Use this to retrieve data from the database."
    )
    async def query_database(request: QueryDatabaseRequest):
        """Execute read-only SQL queries"""
        try:
            # Validate SQL
            validation = validate_sql_query(request.sql)
            if not validation.is_valid:
                return create_error_response(f"Invalid SQL query: {validation.error}")
            
            # Check if it's a write operation
            if is_write_operation(request.sql):
                return create_error_response(
                    "Write operations are not allowed with this tool. "
                    "Use the `execute_database` tool if you have write permissions."
                )
            
            logger.info("Executing query", sql_preview=request.sql[:100])
            
            async def operation():
                result = await execute_query(request.sql)
                
                if not result.success:
                    raise Exception(result.error)
                
                # Apply limit if specified
                data = result.data
                if request.limit and isinstance(data, list):
                    data = data[:request.limit]
                
                return {
                    "rows": data,
                    "row_count": len(data) if isinstance(data, list) else 0,
                    "duration_ms": result.duration_ms
                }
            
            result = await with_database(operation)
            
            # Format response
            response_text = f"**Query Results**\n\n"
            response_text += f"Rows returned: {result['row_count']}\n"
            response_text += f"Execution time: {result['duration_ms']:.2f}ms\n\n"
            response_text += "**Data:**\n```json\n"
            response_text += json.dumps(result["rows"], indent=2, default=str)
            response_text += "\n```"
            
            return create_success_response(response_text)
            
        except Exception as e:
            logger.error("Query execution failed", error=str(e))
            return create_error_response(f"Query execution failed: {str(e)}")
    
    
    @mcp.tool(
        name="describe_table",
        description="Get detailed structure information about a specific table including columns, indexes, and foreign keys."
    )
    async def describe_table(request: DescribeTableRequest):
        """Get detailed table structure"""
        try:
            # Sanitize table name
            table_name = sanitize_identifier(request.table)
            logger.info("Describing table", table=table_name)
            
            async def operation():
                # Get all table information
                columns = await get_table_columns(table_name)
                indexes = await get_table_indexes(table_name) if request.include_indexes else []
                foreign_keys = await get_table_foreign_keys(table_name) if request.include_foreign_keys else []
                
                # Format column information
                formatted_columns = []
                for col in columns:
                    formatted_columns.append({
                        "name": col["column_name"],
                        "type": col["column_type"],
                        "nullable": col["is_nullable"] == "YES",
                        "default": col["column_default"],
                        "key": col["column_key"],  # PRI, UNI, MUL
                        "extra": col["extra"],  # auto_increment, etc.
                        "comment": col.get("column_comment")
                    })
                
                # Format index information
                formatted_indexes = {}
                for idx in indexes:
                    idx_name = idx["index_name"]
                    if idx_name not in formatted_indexes:
                        formatted_indexes[idx_name] = {
                            "name": idx_name,
                            "unique": not idx["non_unique"],
                            "type": idx["index_type"],
                            "columns": []
                        }
                    formatted_indexes[idx_name]["columns"].append({
                        "column": idx["column_name"],
                        "sequence": idx["seq_in_index"],
                        "collation": idx["collation"]
                    })
                
                # Format foreign key information
                formatted_fks = {}
                for fk in foreign_keys:
                    fk_name = fk["constraint_name"]
                    if fk_name not in formatted_fks:
                        formatted_fks[fk_name] = {
                            "name": fk_name,
                            "columns": [],
                            "referenced_table": fk["referenced_table_name"],
                            "referenced_columns": []
                        }
                    formatted_fks[fk_name]["columns"].append(fk["column_name"])
                    formatted_fks[fk_name]["referenced_columns"].append(fk["referenced_column_name"])
                
                return {
                    "table_name": table_name,
                    "columns": formatted_columns,
                    "indexes": list(formatted_indexes.values()),
                    "foreign_keys": list(formatted_fks.values())
                }
            
            result = await with_database(operation)
            
            # Format response
            response_text = f"**Table Structure: `{result['table_name']}`**\n\n"
            
            response_text += "**Columns:**\n```json\n"
            response_text += json.dumps(result["columns"], indent=2)
            response_text += "\n```\n\n"
            
            if result["indexes"]:
                response_text += "**Indexes:**\n```json\n"
                response_text += json.dumps(result["indexes"], indent=2)
                response_text += "\n```\n\n"
            
            if result["foreign_keys"]:
                response_text += "**Foreign Keys:**\n```json\n"
                response_text += json.dumps(result["foreign_keys"], indent=2)
                response_text += "\n```\n"
            
            return create_success_response(response_text)
            
        except Exception as e:
            logger.error("Failed to describe table", error=str(e))
            return create_error_response(f"Failed to describe table: {str(e)}")