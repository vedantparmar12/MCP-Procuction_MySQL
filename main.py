#!/usr/bin/env python3
"""
Cloudflare MySQL MCP Server
A comprehensive MCP server for MySQL database operations with Cloudflare Workers support
"""

import asyncio
import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional, Union, Set
from contextlib import asynccontextmanager
from datetime import datetime, date
from decimal import Decimal
import re
import hashlib
import hmac
import time

import aiomysql
from fastmcp import FastMCP
from pydantic import BaseModel, Field, validator
import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class DatabaseConfig(BaseModel):
    """Database configuration model with Cloudflare support"""
    host: str = Field(description="MySQL host (Cloudflare compatible)")
    port: int = Field(default=3306, description="MySQL port")
    user: str = Field(description="MySQL username")
    password: str = Field(description="MySQL password")
    database: str = Field(description="MySQL database name")
    charset: str = Field(default="utf8mb4", description="Character set")
    autocommit: bool = Field(default=True, description="Auto commit transactions")
    pool_size: int = Field(default=5, description="Connection pool size")
    max_overflow: int = Field(default=10, description="Max overflow connections")
    ssl_mode: str = Field(default="REQUIRED", description="SSL mode for Cloudflare")
    
    # Cloudflare specific settings
    cloudflare_account_id: Optional[str] = Field(default=None, description="Cloudflare account ID")
    cloudflare_token: Optional[str] = Field(default=None, description="Cloudflare API token")
    
    # Role-based access control
    github_admins: List[str] = Field(default=[], description="GitHub usernames with admin access")
    github_writers: List[str] = Field(default=[], description="GitHub usernames with write access")
    github_readers: List[str] = Field(default=[], description="GitHub usernames with read access")
    
    # Monitoring
    sentry_dsn: Optional[str] = Field(default=None, description="Sentry DSN for monitoring")
    enable_monitoring: bool = Field(default=False, description="Enable monitoring")

class QueryResult(BaseModel):
    """Query result model with enhanced metadata"""
    success: bool
    data: Optional[List[Dict[str, Any]]] = None
    affected_rows: Optional[int] = None
    last_insert_id: Optional[int] = None
    error: Optional[str] = None
    execution_time: Optional[float] = None
    query_hash: Optional[str] = None
    timestamp: Optional[str] = None
    user: Optional[str] = None

class UserPermission(BaseModel):
    """User permission model"""
    username: str
    role: str  # admin, writer, reader
    can_read: bool
    can_write: bool
    can_admin: bool

class SecurityValidator:
    """SQL injection protection and validation"""
    
    # Dangerous SQL patterns
    DANGEROUS_PATTERNS = [
        r';\s*(DROP|DELETE|UPDATE|INSERT|ALTER|CREATE|TRUNCATE)',
        r'UNION\s+SELECT',
        r'--\s*$',
        r'/\*.*\*/',
        r'xp_cmdshell',
        r'sp_executesql',
        r'EXEC\s*\(',
        r'EXECUTE\s*\(',
        r'INFORMATION_SCHEMA\.',
        r'mysql\.',
        r'performance_schema\.',
        r'sys\.',
    ]
    
    @classmethod
    def validate_query(cls, query: str) -> tuple[bool, Optional[str]]:
        """Validate SQL query for security"""
        if not query or not query.strip():
            return False, "Empty query"
        
        # Check for dangerous patterns
        for pattern in cls.DANGEROUS_PATTERNS:
            if re.search(pattern, query, re.IGNORECASE):
                return False, f"Potentially dangerous SQL pattern detected: {pattern}"
        
        # Check for multiple statements
        if query.count(';') > 1:
            return False, "Multiple statements not allowed"
        
        return True, None
    
    @classmethod
    def sanitize_identifier(cls, identifier: str) -> str:
        """Sanitize table/column identifiers"""
        # Remove any non-alphanumeric characters except underscore
        return re.sub(r'[^a-zA-Z0-9_]', '', identifier)
    
    @classmethod
    def validate_table_name(cls, table_name: str) -> bool:
        """Validate table name"""
        if not table_name:
            return False
        
        # Check for valid identifier pattern
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', table_name):
            return False
        
        # Check length
        if len(table_name) > 64:
            return False
        
        return True

