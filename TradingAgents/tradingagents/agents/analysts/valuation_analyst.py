from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
import time
import json
from datetime import datetime
from tradingagents.agents.analysts.base_agent import BaseAgent


def create_valuation_analyst(llm):
    base = BaseAgent(llm)
    stock_tool = base.get_tools(["get_stock_data"])[0]
    peer_tool = base.get_tools(["get_peer_companies"])[0]

    async def valuation_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]
        as_of = str(current_date)

        # Fetch common financial data using shared helper (will reuse cached data from fundamentals_analyst if available)
        financial_data = await base.fetch_financial_data(ticker, as_of, "Valuation", state)
        fundamentals_data = financial_data["fundamentals_data"]
        balance_data = financial_data["balance_data"]
        cashflow_data = financial_data["cashflow_data"]
        income_data = financial_data["income_data"]
        
        # Extract cache update if present (will be merged into state by LangGraph)
        cache_update = {k: v for k, v in financial_data.items() if k.startswith("_cached")}

        # Fetch stock price data (specific to valuation analyst)
        base.log_tool("Valuation", "Calling get_stock_data", ticker, f"as_of {as_of}")
        stock_data = await stock_tool.ainvoke({
            "ticker": ticker,
            "start_date": as_of,
            "end_date": as_of,
        })

        # Fetch peer companies for relative valuation
        base.log_tool("Valuation", "Calling get_peer_companies", ticker)
        peer_companies = await peer_tool.ainvoke({"ticker": ticker})

        payload = {
            "fundamentals": base.clip_text(fundamentals_data, "fundamentals", 12000),
            "balance_sheet": base.clip_text(balance_data, "balance_sheet", 12000),
            "cashflow": base.clip_text(cashflow_data, "cashflow", 12000),
            "income_statement": base.clip_text(income_data, "income_statement", 12000),
            "current_price": base.clip_text(stock_data, "current_price", 2000),
            "peer_companies": base.clip_text(peer_companies, "peer_companies", 4000),
        }
        payload_json = json.dumps(payload, ensure_ascii=False)

        system_message = (
            "You are a valuation analyst performing intrinsic value assessment with a 12-24 month horizon."
            " Use the provided financial data, current price, and peer companies to perform DCF, multiples, and peer comparison analysis."
            " Include a concise competitive analysis that benchmarks the company against peers on growth, profitability, leverage, and valuation."
            " Calculate margin of safety and provide a clear valuation assessment."
            " Be conservative and separate facts from assumptions. Translate conclusions into the structured output."
            f"\n\n{base.output_format_instructions('Valuation Analyst', is_valuation=True)}"
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Do not call any tools; use the provided JSON instead."
                    " If you are unable to fully answer, that's OK; another assistant with different tools"
                    " will help where you left off. Execute what you can to make progress."
                    " Respond ONLY with the required JSON object—no extra prose or FINAL TRANSACTION markers."
                    " {system_message}"
                    "For your reference, the current date is {current_date}. The company we want to look at is {ticker}",
                ),
                ("human", "Perform comprehensive valuation analysis for {ticker} as of {current_date} using this JSON (no tool calls): {payload_json}"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(ticker=ticker)
        prompt = prompt.partial(payload_json=payload_json)

        chain = prompt | llm

        # Don't pass message history - we're prefetching all data, so we don't need previous messages
        # This avoids issues with unresolved tool calls from other agents
        result = await chain.ainvoke({})
        draft_report = result.content or ""
        reviewed = await base.self_consistency_review(draft_report, "Valuation Analyst")
        report = reviewed.content or draft_report
        print(f"[Agent: Valuation] Generated valuation_report for {ticker}: {len(report)} chars")
       
        # Return state updates including cache (merged by LangGraph)
        return {
            "messages": [reviewed],
            "valuation_report": report,
            **cache_update,  # Include cache in state update
        }

    return valuation_analyst_node
