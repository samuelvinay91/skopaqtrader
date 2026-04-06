---
name: quote
description: Get real-time stock quote from INDstocks. Use when the user asks for a stock price, LTP, or market data.
argument-hint: <SYMBOL>
user-invocable: true
---

# Get Stock Quote

Fetch a live quote for the given symbol.

**IMPORTANT**: Use the Bash tool to call the Python helper. Do NOT import broker modules directly.

## Your Task

Run this command to get the quote for **$ARGUMENTS**:

```bash
python3 -c "
import asyncio, json
from skopaq.mcp_server import get_quote
result = asyncio.run(get_quote('$ARGUMENTS'))
print(result)
" 2>/dev/null
```

Parse the JSON output and present in a clean format:
- **LTP** with change %
- Day's OHLC range
- Bid/Ask spread
- Volume (formatted in Indian number system)

Format currency in INR (₹).
