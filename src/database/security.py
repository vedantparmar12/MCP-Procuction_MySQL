import re
from typing import Tuple, Optional, Any
import structlog
from ..config import (
    DANGEROUS_SQL_PATTERNS, 
    READ_OPERATIONS, 
    WRITE_OPERATIONS, 
    DDL_OPERATIONS,
    PROCEDURE_OPERATIONS,
    TRANSACTION_OPERATIONS,
    get_operation_type
)
from ..models import SqlValidationResult

logger = structlog.get_logger()


def validate_sql_query(sql: str) -> SqlValidationResult:
    """
    Validate SQL query for safety and determine operation type
    """
    if not sql or not sql.strip():
        return SqlValidationResult(
            is_valid=False,
            error="SQL query cannot be empty"
        )
    
    sql_normalized = sql.strip()
    
    # Check for dangerous patterns
    for pattern in DANGEROUS_SQL_PATTERNS:
        if re.search(pattern, sql_normalized, re.IGNORECASE | re.MULTILINE):
            logger.warning(
                "Dangerous SQL pattern detected",
                pattern=pattern,
                sql_preview=sql_normalized[:100]
            )
            return SqlValidationResult(
                is_valid=False,
                error=f"SQL contains potentially dangerous pattern"
            )
    
    # Determine operation type
    operation_type = get_operation_type(sql_normalized)
    
    # Check if operation requires privileges
    requires_privilege = operation_type in ["write", "ddl", "procedure", "transaction"]
    
    # Additional validation for specific operations
    if operation_type == "unknown":
        # Try to detect if it's a complex query with CTEs or other valid constructs
        if sql_normalized.lower().startswith(("with", "(")):
            operation_type = "read"  # CTEs are typically read operations
    
    return SqlValidationResult(
        is_valid=True,
        operation_type=operation_type,
        requires_privilege=requires_privilege
    )


def is_write_operation(sql: str) -> bool:
    """Check if SQL is a write operation"""
    validation = validate_sql_query(sql)
    return validation.requires_privilege


def sanitize_identifier(identifier: str) -> str:
    """
    Sanitize database identifiers (table names, column names, etc.)
    Only allows alphanumeric characters and underscores
    """
    if not identifier:
        raise ValueError("Identifier cannot be empty")
    
    # Remove any backticks first
    identifier = identifier.replace('`', '')
    
    # Check if identifier is valid
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', identifier):
        raise ValueError(f"Invalid identifier: {identifier}")
    
    return identifier


def quote_identifier(identifier: str) -> str:
    """Properly quote a MySQL identifier"""
    sanitized = sanitize_identifier(identifier)
    return f"`{sanitized}`"


def build_safe_query(base_query: str, **kwargs) -> str:
    """
    Build a safe query by replacing placeholders with sanitized identifiers
    Use this for queries where you need to dynamically specify table/column names
    
    Example:
        build_safe_query("SELECT * FROM {table}", table="users")
    """
    safe_params = {}
    for key, value in kwargs.items():
        if isinstance(value, str):
            safe_params[key] = quote_identifier(value)
        else:
            safe_params[key] = value
    
    return base_query.format(**safe_params)


def format_database_error(error: Any) -> str:
    """
    Format database errors for user display, sanitizing sensitive information
    Matches the TypeScript formatDatabaseError function
    """
    error_str = str(error).lower()
    
    # Check for common error patterns and provide user-friendly messages
    if "access denied" in error_str or "password" in error_str:
        return "Database authentication failed. Please check credentials."
    
    if "timeout" in error_str or "timed out" in error_str:
        return "Database connection timed out. Please try again."
    
    if "connection refused" in error_str or "can't connect" in error_str:
        return "Unable to connect to database. Please check if the database is running."
    
    if "unknown database" in error_str:
        return "Database not found. Please check the database name."
    
    if "table" in error_str and "doesn't exist" in error_str:
        # Extract table name if possible
        match = re.search(r"table '([^']+)' doesn't exist", error_str)
        if match:
            return f"Table '{match.group(1)}' does not exist."
        return "Table does not exist."
    
    if "duplicate entry" in error_str:
        return "Duplicate entry error. A record with this value already exists."
    
    if "foreign key constraint" in error_str:
        return "Foreign key constraint violation. Please check related records."
    
    if "syntax error" in error_str:
        return "SQL syntax error. Please check your query."
    
    # For other errors, return a sanitized version
    # Remove any potential sensitive information
    error_message = str(error)
    
    # Remove connection strings, passwords, etc.
    error_message = re.sub(r'password["\']?\s*[:=]\s*["\']?[^"\'\s]+', 'password=***', error_message, flags=re.IGNORECASE)
    error_message = re.sub(r'mysql://[^@]+@', 'mysql://***@', error_message)
    
    return f"Database error: {error_message}"


def validate_params(params: Optional[list]) -> Tuple[bool, Optional[str]]:
    """
    Validate parameters for prepared statements
    Returns (is_valid, error_message)
    """
    if params is None:
        return True, None
    
    if not isinstance(params, list):
        return False, "Parameters must be a list"
    
    # Check each parameter
    for i, param in enumerate(params):
        # Allow basic types that are safe for prepared statements
        if not isinstance(param, (str, int, float, bool, type(None))):
            return False, f"Parameter at index {i} has invalid type: {type(param).__name__}"
    
    return True, None


def extract_table_names(sql: str) -> list[str]:
    """Extract table names from SQL query for logging/validation"""
    tables = []
    
    # Simple pattern to extract table names (not exhaustive)
    # FROM table_name
    from_pattern = r'FROM\s+`?([a-zA-Z_][a-zA-Z0-9_]*)`?'
    tables.extend(re.findall(from_pattern, sql, re.IGNORECASE))
    
    # JOIN table_name
    join_pattern = r'JOIN\s+`?([a-zA-Z_][a-zA-Z0-9_]*)`?'
    tables.extend(re.findall(join_pattern, sql, re.IGNORECASE))
    
    # UPDATE table_name
    update_pattern = r'UPDATE\s+`?([a-zA-Z_][a-zA-Z0-9_]*)`?'
    tables.extend(re.findall(update_pattern, sql, re.IGNORECASE))
    
    # INSERT INTO table_name
    insert_pattern = r'INSERT\s+INTO\s+`?([a-zA-Z_][a-zA-Z0-9_]*)`?'
    tables.extend(re.findall(insert_pattern, sql, re.IGNORECASE))
    
    # DELETE FROM table_name
    delete_pattern = r'DELETE\s+FROM\s+`?([a-zA-Z_][a-zA-Z0-9_]*)`?'
    tables.extend(re.findall(delete_pattern, sql, re.IGNORECASE))
    
    return list(set(tables))  # Remove duplicates