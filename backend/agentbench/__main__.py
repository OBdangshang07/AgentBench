from __future__ import annotations

import logging
import multiprocessing
import sys

import uvicorn

from .api import create_app
from .config import Settings


def main() -> None:
    multiprocessing.freeze_support()
    if "--studio-mcp" in sys.argv[1:]:
        from .studio_mcp import parse_studio_mcp_args, run_studio_mcp

        bridge_args = [item for item in sys.argv[1:] if item != "--studio-mcp"]
        parsed = parse_studio_mcp_args(bridge_args)
        run_studio_mcp(parsed.api_base, parsed.bridge_token)
        return
    if "--browser-mcp" in sys.argv[1:]:
        from .browser_mcp import parse_browser_mcp_args, run_browser_mcp

        bridge_args = [item for item in sys.argv[1:] if item != "--browser-mcp"]
        parsed = parse_browser_mcp_args(bridge_args)
        run_browser_mcp(parsed.api_base, parsed.bridge_token)
        return
    settings = Settings.from_env()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        access_log=False,
    )


if __name__ == "__main__":
    main()
