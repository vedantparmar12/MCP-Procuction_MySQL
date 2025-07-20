import asyncio
import ssl
import sys
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, Optional

import aiomysql
import structlog
from aiomysql import Connection, Pool

from ..config import settings

logger = structlog.get_logger()

# Windows-specific event loop policy for aiomysql
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Global connection pool
_pool: Optional[Pool] = None
_pool_lock = asyncio.Lock()


async def get_pool() -> Pool:
    """Get or create the database connection pool"""
    global _pool

    async with _pool_lock:
        if _pool is None:
            logger.info("Creating MySQL connection pool")
            logger.info(f"Connection params: host={settings.mysql_host}, port={settings.mysql_port}, user={settings.mysql_user}, db={settings.mysql_database}")

            # Build connection parameters
            connect_params = {
                "host": settings.mysql_host,
                "port": settings.mysql_port,
                "user": settings.mysql_user,
                "password": settings.mysql_password,
                "db": settings.mysql_database,
                "charset": "utf8mb4",
                "autocommit": False,
                "minsize": 1,
                "maxsize": 5,
                "echo": False,
                "pool_recycle": 3600,
                "connect_timeout": 30,  # Increased timeout
            }
            
            # For Windows localhost connections, explicitly set unix_socket to None
            if sys.platform == 'win32' and settings.mysql_host in ['localhost', '127.0.0.1']:
                connect_params["unix_socket"] = None

            # Handle SSL configuration
            if settings.mysql_ssl_ca:
                # Check if it's the auto-populated certifi path
                if "certifi" in str(settings.mysql_ssl_ca):
                    # Ignore certifi auto-populated path, disable SSL
                    connect_params["ssl"] = None
                    logger.info("Ignoring auto-populated certifi SSL CA, disabling SSL")
                else:
                    # Use the explicitly provided SSL CA
                    ssl_context = ssl.create_default_context(cafile=settings.mysql_ssl_ca)
                    ssl_context.check_hostname = True
                    ssl_context.verify_mode = ssl.CERT_REQUIRED
                    connect_params["ssl"] = ssl_context
            elif settings.mysql_host in ['localhost', '127.0.0.1']:
                # For localhost connections, disable SSL completely
                connect_params["ssl"] = None
                logger.info("SSL disabled for localhost connection")
            else:
                # For remote connections without CA, create permissive SSL context
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
                connect_params["ssl"] = ssl_context

            try:
                # Add retry logic for connection pool creation
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        _pool = await aiomysql.create_pool(**connect_params)
                        logger.info("MySQL connection pool created successfully")
                        break
                    except Exception as e:
                        if attempt < max_retries - 1:
                            logger.warning(f"Connection attempt {attempt + 1} failed: {e}, retrying...")
                            await asyncio.sleep(1)
                        else:
                            raise
            except Exception as e:
                logger.error("Failed to create MySQL connection pool", error=str(e))
                raise

        return _pool


async def close_pool() -> None:
    """Close the database connection pool"""
    global _pool

    async with _pool_lock:
        if _pool is not None:
            logger.info("Closing MySQL connection pool")
            _pool.close()
            await _pool.wait_closed()
            _pool = None
            logger.info("MySQL connection pool closed successfully")


@asynccontextmanager
async def get_connection() -> AsyncGenerator[Connection, None]:
    """Get a database connection from the pool"""
    pool = await get_pool()

    async with pool.acquire() as conn:
        try:
            yield conn
        except Exception as e:
            # Ensure we rollback on any error
            await conn.rollback()
            raise
        finally:
            # Commit any pending transaction if no error
            if not conn.closed:
                try:
                    await conn.commit()
                except:
                    pass


@asynccontextmanager
async def get_cursor(conn: Optional[Connection] = None) -> AsyncGenerator[aiomysql.Cursor, None]:
    """Get a database cursor, optionally using an existing connection"""
    if conn is not None:
        # Use provided connection
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            yield cursor
    else:
        # Get new connection from pool
        async with get_connection() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                yield cursor


class TransactionManager:
    """Manage database transactions with automatic rollback on errors"""

    def __init__(self):
        self.conn: Optional[Connection] = None
        self.savepoints: list[str] = []

    async def __aenter__(self) -> "TransactionManager":
        pool = await get_pool()
        self.conn = await pool.acquire()
        await self.conn.begin()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.conn and not self.conn.closed:
            try:
                if exc_type is None:
                    await self.conn.commit()
                else:
                    await self.conn.rollback()
            finally:
                self.conn.close()
                await self.conn.ensure_closed()

    async def create_savepoint(self, name: str) -> None:
        """Create a savepoint in the transaction"""
        if self.conn:
            async with self.conn.cursor() as cursor:
                await cursor.execute(f"SAVEPOINT {name}")
                self.savepoints.append(name)

    async def rollback_to_savepoint(self, name: str) -> None:
        """Rollback to a specific savepoint"""
        if self.conn and name in self.savepoints:
            async with self.conn.cursor() as cursor:
                await cursor.execute(f"ROLLBACK TO SAVEPOINT {name}")

    async def release_savepoint(self, name: str) -> None:
        """Release a savepoint"""
        if self.conn and name in self.savepoints:
            async with self.conn.cursor() as cursor:
                await cursor.execute(f"RELEASE SAVEPOINT {name}")
                self.savepoints.remove(name)

    def get_connection(self) -> Optional[Connection]:
        """Get the underlying connection"""
        return self.conn


async def test_connection() -> bool:
    """Test the database connection"""
    try:
        async with get_cursor() as cursor:
            await cursor.execute("SELECT 1")
            result = await cursor.fetchone()
            return result is not None
    except Exception as e:
        logger.error("Database connection test failed", error=str(e))
        return False


async def with_database(operation):
    """
    Execute a database operation with proper error handling and timing
    Matches the TypeScript withDatabase pattern
    """
    import time
    from ..database.security import format_database_error

    start_time = time.time()

    try:
        result = await operation()
        duration_ms = (time.time() - start_time) * 1000

        logger.info(
            "Database operation completed successfully",
            duration_ms=duration_ms
        )

        return result

    except Exception as error:
        duration_ms = (time.time() - start_time) * 1000

        logger.error(
            "Database operation failed",
            duration_ms=duration_ms,
            error=str(error)
        )

        # Format error for user display
        formatted_error = format_database_error(error)
        raise Exception(formatted_error) from error