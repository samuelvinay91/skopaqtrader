#!/bin/bash
# OpenClaw skill: Analyze a stock symbol
# Usage: analyze.sh RELIANCE
set -e
cd "$(dirname "$0")/../.."
python3 -c "
import asyncio, json, sys
from skopaq.config import SkopaqConfig
from skopaq.chat.session import ChatSession, build_infrastructure
from skopaq.chat.tools import init_tools, analyze_stock

async def main():
    config = SkopaqConfig()
    infra = build_infrastructure(config)
    init_tools(infra)
    result = await analyze_stock.ainvoke({'symbol': sys.argv[1]})
    print(result)

asyncio.run(main())
" "$1"
