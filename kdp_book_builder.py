#!/usr/bin/env python3
"""Entry point for the KDP Book Builder CLI."""
import sys

# Require Python 3.10+
if sys.version_info < (3, 10):
    sys.exit("Python 3.10 or higher is required.")

from kdp.cli import run

if __name__ == "__main__":
    run()
