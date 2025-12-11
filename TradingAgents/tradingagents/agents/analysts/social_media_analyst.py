from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
import time
import json
from datetime import datetime, timedelta
from tradingagents.agents.analysts.base_agent import BaseAgent


def create_social_media_analyst(llm):
    base = BaseAgent(llm)
    news_tool = base.get_tools(["get_news"])[0]

    async def social_media_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]
        company_name = state["company_of_interest"]
        try:
            start_date = (datetime.fromisoformat(str(current_date)) - timedelta(days=7)).date().isoformat()
        except Exception:
            start_date = str(current_date)

        # Single news/social fetch to avoid duplicate tool calls
        base.log_tool("Social", "Calling get_news", ticker, f"{start_date} -> {current_date}")
        news_payload = await news_tool.ainvoke(
            {"ticker": ticker, "start_date": start_date, "end_date": str(current_date)}
        )
        news_json = json.dumps(news_payload, ensure_ascii=False)

        system_message = (
            "You are a social/news sentiment analyst reviewing the past week's chatter for a company."
            " Use the provided payload (social signals + recent company news) to extract sentiment, momentum of sentiment, and notable narratives."
            " Focus on signals that matter for trading decisions and map them into the structured output."
            " If the payload contains errors, still infer what you can."
            f"\n\n{base.output_format_instructions('Sentiment Analyst')}"
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Do not call any tools; use the provided JSON only."
                    " If you are unable to fully answer, that's OK; another assistant with different tools"
                    " will help where you left off. Execute what you can to make progress."
                    " Respond ONLY with the required JSON object—no extra prose or FINAL TRANSACTION markers."
                    " {system_message}"
                    "For your reference, the current date is {current_date}. The current company we want to analyze is {ticker}",
                ),
                ("human", "Summarize social/news signals for {ticker} using this one-shot JSON (no more tool calls): {news_json}"),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(ticker=ticker)
        prompt = prompt.partial(news_json=news_json)

        chain = prompt | llm
        result = await chain.ainvoke(state["messages"])
        draft_report = result.content or ""
        reviewed = await base.self_consistency_review(draft_report, "Social Media Analyst")
        report = reviewed.content or draft_report
        base.log_tool("Social", "Generated sentiment_report", ticker, f"{len(report)} chars")

        return {
            "messages": [reviewed],
            "sentiment_report": report,
        }

    return social_media_analyst_node
