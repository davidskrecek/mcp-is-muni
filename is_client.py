#!/usr/bin/env python3
"""
Backwards-compatible wrapper for mcp_is_muni.client
"""

from mcp_is_muni.client import (
    ISMuniClient,
    CONFIG_DIR,
    CONFIG_FILE,
    BASE_URL,
    get_config_dir,
)

__all__ = [
    "ISMuniClient",
    "CONFIG_DIR",
    "CONFIG_FILE",
    "BASE_URL",
    "get_config_dir",
]
