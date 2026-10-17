"""Starts the MCP server from a plain file path, so an agent can launch it with
just `python <this file>` on any computer (no PATH or PYTHONPATH setup)."""
import os
import sys

sys.path[0] = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from lmsgrab.mcp_server import main  # noqa: E402

main()
