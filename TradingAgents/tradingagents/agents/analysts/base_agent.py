from typing import List
from langchain_core.prompts import ChatPromptTemplate
from tradingagents.agents.utils.agent_utils import (
    get_stock_data,
    get_indicators,
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement,
    get_news,
    get_global_news,
    get_insider_sentiment,
    get_insider_transactions,
    multifactor_snapshot,
    custom_factors,
    risk_metrics,
    get_peer_companies,
)


class BaseAgent:
    """Shared utilities for analyst agents using MCP-exposed tools."""

    SELF_CONSISTENCY_PROMPT = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are a quality-check reviewer for the {analyst_label}. "
                "You will receive a draft JSON output with conviction and a recommendation. "
                "Re-evaluate the conviction score and recommendation against the evidence and risks described. "
                "Adjust only if needed, and explain the reasoning briefly inside the JSON if you change it. "
                "Return ONLY the final JSON object (no extra text, no markdown).",
            ),
            (
                "human",
                "Draft JSON to review:\n{draft_output}\n\n"
                "Re-evaluate the conviction score and recommendation. Is it justified by the evidence and risks? "
                "Adjust only if necessary and explain the reasoning. Return the final JSON only.",
            ),
        ]
    )

    ANALYST_OUTPUT_TEMPLATE = """{
  "analyst": "",
  "recommendation": "<Buy | Hold | Sell>",
  "conviction": <0.25 | 0.50 | 0.75>,
  "conviction_category": "<Low | Medium | High>",
  "evidence_strength": 0.0,
  "signal_clarity": 0.0,
  "data_quality": 0.0,
  "uncertainty_penalty": 0.0,
  "key_factors": ["...", "...", "..."],
  "risks": ["...", "..."],
  "overall_comment": "<concise overall takeaway>",
  "time_horizon": "<in months>",
  "confidence_level": "<Low | Medium | High>",
  "data_sources": ["...", "..."]
}"""

    TOOL_REGISTRY = {
        "get_stock_data": get_stock_data,
        "get_indicators": get_indicators,
        "get_fundamentals": get_fundamentals,
        "get_balance_sheet": get_balance_sheet,
        "get_cashflow": get_cashflow,
        "get_income_statement": get_income_statement,
        "get_news": get_news,
        "get_global_news": get_global_news,
        "get_insider_sentiment": get_insider_sentiment,
        "get_insider_transactions": get_insider_transactions,
        "multifactor_snapshot": multifactor_snapshot,
        "custom_factors": custom_factors,
        "risk_metrics": risk_metrics,
        "get_peer_companies": get_peer_companies,
    }

    def __init__(self, llm):
        self.llm = llm

    def get_tools(self, names: List[str]):
        """Return tool callables by name."""
        return [self.TOOL_REGISTRY[name] for name in names if name in self.TOOL_REGISTRY]

    @staticmethod
    def clip_text(text, label: str, max_chars: int = 8000) -> str:
        """Truncate oversized payloads to keep prompts under token limits."""
        if text is None:
            return ""
        text = str(text)
        if len(text) > max_chars:
            return text[:max_chars] + f"\n\n...[truncated {label}, {len(text)-max_chars} chars omitted]..."
        return text

    @staticmethod
    def log_tool(agent: str, tool: str, ticker: str, extra: str = ""):
        prefix = f"[Agent: {agent}] {tool} for {ticker}"
        if extra:
            prefix += f" {extra}"
        print(prefix)

    @classmethod
    def output_format_instructions(cls, analyst_label: str, is_valuation: bool = False) -> str:
        """Common instruction block enforcing the structured analyst JSON output."""
        overall_rule = (
            'In "overall_comment", include a concise valuation takeaway (intrinsic value range, margin of safety, and peer context).'
            if is_valuation
            else 'In "overall_comment", add a concise 1-2 sentence takeaway that synthesizes your recommendation and why it matters right now.'
        )
        return (
            "Return output EXACTLY in this JSON structure (no markdown, no code fences, no extra text):\n"
            f"{cls.ANALYST_OUTPUT_TEMPLATE}\n"
            f'- Set "analyst" to "{analyst_label}".\n'
            '- "recommendation" must be one of: Buy, Hold, or Sell.\n'
            '- Think step by step: score evidence_strength, signal_clarity, data_quality, and uncertainty_penalty on 0-1. Choose a conviction_category of Low, Medium, or High and set conviction accordingly: Low=0.25, Medium=0.50, High=0.75 (adjust by ±0.1 if the evidence is clearly weaker/stronger but keep within [0,1]). Set confidence_level to match the conviction_category.\n'
            '- Think step by step to choose the final recommendation consistent with the scored evidence and risks.\n'
            '- Self-consistency check before finalizing: "Re-evaluate the conviction score and recommendation. Is it justified by the evidence and risks? Adjust only if necessary and explain the reasoning." Apply any adjustment internally and return the final JSON only.\n'
            '- Include at least 5 concise "key_factors" driving the view and at least 2 "risks".\n'
            f"- {overall_rule}\n"
            '- "time_horizon" should be a months string (e.g., "3", "6-12").\n'
            '- "confidence_level" must be Low, Medium, or High.\n'
            '- "data_sources" should cite the datasets you used (e.g., "prices", "indicators", "fundamentals", "news").\n'
            "Do not add prose before or after the JSON."
        )

    async def self_consistency_review(self, draft_output: str, analyst_label: str):
        """Run a self-consistency check on a draft JSON output and return the reviewed AIMessage."""
        chain = self.SELF_CONSISTENCY_PROMPT.partial(analyst_label=analyst_label) | self.llm
        return await chain.ainvoke({"draft_output": draft_output})

    async def fetch_financial_data(self, ticker: str, as_of: str, agent_name: str = "Agent", state: dict = None):
        """
        Fetch common financial data (fundamentals, balance sheet, cashflow, income statement).
        Checks state cache first to avoid duplicate API calls.
        
        Args:
            ticker: Stock ticker symbol
            as_of: Date string for the data
            agent_name: Name of the agent calling this (for logging)
            state: Optional state dict to check for cached data and store results
        
        Returns:
            dict with keys: fundamentals_data, balance_data, cashflow_data, income_data
        """
        # Check if data is already cached in state (from another analyst running in parallel)
        cache_key = "_cached_financial_data"
        lock_key = "_fetching_financial_data"
        
        if state:
            # Check if another agent is currently fetching (lock mechanism for parallel execution)
            if lock_key in state and state[lock_key]:
                # Another agent is fetching, wait a bit and check cache again
                import asyncio
                await asyncio.sleep(0.5)  # Small delay to let the other agent finish
                if cache_key in state and state[cache_key]:
                    cached = state[cache_key]
                    if cached.get("ticker") == ticker and cached.get("as_of") == as_of:
                        self.log_tool(agent_name, "✅ Using cached financial data", ticker, f"(from {cached.get('cached_by', 'parallel agent')}) - SAVED 4 API CALLS")
                        return {
                            "fundamentals_data": cached["fundamentals_data"],
                            "balance_data": cached["balance_data"],
                            "cashflow_data": cached["cashflow_data"],
                            "income_data": cached["income_data"],
                        }
            
            # Check if cache already exists
            if cache_key in state and state[cache_key]:
                cached = state[cache_key]
                # Verify cache is for the same ticker and date
                if cached.get("ticker") == ticker and cached.get("as_of") == as_of:
                    self.log_tool(agent_name, "✅ Using cached financial data", ticker, f"(from {cached.get('cached_by', 'previous agent')}) - SAVED 4 API CALLS")
                    return {
                        "fundamentals_data": cached["fundamentals_data"],
                        "balance_data": cached["balance_data"],
                        "cashflow_data": cached["cashflow_data"],
                        "income_data": cached["income_data"],
                    }

        # Data not cached, set lock and fetch it
        # Set lock to indicate we're fetching (for parallel execution)
        lock_update = {lock_key: True} if state is not None else {}
        
        fundamentals_tool = self.get_tools(["get_fundamentals"])[0]
        balance_tool = self.get_tools(["get_balance_sheet"])[0]
        cashflow_tool = self.get_tools(["get_cashflow"])[0]
        income_tool = self.get_tools(["get_income_statement"])[0]

        self.log_tool(agent_name, "Calling get_fundamentals", ticker, f"as_of {as_of}")
        fundamentals_data = await fundamentals_tool.ainvoke({"ticker": ticker, "curr_date": as_of})
        
        self.log_tool(agent_name, "Calling get_balance_sheet", ticker)
        balance_data = await balance_tool.ainvoke({"ticker": ticker, "freq": "quarterly", "curr_date": as_of})
        
        self.log_tool(agent_name, "Calling get_cashflow", ticker)
        cashflow_data = await cashflow_tool.ainvoke({"ticker": ticker, "freq": "quarterly", "curr_date": as_of})
        
        self.log_tool(agent_name, "Calling get_income_statement", ticker)
        income_data = await income_tool.ainvoke({"ticker": ticker, "freq": "quarterly", "curr_date": as_of})

        result = {
            "fundamentals_data": fundamentals_data,
            "balance_data": balance_data,
            "cashflow_data": cashflow_data,
            "income_data": income_data,
        }

        # Cache the data in state for reuse by other agents
        # Note: In LangGraph, we need to return state updates, not modify state directly
        # The cache will be merged into state when returned from the node
        cache_update = {
            cache_key: {
                "ticker": ticker,
                "as_of": as_of,
                "cached_by": agent_name,
                **result
            },
            lock_key: False  # Release lock
        } if state is not None else {}

        return {**result, **cache_update, **lock_update}
