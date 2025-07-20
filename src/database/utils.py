from typing import Any, Dict, List, Optional, Callable
import time
import structlog
from .connection import get_cursor, get_connection
from .security import format_database_error
from ..models import DatabaseOperationResult

logger = structlog.get_logger()


async def execute_query(
    sql: str,
    params: Optional[List[Any]] = None,
    fetch_one: bool = False,
    fetch_all: bool = True,
    return_cursor: bool = False
) -> DatabaseOperationResult:
    """
    Execute a SQL query with proper error handling and timing
    
    Args:
        sql: SQL query to execute
        params: Parameters for prepared statement
        fetch_one: Fetch only one row
        fetch_all: Fetch all rows (default)
        return_cursor: Return cursor info (rowcount, lastrowid)
    
    Returns:
        DatabaseOperationResult with query results
    """
    start_time = time.time()
    
    try:
        async with get_cursor() as cursor:
            # Execute query
            if params:
                await cursor.execute(sql, params)
            else:
                await cursor.execute(sql)
            
            # Get results based on options
            data = None
            rows_affected = cursor.rowcount
            
            if return_cursor:
                data = {
                    "rowcount": cursor.rowcount,
                    "lastrowid": cursor.lastrowid if hasattr(cursor, 'lastrowid') else None
                }
            elif fetch_one:
                data = await cursor.fetchone()
            elif fetch_all:
                data = await cursor.fetchall()
            
            duration_ms = (time.time() - start_time) * 1000
            
            return DatabaseOperationResult(
                success=True,
                data=data,
                duration_ms=duration_ms,
                rows_affected=rows_affected
            )
            
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        error_msg = format_database_error(e)
        
        logger.error(
            "Query execution failed",
            sql=sql[:100],  # Log first 100 chars
            duration_ms=duration_ms,
            error=str(e)
        )
        
        return DatabaseOperationResult(
            success=False,
            error=error_msg,
            duration_ms=duration_ms
        )


async def get_table_list(schema: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get list of all tables with their structure"""
    # Build query based on schema
    if schema:
        sql = """
        SELECT 
            table_name,
            table_schema,
            table_type,
            engine,
            table_rows,
            data_length,
            index_length,
            create_time,
            update_time
        FROM information_schema.tables
        WHERE table_schema = %s
        ORDER BY table_name
        """
        params = [schema]
    else:
        sql = """
        SELECT 
            table_name,
            table_schema,
            table_type,
            engine,
            table_rows,
            data_length,
            index_length,
            create_time,
            update_time
        FROM information_schema.tables
        WHERE table_schema = DATABASE()
        ORDER BY table_name
        """
        params = None
    
    result = await execute_query(sql, params)
    return result.data if result.success else []


async def get_table_columns(table_name: str, schema: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get column information for a table"""
    if schema:
        sql = """
        SELECT 
            column_name,
            data_type,
            column_type,
            is_nullable,
            column_default,
            column_key,
            extra,
            column_comment
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
        """
        params = [schema, table_name]
    else:
        sql = """
        SELECT 
            column_name,
            data_type,
            column_type,
            is_nullable,
            column_default,
            column_key,
            extra,
            column_comment
        FROM information_schema.columns
        WHERE table_schema = DATABASE() AND table_name = %s
        ORDER BY ordinal_position
        """
        params = [table_name]
    
    result = await execute_query(sql, params)
    return result.data if result.success else []


async def get_table_indexes(table_name: str, schema: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get index information for a table"""
    if schema:
        sql = """
        SELECT 
            index_name,
            non_unique,
            seq_in_index,
            column_name,
            collation,
            cardinality,
            sub_part,
            packed,
            nullable,
            index_type,
            comment
        FROM information_schema.statistics
        WHERE table_schema = %s AND table_name = %s
        ORDER BY index_name, seq_in_index
        """
        params = [schema, table_name]
    else:
        sql = """
        SELECT 
            index_name,
            non_unique,
            seq_in_index,
            column_name,
            collation,
            cardinality,
            sub_part,
            packed,
            nullable,
            index_type,
            comment
        FROM information_schema.statistics
        WHERE table_schema = DATABASE() AND table_name = %s
        ORDER BY index_name, seq_in_index
        """
        params = [table_name]
    
    result = await execute_query(sql, params)
    return result.data if result.success else []


async def get_table_foreign_keys(table_name: str, schema: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get foreign key information for a table"""
    if schema:
        sql = """
        SELECT 
            constraint_name,
            column_name,
            referenced_table_schema,
            referenced_table_name,
            referenced_column_name
        FROM information_schema.key_column_usage
        WHERE table_schema = %s 
            AND table_name = %s
            AND referenced_table_name IS NOT NULL
        ORDER BY constraint_name, ordinal_position
        """
        params = [schema, table_name]
    else:
        sql = """
        SELECT 
            constraint_name,
            column_name,
            referenced_table_schema,
            referenced_table_name,
            referenced_column_name
        FROM information_schema.key_column_usage
        WHERE table_schema = DATABASE() 
            AND table_name = %s
            AND referenced_table_name IS NOT NULL
        ORDER BY constraint_name, ordinal_position
        """
        params = [table_name]
    
    result = await execute_query(sql, params)
    return result.data if result.success else []


async def analyze_query_plan(sql: str) -> Dict[str, Any]:
    """Get query execution plan and optimization suggestions"""
    explain_result = await execute_query(f"EXPLAIN {sql}")
    
    if not explain_result.success:
        return {"error": explain_result.error}
    
    # Also get extended explain for more details
    explain_extended = await execute_query(f"EXPLAIN EXTENDED {sql}")
    
    # Get query cost if available (MySQL 5.7+)
    explain_analyze = None
    try:
        explain_analyze_result = await execute_query(f"EXPLAIN ANALYZE {sql}")
        if explain_analyze_result.success:
            explain_analyze = explain_analyze_result.data
    except:
        pass  # EXPLAIN ANALYZE not available in this MySQL version
    
    # Analyze the explain output for optimization suggestions
    suggestions = []
    explain_data = explain_result.data or []
    
    for row in explain_data:
        # Check for full table scans
        if row.get('type') == 'ALL':
            suggestions.append(f"Full table scan on table '{row.get('table')}'. Consider adding an index.")
        
        # Check for filesort
        if row.get('Extra') and 'filesort' in row.get('Extra', ''):
            suggestions.append(f"Query uses filesort on table '{row.get('table')}'. Consider adding an index on ORDER BY columns.")
        
        # Check for temporary tables
        if row.get('Extra') and 'temporary' in row.get('Extra', ''):
            suggestions.append(f"Query creates temporary table for '{row.get('table')}'. Consider optimizing GROUP BY or DISTINCT.")
        
        # Check for low key efficiency
        if row.get('rows') and row.get('rows_examined'):
            efficiency = row.get('rows') / row.get('rows_examined')
            if efficiency < 0.1:
                suggestions.append(f"Low key efficiency for table '{row.get('table')}'. Only {efficiency:.1%} of examined rows are used.")
    
    return {
        "explain": explain_data,
        "explain_extended": explain_extended.data if explain_extended.success else None,
        "explain_analyze": explain_analyze,
        "suggestions": suggestions
    }