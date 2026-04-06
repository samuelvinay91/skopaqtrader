#!/bin/bash
# OpenClaw skill: Show portfolio positions and funds
# Usage: portfolio.sh
set -e
cd "$(dirname "$0")/../.."
python3 -c "
import asyncio
from skopaq.config import SkopaqConfig
from skopaq.chat.session import build_infrastructure
from skopaq.chat.tools import init_tools, get_portfolio

async def main():
    config = SkopaqConfig()
    infra = build_infrastructure(config)
    init_tools(infra)
    result = await get_portfolio.ainvoke({})
    print(result)

asyncio.run(main())
"
