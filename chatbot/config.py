import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
MAX_TOKENS = int(os.getenv("ANTHROPIC_MAX_TOKENS", "1024"))

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MCP_SERVERS_CONFIG = PROJECT_ROOT / "mcp_servers.json"
LOGS_DIR = PROJECT_ROOT / "logs"
