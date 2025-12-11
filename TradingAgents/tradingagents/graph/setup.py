# TradingAgents/graph/setup.py

from typing import Dict, Any
import time
import asyncio
import inspect
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
        invest_judge_memory,
        risk_manager_memory,
        conditional_logic: ConditionalLogic,
    ):
        """Initialize with required components."""
        self.quick_thinking_llm = quick_thinking_llm
        self.deep_thinking_llm = deep_thinking_llm
        self.tool_nodes = tool_nodes
        self.bull_memory = bull_memory
        self.bear_memory = bear_memory
        self.invest_judge_memory = invest_judge_memory
        self.risk_manager_memory = risk_manager_memory
        self.conditional_logic = conditional_logic

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
        """
        if len(selected_analysts) == 0:
            raise ValueError("Trading Agents Graph Setup Error: no analysts selected!")

        # Create analyst nodes
        analyst_nodes = {}
        delete_nodes = {}
        tool_nodes = {}

        if "market" in selected_analysts:
            analyst_nodes["market"] = create_market_analyst(
                self.quick_thinking_llm
            )
            delete_nodes["market"] = create_msg_delete()
            tool_nodes["market"] = self.tool_nodes["market"]

        if "social" in selected_analysts:
            analyst_nodes["social"] = create_social_media_analyst(
                self.quick_thinking_llm
            )
            delete_nodes["social"] = create_msg_delete()
            tool_nodes["social"] = self.tool_nodes["social"]

        if "news" in selected_analysts:
            analyst_nodes["news"] = create_news_analyst(
                self.quick_thinking_llm
            )
            delete_nodes["news"] = create_msg_delete()
            tool_nodes["news"] = self.tool_nodes["news"]

        if "fundamentals" in selected_analysts:
            analyst_nodes["fundamentals"] = create_fundamentals_analyst(
                self.quick_thinking_llm
            )
            delete_nodes["fundamentals"] = create_msg_delete()
            tool_nodes["fundamentals"] = self.tool_nodes["fundamentals"]

        # Valuation analyst always runs in parallel; prefetches data directly (no tool calls)
        valuation_analyst_node = create_valuation_analyst(self.quick_thinking_llm)
        analyst_nodes["valuation"] = valuation_analyst_node
        delete_nodes["valuation"] = create_msg_delete()
        # Explicitly mark valuation as having no tool node
        tool_nodes["valuation"] = None

        # Create researcher and manager nodes
        bull_researcher_node = create_bull_researcher(
            self.quick_thinking_llm, self.bull_memory
        )
        research_manager_node = create_research_manager(
            self.deep_thinking_llm, self.invest_judge_memory
        )

        # Create risk analysis nodes
        risky_analyst = create_risky_debator(self.quick_thinking_llm)
        neutral_analyst = create_neutral_debator(self.quick_thinking_llm)
        safe_analyst = create_safe_debator(self.quick_thinking_llm)
        risk_manager_node = create_risk_manager(
            self.deep_thinking_llm, self.risk_manager_memory
        )

        # Create workflow
        workflow = StateGraph(AgentState)
        # Instrumented timing: track start/end timestamps per node
        def timed_node(label, fn):
            async def wrapper(state):
                start_key = f"__stage_starts.{label}"
                end_key = f"__stage_ends.{label}"

                start_ts = state.get(start_key, time.time())
                result = fn(state)
                if asyncio.iscoroutine(result) or isinstance(result, asyncio.Future):
                    result = await result
                end_ts = time.time()

                timing_update = {start_key: start_ts, end_key: end_ts}

                if isinstance(result, dict):
                    result = {**result, **timing_update}
                else:
                    result = timing_update
                return result
            return wrapper

        # Join node to gate progression until all analysts produce reports
        def analyst_join_node(state):
            return state

        workflow.add_node("Analyst Join", analyst_join_node)
        workflow.add_node("Analyst Wait", lambda state: state)

        def should_proceed_all_analysts(state):
            required = []
            if "market" in selected_analysts:
                required.append(state.get("market_report"))
            if "social" in selected_analysts:
                required.append(state.get("sentiment_report"))
            if "news" in selected_analysts:
                required.append(state.get("news_report"))
            if "fundamentals" in selected_analysts:
                required.append(state.get("fundamentals_report"))
            # Valuation analyst runs in parallel with other analysts, but we don't wait for it
            # proceed only when all required reports are present and non-empty
            ready = all(bool(r) for r in required)
            return "proceed" if ready else "wait"

        # Add analyst nodes to the graph
        for analyst_type, node in analyst_nodes.items():
            tool_node = tool_nodes.get(analyst_type)
            workflow.add_node(f"{analyst_type.capitalize()} Analyst", timed_node(f"{analyst_type}_start", node))
            workflow.add_node(
                f"Msg Clear {analyst_type.capitalize()}", delete_nodes[analyst_type]
            )
            # Tool nodes may be optional (some analysts prefetch); guard existence
            if tool_node is not None:
                workflow.add_node(f"tools_{analyst_type}", tool_node)
            workflow.add_edge(START, f"{analyst_type.capitalize()} Analyst")

        # Analysts run in parallel; each loops tools/clear, then goes to join
        # Only add conditional edges for analysts that were actually created
        for analyst_type in analyst_nodes.keys():
            current_analyst = f"{analyst_type.capitalize()} Analyst"
            current_tools = f"tools_{analyst_type}"
            current_clear = f"Msg Clear {analyst_type.capitalize()}"
            tool_node = tool_nodes.get(analyst_type)

            # Add conditional edges for current analyst (same pattern for all)
            path_options = (
                [current_tools, current_clear] if tool_node is not None else [current_clear]
            )
            workflow.add_conditional_edges(
                current_analyst,
                getattr(self.conditional_logic, f"should_continue_{analyst_type}"),
                path_options,
            )
            if tool_node is not None:
                workflow.add_edge(current_tools, current_analyst)

            # After analyst clear, go to join gate
            workflow.add_edge(current_clear, "Analyst Join")

        # Add other nodes
        workflow.add_node("Research Manager", timed_node("research_manager", research_manager_node))
        
        workflow.add_node("Risky Analyst", timed_node("risky_analyst", risky_analyst))
        workflow.add_node("Risk Judge", timed_node("risk_judge", risk_manager_node))

        # Join gate: when all required analyst reports ready, proceed to PM Engine
        workflow.add_conditional_edges(
            "Analyst Join",
            should_proceed_all_analysts,
            {
                "proceed": "Research Manager",
                "wait": "Analyst Wait",
            },
        )

        # Add remaining edges
        workflow.add_edge("Research Manager", "Risky Analyst")
        workflow.add_edge("Risky Analyst", "Risk Judge")

        workflow.add_edge("Risk Judge", END)

        # Compile and return
        return workflow.compile()
