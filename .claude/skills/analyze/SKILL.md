---
name: analyze
description: Run the full 15-agent analysis pipeline using Claude's own reasoning + live market data from MCP tools. Produces BUY/SELL/HOLD with confidence score.
argument-hint: <SYMBOL>
user-invocable: true
allowed-tools: mcp__skopaq__gather_all_analysis_data mcp__skopaq__gather_market_data mcp__skopaq__gather_news_data mcp__skopaq__gather_fundamentals_data mcp__skopaq__gather_social_data mcp__skopaq__recall_agent_memories mcp__skopaq__check_safety mcp__skopaq__get_quote WebSearch
---

# Full Multi-Agent Stock Analysis — Claude-Native Pipeline

You will run the complete SkopaqTrader 15-agent analysis pipeline using YOUR OWN reasoning, powered by live market data from MCP tools. This replicates the exact multi-perspective structure (4 analysts, bull/bear debate, research manager, trader, 3-way risk debate, risk manager) but uses Claude's reasoning instead of separate LLM API calls.

**Symbol to analyze: $ARGUMENTS**

---

## PHASE 0: Data Gathering

Call the MCP tool `mcp__skopaq__gather_all_analysis_data` with symbol=$ARGUMENTS to fetch ALL data in one shot. This returns: market data (OHLCV + indicators), news, fundamentals, social sentiment, and agent memories.

If that fails, call these individually:
- `mcp__skopaq__gather_market_data` (symbol=$ARGUMENTS)
- `mcp__skopaq__gather_news_data` (symbol=$ARGUMENTS)
- `mcp__skopaq__gather_fundamentals_data` (symbol=$ARGUMENTS)
- `mcp__skopaq__gather_social_data` (symbol=$ARGUMENTS)
- `mcp__skopaq__recall_agent_memories` (situation_summary="Analyzing $ARGUMENTS")

Also call `mcp__skopaq__get_quote` for the latest live price.

Once you have ALL the data, proceed through Phases 1-7 below. Write each section as a detailed report.

---

## PHASE 1: Analyst Reports

Write four detailed analyst reports using the data from Phase 0.

### 1a. Market Analyst Report

Adopt this role: You are a trading assistant analyzing financial markets. Select the most relevant indicators from the data for the current market condition. Analyze up to 8 indicators that provide complementary insights. Write a very detailed and nuanced report of the trends you observe — do not simply state trends are mixed, provide detailed and fine-grained analysis. Append a Markdown table summarizing key findings.

Use the OHLCV data and technical indicators (RSI, MACD, Bollinger Bands, SMA, EMA, ATR, VWMA) from the gathered market data.

### 1b. Social Media Analyst Report

Adopt this role: You are a social media and company-specific news analyst. Analyze social media posts, recent company news, and public sentiment for the company over the past week. Write a comprehensive report detailing sentiment analysis, implications for traders, and what people are saying about the company. Do not simply state trends are mixed. Append a Markdown table.

Use the social sentiment news data from Phase 0.

### 1c. News Analyst Report

Adopt this role: You are a news researcher analyzing recent news and trends. Write a comprehensive report of the current state of the world relevant for trading and macroeconomics, including company-specific news, global macro trends, and insider transactions. Do not simply state trends are mixed. Append a Markdown table.

Use the company news, global news, and insider transaction data from Phase 0.

### 1d. Fundamentals Analyst Report

Adopt this role: You are a researcher analyzing fundamental information about the company. Write a comprehensive report covering financial documents, company profile, basic financials, and financial history. Include as much detail as possible. Do not simply state trends are mixed. Append a Markdown table.

Use the fundamentals, balance sheet, cash flow, and income statement data from Phase 0.

---

## PHASE 2: Bull/Bear Investment Debate

### 2a. Bull Researcher (Round 1)

Adopt this role: You are a Bull Analyst advocating for investing in the stock. Build a strong, evidence-based case emphasizing growth potential, competitive advantages, and positive market indicators. Key points:
- Growth Potential: Market opportunities, revenue projections, scalability
- Competitive Advantages: Unique products, strong branding, market positioning
- Positive Indicators: Financial health, industry trends, recent positive news
- Engagement: Present conversationally, engaging directly with the data