class PermissionManager:
    """Role-based access control manager"""
    
    def __init__(self, config: DatabaseConfig):
        self.config = config
        self.permissions: Dict[str, UserPermission] = {}
        self._build_permissions()
    
    def _build_permissions(self):
        """Build permission mappings"""
        # Admin users
        for username in self.config.github_admins:
            self.permissions[username] = UserPermission(
                username=username,
                role="admin",
                can_read=True,
                can_write=True,
                can_admin=True
            )
        
        # Writer users
        for username in self.config.github_writers:
            if username not in self.permissions:
                self.permissions[username] = UserPermission(
                    username=username,
                    role="writer",
                    can_read=True,
                    can_write=True,
                    can_admin=False
                )
        
        # Reader users
        for username in self.config.github_readers:
            if username not in self.permissions:
                self.permissions[username] = UserPermission(
                    username=username,
                    role="reader",
                    can_read=True,
                    can_write=False,
                    can_admin=False
                )
    
    def get_user_permission(self, username: str) -> Optional[UserPermission]:
        """Get user permission"""
        return self.permissions.get(username)
    
    def can_execute_query(self, username: str, query: str) -> tuple[bool, Optional[str]]:
        """Check if user can execute a query"""
        user_perm = self.get_user_permission(username)
        if not user_perm:
            return False, "User not found or no permissions"
        
        # Check query type
        query_upper = query.upper().strip()
        
        # Admin operations
        if any(query_upper.startswith(op) for op in ['DROP', 'ALTER', 'CREATE', 'TRUNCATE']):
            if not user_perm.can_admin:
                return False, "Admin permissions required"
        
        # Write operations
        elif any(query_upper.startswith(op) for op in ['INSERT', 'UPDATE', 'DELETE']):
            if not user_perm.can_write:
                return False, "Write permissions required"
        
        # Read operations
        elif query_upper.startswith('SELECT'):
            if not user_perm.can_read:
                return False, "Read permissions required"
        
        return True, None

