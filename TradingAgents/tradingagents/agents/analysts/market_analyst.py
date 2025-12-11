from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
import time
import json
from datetime import datetime, timedelta
from tradingagents.agents.analysts.base_agent import BaseAgent


def create_market_analyst(llm):
    base = BaseAgent(llm)
    stock_tool = base.get_tools(["get_stock_data"])[0]
    indicator_tool = base.get_tools(["get_indicators"])[0]

    async def market_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]
        company_name = state["company_of_interest"]

        # Compute a 90-day window ending at trade_date (fallback to today)
        try:
            end_dt = datetime.fromisoformat(str(current_date)).date()
        except Exception:
            end_dt = datetime.utcnow().date()
        start_dt = end_dt - timedelta(days=120)

        # Single batch of data fetches (no tool calls inside the LLM)
        base.log_tool("Market", "Calling get_stock_data", ticker, f"{start_dt.isoformat()} -> {end_dt.isoformat()}")
        stock_data = await stock_tool.ainvoke(
            {
                "ticker": ticker,
                "start_date": start_dt.isoformat(),
                "end_date": end_dt.isoformat(),
            }
        )
        indicators = {}
        for ind in ["rsi", "macd", "macds", "macdh", "boll_ub", "boll_lb", "atr"]:
            base.log_tool("Market", f"Calling get_indicators:{ind}", ticker)
            ind_resp = await indicator_tool.ainvoke(
                {
                    "ticker": ticker,
                    "indicator": ind,
                    "curr_date": end_dt.isoformat(),
                    "look_back_days": 60,
                }
            )
            indicators[ind] = ind_resp

        payload = {
            "price_window": base.clip_text(stock_data, "price_window", 8000),
            "indicators": {k: base.clip_text(v, f"indicator:{k}", 4000) for k, v in indicators.items()},
        }
        payload_json = json.dumps(payload, ensure_ascii=False)

        system_message = (
            "You are a market/technical analyst selecting the most relevant indicators for current conditions."
            " Use the provided price window and indicators to explain momentum, trend strength, volatility, and support/resistance."
            " Avoid redundant signals—highlight the few indicators that actually matter for this ticker right now."
            " Translate those observations into a trading stance for the structured output."
            f"\n\n{base.output_format_instructions('Market Analyst')}"
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Do not call any tools; a single JSON payload with prices and indicators is provided."
                    " If you are unable to fully answer, that's OK; another assistant with different tools"
                    " will help where you left off. Execute what you can to make progress."
                    " Respond ONLY with the required JSON object—do not prepend any text or FINAL TRANSACTION markers."
                    " {system_message}"
                    "For your reference, the current date is {current_date}. The company we want to look at is {ticker}",
                ),
                ("human", "Use this one-shot market data (no tool calls): {payload_json}"),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(ticker=ticker)
        prompt = prompt.partial(payload_json=payload_json)

        chain = prompt | llm

        result = await chain.ainvoke(state["messages"])
        draft_report = result.content or ""
        reviewed = await base.self_consistency_review(draft_report, "Market Analyst")
        report = reviewed.content or draft_report
        print(f"[Agent: Market] Generated market_report for {ticker}: {len(report)} chars")
       
        return {
            "messages": [reviewed],
            "market_report": report,
        }

    return market_analyst_node
