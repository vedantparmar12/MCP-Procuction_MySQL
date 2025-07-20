# MySQL MCP Server Documentation

## Overview

This is a production-ready MySQL MCP (Model Context Protocol) server that provides secure database access through MCP tools. The server includes authentication, monitoring, and comprehensive database operations.

## Quick Start

### Prerequisites

- Python 3.8+
- MySQL database server
- Claude Desktop application
- Git

### Installation

1. Clone and navigate to the project:
```bash
cd C:\Users\MCP-Procuction_MySQL
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables (create `.env` file):
```env
# Database Configuration
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=your_username
MYSQL_PASSWORD=your_password
MYSQL_DATABASE=your_database

# Security
SECRET_KEY=your-secret-key-here
ALLOWED_OPERATIONS=SELECT,INSERT,UPDATE,DELETE

# Optional: GitHub OAuth
GITHUB_CLIENT_ID=your_github_client_id
GITHUB_CLIENT_SECRET=your_github_client_secret

# Optional: Monitoring
SENTRY_DSN=your_sentry_dsn
```

### Running the Server

**Primary method:**
```bash
python -m src.main
```

**Alternative methods:**
```bash
# Using run script
python run_server.py

# Standalone mode
python mcp_standalone.py
```

## Claude Desktop Integration

### MCP Configuration for Claude Desktop

Add this configuration to your Claude Desktop MCP settings file. The configuration file is typically located at:

**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**Linux:** `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "mysql-mcp": {
      "command": "python",
      "args": ["src/server.py"],
      "cwd": "/path/to/your/MYSQL-Production"
    }
  }
}
```

### Setup Steps for Claude Desktop

1. **Install the MCP server** (follow installation steps above)
2. **Locate your Claude Desktop config file** using the paths above
3. **Add the MCP configuration** to the config file
4. **Update the `cwd` path** to match your actual installation directory
5. **Set up environment variables** in a `.env` file in your project directory
6. **Restart Claude Desktop** to load the new MCP server
7. **Verify connection** by asking Claude to list database tables

### Configuration Notes

- Replace `your_username`, `your_password`, etc. with your actual database credentials
- Update the `cwd` path to match your actual installation directory
- Ensure Python is available in your system PATH
- The server will be available as "mysql-mcp" in Claude Desktop

### Testing Claude Integration

Once configured, you can test the integration by asking Claude:
- "List all tables in my database"
- "Show me the structure of the users table"
- "Query the first 5 rows from my products table"

## Project Structure

```
MYSQL-Production/
├── src/
│   ├── main.py              # Main MCP server entry point
│   ├── server.py            # Core MCP server implementation
│   ├── config.py            # Configuration management
│   ├── models.py            # Data models
│   ├── auth/                # Authentication modules
│   │   ├── github_oauth.py  # GitHub OAuth integration
│   │   └── session.py       # Session management
│   ├── database/            # Database modules
│   │   ├── connection.py    # Database connection handling
│   │   ├── security.py      # Security and validation
│   │   └── utils.py         # Database utilities
│   ├── tools/               # MCP tools implementation
│   │   ├── basic_tools.py   # Basic database operations
│   │   ├── advanced_tools.py# Advanced database features
│   │   ├── write_tools.py   # Write operations
│   │   └── transaction_tools.py # Transaction management
│   └── monitoring/          # Monitoring and logging
│       └── sentry.py        # Sentry integration
├── tests/                   # Test suite
├── requirements.txt         # Python dependencies
├── pyproject.toml          # Project configuration
├── docker-compose.yml      # Docker setup
└── README.md               # Basic documentation
```

## Available MCP Tools

### Basic Operations
- `mysql-mcp:query_database` - Execute SELECT queries
- `mysql-mcp:list_tables` - List all database tables
- `mysql-mcp:describe_table` - Get table schema information

### Write Operations
- `mysql-mcp:execute_sql` - Execute INSERT, UPDATE, DELETE operations
- `mysql-mcp:create_table` - Create new tables

### Advanced Features
- Transaction management
- Query optimization
- Performance monitoring
- Security validation

## Configuration

### Environment Variables

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `MYSQL_HOST` | MySQL server host | Yes | localhost |
| `MYSQL_PORT` | MySQL server port | No | 3306 |
| `MYSQL_USER` | Database username | Yes | - |
| `MYSQL_PASSWORD` | Database password | Yes | - |
| `MYSQL_DATABASE` | Database name | Yes | - |
| `SECRET_KEY` | Security secret key | Yes | - |
| `ALLOWED_OPERATIONS` | Permitted SQL operations | No | SELECT,INSERT,UPDATE,DELETE |
| `MAX_CONNECTIONS` | Connection pool size | No | 10 |
| `QUERY_TIMEOUT` | Query timeout (seconds) | No | 30 |

### Security Features

- SQL injection prevention
- Query validation and sanitization
- Operation restrictions
- Connection pooling with limits
- Session-based authentication
- Optional GitHub OAuth integration

## Usage Examples

### Basic Query
```python
# Using MCP client
result = await client.call_tool("mysql-mcp:query_database", {
    "sql": "SELECT * FROM users LIMIT 10"
})
```

### Table Operations
```python
# List tables
tables = await client.call_tool("mysql-mcp:list_tables", {})

