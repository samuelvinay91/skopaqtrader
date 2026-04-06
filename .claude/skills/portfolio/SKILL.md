---
name: portfolio
description: Show current portfolio — positions, holdings, funds, and P&L. Works in both paper and live mode.
user-invocable: true
---

# Portfolio Overview

Fetch and display the complete portfolio state.

**IMPORTANT**: Use the Bash tool to call the Python helpers. Do NOT import broker modules directly.

## Your Task

Run these commands to get portfolio data:

```bash
python3 -c "
import asyncio, json
from skopaq.mcp_server import get_positions, get_holdings, get_funds
async def main():
    p = json.loads(await get_positions())
    h = json.loads(await get_holdings())
    f = json.loads(await get_funds())
    print(json.dumps({'positions': p, 'holdings': h, 'funds': f}, indent=2))
asyncio.run(main())
" 2>/dev/null
```

Present a clean summary:
- **Funds**: Available cash, used margin, total collateral
- **Positions**: Table with symbol, qty, avg price, LTP, P&L (if any)
- **Holdings**: Table with symbol, qty, avg price, LTP, P&L (if any)

Format all amounts in INR (₹) using Indian number system.
