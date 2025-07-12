#!/usr/bin/env python3
"""
Setup script for Cloudflare MySQL MCP Server
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path

def run_command(cmd, check=True):
    """Run a command and return the result"""
    print(f"Running: {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"Error: {result.stderr}")
        sys.exit(1)
    return result

def check_python_version():
    """Check if Python version is compatible"""
    if sys.version_info < (3, 11):
        print("Error: Python 3.11 or higher is required")
        sys.exit(1)
    print(f"✓ Python {sys.version_info.major}.{sys.version_info.minor} detected")

def check_dependencies():
    """Check for required system dependencies"""
    dependencies = {
        "python": "python --version",
        "pip": "pip --version",
        "git": "git --version",
    }
    
    for dep, cmd in dependencies.items():
        try:
            run_command(cmd)
            print(f"✓ {dep} is available")
        except:
            print(f"✗ {dep} is not available")
            if dep == "git":
                print("  Git is optional but recommended")
            else:
                sys.exit(1)

def create_virtual_environment():
    """Create and activate virtual environment"""
    print("\n📦 Setting up virtual environment...")
    
    if not os.path.exists("venv"):
        run_command("python -m venv venv")
        print("✓ Virtual environment created")
    else:
        print("✓ Virtual environment already exists")
    
    # Provide activation instructions
    if os.name == 'nt':  # Windows
        activate_cmd = "venv\\Scripts\\activate"
    else:  # Unix/Linux/Mac
        activate_cmd = "source venv/bin/activate"
    
    print(f"To activate the virtual environment, run: {activate_cmd}")
    return activate_cmd

def install_python_dependencies():
    """Install Python dependencies"""
    print("\n📚 Installing Python dependencies...")
    
    # Use the virtual environment's pip
    pip_cmd = "venv\\Scripts\\pip" if os.name == 'nt' else "venv/bin/pip"
    
    try:
        run_command(f"{pip_cmd} install -r requirements.txt")
        print("✓ Python dependencies installed")
    except:
        print("⚠️  Failed to install dependencies automatically")
        print("Please activate the virtual environment and run: pip install -r requirements.txt")

def setup_environment_file():
    """Setup environment configuration file"""
    print("\n⚙️  Setting up environment configuration...")
    
    if not os.path.exists(".env"):
        shutil.copy(".env.example", ".env")
        print("✓ Environment file created (.env)")
        print("⚠️  Please edit .env with your database configuration")
    else:
        print("✓ Environment file already exists")

def setup_claude_desktop_config():
    """Setup Claude Desktop configuration"""
    print("\n🤖 Setting up Claude Desktop configuration...")
    
    # Get the absolute path to main.py
    current_dir = Path(__file__).parent.absolute()
    main_py_path = current_dir / "main.py"
    
    # Update the Claude Desktop config with the correct path
    config_content = f"""{{
  "mcpServers": {{
    "mysql-server": {{
      "command": "python",
      "args": [
        "{str(main_py_path).replace(os.sep, '/')}"
      ],
      "env": {{
        "MYSQL_HOST": "localhost",
        "MYSQL_PORT": "3306",
        "MYSQL_USER": "root",
        "MYSQL_PASSWORD": "your_password_here",
        "MYSQL_DATABASE": "testdb",
        "MYSQL_CHARSET": "utf8mb4",
        "MYSQL_AUTOCOMMIT": "true",
        "MYSQL_POOL_SIZE": "5",
        "MYSQL_SSL_MODE": "REQUIRED",
        "GITHUB_ADMINS": "your_github_username",
        "GITHUB_WRITERS": "",
        "GITHUB_READERS": "",
        "ENABLE_MONITORING": "false"
      }}
    }}
  }}
}}"""
    
    with open("claude_desktop_config.json", "w") as f:
        f.write(config_content)
    
    print("✓ Claude Desktop configuration updated")
    print("⚠️  Please copy the contents of claude_desktop_config.json to your Claude Desktop config")

def check_docker():
    """Check if Docker is available"""
    print("\n🐳 Checking Docker availability...")
    
    try:
        run_command("docker --version")
        print("✓ Docker is available")
        
        try:
            run_command("docker-compose --version")
            print("✓ Docker Compose is available")
            return True
        except:
            print("⚠️  Docker Compose is not available")
            return False
    except:
        print("⚠️  Docker is not available")
        return False

def setup_docker():
    """Setup Docker environment"""
    print("\n🐳 Setting up Docker environment...")
    
    if check_docker():
        print("You can use Docker for easy setup:")
        print("  docker-compose up -d    # Start MySQL + MCP Server")
        print("  docker-compose logs -f  # View logs")
        print("  docker-compose down     # Stop services")
    else:
        print("Docker is not available. Please install Docker for easier setup.")

def display_next_steps():
    """Display next steps for the user"""
    print("\n🎉 Setup completed!")
    print("\n📋 Next steps:")
    print("1. Edit .env file with your database configuration")
    print("2. Configure your database connection (MySQL required)")
    print("3. Set up role-based access by editing GITHUB_ADMINS, GITHUB_WRITERS, GITHUB_READERS")
    print("4. Choose one of the following options to run the server:")
    print("")
    print("   Option A - Direct Python:")
    if os.name == 'nt':
        print("     venv\\Scripts\\activate")
    else:
        print("     source venv/bin/activate")
    print("     python main.py")
    print("")
    print("   Option B - Docker (if available):")
    print("     docker-compose up -d")
    print("")
    print("   Option C - Claude Desktop Integration:")
    print("     Copy claude_desktop_config.json contents to your Claude Desktop config")
    print("")
    print("📖 For detailed instructions, see README.md")

def main():
    """Main setup function"""
    print("🚀 Cloudflare MySQL MCP Server Setup")
    print("=" * 40)
    
    # Check system requirements
    check_python_version()
    check_dependencies()
    
    # Setup Python environment
    create_virtual_environment()
    install_python_dependencies()
    
    # Setup configuration files
    setup_environment_file()
    setup_claude_desktop_config()
    
    # Check Docker availability
    setup_docker()
    
    # Display next steps
    display_next_steps()

if __name__ == "__main__":
    main()
