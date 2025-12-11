from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
import time
import json
from datetime import datetime, timedelta
from tradingagents.agents.analysts.base_agent import BaseAgent


def create_news_analyst(llm):
    base = BaseAgent(llm)
    news_tool = base.get_tools(["get_news"])[0]

    async def news_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]
        try:
            start_date = (datetime.fromisoformat(str(current_date)) - timedelta(days=7)).date().isoformat()
        except Exception:
            start_date = str(current_date)

        # Single news call per run to avoid duplicate tool invocations
        base.log_tool("News", "Calling get_news", ticker, f"{start_date} -> {current_date}")
        news_payload = await news_tool.ainvoke(
            {"ticker": ticker, "start_date": start_date, "end_date": str(current_date)}
        )
        news_json = json.dumps(news_payload, ensure_ascii=False)

        system_message = (
            "You are a news researcher assessing the past week's headlines relevant to the ticker."
            " Use the provided news JSON to extract catalysts, macro context, and momentum of coverage."
            " Translate the news impact into a clear trading leaning and populate the structured output."
            " If the JSON contains errors, still summarize what is usable."
            f"\n\n{base.output_format_instructions('News Analyst')}"
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Do not call any tools; use the provided news JSON."
                    " If you are unable to fully answer, that's OK; another assistant with different tools"
                    " will help where you left off. Execute what you can to make progress."
                    " Respond ONLY with the required JSON object—no extra prose or FINAL TRANSACTION markers."
                    " {system_message}"
                    "For your reference, the current date is {current_date}. We are looking at the company {ticker}",
                ),
                ("human", "Use this one-shot news payload (do not call tools again). Ticker: {ticker}. Window: {start_date} → {current_date}. JSON: {news_json}"),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(ticker=ticker)
        prompt = prompt.partial(start_date=start_date)
        prompt = prompt.partial(news_json=news_json)

        chain = prompt | llm
        result = await chain.ainvoke(state["messages"])
        draft_report = result.content or ""
        reviewed = await base.self_consistency_review(draft_report, "News Analyst")
        report = reviewed.content or draft_report
        base.log_tool("News", "Generated news_report", ticker, f"{len(report)} chars window {start_date} -> {current_date}")

        return {
            "messages": [reviewed],
            "news_report": report,
        }

    return news_analyst_node
