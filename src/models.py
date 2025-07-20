from typing import Optional, Dict, Any, List, TypedDict, Literal
from dataclasses import dataclass
from datetime import datetime
from pydantic import BaseModel, Field


# User context from OAuth
@dataclass
class UserProps:
    """User properties from GitHub OAuth"""
    login: str  # GitHub username
    name: str
    email: str
    access_token: str
    
    @property
    def has_write_access(self) -> bool:
        """Check if user has write access"""
        from .config import is_write_access_allowed
        return is_write_access_allowed(self.login)


# MCP Response Types
class McpTextContent(TypedDict):
    """Text content for MCP responses"""
    type: Literal["text"]
    text: str
    isError: Optional[bool]


class McpResponse(TypedDict):
    """Standard MCP response format"""
    content: List[McpTextContent]


# Request Schemas using Pydantic
class ListTablesRequest(BaseModel):
    """Request for listing tables"""
    schema: Optional[str] = Field(None, description="Database schema to list tables from")


class QueryDatabaseRequest(BaseModel):
    """Request for read-only queries"""
    sql: str = Field(..., min_length=1, description="SQL query to execute (SELECT queries only)")
    limit: Optional[int] = Field(None, ge=1, le=10000, description="Maximum number of rows to return")


class ExecuteDatabaseRequest(BaseModel):
    """Request for write operations"""
    sql: str = Field(..., min_length=1, description="SQL command to execute (INSERT, UPDATE, DELETE, etc.)")
    params: Optional[List[Any]] = Field(None, description="Parameters for prepared statement")


class ManageTransactionRequest(BaseModel):
    """Request for transaction management"""
    action: Literal["begin", "commit", "rollback", "savepoint", "release_savepoint"]
    savepoint_name: Optional[str] = Field(None, description="Name for savepoint operations")


class StoredProcedureRequest(BaseModel):
    """Request for stored procedure management"""
    action: Literal["create", "drop", "show", "modify"]
    name: Optional[str] = Field(None, description="Procedure name")
    definition: Optional[str] = Field(None, description="Procedure definition for create/modify")
    
    
class ExecuteProcedureRequest(BaseModel):
    """Request to execute a stored procedure"""
    name: str = Field(..., description="Stored procedure name")
    params: Optional[List[Any]] = Field(None, description="Parameters to pass")
    

class FunctionRequest(BaseModel):
    """Request for function management"""
    action: Literal["create", "drop", "show", "modify"]
    name: Optional[str] = Field(None, description="Function name")
    definition: Optional[str] = Field(None, description="Function definition for create/modify")


class TriggerRequest(BaseModel):
    """Request for trigger management"""
    action: Literal["create", "drop", "show", "modify", "enable", "disable"]
    name: Optional[str] = Field(None, description="Trigger name")
    table: Optional[str] = Field(None, description="Table name for the trigger")
    definition: Optional[str] = Field(None, description="Trigger definition for create/modify")


class IndexRequest(BaseModel):
    """Request for index management"""
    action: Literal["create", "drop", "show", "analyze"]
    table: str = Field(..., description="Table name")
    index_name: Optional[str] = Field(None, description="Index name")
    columns: Optional[List[str]] = Field(None, description="Columns for index creation")
    index_type: Optional[Literal["btree", "hash", "fulltext"]] = Field(None, description="Index type")


class ComplexQueryRequest(BaseModel):
    """Request for complex queries (joins, CTEs, window functions)"""
    sql: str = Field(..., min_length=1, description="Complex SQL query")
    explain: bool = Field(False, description="Show query execution plan")
    optimize_hints: bool = Field(False, description="Provide optimization suggestions")


class DescribeTableRequest(BaseModel):
    """Request to describe table structure"""
    table: str = Field(..., description="Table name to describe")
    include_indexes: bool = Field(True, description="Include index information")
    include_foreign_keys: bool = Field(True, description="Include foreign key information")


# Database operation results
@dataclass
class DatabaseOperationResult:
    """Result of a database operation"""
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    duration_ms: Optional[float] = None
    rows_affected: Optional[int] = None
    
    def to_mcp_response(self) -> McpResponse:
        """Convert to MCP response format"""
        if self.success:
            return create_success_response(
                "Operation completed successfully",
                {
                    "data": self.data,
                    "duration_ms": self.duration_ms,
                    "rows_affected": self.rows_affected
                }
            )
        else:
            return create_error_response(self.error or "Unknown error")


# Response creators
def create_success_response(message: str, data: Optional[Any] = None) -> McpResponse:
    """Create a success response"""
    text = f"**Success**\n\n{message}"
    if data is not None:
        import json
        text += f"\n\n**Result:**\n```json\n{json.dumps(data, indent=2, default=str)}\n```"
    
    return {
        "content": [{
            "type": "text",
            "text": text,
            "isError": False
        }]
    }


def create_error_response(message: str, details: Optional[Any] = None) -> McpResponse:
    """Create an error response"""
    text = f"**Error**\n\n{message}"
    if details is not None:
        import json
        text += f"\n\n**Details:**\n```json\n{json.dumps(details, indent=2, default=str)}\n```"
    
    return {
        "content": [{
            "type": "text",
            "text": text,
            "isError": True
        }]
    }


# SQL Validation result
@dataclass 
class SqlValidationResult:
    """Result of SQL validation"""
    is_valid: bool
    error: Optional[str] = None
    operation_type: Optional[str] = None
    requires_privilege: bool = False