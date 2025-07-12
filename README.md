# Cloudflare MySQL MCP Server

A comprehensive Model Context Protocol (MCP) server for MySQL database operations with Cloudflare Workers support, role-based access control, and security features.

## Features

- 🗄️ **Database Integration with Lifespan**: Direct MySQL database connection for all MCP tool calls
- 🛠️ **Modular, Single Purpose Tools**: Following best practices around MCP tools and their descriptions
- 🔐 **Role-Based Access**: GitHub username-based permissions for database write operations
- 📊 **Schema Discovery**: Automatic table and column information retrieval
- 🛡️ **SQL Injection Protection**: Built-in validation and sanitization
- 📈 **Monitoring**: Optional Sentry integration for production monitoring
- ☁️ **Cloud Native**: Powered by Cloudflare Workers for global scale

## Quick Start

### 1. Local Development Setup

#### Prerequisites
- Python 3.11 or higher
- MySQL server (local or remote)
- Git

#### Installation

1. **Clone and navigate to the project:**
   ```bash
   cd SQLMCP
   ```

2. **Create a virtual environment:**
   ```bash
   python -m venv venv
   # Windows
   venv\Scripts\activate
   # Linux/Mac
   source venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables:**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

5. **Run the server:**
   ```bash
   python main.py
   ```

### 2. Docker Setup (Recommended)

#### Using Docker Compose (includes MySQL)

1. **Start the entire stack:**
   ```bash
   docker-compose up -d
   ```

2. **View logs:**
   ```bash
   docker-compose logs -f mcp-server
   ```

3. **Stop the stack:**
   ```bash
   docker-compose down
   ```

#### Using Docker only

1. **Build the image:**
   ```bash
   docker build -t mysql-mcp-server .
   ```

2. **Run with environment variables:**
   ```bash
   docker run -d --name mysql-mcp-server \
     -e MYSQL_HOST=your-mysql-host \
     -e MYSQL_USER=your-user \
     -e MYSQL_PASSWORD=your-password \
     -e MYSQL_DATABASE=your-database \
     -e GITHUB_ADMINS=your-github-username \
     mysql-mcp-server
   ```

### 3. Claude Desktop Integration

1. **Locate your Claude Desktop config file:**
   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`
   - Mac: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - Linux: `~/.config/Claude/claude_desktop_config.json`

2. **Add the MCP server configuration:**
   ```json
   {
     "mcpServers": {
       "mysql-server": {
         "command": "python",
         "args": ["C:\\path\\to\\SQLMCP\\main.py"],
         "env": {
           "MYSQL_HOST": "localhost",
           "MYSQL_PORT": "3306",
           "MYSQL_USER": "root",
           "MYSQL_PASSWORD": "your_password",
           "MYSQL_DATABASE": "testdb",
           "GITHUB_ADMINS": "your_github_username"
         }
       }
     }
   }
   ```

3. **Restart Claude Desktop**

### 4. Cloudflare Workers Deployment

#### Prerequisites
- Cloudflare account
- Wrangler CLI installed (`npm install -g wrangler`)

#### Setup

1. **Login to Cloudflare:**
   ```bash
   wrangler login
   ```

2. **Configure wrangler.toml:**
   ```bash
   # Edit wrangler.toml with your configuration
   ```

3. **Set secrets:**
   ```bash
   wrangler secret put MYSQL_USER
   wrangler secret put MYSQL_PASSWORD
   wrangler secret put GITHUB_ADMINS
   wrangler secret put GITHUB_WRITERS
   wrangler secret put GITHUB_READERS
   ```

4. **Deploy:**
   ```bash
   wrangler deploy
   ```

## Configuration

### Environment Variables

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `MYSQL_HOST` | MySQL server hostname | `localhost` | Yes |
| `MYSQL_PORT` | MySQL server port | `3306` | No |
| `MYSQL_USER` | MySQL username | `root` | Yes |
| `MYSQL_PASSWORD` | MySQL password | - | Yes |
| `MYSQL_DATABASE` | MySQL database name | `test` | Yes |
| `MYSQL_CHARSET` | Character set | `utf8mb4` | No |
| `MYSQL_SSL_MODE` | SSL mode | `REQUIRED` | No |
| `GITHUB_ADMINS` | Comma-separated admin usernames | - | No |
| `GITHUB_WRITERS` | Comma-separated writer usernames | - | No |
| `GITHUB_READERS` | Comma-separated reader usernames | - | No |
| `SENTRY_DSN` | Sentry DSN for monitoring | - | No |
| `ENABLE_MONITORING` | Enable Sentry monitoring | `false` | No |