# Describe table structure
schema = await client.call_tool("mysql-mcp:describe_table", {
    "table": "users"
})
```

### Data Modification
```python
# Insert data
result = await client.call_tool("mysql-mcp:execute_sql", {
    "sql": "INSERT INTO users (name, email) VALUES ('John', 'john@example.com')"
})
```

## Testing

Run the test suite:
```bash
# Run all tests
python -m pytest tests/

# Run specific test
python test_mcp.py
```

## Docker Deployment

Use the provided Docker setup:
```bash
# Start services
docker-compose up -d

# View logs
docker-compose logs -f
```

## Monitoring and Debugging

### Logging
The server includes structured logging with different levels:
- INFO: General operations
- WARNING: Potential issues
- ERROR: Operation failures
- DEBUG: Detailed debugging info

### Sentry Integration
Configure Sentry for error tracking:
```env
SENTRY_DSN=your_sentry_dsn
SENTRY_ENVIRONMENT=production
```

### Debug Mode
Enable debug mode in `debug_settings.py`:
```python
DEBUG = True
LOG_LEVEL = "DEBUG"
```

## Troubleshooting

### Common Issues

1. **Connection Errors**
   - Verify MySQL server is running
   - Check credentials in `.env` file
   - Ensure network connectivity

2. **Permission Errors**
   - Verify database user permissions
   - Check `ALLOWED_OPERATIONS` configuration

3. **Performance Issues**
   - Monitor connection pool usage
   - Check query execution times
   - Review database indexes

### Debug Commands
```bash
# Test database connection
python -c "from src.database.connection import test_connection; test_connection()"

# Check MCP server status
python -c "from src.main import main; main()"
```

## Development

### Code Style
The project uses:
- Black for code formatting
- Ruff for linting
- MyPy for type checking

```bash
# Format code
black src/

# Run linting
ruff check src/

# Type checking
mypy src/
```

### Adding New Tools
1. Create tool function in appropriate module
2. Register in `src/tools/register_tools.py`
3. Add tests in `tests/`
4. Update documentation

## Production Deployment

See `DEPLOYMENT.md` for detailed production deployment instructions including:
- Environment setup
- Security hardening
- Performance optimization
- Monitoring configuration

## Security Considerations

- Always use parameterized queries
- Implement proper authentication
- Regularly update dependencies
- Monitor for suspicious activity
- Use SSL/TLS for connections
- Implement rate limiting

## Support

For issues and questions:
1. Check the troubleshooting section
2. Review logs for error details
3. Consult the existing README.md and DEPLOYMENT.md files
4. Check the test files for usage examples
