"""
Basic tests for MySQL MCP Server
"""

import pytest
from src.config import Settings, is_write_access_allowed, get_operation_type
from src.types import UserProps, create_success_response, create_error_response
from src.database.security import validate_sql_query, sanitize_identifier


class TestConfig:
    """Test configuration and settings"""
    
    def test_settings_load(self):
        """Test that settings can be loaded"""
        settings = Settings(
            github_client_id="test_id",
            github_client_secret="test_secret",
            cookie_secret_key="test_key",
            mysql_user="test_user",
            mysql_password="test_pass",
            mysql_database="test_db"
        )
        
        assert settings.github_client_id == "test_id"
        assert settings.mysql_database == "test_db"
        assert settings.mcp_server_name == "MySQL MCP Server"
    
    def test_write_access_check(self):
        """Test write access checking"""
        assert is_write_access_allowed("coleam00") == True
        assert is_write_access_allowed("COLEAM00") == True  # Case insensitive
        assert is_write_access_allowed("randomuser") == False
    
    def test_operation_type_detection(self):
        """Test SQL operation type detection"""
        assert get_operation_type("SELECT * FROM users") == "read"
        assert get_operation_type("INSERT INTO users VALUES (1)") == "write"
        assert get_operation_type("UPDATE users SET name='test'") == "write"
        assert get_operation_type("DELETE FROM users") == "write"
        assert get_operation_type("CREATE TABLE test (id INT)") == "ddl"
        assert get_operation_type("DROP TABLE test") == "ddl"
        assert get_operation_type("BEGIN") == "transaction"
        assert get_operation_type("COMMIT") == "transaction"
        assert get_operation_type("CALL my_procedure()") == "procedure"


class TestTypes:
    """Test type definitions and response creators"""
    
    def test_user_props(self):
        """Test UserProps creation and methods"""
        user = UserProps(
            login="testuser",
            name="Test User",
            email="test@example.com",
            access_token="token123"
        )
        
        assert user.login == "testuser"
        assert user.has_write_access == False
        
        # Test with allowed user
        user2 = UserProps(
            login="coleam00",
            name="Cole AM",
            email="cole@example.com",
            access_token="token456"
        )
        assert user2.has_write_access == True
    
    def test_response_creators(self):
        """Test response creation functions"""
        # Success response
        success = create_success_response("Operation completed", {"count": 5})
        assert success["content"][0]["type"] == "text"
        assert "Success" in success["content"][0]["text"]
        assert "Operation completed" in success["content"][0]["text"]
        assert '"count": 5' in success["content"][0]["text"]
        
        # Error response
        error = create_error_response("Something went wrong", {"code": "ERR001"})
        assert error["content"][0]["type"] == "text"
        assert error["content"][0]["isError"] == True
        assert "Error" in error["content"][0]["text"]
        assert "Something went wrong" in error["content"][0]["text"]


class TestSecurity:
    """Test security functions"""
    
    def test_sql_validation(self):
        """Test SQL query validation"""
        # Valid queries
        result = validate_sql_query("SELECT * FROM users")
        assert result.is_valid == True
        assert result.operation_type == "read"
        
        # Invalid queries
        result = validate_sql_query("")
        assert result.is_valid == False
        
        # Dangerous patterns
        result = validate_sql_query("SELECT * FROM users; DROP TABLE users")
        assert result.is_valid == False
        
        result = validate_sql_query("SELECT * FROM users WHERE 1=1; DELETE FROM users WHERE 1=1")
        assert result.is_valid == False
    
    def test_identifier_sanitization(self):
        """Test identifier sanitization"""
        # Valid identifiers
        assert sanitize_identifier("users") == "users"
        assert sanitize_identifier("user_profiles") == "user_profiles"
        assert sanitize_identifier("Table123") == "Table123"
        
        # Invalid identifiers should raise
        with pytest.raises(ValueError):
            sanitize_identifier("")
        
        with pytest.raises(ValueError):
            sanitize_identifier("users; DROP TABLE")
        
        with pytest.raises(ValueError):
            sanitize_identifier("users`")


@pytest.mark.asyncio
class TestDatabaseConnection:
    """Test database connection (requires database)"""
    
    async def test_connection_pool(self):
        """Test that connection pool can be created"""
        # This test requires a real database connection
        # Skip if not available
        pytest.skip("Requires database connection")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])