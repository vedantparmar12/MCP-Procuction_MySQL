from typing import List, Optional
from pydantic import Field, field_validator, ConfigDict
from pydantic_settings import BaseSettings
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )
    
    github_client_id: str = Field(...)
    github_client_secret: str = Field(...)
    cookie_secret_key: str = Field(...)
    mysql_host: str = Field(default="127.0.0.1")
    mysql_port: int = Field(default=3306)
    mysql_user: str = Field(...)
    mysql_password: str = Field(...)
    mysql_database: str = Field(...)
    mysql_ssl_ca: Optional[str] = Field(default=None)
    
    mcp_server_name: str = Field(default="MySQL MCP Server")
    mcp_server_version: str = Field(default="1.0.0")
    mcp_server_port: int = Field(default=8000)
    
    sentry_dsn: Optional[str] = Field(default=None)
    environment: str = Field(default="development")
    
    allowed_origins: List[str] = Field(
        default=["http://localhost:*", "https://claude.ai"]
    )
    session_lifetime_minutes: int = Field(default=60)
    
    log_level: str = Field(default="INFO")
    log_format: str = Field(default="json")
    
    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_allowed_origins(cls, v):
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v
    
    @field_validator("mysql_ssl_ca", mode="before")
    @classmethod
    def validate_ssl_ca(cls, v):
        # If SSL CA is empty string, return None
        if v == "" or v is None:
            return None
        # If it's the auto-populated certifi path, ignore it
        if v and "certifi" in str(v):
            return None
        # Only return the value if it's a valid, intentional SSL CA path
        return v
    
    @property
    def mysql_connection_url(self) -> str:
        return f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
    
    @property
    def mysql_connection_params(self) -> dict:
        params = {
            "host": self.mysql_host,
            "port": self.mysql_port,
            "user": self.mysql_user,
            "password": self.mysql_password,
            "database": self.mysql_database,
            "autocommit": False,
            "charset": "utf8mb4",
            "collation": "utf8mb4_unicode_ci"
        }
        
        if self.mysql_ssl_ca:
            params["ssl"] = {
                "ca": self.mysql_ssl_ca,
                "verify_cert": True,
                "verify_identity": True
            }
        
        return params


ALLOWED_USERNAMES = {
    'vedantparmar12'
}

READ_OPERATIONS = {
    'select', 'show', 'describe', 'desc', 'explain'
}

WRITE_OPERATIONS = {
    'insert', 'update', 'delete', 'replace'
}

DDL_OPERATIONS = {
    'create', 'alter', 'drop', 'truncate', 'rename'
}

PROCEDURE_OPERATIONS = {
    'call', 'execute'
}

TRANSACTION_OPERATIONS = {
    'begin', 'start', 'commit', 'rollback', 'savepoint'
}

DANGEROUS_SQL_PATTERNS = [
    r';\s*(drop|delete|truncate|alter)\s+',
    r';\s*delete\s+.*\s+where\s+1\s*=\s*1',
    r'--.*drop\s+',
    r'/\*.*\*/\s*;\s*drop',
    r'(mysql|information_schema|performance_schema|sys)\.(user|db|tables_priv|columns_priv)',
    r'(into\s+outfile|load_file|load\s+data)',
    r'(grant|revoke|create\s+user|drop\s+user|alter\s+user)',
]

settings = Settings()


def is_write_access_allowed(github_username: str) -> bool:
    return github_username.lower() in {username.lower() for username in ALLOWED_USERNAMES}


def get_operation_type(sql: str) -> str:
    sql_lower = sql.strip().lower()
    first_word = sql_lower.split()[0] if sql_lower else ""
    
    if first_word in READ_OPERATIONS:
        return "read"
    elif first_word in WRITE_OPERATIONS:
        return "write"
    elif first_word in DDL_OPERATIONS:
        return "ddl"
    elif first_word in PROCEDURE_OPERATIONS:
        return "procedure"
    elif first_word in TRANSACTION_OPERATIONS:
        return "transaction"
    else:
        return "unknown"