from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
import time
import json
from datetime import datetime
from tradingagents.agents.analysts.base_agent import BaseAgent


def create_fundamentals_analyst(llm):
    base = BaseAgent(llm)
    insider_sentiment_tool = base.get_tools(["get_insider_sentiment"])[0]
    insider_tx_tool = base.get_tools(["get_insider_transactions"])[0]

    async def fundamentals_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]
        as_of = str(current_date)

        # Fetch common financial data using shared helper (will cache in state)
        financial_data = await base.fetch_financial_data(ticker, as_of, "Fundamentals", state)
        fundamentals_data = financial_data["fundamentals_data"]
        balance_data = financial_data["balance_data"]
        cashflow_data = financial_data["cashflow_data"]
        income_data = financial_data["income_data"]
        
        # Extract cache update if present (will be merged into state by LangGraph)
        cache_update = {k: v for k, v in financial_data.items() if k.startswith("_cached")}

        # Fetch insider data (specific to fundamentals analyst)
        base.log_tool("Fundamentals", "Calling get_insider_sentiment", ticker)
        insider_sentiment = await insider_sentiment_tool.ainvoke({"ticker": ticker, "curr_date": as_of})
        base.log_tool("Fundamentals", "Calling get_insider_transactions", ticker)
        insider_transactions = await insider_tx_tool.ainvoke({"ticker": ticker, "curr_date": as_of})

        payload = {
            "fundamentals": base.clip_text(fundamentals_data, "fundamentals", 12000),
            "balance_sheet": base.clip_text(balance_data, "balance_sheet", 12000),
            "cashflow": base.clip_text(cashflow_data, "cashflow", 12000),
            "income_statement": base.clip_text(income_data, "income_statement", 12000),
            "insider_sentiment": base.clip_text(insider_sentiment, "insider_sentiment", 6000),
            "insider_transactions": base.clip_text(insider_transactions, "insider_transactions", 6000),
        }
        payload_json = json.dumps(payload, ensure_ascii=False)

        system_message = (
            "You are a fundamental analyst reviewing the provided fundamentals, statements, and insider data for the company."
            " Use the payload to identify profitability trends, balance sheet quality, cashflow durability, and insider sentiment."
            " Map those insights into the structured output with a clear trading leaning."
            " If some sections contain errors, still use what is available."
            f"\n\n{base.output_format_instructions('Fundamentals Analyst')}"
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
                ("human", "Summarize fundamentals for {ticker} as of {current_date} using this JSON (no tool calls): {payload_json}"),
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
        reviewed = await base.self_consistency_review(draft_report, "Fundamentals Analyst")
        report = reviewed.content or draft_report
        print(f"[Agent: Fundamentals] Generated fundamentals_report for {ticker}: {len(report)} chars")

        # Return state updates including cache (merged by LangGraph)
        return {
            "messages": [reviewed],
            "fundamentals_report": report,
            **cache_update,  # Include cache in state update
        }

    return fundamentals_analyst_node
