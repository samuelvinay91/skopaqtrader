# TradingAgents/graph/setup.py

from typing import Dict, Any, Optional
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph, START
from langgraph.prebuilt import ToolNode

from tradingagents.agents import *
from tradingagents.agents.utils.agent_states import AgentState

from .conditional_logic import ConditionalLogic


class GraphSetup:
    """Handles the setup and configuration of the agent graph."""

    def __init__(
        self,
        quick_thinking_llm: ChatOpenAI,
        deep_thinking_llm: ChatOpenAI,
        tool_nodes: Dict[str, ToolNode],
        bull_memory,
        bear_memory,
        trader_memory,
        invest_judge_memory,
        risk_manager_memory,
        conditional_logic: ConditionalLogic,
        llm_map: Optional[Dict[str, Any]] = None,
    ):
        """Initialize with required components.

        Args:
            llm_map: Optional per-role LLM mapping.  If provided, each
                agent node looks up its role key (e.g. ``market_analyst``)
                in this dict.  Falls back to ``_default`` or the
                quick/deep pair when a role key is absent.
        """
        self.quick_thinking_llm = quick_thinking_llm
        self.deep_thinking_llm = deep_thinking_llm
        self.tool_nodes = tool_nodes
        self.bull_memory = bull_memory
        self.bear_memory = bear_memory
        self.trader_memory = trader_memory
        self.invest_judge_memory = invest_judge_memory
        self.risk_manager_memory = risk_manager_memory
        self.conditional_logic = conditional_logic
        self.llm_map = llm_map or {}

    def _get_llm(self, role: str, *, deep: bool = False):
        """Look up LLM for *role*, falling back to quick/deep pair."""
        if role in self.llm_map:
            return self.llm_map[role]
        if "_default" in self.llm_map:
            return self.llm_map["_default"]
        return self.deep_thinking_llm if deep else self.quick_thinking_llm

    def setup_graph(
        self, selected_analysts=["market", "social", "news", "fundamentals"]
    ):
        """Set up and compile the agent workflow graph.

        Args:
            selected_analysts (list): List of analyst types to include. Options are:
                - "market": Market analyst
                - "social": Social media analyst
                - "news": News analyst
                - "fundamentals": Fundamentals analyst
                - "onchain": On-chain analyst (crypto only)
                - "defi": DeFi/tokenomics analyst (crypto only)
                - "funding": Funding rate analyst (crypto only)
        """
        if len(selected_analysts) == 0:
            raise ValueError("Trading Agents Graph Setup Error: no analysts selected!")

        # Create analyst nodes
        analyst_nodes = {}
        tool_nodes = {}

        if "market" in selected_analysts:
            analyst_nodes["market"] = create_market_analyst(
                self._get_llm("market_analyst")
            )
            tool_nodes["market"] = self.tool_nodes["market"]

        if "social" in selected_analysts:
            analyst_nodes["social"] = create_social_media_analyst(
                self._get_llm("social_analyst")
            )
            tool_nodes["social"] = self.tool_nodes["social"]

        if "news" in selected_analysts:
            analyst_nodes["news"] = create_news_analyst(
                self._get_llm("news_analyst")
            )
            tool_nodes["news"] = self.tool_nodes["news"]

        if "fundamentals" in selected_analysts:
            analyst_nodes["fundamentals"] = create_fundamentals_analyst(
                self._get_llm("fundamentals_analyst")
            )
            tool_nodes["fundamentals"] = self.tool_nodes["fundamentals"]

        # Crypto-specific analysts (activated when asset_class == "crypto")
        if "onchain" in selected_analysts:
            analyst_nodes["onchain"] = create_onchain_analyst(
                self._get_llm("onchain_analyst")
            )
            tool_nodes["onchain"] = self.tool_nodes["onchain"]

        if "defi" in selected_analysts:
            analyst_nodes["defi"] = create_defi_analyst(
                self._get_llm("defi_analyst")
            )
            tool_nodes["defi"] = self.tool_nodes["defi"]

        if "funding" in selected_analysts:
            analyst_nodes["funding"] = create_funding_analyst(
                self._get_llm("funding_analyst")
            )
            tool_nodes["funding"] = self.tool_nodes["funding"]

        # Create researcher and manager nodes
        bull_researcher_node = create_bull_researcher(
            self._get_llm("bull_researcher"), self.bull_memory
        )
        bear_researcher_node = create_bear_researcher(
            self._get_llm("bear_researcher"), self.bear_memory
        )
        research_manager_node = create_research_manager(
            self._get_llm("research_manager", deep=True), self.invest_judge_memory
        )
        trader_node = create_trader(self._get_llm("trader"), self.trader_memory)

        # Create risk analysis nodes
        aggressive_analyst = create_aggressive_debator(self._get_llm("aggressive_debator"))
        neutral_analyst = create_neutral_debator(self._get_llm("neutral_debator"))
        conservative_analyst = create_conservative_debator(self._get_llm("conservative_debator"))
        risk_manager_node = create_risk_manager(
            self._get_llm("risk_manager", deep=True), self.risk_manager_memory
        )

        # Create workflow
        workflow = StateGraph(AgentState)

        # Per-analyst no-op pass-through (replaces Msg Clear in parallel mode).
        # In parallel fan-out, each branch's Msg Clear would try to
        # RemoveMessage the same initial message ID, causing a conflict.
        # Instead, each analyst branch ends with a no-op, and a single
        # "Clear Analyst Messages" node clears all messages after fan-in.
        def _analyst_done(state):
            """No-op pass-through — message clearing happens after fan-in."""
            return {}

        # Add analyst nodes to the graph
        for analyst_type, node in analyst_nodes.items():
            workflow.add_node(f"{analyst_type.capitalize()} Analyst", node)
            workflow.add_node(f"Done {analyst_type.capitalize()}", _analyst_done)
            workflow.add_node(f"tools_{analyst_type}", tool_nodes[analyst_type])

        # Single message-clear node runs AFTER all parallel branches merge
        workflow.add_node("Clear Analyst Messages", create_msg_delete())

        # Add other nodes
        workflow.add_node("Bull Researcher", bull_researcher_node)
        workflow.add_node("Bear Researcher", bear_researcher_node)
        workflow.add_node("Research Manager", research_manager_node)
        workflow.add_node("Trader", trader_node)
        workflow.add_node("Aggressive Analyst", aggressive_analyst)
        workflow.add_node("Neutral Analyst", neutral_analyst)
        workflow.add_node("Conservative Analyst", conservative_analyst)
        workflow.add_node("Risk Judge", risk_manager_node)

        # Define edges
        # Fan-out: START → all analysts in parallel
        for analyst_type in selected_analysts:
            workflow.add_edge(START, f"{analyst_type.capitalize()} Analyst")

        # Each analyst has its own tool loop; ends with no-op Done node
        for analyst_type in selected_analysts:
            current_analyst = f"{analyst_type.capitalize()} Analyst"
            current_tools = f"tools_{analyst_type}"
            current_done = f"Done {analyst_type.capitalize()}"

            # Conditional: tool_calls → tools, else → done (no-op)
            workflow.add_conditional_edges(
                current_analyst,
                getattr(self.conditional_logic, f"should_continue_{analyst_type}"),
                [current_tools, current_done],
            )
            workflow.add_edge(current_tools, current_analyst)

            # Fan-in: all done nodes converge to single message-clear
            workflow.add_edge(current_done, "Clear Analyst Messages")

        # After clearing, proceed to debate phase
        workflow.add_edge("Clear Analyst Messages", "Bull Researcher")

        # Add remaining edges
        workflow.add_conditional_edges(
            "Bull Researcher",
            self.conditional_logic.should_continue_debate,
            {
                "Bear Researcher": "Bear Researcher",
                "Research Manager": "Research Manager",
            },
        )
        workflow.add_conditional_edges(
            "Bear Researcher",
            self.conditional_logic.should_continue_debate,
            {
                "Bull Researcher": "Bull Researcher",
                "Research Manager": "Research Manager",
            },
        )
        workflow.add_edge("Research Manager", "Trader")
        workflow.add_edge("Trader", "Aggressive Analyst")
        workflow.add_conditional_edges(
            "Aggressive Analyst",
            self.conditional_logic.should_continue_risk_analysis,
            {
                "Conservative Analyst": "Conservative Analyst",
                "Risk Judge": "Risk Judge",
            },
        )
        workflow.add_conditional_edges(
            "Conservative Analyst",
            self.conditional_logic.should_continue_risk_analysis,
            {
                "Neutral Analyst": "Neutral Analyst",
                "Risk Judge": "Risk Judge",
            },
        )
        workflow.add_conditional_edges(
            "Neutral Analyst",
            self.conditional_logic.should_continue_risk_analysis,
            {
                "Aggressive Analyst": "Aggressive Analyst",
                "Risk Judge": "Risk Judge",
            },
        )

        workflow.add_edge("Risk Judge", END)

        # Compile and return
        return workflow.compile()
