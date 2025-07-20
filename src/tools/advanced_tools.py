from fastmcp import FastMCP
from ..models import (
    StoredProcedureRequest,
    ExecuteProcedureRequest,
    FunctionRequest,
    TriggerRequest,
    IndexRequest,
    ComplexQueryRequest,
    create_success_response,
    create_error_response
)
from ..database import (
    with_database,
    execute_query,
    sanitize_identifier,
    quote_identifier,
    analyze_query_plan,
    validate_params
)
import structlog
import json

logger = structlog.get_logger()


def register_advanced_tools(mcp: FastMCP) -> None:
    """Register advanced MySQL feature tools"""
    
    @mcp.tool(
        name="manage_stored_procedure",
        description="Create, modify, drop, or show stored procedures in the database."
    )
    async def manage_stored_procedure(request: StoredProcedureRequest):
        """Manage stored procedures"""
        try:
            async def operation():
                if request.action == "show":
                    # Show all procedures or specific one
                    if request.name:
                        sql = "SHOW CREATE PROCEDURE " + quote_identifier(request.name)
                        result = await execute_query(sql, fetch_one=True)
                        return {"procedure": result.data}
                    else:
                        sql = "SHOW PROCEDURE STATUS WHERE Db = DATABASE()"
                        result = await execute_query(sql)
                        return {"procedures": result.data}
                
                elif request.action == "create":
                    if not request.name or not request.definition:
                        raise ValueError("Name and definition required for create")
                    
                    # Drop if exists and create new
                    await execute_query(f"DROP PROCEDURE IF EXISTS {quote_identifier(request.name)}")
                    result = await execute_query(request.definition, fetch_all=False, return_cursor=True)
                    return {
                        "action": "created",
                        "procedure": request.name,
                        "success": result.success
                    }
                
                elif request.action == "drop":
                    if not request.name:
                        raise ValueError("Name required for drop")
                    
                    sql = f"DROP PROCEDURE IF EXISTS {quote_identifier(request.name)}"
                    result = await execute_query(sql, fetch_all=False, return_cursor=True)
                    return {
                        "action": "dropped",
                        "procedure": request.name,
                        "success": result.success
                    }
                
                elif request.action == "modify":
                    if not request.name or not request.definition:
                        raise ValueError("Name and definition required for modify")
                    
                    # MySQL doesn't have ALTER PROCEDURE for body, so drop and recreate
                    await execute_query(f"DROP PROCEDURE IF EXISTS {quote_identifier(request.name)}")
                    result = await execute_query(request.definition, fetch_all=False, return_cursor=True)
                    return {
                        "action": "modified",
                        "procedure": request.name,
                        "success": result.success
                    }
            
            result = await with_database(operation)
            
            # Format response
            if request.action == "show":
                response_text = "**Stored Procedures**\n\n```json\n"
                response_text += json.dumps(result, indent=2, default=str)
                response_text += "\n```"
            else:
                response_text = f"**Stored Procedure {result['action'].title()}**\n\n"
                response_text += f"Procedure: `{result['procedure']}`\n"
                response_text += f"Status: {'Success' if result['success'] else 'Failed'}"
            
            return create_success_response(response_text)
            
        except Exception as e:
            logger.error(f"Failed to {request.action} stored procedure", error=str(e))
            return create_error_response(f"Failed to {request.action} stored procedure: {str(e)}")
    
    
    @mcp.tool(
        name="execute_stored_procedure",
        description="Execute a stored procedure with parameters."
    )
    async def execute_stored_procedure(request: ExecuteProcedureRequest):
        """Execute a stored procedure"""
        try:
            # Validate parameters
            if request.params:
                params_valid, params_error = validate_params(request.params)
                if not params_valid:
                    return create_error_response(f"Invalid parameters: {params_error}")
            
            async def operation():
                # Build CALL statement
                proc_name = quote_identifier(request.name)
                
                if request.params:
                    placeholders = ', '.join(['%s'] * len(request.params))
                    sql = f"CALL {proc_name}({placeholders})"
                    result = await execute_query(sql, params=request.params)
                else:
                    sql = f"CALL {proc_name}()"
                    result = await execute_query(sql)
                
                return {
                    "procedure": request.name,
                    "result": result.data,
                    "success": result.success,
                    "duration_ms": result.duration_ms
                }
            
            result = await with_database(operation)
            
            response_text = f"**Stored Procedure Executed**\n\n"
            response_text += f"Procedure: `{result['procedure']}`\n"
            response_text += f"Execution Time: {result['duration_ms']:.2f}ms\n\n"
            response_text += "**Result:**\n```json\n"
            response_text += json.dumps(result['result'], indent=2, default=str)
            response_text += "\n```"
            
            return create_success_response(response_text)
            
        except Exception as e:
            logger.error("Failed to execute stored procedure", error=str(e))
            return create_error_response(f"Failed to execute stored procedure: {str(e)}")
    
    
    @mcp.tool(
        name="manage_function",
        description="Create, modify, drop, or show user-defined functions in the database."
    )
    async def manage_function(request: FunctionRequest):
        """Manage user-defined functions"""
        try:
            async def operation():
                if request.action == "show":
                    if request.name:
                        sql = "SHOW CREATE FUNCTION " + quote_identifier(request.name)
                        result = await execute_query(sql, fetch_one=True)
                        return {"function": result.data}
                    else:
                        sql = "SHOW FUNCTION STATUS WHERE Db = DATABASE()"
                        result = await execute_query(sql)
                        return {"functions": result.data}
                
                elif request.action == "create":
                    if not request.name or not request.definition:
                        raise ValueError("Name and definition required for create")
                    
                    await execute_query(f"DROP FUNCTION IF EXISTS {quote_identifier(request.name)}")
                    result = await execute_query(request.definition, fetch_all=False, return_cursor=True)
                    return {
                        "action": "created",
                        "function": request.name,
                        "success": result.success
                    }
                
                elif request.action == "drop":
                    if not request.name:
                        raise ValueError("Name required for drop")
                    
                    sql = f"DROP FUNCTION IF EXISTS {quote_identifier(request.name)}"
                    result = await execute_query(sql, fetch_all=False, return_cursor=True)
                    return {
                        "action": "dropped",
                        "function": request.name,
                        "success": result.success
                    }
                
                elif request.action == "modify":
                    if not request.name or not request.definition:
                        raise ValueError("Name and definition required for modify")
                    
                    await execute_query(f"DROP FUNCTION IF EXISTS {quote_identifier(request.name)}")
                    result = await execute_query(request.definition, fetch_all=False, return_cursor=True)
                    return {
                        "action": "modified",
                        "function": request.name,
                        "success": result.success
                    }
            
            result = await with_database(operation)
            
            if request.action == "show":
                response_text = "**User-Defined Functions**\n\n```json\n"
                response_text += json.dumps(result, indent=2, default=str)
                response_text += "\n```"
            else:
                response_text = f"**Function {result['action'].title()}**\n\n"
                response_text += f"Function: `{result['function']}`\n"
                response_text += f"Status: {'Success' if result['success'] else 'Failed'}"
            
            return create_success_response(response_text)
            
        except Exception as e:
            logger.error(f"Failed to {request.action} function", error=str(e))
            return create_error_response(f"Failed to {request.action} function: {str(e)}")
    
    
    @mcp.tool(
        name="manage_trigger", 
        description="Create, modify, drop, enable, disable, or show triggers in the database."
    )
    async def manage_trigger(request: TriggerRequest):
        """Manage database triggers"""
        try:
            async def operation():
                if request.action == "show":
                    if request.name:
                        sql = "SHOW CREATE TRIGGER " + quote_identifier(request.name)
                        result = await execute_query(sql, fetch_one=True)
                        return {"trigger": result.data}
                    else:
                        sql = "SHOW TRIGGERS"
                        if request.table:
                            sql += f" FROM {quote_identifier(request.table)}"
                        result = await execute_query(sql)
                        return {"triggers": result.data}
                
                elif request.action == "create":
                    if not request.name or not request.definition:
                        raise ValueError("Name and definition required for create")
                    
                    await execute_query(f"DROP TRIGGER IF EXISTS {quote_identifier(request.name)}")
                    result = await execute_query(request.definition, fetch_all=False, return_cursor=True)
                    return {
                        "action": "created",
                        "trigger": request.name,
                        "success": result.success
                    }
                
                elif request.action == "drop":
                    if not request.name:
                        raise ValueError("Name required for drop")
                    
                    sql = f"DROP TRIGGER IF EXISTS {quote_identifier(request.name)}"
                    result = await execute_query(sql, fetch_all=False, return_cursor=True)
                    return {
                        "action": "dropped",
                        "trigger": request.name,
                        "success": result.success
                    }
                
                elif request.action in ["enable", "disable"]:
                    # MySQL doesn't support ENABLE/DISABLE TRIGGER directly
                    # This would require altering the trigger or using a workaround
                    raise NotImplementedError(f"MySQL does not support {request.action} trigger directly")
            
            result = await with_database(operation)
            
            if request.action == "show":
                response_text = "**Database Triggers**\n\n```json\n"
                response_text += json.dumps(result, indent=2, default=str)
                response_text += "\n```"
            else:
                response_text = f"**Trigger {result['action'].title()}**\n\n"
                response_text += f"Trigger: `{result['trigger']}`\n"
                response_text += f"Status: {'Success' if result['success'] else 'Failed'}"
            
            return create_success_response(response_text)
            
        except Exception as e:
            logger.error(f"Failed to {request.action} trigger", error=str(e))
            return create_error_response(f"Failed to {request.action} trigger: {str(e)}")
    
    
    @mcp.tool(
        name="manage_index",
        description="Create, drop, show, or analyze indexes on tables."
    )
    async def manage_index(request: IndexRequest):
        """Manage table indexes"""
        try:
            table_name = quote_identifier(request.table)
            
            async def operation():
                if request.action == "show":
                    sql = f"SHOW INDEX FROM {table_name}"
                    result = await execute_query(sql)
                    
                    # Group by index name
                    indexes = {}
                    for row in result.data:
                        idx_name = row['Key_name']
                        if idx_name not in indexes:
                            indexes[idx_name] = {
                                'name': idx_name,
                                'unique': not row['Non_unique'],
                                'type': row['Index_type'],
                                'columns': []
                            }
                        indexes[idx_name]['columns'].append({
                            'column': row['Column_name'],
                            'sequence': row['Seq_in_index'],
                            'cardinality': row['Cardinality']
                        })
                    
                    return {"indexes": list(indexes.values())}
                
                elif request.action == "create":
                    if not request.index_name or not request.columns:
                        raise ValueError("Index name and columns required for create")
                    
                    # Build CREATE INDEX statement
                    index_type = ""
                    if request.index_type == "fulltext":
                        index_type = "FULLTEXT "
                    elif request.index_type == "unique":
                        index_type = "UNIQUE "
                    
                    columns = ', '.join([quote_identifier(col) for col in request.columns])
                    sql = f"CREATE {index_type}INDEX {quote_identifier(request.index_name)} ON {table_name} ({columns})"
                    
                    if request.index_type == "hash":
                        sql += " USING HASH"
                    
                    result = await execute_query(sql, fetch_all=False, return_cursor=True)
                    return {
                        "action": "created",
                        "index": request.index_name,
                        "table": request.table,
                        "success": result.success
                    }
                
                elif request.action == "drop":
                    if not request.index_name:
                        raise ValueError("Index name required for drop")
                    
                    sql = f"DROP INDEX {quote_identifier(request.index_name)} ON {table_name}"
                    result = await execute_query(sql, fetch_all=False, return_cursor=True)
                    return {
                        "action": "dropped",
                        "index": request.index_name,
                        "table": request.table,
                        "success": result.success
                    }
                
                elif request.action == "analyze":
                    sql = f"ANALYZE TABLE {table_name}"
                    result = await execute_query(sql)
                    return {
                        "action": "analyzed",
                        "table": request.table,
                        "result": result.data
                    }
            
            result = await with_database(operation)
            
            if request.action == "show":
                response_text = f"**Indexes for table `{request.table}`**\n\n```json\n"
                response_text += json.dumps(result['indexes'], indent=2)
                response_text += "\n```"
            else:
                response_text = f"**Index {result['action'].title()}**\n\n"
                response_text += f"Table: `{result['table']}`\n"
                if 'index' in result:
                    response_text += f"Index: `{result['index']}`\n"
                response_text += f"Status: {'Success' if result.get('success', True) else 'Failed'}"
                
                if request.action == "analyze":
                    response_text += f"\n\n**Analysis Result:**\n```json\n"
                    response_text += json.dumps(result['result'], indent=2, default=str)
                    response_text += "\n```"
            
            return create_success_response(response_text)
            
        except Exception as e:
            logger.error(f"Failed to {request.action} index", error=str(e))
            return create_error_response(f"Failed to {request.action} index: {str(e)}")
    
    
    @mcp.tool(
        name="execute_complex_query",
        description="Execute complex queries with joins, subqueries, CTEs, window functions. Includes query analysis and optimization suggestions."
    )
    async def execute_complex_query(request: ComplexQueryRequest):
        """Execute complex SQL queries with analysis"""
        try:
            async def operation():
                # First analyze the query if requested
                analysis = None
                if request.explain or request.optimize_hints:
                    analysis = await analyze_query_plan(request.sql)
                
                # Execute the query
                result = await execute_query(request.sql)
                
                if not result.success:
                    raise Exception(result.error)
                
                return {
                    "data": result.data,
                    "row_count": len(result.data) if isinstance(result.data, list) else 0,
                    "duration_ms": result.duration_ms,
                    "analysis": analysis
                }
            
            result = await with_database(operation)
            
            # Format response
            response_text = "**Complex Query Results**\n\n"
            response_text += f"Rows returned: {result['row_count']}\n"
            response_text += f"Execution time: {result['duration_ms']:.2f}ms\n\n"
            
            if result['analysis']:
                response_text += "**Query Analysis:**\n"
                
                if result['analysis'].get('explain'):
                    response_text += "\n*Execution Plan:*\n```json\n"
                    response_text += json.dumps(result['analysis']['explain'], indent=2, default=str)
                    response_text += "\n```\n"
                
                if result['analysis'].get('suggestions'):
                    response_text += "\n*Optimization Suggestions:*\n"
                    for suggestion in result['analysis']['suggestions']:
                        response_text += f"- {suggestion}\n"
                    response_text += "\n"
            
            response_text += "**Data:**\n```json\n"
            response_text += json.dumps(result["data"], indent=2, default=str)
            response_text += "\n```"
            
            return create_success_response(response_text)
            
        except Exception as e:
            logger.error("Complex query execution failed", error=str(e))
            return create_error_response(f"Complex query execution failed: {str(e)}")