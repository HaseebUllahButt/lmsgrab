"""Run the CLI from an absolute path without relying on PYTHONPATH."""
import os
import sys

sys.path[0] = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from lmsgrab.cli import main

main()
