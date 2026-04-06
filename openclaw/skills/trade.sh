#!/bin/bash
# OpenClaw skill: Trade a stock symbol (paper mode by default)
# Usage: trade.sh RELIANCE
set -e
cd "$(dirname "$0")/../.."
python3 -c "
import asyncio, sys
from skopaq.config import SkopaqConfig
from skopaq.chat.session import ChatSession, build_infrastructure
from skopaq.chat.tools import init_tools, trade_stock

async def main():
    config = SkopaqConfig()
    infra = build_infrastructure(config)
    init_tools(infra)
    result = await trade_stock.ainvoke({'symbol': sys.argv[1]})
    print(result)

asyncio.run(main())
" "$1"
