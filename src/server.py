#!/usr/bin/env python3
import asyncio
import argparse
import logging
from typing import Any, Dict, List
import os
import sys
from pathlib import Path

# Suppress ALL output before any imports
import warnings
warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.CRITICAL)
logging.disable(logging.CRITICAL)

# Mock structlog before it's imported anywhere
class SilentLogger:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None

sys.modules['structlog'] = type(sys)('structlog')
sys.modules['structlog'].get_logger = lambda: SilentLogger()
sys.modules['structlog'].configure = lambda **kwargs: None

# Add the parent directory to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load environment variables
from dotenv import load_dotenv
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(env_path)

# Now import with all logging disabled
from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.server.lowlevel.server import NotificationOptions
from mcp.types import TextContent, Tool, JSONRPCError, INTERNAL_ERROR

from src.models import UserProps
from src.database.connection import get_pool, close_pool, test_connection
from src.database.utils import execute_query, get_table_list, get_table_columns
from src.database.security import validate_sql_query, is_write_operation

class MySQLMCPServer:
    def __init__(self):
        self.server = Server("mysql-mcp-server")
        self.user_props = UserProps(
            login="vedantparmar12",  # Changed to give write access
            name="STDIO User",
            email="stdio@localhost",
            access_token="stdio_token"
        )
        self.setup_handlers()

    def setup_handlers(self):
        @self.server.list_tools()
        async def handle_list_tools() -> List[Tool]:
            tools = [
                Tool(
                    name="query_database",
                    description="Execute a SELECT query on the database",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "sql": {
                                "type": "string",
                                "description": "SELECT SQL query to execute"
                            }
                        },
                        "required": ["sql"]
                    }
                ),
                Tool(
                    name="list_tables",
                    description="List all tables in the database",
                    inputSchema={
                        "type": "object",
                        "properties": {}
                    }
                ),
                Tool(
                    name="describe_table",
                    description="Get information about a table",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "table": {
                                "type": "string",
                                "description": "Table name to describe"
                            }
                        },
                        "required": ["table"]
                    }
                )
            ]
            
            # Add write operations if user has access
            if self.user_props.has_write_access:
                tools.extend([
                    Tool(
                        name="execute_sql",
                        description="Execute INSERT, UPDATE, DELETE, or DDL operations",
                        inputSchema={
                            "type": "object",
                            "properties": {
                                "sql": {
                                    "type": "string",
                                    "description": "SQL command to execute"
                                }
                            },
                            "required": ["sql"]
                        }
                    ),
                    Tool(
                        name="create_table",
                        description="Create a new table in the database",
                        inputSchema={
                            "type": "object",
                            "properties": {
                                "sql": {
                                    "type": "string",
                                    "description": "CREATE TABLE SQL statement"
                                }
                            },
                            "required": ["sql"]
                        }
                    )
                ])
            
            return tools

        @self.server.call_tool()
        async def handle_call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
            try:
                if name == "query_database":
                    sql = arguments.get("sql")
                    
                    # Validate it's a read query
                    validation = validate_sql_query(sql)
                    if not validation.is_valid:
                        return [TextContent(type="text", text=f"Error: {validation.error}")]
                    
                    if is_write_operation(sql):
                        return [TextContent(type="text", text="Error: Use execute_sql for write operations")]
                    
                    result = await execute_query(sql)
                    
                    if result.success:
                        import json
                        return [TextContent(type="text", text=json.dumps(result.data, indent=2, default=str))]
                    else:
                        return [TextContent(type="text", text=f"Error: {result.error}")]
                
                elif name == "list_tables":
                    tables = await get_table_list()
                    if not tables:
                        return [TextContent(type="text", text="No tables found")]
                    
                    table_list = "Tables:\n"
                    for table in tables:
                        # Handle both uppercase and lowercase field names
                        table_name = table.get('TABLE_NAME', table.get('table_name', 'Unknown'))
                        table_type = table.get('TABLE_TYPE', table.get('table_type', 'BASE TABLE'))
                        table_rows = table.get('TABLE_ROWS', table.get('table_rows', 'N/A'))
                        table_list += f"- {table_name} (Type: {table_type}, Rows: {table_rows})\n"
                    
                    return [TextContent(type="text", text=table_list)]
                
                elif name == "describe_table":
                    table_name = arguments.get("table")
                    columns = await get_table_columns(table_name)
                    
                    if not columns:
                        return [TextContent(type="text", text=f"Table '{table_name}' not found")]
                    
                    description = f"Table: {table_name}\n\nColumns:\n"
                    for col in columns:
                        # Handle both uppercase and lowercase field names
                        col_name = col.get('COLUMN_NAME', col.get('column_name', 'Unknown'))
                        col_type = col.get('COLUMN_TYPE', col.get('column_type', 'Unknown'))
                        is_nullable = col.get('IS_NULLABLE', col.get('is_nullable', 'YES'))
                        col_key = col.get('COLUMN_KEY', col.get('column_key', ''))
                        extra = col.get('EXTRA', col.get('extra', ''))
                        
                        description += f"- {col_name}: {col_type}"
                        if is_nullable == 'NO':
                            description += " NOT NULL"
                        if col_key == 'PRI':
                            description += " PRIMARY KEY"
                        if extra:
                            description += f" {extra.upper()}"
                        description += "\n"
                    
                    return [TextContent(type="text", text=description)]
                
                elif name == "execute_sql" or name == "create_table":
                    if not self.user_props.has_write_access:
                        return [TextContent(type="text", text="Error: Write access required")]
                    
                    sql = arguments.get("sql")
                    
                    # Validate SQL
                    validation = validate_sql_query(sql)
                    if not validation.is_valid:
                        return [TextContent(type="text", text=f"Error: {validation.error}")]
                    
                    result = await execute_query(sql, fetch_all=False, return_cursor=True)
                    
                    if result.success:
                        return [TextContent(type="text", text=f"Query executed successfully. Rows affected: {result.rows_affected}")]
                    else:
                        return [TextContent(type="text", text=f"Error: {result.error}")]
                
                else:
                    return [TextContent(type="text", text=f"Unknown tool: {name}")]
                    
            except Exception as e:
                return [TextContent(type="text", text=f"Error: {str(e)}")]

    async def run(self):
        # Initialize database connection pool silently
        try:
            pool = await get_pool()
            await test_connection()
        except:
            pass
        
        try:
            async with stdio_server() as (read_stream, write_stream):
                await self.server.run(
                    read_stream,
                    write_stream,
                    InitializationOptions(
                        server_name="mysql-mcp-server",
                        server_version="1.0.0",
                        capabilities=self.server.get_capabilities(
                            notification_options=NotificationOptions(),
                            experimental_capabilities={}
                        )
                    )
                )
        finally:
            try:
                await close_pool()
            except:
                pass

def main():
    parser = argparse.ArgumentParser(description="MySQL MCP Server")
    parser.add_argument("--log-level", default="CRITICAL", help="Set the logging level")
    args = parser.parse_args()

    server = MySQLMCPServer()
    asyncio.run(server.run())

if __name__ == "__main__":
    main()