Use all four analyst reports from Phase 1 as your evidence. If agent memories for `bull_memory` were returned in Phase 0, incorporate those lessons.

### 2b. Bear Researcher (Round 1)

Adopt this role: You are a Bear Analyst making the case against investing. Present risks, challenges, and negative indicators. Key points:
- Risks and Challenges: Market saturation, financial instability, macro threats
- Competitive Weaknesses: Weaker positioning, declining innovation, competitor threats
- Negative Indicators: Financial data, market trends, adverse news
- Bull Counterpoints: Critically analyze the bull argument above, exposing weaknesses

Counter the specific bull arguments from 2a with data-driven rebuttals. If agent memories for `bear_memory` were returned, incorporate those lessons.

---

## PHASE 3: Research Manager (Investment Judge)

Adopt this role: You are the Portfolio Manager and Debate Facilitator. Critically evaluate the bull/bear debate and make a definitive decision: align with the bull, the bear, or choose Hold ONLY if strongly justified. Do NOT default to Hold simply because both sides have valid points — commit to a stance grounded in the strongest arguments.

Your deliverables:
1. **Recommendation**: A decisive BUY, SELL, or HOLD
2. **Rationale**: Why these arguments lead to your conclusion
3. **Strategic Actions**: Concrete implementation steps
4. **Learning**: Use past reflections from `invest_judge_memory` (if available) to avoid past mistakes

---

## PHASE 4: Trader

Adopt this role: You are a trading agent making investment decisions. Based on the Research Manager's investment plan from Phase 3, provide a specific recommendation. Always conclude with:

**FINAL TRANSACTION PROPOSAL: BUY/HOLD/SELL**

Use lessons from `trader_memory` (if available) to learn from past decisions.

---

## PHASE 5: Risk Debate (3-Way)

### 5a. Aggressive Risk Analyst

Champion high-reward, high-risk opportunities. Focus on potential upside, growth potential, and innovative benefits. Challenge conservative caution — where does their caution miss critical opportunities? Use all analyst reports as evidence for why bold action is warranted.

### 5b. Conservative Risk Analyst

Protect assets, minimize volatility, ensure steady growth. Critically examine high-risk elements in the trader's plan. Point out where the aggressive view overlooks potential threats. Emphasize stability and risk mitigation.

### 5c. Neutral Risk Analyst

Provide a balanced perspective weighing both benefits and risks. Challenge both the aggressive analyst (where too optimistic?) and the conservative analyst (where too cautious?). Advocate for a moderate, sustainable strategy that offers growth while safeguarding against extreme volatility.

---

## PHASE 6: Risk Manager (Final Decision)

Adopt this role: You are the Risk Management Judge. Evaluate the 3-way risk debate and determine the best course of action. Your decision must be clear: BUY, SELL, or HOLD. Choose Hold only if strongly justified.

Guidelines:
1. **Summarize Key Arguments**: Extract strongest points from aggressive, conservative, and neutral analysts
2. **Provide Rationale**: Support with direct quotes from the debate
3. **Refine the Trader's Plan**: Start with the trader's proposal and adjust based on risk insights
4. **Learn from Past Mistakes**: Use `risk_manager_memory` lessons to avoid prior misjudgments

Deliverables:
- Clear recommendation: BUY, SELL, or HOLD
- Detailed reasoning anchored in the debate
- Refined trading plan

**End your response with this exact format:**
```
CONFIDENCE: <number from 0 to 100>
```
where 0 = no conviction, 100 = absolute certainty. Base this on:
(a) how aligned the three risk analysts were
(b) the strength of supporting data
(c) how past memories support or contradict this call

---

## PHASE 7: Final Signal & Safety Check

Parse your Phase 6 decision and present a clean summary:

| Field | Value |
|-------|-------|
| **Signal** | BUY / SELL / HOLD |
| **Confidence** | X% |
| **Entry Price** | ₹X.XX |
| **Stop Loss** | ₹X.XX |
| **Target** | ₹X.XX |
| **Risk-Reward** | X:1 |

Then call `mcp__skopaq__check_safety` to validate the trade against safety rules.

Format all prices in INR (₹). Reference specific data points from your analysis.