### Role-Based Access Control

The server supports three permission levels:

- **Admin**: Full database access (CREATE, DROP, ALTER, etc.)
- **Writer**: Read and write access (SELECT, INSERT, UPDATE, DELETE)
- **Reader**: Read-only access (SELECT)

Users are identified by their GitHub username passed as a parameter to tools.

## Available Tools

### Core Database Operations

#### `execute_safe_query`
Execute raw SQL queries with security validation.

```python
# Example usage in Claude
execute_safe_query(
    query="SELECT * FROM users WHERE id = %s",
    params=[1],
    user="your_github_username"
)
```

#### `select_table_data`
Select data from tables with filtering and pagination.

```python
select_table_data(
    table="users",
    columns=["id", "name", "email"],
    where_conditions={"status": "active"},
    limit=10,
    user="your_github_username"
)
```

#### `insert_table_data`
Insert single or multiple rows into tables.

```python
insert_table_data(
    table="users",
    data={"name": "John Doe", "email": "john@example.com"},
    user="your_github_username"
)
```

#### `update_table_data`
Update existing records in tables.

```python
update_table_data(
    table="users",
    data={"name": "Jane Doe"},
    where_conditions={"id": 1},
    user="your_github_username"
)
```

#### `delete_table_data`
Delete records from tables.

```python
delete_table_data(
    table="users",
    where_conditions={"id": 1},
    user="your_github_username"
)
```

### Schema Discovery

#### `discover_database_schema`
Get complete database schema information.

```python
discover_database_schema(user="your_github_username")
```

#### `get_table_structure`
Get detailed structure of a specific table.

```python
get_table_structure(
    table="users",
    user="your_github_username"
)
```

### Administrative Operations

#### `create_table_secure`
Create new tables (Admin only).

```python
create_table_secure(
    table="new_table",
    columns={
        "id": "INT AUTO_INCREMENT PRIMARY KEY",
        "name": "VARCHAR(100) NOT NULL",
        "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
    },
    user="your_github_username"
)
```

#### `get_database_statistics`
Get comprehensive database statistics.

```python
get_database_statistics(user="your_github_username")
```

#### `check_user_permissions`
Check current user's permissions.

```python
check_user_permissions(user="your_github_username")
```

## Security Features

### SQL Injection Protection

The server implements multiple layers of protection:

1. **Query Pattern Validation**: Blocks dangerous SQL patterns
2. **Parameter Sanitization**: Sanitizes all identifiers
3. **Prepared Statements**: Uses parameterized queries
4. **Input Validation**: Validates all user inputs

### Access Control

- **Role-based permissions** based on GitHub usernames
- **Operation-level security** (read/write/admin)
- **Audit logging** for all database operations
- **Query validation** before execution

### Monitoring & Logging

- **Sentry integration** for error tracking
- **Comprehensive logging** of all operations
- **Performance monitoring** with execution times
- **Security event tracking**

## Testing

### Test Database Setup

The included `init.sql` creates a test database with sample data:
- Users table with sample users
- Products table with sample products
- Orders table with sample orders

### Manual Testing

1. **Start the server with test database:**
   ```bash
   docker-compose up -d
   ```

2. **Test basic operations:**
   ```bash
   # Test schema discovery
   python -c "import asyncio; from main import *; asyncio.run(test_schema_discovery())"
   ```

## Troubleshooting

### Common Issues

1. **Connection Refused**
   - Check MySQL server is running
   - Verify connection parameters
   - Check firewall settings

2. **Permission Denied**
   - Verify GitHub username in environment variables
   - Check role assignments
   - Ensure user has required permissions

3. **SSL Connection Issues**
   - Set `MYSQL_SSL_MODE=DISABLED` for local development
   - Verify SSL certificates for production

### Debug Mode

Enable debug logging:
```bash
export PYTHONPATH=.
export DEBUG=true
python main.py
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

For issues and questions:
- Create an issue in the GitHub repository
- Check the troubleshooting section
- Review the logs for error messages

---

**Note**: This server is designed for production use with proper security measures. Always use strong passwords, enable SSL, and configure proper access controls in production environments.
#   M C P - P r o c u c t i o n _ M y S Q L 
 
 
