from langchain_core.messages import HumanMessage, RemoveMessage
from langchain_core.tools import tool
import sys
from pathlib import Path
import asyncio

# Route tool calls through MCP server implementations
MCP_DIR = Path(__file__).resolve().parents[3] / "langchain-v1"
if str(MCP_DIR) not in sys.path:
    sys.path.insert(0, str(MCP_DIR))

from mcp_server import (  # type: ignore
    stock_data as _stock_data,
    indicators as _indicators,
    fundamentals as _fundamentals,
    balance_sheet as _balance_sheet,
    cashflow as _cashflow,
    income_statement as _income_statement,
    news as _news,
    global_news as _global_news,
    insider_sentiment as _insider_sentiment,
    insider_transactions as _insider_transactions,
    multifactor_snapshot as _multifactor_snapshot,
    custom_factors as _custom_factors,
    risk_metrics as _risk_metrics,
    peer_companies as _peer_companies,
)

# Async wrappers without ctx parameter so LangChain tool schema is clean
async def _get_stock_data(ticker: str, start_date: str, end_date: str):
    return await asyncio.to_thread(_stock_data, None, ticker, start_date, end_date)

async def _get_indicators(ticker: str, indicator: str, curr_date: str, look_back_days: int = 30):
    return await asyncio.to_thread(_indicators, None, ticker, indicator, curr_date, look_back_days)

async def _get_fundamentals(ticker: str, curr_date: str):
    return await asyncio.to_thread(_fundamentals, None, ticker, curr_date)

async def _get_balance_sheet(ticker: str, freq: str = "quarterly", curr_date: str = None):
    return await asyncio.to_thread(_balance_sheet, None, ticker, freq, curr_date)

async def _get_cashflow(ticker: str, freq: str = "quarterly", curr_date: str = None):
    return await asyncio.to_thread(_cashflow, None, ticker, freq, curr_date)

async def _get_income_statement(ticker: str, freq: str = "quarterly", curr_date: str = None):
    return await asyncio.to_thread(_income_statement, None, ticker, freq, curr_date)

async def _get_news(ticker: str, start_date: str, end_date: str):
    try:
        return await asyncio.to_thread(_news, None, ticker, start_date, end_date)
    except Exception as e:
        return {"error": f"news failed: {e}"}

async def _get_global_news(curr_date: str, look_back_days: int = 7, limit: int = 5):
    try:
        return await asyncio.to_thread(_global_news, None, curr_date, look_back_days, limit)
    except Exception as e:
        return {"error": f"global_news failed: {e}"}

async def _get_insider_sentiment(ticker: str, curr_date: str):
    return await asyncio.to_thread(_insider_sentiment, None, ticker, curr_date)

async def _get_insider_transactions(ticker: str, curr_date: str):
    return await asyncio.to_thread(_insider_transactions, None, ticker)

async def _multifactor_snapshot(ticker: str, lookback_days: int = 90, risk_free_rate: float = 0.0):
    return await asyncio.to_thread(_multifactor_snapshot, None, ticker, lookback_days, risk_free_rate)

async def _custom_factors(ticker: str, momentum_days: int = 20, long_momentum_days: int = 60, vol_window: int = 20):
    return await asyncio.to_thread(_custom_factors, None, ticker, momentum_days, long_momentum_days, vol_window)

async def _risk_metrics(ticker: str, benchmark: str = "SPY", lookback_days: int = 90, var_percentile: float = 5.0):
    return await asyncio.to_thread(_risk_metrics, None, ticker, benchmark, lookback_days, var_percentile)

async def _get_peer_companies(ticker: str):
    return await asyncio.to_thread(_peer_companies, None, ticker)

# Export LangChain tools with clean signatures
get_stock_data = tool(description=_stock_data.__doc__ or "get_stock_data")(_get_stock_data)
get_indicators = tool(description=_indicators.__doc__ or "get_indicators")(_get_indicators)
get_fundamentals = tool(description=_fundamentals.__doc__ or "get_fundamentals")(_get_fundamentals)
get_balance_sheet = tool(description=_balance_sheet.__doc__ or "get_balance_sheet")(_get_balance_sheet)
get_cashflow = tool(description=_cashflow.__doc__ or "get_cashflow")(_get_cashflow)
get_income_statement = tool(description=_income_statement.__doc__ or "get_income_statement")(_get_income_statement)
get_news = tool(description=_news.__doc__ or "get_news")(_get_news)
get_global_news = tool(description=_global_news.__doc__ or "get_global_news")(_get_global_news)
get_insider_sentiment = tool(description=_insider_sentiment.__doc__ or "get_insider_sentiment")(_get_insider_sentiment)
get_insider_transactions = tool(description=_insider_transactions.__doc__ or "get_insider_transactions")(_get_insider_transactions)
multifactor_snapshot = tool(description=_multifactor_snapshot.__doc__ or "multifactor_snapshot")(_multifactor_snapshot)
custom_factors = tool(description=_custom_factors.__doc__ or "custom_factors")(_custom_factors)
risk_metrics = tool(description=_risk_metrics.__doc__ or "risk_metrics")(_risk_metrics)
get_peer_companies = tool(description="Get peer tickers for a company (sector-based heuristic)")(_get_peer_companies)

def create_msg_delete():
    def delete_messages(state):
        """Clear messages and add placeholder for Anthropic compatibility"""
        # Instead of removing by ID (can fail if IDs not present), just reset to a
        # single placeholder message to keep the graph moving.
        placeholder = HumanMessage(content="Continue")
        return {"messages": [placeholder]}
    
    return delete_messages


        