class CloudflareMySQLMCPServer:
    """Cloudflare MySQL MCP Server with comprehensive features"""
    
    def __init__(self, config: DatabaseConfig):
        self.config = config
        self.pool: Optional[aiomysql.Pool] = None
        self.mcp = FastMCP("Cloudflare MySQL Database Server")
        self.permission_manager = PermissionManager(config)
        self.security_validator = SecurityValidator()
        self._setup_monitoring()
        self._setup_tools()
        self._setup_resources()
        self._setup_prompts()
    
    def _setup_monitoring(self):
        """Setup Sentry monitoring if enabled"""
        if self.config.enable_monitoring and self.config.sentry_dsn:
            sentry_logging = LoggingIntegration(
                level=logging.INFO,
                event_level=logging.ERROR
            )
            sentry_sdk.init(
                dsn=self.config.sentry_dsn,
                integrations=[sentry_logging],
                traces_sample_rate=1.0,
                environment="production" if self.config.cloudflare_account_id else "development"
            )
            logger.info("Sentry monitoring enabled")
    
    def _setup_tools(self):
        """Setup MCP tools with role-based access"""
        
        @self.mcp.tool()
        async def execute_safe_query(
            query: str,
            params: Optional[List[Any]] = None,
            user: str = "anonymous"
        ) -> QueryResult:
            """
            Execute a safe SQL query with security validation and role-based access
            
            Args:
                query: SQL query to execute (validated for security)
                params: Optional parameters for prepared statements
                user: GitHub username for permission checking
            
            Returns:
                QueryResult with execution details
            """
            # Validate security
            is_valid, error_msg = self.security_validator.validate_query(query)
            if not is_valid:
                return QueryResult(
                    success=False,
                    error=f"Security validation failed: {error_msg}",
                    user=user,
                    timestamp=datetime.now().isoformat()
                )
            
            # Check permissions
            can_execute, perm_error = self.permission_manager.can_execute_query(user, query)
            if not can_execute:
                return QueryResult(
                    success=False,
                    error=f"Permission denied: {perm_error}",
                    user=user,
                    timestamp=datetime.now().isoformat()
                )
            
            return await self._execute_query(query, params, True, user)
        
        @self.mcp.tool()
        async def select_table_data(
            table: str,
            columns: Optional[List[str]] = None,
            where_conditions: Optional[Dict[str, Any]] = None,
            order_by: Optional[str] = None,
            limit: Optional[int] = None,
            offset: Optional[int] = None,
            user: str = "anonymous"
        ) -> QueryResult:
            """
            Select data from a table with security validation
            
            Args:
                table: Table name to select from
                columns: List of columns to select (None for all)
                where_conditions: Dictionary of column=value conditions
                order_by: Column to order by
                limit: Maximum number of rows to return
                offset: Number of rows to skip
                user: GitHub username for permission checking
            
            Returns:
                QueryResult with selected data
            """
            # Check read permissions
            user_perm = self.permission_manager.get_user_permission(user)
            if not user_perm or not user_perm.can_read:
                return QueryResult(
                    success=False,
                    error="Read permissions required",
                    user=user,
                    timestamp=datetime.now().isoformat()
                )
            
            # Validate table name
            if not self.security_validator.validate_table_name(table):
                return QueryResult(
                    success=False,
                    error="Invalid table name",
                    user=user,
                    timestamp=datetime.now().isoformat()
                )
            
            return await self._select_data(table, columns, where_conditions, order_by, limit, offset, user)
        
        @self.mcp.tool()
        async def insert_table_data(
            table: str,
            data: Union[Dict[str, Any], List[Dict[str, Any]]],
            on_duplicate_key_update: bool = False,
            user: str = "anonymous"
        ) -> QueryResult:
            """
            Insert data into a table with security validation
            
            Args:
                table: Table name to insert into
                data: Dictionary or list of dictionaries with column=value pairs
                on_duplicate_key_update: Whether to update on duplicate key
                user: GitHub username for permission checking
            
            Returns:
                QueryResult with insertion details
            """
            # Check write permissions
            user_perm = self.permission_manager.get_user_permission(user)
            if not user_perm or not user_perm.can_write:
                return QueryResult(
                    success=False,
                    error="Write permissions required",
                    user=user,
                    timestamp=datetime.now().isoformat()
                )
            
            # Validate table name
            if not self.security_validator.validate_table_name(table):
                return QueryResult(
                    success=False,
                    error="Invalid table name",
                    user=user,
                    timestamp=datetime.now().isoformat()
                )
            
            return await self._insert_data(table, data, on_duplicate_key_update, user)
        
        @self.mcp.tool()
        async def update_table_data(
            table: str,
            data: Dict[str, Any],
            where_conditions: Dict[str, Any],
            user: str = "anonymous"
        ) -> QueryResult:
            """
            Update data in a table with security validation
            
            Args:
                table: Table name to update
                data: Dictionary of column=value pairs to update
                where_conditions: Dictionary of column=value conditions
                user: GitHub username for permission checking
            
            Returns:
                QueryResult with update details
            """
            # Check write permissions
            user_perm = self.permission_manager.get_user_permission(user)
            if not user_perm or not user_perm.can_write:
                return QueryResult(
                    success=False,
                    error="Write permissions required",
                    user=user,
                    timestamp=datetime.now().isoformat()
                )
            
            # Validate table name
            if not self.security_validator.validate_table_name(table):
                return QueryResult(
                    success=False,
                    error="Invalid table name",
                    user=user,
                    timestamp=datetime.now().isoformat()
                )
            
            return await self._update_data(table, data, where_conditions, user)
        
        @self.mcp.tool()
        async def delete_table_data(
            table: str,
            where_conditions: Dict[str, Any],
            user: str = "anonymous"
        ) -> QueryResult:
            """
            Delete data from a table with security validation
            
            Args:
                table: Table name to delete from
                where_conditions: Dictionary of column=value conditions
                user: GitHub username for permission checking
            
            Returns:
                QueryResult with deletion details
            """
            # Check write permissions
            user_perm = self.permission_manager.get_user_permission(user)
            if not user_perm or not user_perm.can_write:
                return QueryResult(
                    success=False,
                    error="Write permissions required",
                    user=user,
                    timestamp=datetime.now().isoformat()
                )
            
            # Validate table name
            if not self.security_validator.validate_table_name(table):
                return QueryResult(
                    success=False,
                    error="Invalid table name",
                    user=user,
                    timestamp=datetime.now().isoformat()
                )
            
            return await self._delete_data(table, where_conditions, user)
        
        @self.mcp.tool()
        async def discover_database_schema(
            user: str = "anonymous"
        ) -> QueryResult:
            """
            Discover database schema - tables and columns
            
            Args:
                user: GitHub username for permission checking
            
            Returns:
                QueryResult with schema information
            """
            # Check read permissions
            user_perm = self.permission_manager.get_user_permission(user)
            if not user_perm or not user_perm.can_read:
                return QueryResult(
                    success=False,
                    error="Read permissions required",
                    user=user,
                    timestamp=datetime.now().isoformat()
                )
            
            return await self._discover_schema(user)
        
        @self.mcp.tool()
        async def get_table_structure(
            table: str,
            user: str = "anonymous"
        ) -> QueryResult:
            """
            Get detailed table structure information
            
            Args:
                table: Table name to get structure for
                user: GitHub username for permission checking
            
            Returns:
                QueryResult with table structure details
            """
            # Check read permissions
            user_perm = self.permission_manager.get_user_permission(user)
            if not user_perm or not user_perm.can_read:
                return QueryResult(
                    success=False,
                    error="Read permissions required",
                    user=user,
                    timestamp=datetime.now().isoformat()
                )
            
            # Validate table name
            if not self.security_validator.validate_table_name(table):
                return QueryResult(
                    success=False,
                    error="Invalid table name",
                    user=user,
                    timestamp=datetime.now().isoformat()
                )
            
            return await self._get_table_structure(table, user)
        
        @self.mcp.tool()
        async def create_table_secure(
            table: str,
            columns: Dict[str, str],
            primary_key: Optional[str] = None,
            indexes: Optional[List[str]] = None,
            engine: str = "InnoDB",
            charset: str = "utf8mb4",
            user: str = "anonymous"
        ) -> QueryResult:
            """
            Create a new table with admin permissions
            
            Args:
                table: Table name to create
                columns: Dictionary of column_name=column_definition
                primary_key: Primary key column name
                indexes: List of columns to create indexes on
                engine: MySQL engine to use
                charset: Character set for the table
                user: GitHub username for permission checking
            
            Returns:
                QueryResult with creation details
            """
            # Check admin permissions
            user_perm = self.permission_manager.get_user_permission(user)
            if not user_perm or not user_perm.can_admin:
                return QueryResult(
                    success=False,
                    error="Admin permissions required",
                    user=user,
                    timestamp=datetime.now().isoformat()
                )
            
            # Validate table name
            if not self.security_validator.validate_table_name(table):
                return QueryResult(
                    success=False,
                    error="Invalid table name",
                    user=user,
                    timestamp=datetime.now().isoformat()
                )
            
            return await self._create_table(table, columns, primary_key, indexes, engine, charset, user)
        
        @self.mcp.tool()
        async def get_database_statistics(
            user: str = "anonymous"
        ) -> QueryResult:
            """
            Get comprehensive database statistics
            
            Args:
                user: GitHub username for permission checking
            
            Returns:
                QueryResult with database statistics
            """
            # Check read permissions
            user_perm = self.permission_manager.get_user_permission(user)
            if not user_perm or not user_perm.can_read:
                return QueryResult(
                    success=False,
                    error="Read permissions required",
                    user=user,
                    timestamp=datetime.now().isoformat()
                )
            
            return await self._get_database_stats(user)
        
        @self.mcp.tool()
        async def check_user_permissions(
            user: str = "anonymous"
        ) -> QueryResult:
            """
            Check current user permissions
            
            Args:
                user: GitHub username to check permissions for
            
            Returns:
                QueryResult with user permission details
            """
            user_perm = self.permission_manager.get_user_permission(user)
            if not user_perm:
                return QueryResult(
                    success=False,
                    error="User not found or no permissions",
                    user=user,
                    timestamp=datetime.now().isoformat()
                )
            
            return QueryResult(
                success=True,
                data=[{
                    "username": user_perm.username,
                    "role": user_perm.role,
                    "can_read": user_perm.can_read,
                    "can_write": user_perm.can_write,
                    "can_admin": user_perm.can_admin
                }],
                user=user,
                timestamp=datetime.now().isoformat()
            )
    
    def _setup_resources(self):
        """Setup MCP resources"""
        
        @self.mcp.resource("mysql://connection-status")
        async def get_connection_status():
            """Get current database connection status"""
            if self.pool:
                return {
                    "connected": True,
                    "pool_size": self.pool.size,
                    "free_connections": self.pool.freesize,
                    "config": {
                        "host": self.config.host,
                        "port": self.config.port,
                        "database": self.config.database,
                        "user": self.config.user,
                        "ssl_mode": self.config.ssl_mode,
                        "cloudflare_enabled": bool(self.config.cloudflare_account_id)
                    }
                }
            return {"connected": False}
        
        @self.mcp.resource("mysql://database-info")
        async def get_database_info():
            """Get database information"""
            if not self.pool:
                return {"error": "Not connected to database"}
            
            try:
                async with self.pool.acquire() as conn:
                    async with conn.cursor() as cursor:
                        await cursor.execute("SELECT VERSION()")
                        version = await cursor.fetchone()
                        
                        await cursor.execute("SELECT DATABASE()")
                        database = await cursor.fetchone()
                        
                        await cursor.execute("SHOW VARIABLES LIKE 'character_set_database'")
                        charset = await cursor.fetchone()
                        
                        await cursor.execute("SHOW VARIABLES LIKE 'innodb_version'")
                        innodb = await cursor.fetchone()
                        
                        return {
                            "version": version[0] if version else "Unknown",
                            "database": database[0] if database else "Unknown",
                            "charset": charset[1] if charset else "Unknown",
                            "innodb_version": innodb[1] if innodb else "Unknown",
                            "connection_time": datetime.now().isoformat(),
                            "cloudflare_optimized": True
                        }
            except Exception as e:
                return {"error": str(e)}
        
        @self.mcp.resource("mysql://security-config")
        async def get_security_config():
            """Get security configuration"""
            return {
                "sql_injection_protection": True,
                "role_based_access": True,
                "monitoring_enabled": self.config.enable_monitoring,
                "admin_users": len(self.config.github_admins),
                "writer_users": len(self.config.github_writers),
                "reader_users": len(self.config.github_readers),
                "cloudflare_workers_ready": bool(self.config.cloudflare_account_id)
            }
    
    def _setup_prompts(self):
        """Setup MCP prompts"""
        
        @self.mcp.prompt()
        async def database_query_assistant():
            """
            Database Query Assistant
            
            Help users construct safe and efficient database queries with proper permissions.
            """
            return """
            I'm a database query assistant that helps you interact with MySQL databases safely.
            
            Available Operations:
            - SELECT: Read data from tables
            - INSERT: Add new data to tables
            - UPDATE: Modify existing data
            - DELETE: Remove data from tables
            - Schema Discovery: Explore database structure
            
            Security Features:
            - SQL injection protection
            - Role-based access control
            - Query validation
            - Audit logging
            
            Please provide your GitHub username for proper permission checking.
            """
        
        @self.mcp.prompt()
        async def cloudflare_optimization_guide():
            """
            Cloudflare Workers Optimization Guide
            
            Best practices for running this MCP server on Cloudflare Workers.
            """
            return """
            Cloudflare Workers Optimization Guide:
            
            1. Connection Pooling: Use persistent connections for better performance
            2. Caching: Implement query result caching where appropriate
            3. Edge Computing: Leverage Cloudflare's global network
            4. Security: Built-in DDoS protection and WAF
            5. Monitoring: Integrated with Sentry for error tracking
            
            Configuration:
            - Set CLOUDFLARE_ACCOUNT_ID environment variable
            - Configure SSL_MODE to REQUIRED for secure connections
            - Use connection pooling for better resource management
            """
    
    async def _execute_query(
        self,
        query: str,
        params: Optional[List[Any]] = None,
        fetch_results: bool = True,
        user: str = "anonymous"
    ) -> QueryResult:
        """Execute a query with enhanced logging and monitoring"""
        if not self.pool:
            return QueryResult(
                success=False,
                error="Not connected to database",
                user=user,
                timestamp=datetime.now().isoformat()
            )
        
        start_time = datetime.now()
        query_hash = hashlib.md5(query.encode()).hexdigest()
        
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(query, params)
                    
                    if fetch_results and cursor.description:
                        data = await cursor.fetchall()
                        data = [self._serialize_row(row) for row in data]
                    else:
                        data = None
                    
                    execution_time = (datetime.now() - start_time).total_seconds()
                    
                    # Log successful query
                    logger.info(f"Query executed successfully by {user}: {query_hash}")
                    
                    return QueryResult(
                        success=True,
                        data=data,
                        affected_rows=cursor.rowcount,
                        last_insert_id=cursor.lastrowid,
                        execution_time=execution_time,
                        query_hash=query_hash,
                        timestamp=datetime.now().isoformat(),
                        user=user
                    )
        
        except Exception as e:
            execution_time = (datetime.now() - start_time).total_seconds()
            error_msg = str(e)
            
            # Log error
            logger.error(f"Query execution error by {user}: {error_msg}")
            
            # Report to Sentry if enabled
            if self.config.enable_monitoring:
                sentry_sdk.capture_exception(e)
            
            return QueryResult(
                success=False,
                error=error_msg,
                execution_time=execution_time,
                query_hash=query_hash,
                timestamp=datetime.now().isoformat(),
                user=user
            )
    
    async def _select_data(
        self,
        table: str,
        columns: Optional[List[str]] = None,
        where_conditions: Optional[Dict[str, Any]] = None,
        order_by: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        user: str = "anonymous"
    ) -> QueryResult:
        """Select data with security validation"""
        try:
            # Sanitize table name
            table = self.security_validator.sanitize_identifier(table)
            
            # Build SELECT query
            if columns:
                # Sanitize column names
                safe_columns = [self.security_validator.sanitize_identifier(col) for col in columns]
                cols = ", ".join([f"`{col}`" for col in safe_columns])
            else:
                cols = "*"
            
            query = f"SELECT {cols} FROM `{table}`"
            params = []
            
            # Add WHERE conditions
            if where_conditions:
                where_parts = []
                for key, value in where_conditions.items():
                    safe_key = self.security_validator.sanitize_identifier(key)
                    where_parts.append(f"`{safe_key}` = %s")
                    params.append(value)
                query += f" WHERE {' AND '.join(where_parts)}"
            
            # Add ORDER BY
            if order_by:
                safe_order = self.security_validator.sanitize_identifier(order_by)
                query += f" ORDER BY `{safe_order}`"
            
            # Add LIMIT and OFFSET
            if limit:
                query += f" LIMIT {int(limit)}"
                if offset:
                    query += f" OFFSET {int(offset)}"
            
            return await self._execute_query(query, params, True, user)
        
        except Exception as e:
            logger.error(f"Select error: {e}")
            return QueryResult(
                success=False,
                error=str(e),
                user=user,
                timestamp=datetime.now().isoformat()
            )
    
    async def _insert_data(
        self,
        table: str,
        data: Union[Dict[str, Any], List[Dict[str, Any]]],
        on_duplicate_key_update: bool = False,
        user: str = "anonymous"
    ) -> QueryResult:
        """Insert data with security validation"""
        try:
            # Sanitize table name
            table = self.security_validator.sanitize_identifier(table)
            
            # Handle single row or multiple rows
            if isinstance(data, dict):
                data = [data]
            
            if not data:
                return QueryResult(
                    success=False,
                    error="No data to insert",
                    user=user,
                    timestamp=datetime.now().isoformat()
                )
            
            # Get and sanitize column names from first row
            columns = [self.security_validator.sanitize_identifier(col) for col in data[0].keys()]
            placeholders = ", ".join(["%s"] * len(columns))
            column_names = ", ".join([f"`{col}`" for col in columns])
            
            query = f"INSERT INTO `{table}` ({column_names}) VALUES ({placeholders})"
            
            # Add ON DUPLICATE KEY UPDATE if requested
            if on_duplicate_key_update:
                update_parts = [f"`{col}` = VALUES(`{col}`)" for col in columns]
                query += f" ON DUPLICATE KEY UPDATE {', '.join(update_parts)}"
            
            # Prepare parameters
            if len(data) == 1:
                params = [data[0].get(col) for col in data[0].keys()]
                return await self._execute_query(query, params, False, user)
            else:
                # For multiple rows, use executemany
                params_list = []
                for row in data:
                    row_params = [row.get(col) for col in columns]
                    params_list.append(row_params)
                return await self._execute_many(query, params_list, user)
        
        except Exception as e:
            logger.error(f"Insert error: {e}")
            return QueryResult(
                success=False,
                error=str(e),
                user=user,
                timestamp=datetime.now().isoformat()
            )
    
    async def _update_data(
        self,
        table: str,
        data: Dict[str, Any],
        where_conditions: Dict[str, Any],
        user: str = "anonymous"
    ) -> QueryResult:
        """Update data with security validation"""
        try:
            # Sanitize table name
            table = self.security_validator.sanitize_identifier(table)
            
            if not data:
                return QueryResult(
                    success=False,
                    error="No data to update",
                    user=user,
                    timestamp=datetime.now().isoformat()
                )
            
            if not where_conditions:
                return QueryResult(
                    success=False,
                    error="WHERE conditions required for UPDATE",
                    user=user,
                    timestamp=datetime.now().isoformat()
                )
            
            # Build UPDATE query
            set_parts = []
            params = []
            
            for key, value in data.items():
                safe_key = self.security_validator.sanitize_identifier(key)
                set_parts.append(f"`{safe_key}` = %s")
                params.append(value)
            
            where_parts = []
            for key, value in where_conditions.items():
                safe_key = self.security_validator.sanitize_identifier(key)
                where_parts.append(f"`{safe_key}` = %s")
                params.append(value)
            
            query = f"UPDATE `{table}` SET {', '.join(set_parts)} WHERE {' AND '.join(where_parts)}"
            
            return await self._execute_query(query, params, False, user)
        
        except Exception as e:
            logger.error(f"Update error: {e}")
            return QueryResult(
                success=False,
                error=str(e),
                user=user,
                timestamp=datetime.now().isoformat()
            )
    
    async def _delete_data(
        self,
        table: str,
        where_conditions: Dict[str, Any],
        user: str = "anonymous"
    ) -> QueryResult:
        """Delete data with security validation"""
        try:
            # Sanitize table name
            table = self.security_validator.sanitize_identifier(table)
            
            if not where_conditions:
                return QueryResult(
                    success=False,
                    error="WHERE conditions required for DELETE",
                    user=user,
                    timestamp=datetime.now().isoformat()
                )
            
            # Build DELETE query
            where_parts = []
            params = []
            
            for key, value in where_conditions.items():
                safe_key = self.security_validator.sanitize_identifier(key)
                where_parts.append(f"`{safe_key}` = %s")
                params.append(value)
            
            query = f"DELETE FROM `{table}` WHERE {' AND '.join(where_parts)}"
            
            return await self._execute_query(query, params, False, user)
        
        except Exception as e:
            logger.error(f"Delete error: {e}")
            return QueryResult(
                success=False,
                error=str(e),
                user=user,
                timestamp=datetime.now().isoformat()
            )
    
    async def _discover_schema(self, user: str = "anonymous") -> QueryResult:
        """Discover database schema"""
        try:
            query = """
            SELECT 
                table_name,
                column_name,
                data_type,
                is_nullable,
                column_default,
                column_key,
                extra,
                column_comment
            FROM information_schema.columns 
            WHERE table_schema = DATABASE()
            ORDER BY table_name, ordinal_position
            """
            
            return await self._execute_query(query, None, True, user)
        
        except Exception as e:
            logger.error(f"Schema discovery error: {e}")
            return QueryResult(
                success=False,
                error=str(e),
                user=user,
                timestamp=datetime.now().isoformat()
            )
    
    async def _get_table_structure(self, table: str, user: str = "anonymous") -> QueryResult:
        """Get detailed table structure"""
        try:
            # Sanitize table name
            table = self.security_validator.sanitize_identifier(table)
            
            query = f"DESCRIBE `{table}`"
            return await self._execute_query(query, None, True, user)
        
        except Exception as e:
            logger.error(f"Get table structure error: {e}")
            return QueryResult(
                success=False,
                error=str(e),
                user=user,
                timestamp=datetime.now().isoformat()
            )
    
    async def _create_table(
        self,
        table: str,
        columns: Dict[str, str],
        primary_key: Optional[str] = None,
        indexes: Optional[List[str]] = None,
        engine: str = "InnoDB",
        charset: str = "utf8mb4",
        user: str = "anonymous"
    ) -> QueryResult:
        """Create a new table with security validation"""
        try:
            # Sanitize table name
            table = self.security_validator.sanitize_identifier(table)
            
            if not columns:
                return QueryResult(
                    success=False,
                    error="Column definitions required",
                    user=user,
                    timestamp=datetime.now().isoformat()
                )
            
            # Build CREATE TABLE query
            column_defs = []
            for col_name, col_def in columns.items():
                safe_col_name = self.security_validator.sanitize_identifier(col_name)
                # Basic validation of column definition
                if not re.match(r'^[a-zA-Z0-9_\s\(\),]+$', col_def):
                    return QueryResult(
                        success=False,
                        error=f"Invalid column definition for {col_name}",
                        user=user,
                        timestamp=datetime.now().isoformat()
                    )
                column_defs.append(f"`{safe_col_name}` {col_def}")
            
            if primary_key:
                safe_pk = self.security_validator.sanitize_identifier(primary_key)
                column_defs.append(f"PRIMARY KEY (`{safe_pk}`)")
            
            if indexes:
                for index_col in indexes:
                    safe_index = self.security_validator.sanitize_identifier(index_col)
                    column_defs.append(f"INDEX (`{safe_index}`)")
            
            query = f"""
            CREATE TABLE `{table}` (
                {', '.join(column_defs)}
            ) ENGINE={engine} DEFAULT CHARSET={charset}
            """
            
            return await self._execute_query(query, None, False, user)
        
        except Exception as e:
            logger.error(f"Create table error: {e}")
            return QueryResult(
                success=False,
                error=str(e),
                user=user,
                timestamp=datetime.now().isoformat()
            )
    
    async def _get_database_stats(self, user: str = "anonymous") -> QueryResult:
        """Get comprehensive database statistics"""
        try:
            query = """
            SELECT 
                COUNT(*) as table_count,
                SUM(table_rows) as total_rows,
                SUM(data_length + index_length) as total_size,
                SUM(data_length) as data_size,
                SUM(index_length) as index_size,
                AVG(avg_row_length) as avg_row_length
            FROM information_schema.tables 
            WHERE table_schema = DATABASE()
            """
            
            return await self._execute_query(query, None, True, user)
        
        except Exception as e:
            logger.error(f"Get database stats error: {e}")
            return QueryResult(
                success=False,
                error=str(e),
                user=user,
                timestamp=datetime.now().isoformat()
            )
    
    async def _execute_many(self, query: str, params_list: List[List[Any]], user: str = "anonymous") -> QueryResult:
        """Execute query with multiple parameter sets"""
        if not self.pool:
            return QueryResult(
                success=False,
                error="Not connected to database",
                user=user,
                timestamp=datetime.now().isoformat()
            )
        
        start_time = datetime.now()
        query_hash = hashlib.md5(query.encode()).hexdigest()
        
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.executemany(query, params_list)
                    
                    execution_time = (datetime.now() - start_time).total_seconds()
                    
                    # Log successful query
                    logger.info(f"Batch query executed successfully by {user}: {query_hash}")
                    
                    return QueryResult(
                        success=True,
                        affected_rows=cursor.rowcount,
                        last_insert_id=cursor.lastrowid,
                        execution_time=execution_time,
                        query_hash=query_hash,
                        timestamp=datetime.now().isoformat(),
                        user=user
                    )
        
        except Exception as e:
            execution_time = (datetime.now() - start_time).total_seconds()
            error_msg = str(e)
            
            # Log error
            logger.error(f"Batch query execution error by {user}: {error_msg}")
            
            # Report to Sentry if enabled
            if self.config.enable_monitoring:
                sentry_sdk.capture_exception(e)
            
            return QueryResult(
                success=False,
                error=error_msg,
                execution_time=execution_time,
                query_hash=query_hash,
                timestamp=datetime.now().isoformat(),
                user=user
            )
    
    def _serialize_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Serialize a database row for JSON output"""
        serialized = {}
        for key, value in row.items():
            if isinstance(value, (datetime, date)):
                serialized[key] = value.isoformat()
            elif isinstance(value, Decimal):
                serialized[key] = float(value)
            elif isinstance(value, bytes):
                serialized[key] = value.decode('utf-8', errors='replace')
            else:
                serialized[key] = value
        return serialized
    
    async def connect(self):
        """Connect to the MySQL database with Cloudflare optimization"""
        try:
            # SSL configuration for Cloudflare
            ssl_config = None
            if self.config.ssl_mode == "REQUIRED":
                ssl_config = {"ssl": True}
            
            self.pool = await aiomysql.create_pool(
                host=self.config.host,
                port=self.config.port,
                user=self.config.user,
                password=self.config.password,
                db=self.config.database,
                charset=self.config.charset,
                autocommit=self.config.autocommit,
                minsize=1,
                maxsize=self.config.pool_size,
                **ssl_config if ssl_config else {}
            )
            
            logger.info(f"Connected to MySQL database: {self.config.database}")
            
            # Test connection
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("SELECT 1")
                    result = await cursor.fetchone()
                    if result[0] != 1:
                        raise Exception("Connection test failed")
            
            logger.info("Database connection test successful")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to MySQL: {e}")
            return False
    
    async def disconnect(self):
        """Disconnect from the MySQL database"""
        if self.pool:
            self.pool.close()
            await self.pool.wait_closed()
            logger.info("Disconnected from MySQL database")
    
    async def run_server(self):
        """Run the MCP server with lifespan management"""
        try:
            # Connect to database
            if not await self.connect():
                raise Exception("Failed to connect to database")
            
            logger.info("Starting Cloudflare MySQL MCP Server...")
            
            # Run the FastMCP server
            await self.mcp.run(transport="stdio")
        
        except KeyboardInterrupt:
            logger.info("Server shutdown requested")
        except Exception as e:
            logger.error(f"Server error: {e}")
            if self.config.enable_monitoring:
                sentry_sdk.capture_exception(e)
        finally:
            await self.disconnect()

async def main():
    """Main function to run the MCP server"""
    # Load configuration from environment variables
    config = DatabaseConfig(
        host=os.getenv("MYSQL_HOST", "localhost"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        database=os.getenv("MYSQL_DATABASE", "test"),
        charset=os.getenv("MYSQL_CHARSET", "utf8mb4"),
        autocommit=os.getenv("MYSQL_AUTOCOMMIT", "true").lower() == "true",
        pool_size=int(os.getenv("MYSQL_POOL_SIZE", "5")),
        ssl_mode=os.getenv("MYSQL_SSL_MODE", "REQUIRED"),
        
        # Cloudflare configuration
        cloudflare_account_id=os.getenv("CLOUDFLARE_ACCOUNT_ID"),
        cloudflare_token=os.getenv("CLOUDFLARE_TOKEN"),
        
        # Role-based access control
        github_admins=os.getenv("GITHUB_ADMINS", "").split(",") if os.getenv("GITHUB_ADMINS") else [],
        github_writers=os.getenv("GITHUB_WRITERS", "").split(",") if os.getenv("GITHUB_WRITERS") else [],
        github_readers=os.getenv("GITHUB_READERS", "").split(",") if os.getenv("GITHUB_READERS") else [],
        
        # Monitoring
        sentry_dsn=os.getenv("SENTRY_DSN"),
        enable_monitoring=os.getenv("ENABLE_MONITORING", "false").lower() == "true"
    )
    
    # Create and run server
    server = CloudflareMySQLMCPServer(config)
    await server.run_server()

if __name__ == "__main__":
    asyncio.run(main())
