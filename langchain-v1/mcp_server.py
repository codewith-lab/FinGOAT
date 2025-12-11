"""
TradingAgents MCP server

Exposes the same data tools used by TradingAgents analysts (price, indicators,
fundamentals, news/insiders) plus quantitative risk/factor helpers, and the
trading analysis endpoints. Suitable for MCP-compatible clients.
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, List

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from mcp.server.fastmcp import FastMCP, Context
import uuid

# Ensure TradingAgents package is importable
ROOT = Path(__file__).resolve().parents[1] / "TradingAgents"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tradingagents.default_config import DEFAULT_CONFIG  # type: ignore
from tradingagents.dataflows.config import set_config  # type: ignore
from tradingagents.dataflows.interface import route_to_vendor  # type: ignore


TRADING_SERVICE_URL = os.getenv("TRADING_SERVICE_URL", "http://localhost:8001")
DEFAULT_TIMEOUT = int(os.getenv("TRADING_SERVICE_TIMEOUT", "20"))

mcp = FastMCP("tradingagents-mcp")
_config_initialized = False


def _ensure_config():
    """Initialize TradingAgents dataflow config once, with vendor overrides."""
    global _config_initialized
    if _config_initialized:
        return
    cfg = DEFAULT_CONFIG.copy()
    cfg["data_vendors"] = {
        "core_stock_apis": os.getenv("TA_VENDOR_CORE_STOCK", cfg["data_vendors"].get("core_stock_apis", "yfinance")),
        "technical_indicators": os.getenv("TA_VENDOR_TECHNICAL", cfg["data_vendors"].get("technical_indicators", "yfinance")),
        "fundamental_data": os.getenv("TA_VENDOR_FUNDAMENTAL", cfg["data_vendors"].get("fundamental_data", "alpha_vantage")),
        "news_data": os.getenv("TA_VENDOR_NEWS", cfg["data_vendors"].get("news_data", "alpha_vantage")),
    }
    set_config(cfg)
    _config_initialized = True


def _request(method: str, path: str, **kwargs) -> Dict[str, Any]:
    url = f"{TRADING_SERVICE_URL.rstrip('/')}{path}"
    resp = requests.request(method, url, timeout=DEFAULT_TIMEOUT, **kwargs)
    resp.raise_for_status()
    if resp.text:
        try:
            return resp.json()
        except Exception:
            return {"raw": resp.text}
    return {}


def _call_vendor(method: str, *args, **kwargs) -> Any:
    """Call a dataflow vendor method but never raise so MCP always returns JSON."""
    _ensure_config()
    try:
        return route_to_vendor(method, *args, **kwargs)
    except Exception as e:
        return {"error": str(e), "method": method, "args": args, "kwargs": kwargs}


def _peer_fallback(sector: Optional[str] = None) -> Dict[str, Any]:
    sector_peers = {
        "Technology": ["AAPL", "MSFT", "GOOG", "AMZN", "NVDA", "META"],
        "Financial Services": ["JPM", "BAC", "C", "WFC", "GS"],
        "Healthcare": ["JNJ", "PFE", "MRK", "ABBV", "LLY"],
        "Industrials": ["BA", "HON", "UNP", "CAT", "GE"],
        "Consumer Cyclical": ["HD", "MCD", "NKE", "SBUX", "LOW"],
        "Consumer Defensive": ["PG", "KO", "PEP", "WMT", "COST"],
        "Energy": ["XOM", "CVX", "COP", "SLB", "EOG"],
        "Utilities": ["NEE", "DUK", "SO", "D", "AEP"],
        "Basic Materials": ["LIN", "SHW", "ECL", "APD", "DD"],
        "Communication Services": ["GOOG", "META", "CMCSA", "DIS", "VZ"],
    }
    peers = sector_peers.get(sector or "", ["SPY", "QQQ", "DIA"])
    return {"peers": peers[:5]}


# ----------------------------- PM scoring helper -----------------------------

@mcp.tool(description="Compute PM composite directional score and recommendation from analyst signals")
def pm_directional_score(
    ctx: Optional[Context] = None,
    analysts: Optional[List[Dict[str, Any]]] = None,
    threshold: float = 0.33,
) -> Dict[str, Any]:
    """
    analysts: list of {analyst, recommendation, conviction}
      - recommendation in {Buy, Hold, Sell}
      - conviction in [0,1]
      - analyst/name used to infer role (e.g., 'Fundamental', 'Valuation', 'Sentiment', 'Technical')
    Weights are NOT taken from input; they are hardcoded by role.
    """
    signal_map = {"buy": 1.0, "hold": 0.2, "sell": -1.0}
    ROLE_WEIGHTS = {
        "fundamental": 0.40,
        "valuation": 0.30,
        "sentiment": 0.20,
        "news": 0.20,
        "technical": 0.10,
        "macro": 0.10,
    }

    analysts = analysts or []
    valid_entries: List[Dict[str, Any]] = []

    # Validate & normalize raw entries
    for entry in analysts:
        rec = str(entry.get("recommendation", "")).strip().lower()
        if rec not in signal_map:
            continue

        conviction = entry.get("conviction", 0.0)
        try:
            conviction = float(conviction)
        except Exception:
            conviction = 0.0
        conviction = max(0.0, min(1.0, conviction))

        raw_name = entry.get("analyst") or entry.get("name") or ""
        role_key = str(raw_name).strip().lower()
        if "fundamental" in role_key:
            role = "fundamental"
        elif "valuation" in role_key or "val" in role_key:
            role = "valuation"
        elif "sentiment" in role_key:
            role = "sentiment"
        elif "news" in role_key:
            role = "news"
        elif "technical" in role_key or "chart" in role_key or "market" in role_key:
            role = "technical"
        elif "macro" in role_key:
            role = "macro"
        else:
            role = "other"

        valid_entries.append(
            {
                "analyst": raw_name,
                "role": role,
                "recommendation": rec.title(),
                "conviction": conviction,
                "signal": signal_map[rec],
                "raw_weight": ROLE_WEIGHTS.get(role, 1.0),
            }
        )

    if not valid_entries:
        return {
            "pm_composite_score": 0.0,
            "pm_direction": "Hold",
            "pm_threshold": threshold,
            "pm_base_conviction": 0.0,
            "bullish_strength": 0.0,
            "bearish_strength": 0.0,
            "pm_inputs": [],
            "warning": "No valid analyst entries provided.",
        }

    # Normalize hardcoded weights
    total_raw = sum(ve["raw_weight"] for ve in valid_entries)
    if total_raw <= 0:
        equal_w = 1.0 / len(valid_entries)
        for ve in valid_entries:
            ve["weight"] = equal_w
    else:
        for ve in valid_entries:
            ve["weight"] = ve["raw_weight"] / total_raw

    # Composite directional score S
    numerator = sum(ve["weight"] * ve["conviction"] * ve["signal"] for ve in valid_entries)
    denominator = sum(ve["weight"] * ve["conviction"] for ve in valid_entries)
    pm_composite_score = numerator / denominator if denominator != 0 else 0.0
    pm_composite_score = float(pm_composite_score)

    if pm_composite_score >= threshold:
        pm_direction = "Buy"
    elif pm_composite_score <= -threshold:
        pm_direction = "Sell"
    else:
        pm_direction = "Hold"

    # Category strengths (weighted average conviction by recommendation)
    def weighted_avg(reco: str) -> float:
        num = sum(ve["weight"] * ve["conviction"] for ve in valid_entries if ve["recommendation"].lower() == reco)
        denom = sum(ve["weight"] for ve in valid_entries if ve["recommendation"].lower() == reco)
        return num / denom if denom > 0 else 0.0

    buy_strength = weighted_avg("buy")
    sell_strength = weighted_avg("sell")
    hold_strength = weighted_avg("hold")

    if pm_direction == "Buy":
        pm_base_conviction = buy_strength
    elif pm_direction == "Sell":
        pm_base_conviction = sell_strength
    else:
        pm_base_conviction = hold_strength
    pm_base_conviction = max(0.0, min(1.0, pm_base_conviction))

    return {
        "pm_composite_score": round(pm_composite_score, 4),
        "pm_direction": pm_direction,
        "pm_threshold": threshold,
        "pm_base_conviction": round(pm_base_conviction, 4),
        "bullish_strength": round(buy_strength, 4),
        "bearish_strength": round(sell_strength, 4),
        "hold_strength": round(hold_strength, 4),
        "pm_inputs": valid_entries,
    }


# ----------------------- TradingAgents service endpoints -----------------------

@mcp.tool(description="Check TradingAgents FastAPI service health")
def health_check(ctx: Optional[Context] = None) -> Dict[str, Any]:
    try:
        return _request("GET", "/health")
    except Exception as e:
        return {"error": str(e)}


@mcp.tool(description="Start asynchronous TradingAgents analysis")
def start_analysis(
    ctx: Optional[Context] = None,
    ticker: str = "",
    date: str = "",
    llm_model: str = "gpt-4o-mini",
    provider: str = "openai",
    base_url: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "ticker": ticker.upper(),
        "date": date,
        "llm_config": {
            "deep_think_llm": llm_model,
            "quick_think_llm": llm_model,
            "provider": provider,
        },
    }
    if base_url:
        payload["llm_config"]["base_url"] = base_url

    try:
        return _request("POST", "/api/v1/analyze", json=payload)
    except Exception as e:
        return {"error": str(e), "payload": payload}


@mcp.tool(description="Get analysis status/result by task_id")
def get_analysis(ctx: Optional[Context] = None, task_id: str = "") -> Dict[str, Any]:
    try:
        return _request("GET", f"/api/v1/analysis/{task_id}")
    except Exception as e:
        return {"error": str(e), "task_id": task_id}


@mcp.tool(description="List recent analysis tasks")
def list_tasks(ctx: Optional[Context] = None, limit: int = 10) -> Dict[str, Any]:
    try:
        return _request("GET", f"/api/v1/tasks?limit={limit}")
    except Exception as e:
        return {"error": str(e), "limit": limit}


# ----------------------------- Analyst parity tools -----------------------------
# These mirror the tools used by TradingAgents analysts (market, fundamentals, news).

@mcp.tool(description="OHLCV stock data from configured vendor")
def stock_data(ctx: Optional[Context] = None, ticker: str = "", start_date: str = "", end_date: str = "") -> Dict[str, Any]:
    try:
        data = _call_vendor("get_stock_data", ticker, start_date, end_date)
        return {"ticker": ticker.upper(), "start_date": start_date, "end_date": end_date, "stock_data": data}
    except Exception as e:
        return {"error": str(e), "ticker": ticker.upper(), "start_date": start_date, "end_date": end_date}


@mcp.tool(description="Technical indicators from configured vendor")
def indicators(
    ctx: Optional[Context] = None,
    ticker: str = "",
    indicator: str = "",
    curr_date: str = "",
    look_back_days: int = 30,
) -> Dict[str, Any]:
    try:
        data = _call_vendor("get_indicators", ticker, indicator, curr_date, look_back_days)
        return {
            "ticker": ticker.upper(),
            "indicator": indicator,
            "as_of": curr_date,
            "look_back_days": look_back_days,
            "indicator_data": data,
        }
    except Exception as e:
        return {"error": str(e), "ticker": ticker.upper(), "indicator": indicator, "as_of": curr_date, "look_back_days": look_back_days}


@mcp.tool(description="Fundamentals summary from configured vendor")
def fundamentals(ctx: Optional[Context] = None, ticker: str = "", curr_date: str = "") -> Dict[str, Any]:
    try:
        data = _call_vendor("get_fundamentals", ticker, curr_date)
        return {"ticker": ticker.upper(), "as_of": curr_date, "fundamentals": data}
    except Exception as e:
        return {"error": str(e), "ticker": ticker.upper(), "as_of": curr_date}


@mcp.tool(description="Get peer tickers for a company (sector-based heuristic)")
def peer_companies(ctx: Optional[Context] = None, ticker: str = "") -> Dict[str, Any]:
    try:
        info = {}
        try:
            info = yf.Ticker(ticker).get_info() or {}
        except Exception:
            info = {}
        sector = info.get("sector")
        industry = info.get("industry")
        fallback = _peer_fallback(sector)
        peers = fallback.get("peers", [])
        peers = [p for p in peers if p.upper() != ticker.upper()]
        return {
            "ticker": ticker.upper(),
            "sector": sector,
            "industry": industry,
            "peers": peers,
            "source": "yfinance_sector_map" if sector else "fallback",
        }
    except Exception as e:
        return {"error": str(e), "ticker": ticker.upper()}


@mcp.tool(description="Balance sheet (annual/quarterly) from configured vendor")
def balance_sheet(
    ctx: Optional[Context] = None,
    ticker: str = "",
    freq: str = "quarterly",
    curr_date: Optional[str] = None,
) -> Dict[str, Any]:
    try:
        data = _call_vendor("get_balance_sheet", ticker, freq, curr_date)
        return {"ticker": ticker.upper(), "freq": freq, "as_of": curr_date, "balance_sheet": data}
    except Exception as e:
        return {"error": str(e), "ticker": ticker.upper(), "freq": freq, "as_of": curr_date}


@mcp.tool(description="Cashflow (annual/quarterly) from configured vendor")
def cashflow(
    ctx: Optional[Context] = None,
    ticker: str = "",
    freq: str = "quarterly",
    curr_date: Optional[str] = None,
) -> Dict[str, Any]:
    try:
        data = _call_vendor("get_cashflow", ticker, freq, curr_date)
        return {"ticker": ticker.upper(), "freq": freq, "as_of": curr_date, "cashflow": data}
    except Exception as e:
        return {"error": str(e), "ticker": ticker.upper(), "freq": freq, "as_of": curr_date}


@mcp.tool(description="Income statement (annual/quarterly) from configured vendor")
def income_statement(
    ctx: Optional[Context] = None,
    ticker: str = "",
    freq: str = "quarterly",
    curr_date: Optional[str] = None,
) -> Dict[str, Any]:
    try:
        data = _call_vendor("get_income_statement", ticker, freq, curr_date)
        return {"ticker": ticker.upper(), "freq": freq, "as_of": curr_date, "income_statement": data}
    except Exception as e:
        return {"error": str(e), "ticker": ticker.upper(), "freq": freq, "as_of": curr_date}


@mcp.tool(description="Company-specific news from configured vendor")
def news(ctx: Optional[Context] = None, ticker: str = "", start_date: str = "", end_date: str = "") -> Dict[str, Any]:
    try:
        data = _call_vendor("get_news", ticker, start_date, end_date)
        return {"ticker": ticker.upper(), "start_date": start_date, "end_date": end_date, "news": data}
    except Exception as e:
        return {"error": str(e), "ticker": ticker.upper(), "start_date": start_date, "end_date": end_date}


@mcp.tool(description="Global/macro news from configured vendor")
def global_news(ctx: Optional[Context] = None, curr_date: str = "", look_back_days: int = 7, limit: int = 5) -> Dict[str, Any]:
    try:
        data = _call_vendor("get_global_news", curr_date, look_back_days, limit)
        return {"as_of": curr_date, "look_back_days": look_back_days, "limit": limit, "news": data}
    except Exception as e:
        return {"error": str(e), "as_of": curr_date, "look_back_days": look_back_days, "limit": limit}


@mcp.tool(description="Insider sentiment from configured vendor")
def insider_sentiment(ctx: Optional[Context] = None, ticker: str = "", curr_date: str = "") -> Dict[str, Any]:
    try:
        data = _call_vendor("get_insider_sentiment", ticker, curr_date)
        return {"ticker": ticker.upper(), "as_of": curr_date, "insider_sentiment": data}
    except Exception as e:
        return {"error": str(e), "ticker": ticker.upper(), "as_of": curr_date}


@mcp.tool(description="Insider transactions from configured vendor")
def insider_transactions(ctx: Optional[Context] = None, ticker: str = "", curr_date: str = "") -> Dict[str, Any]:
    try:
        # Most vendors only need ticker; tolerate curr_date but pass ticker only to avoid arg mismatch
        data = _call_vendor("get_insider_transactions", ticker)
        return {"ticker": ticker.upper(), "as_of": curr_date, "insider_transactions": data}
    except Exception as e:
        return {"error": str(e), "ticker": ticker.upper(), "as_of": curr_date}


# ----------------------------- Quant/technical helpers -----------------------------

def _fetch_history(ticker: str, days: int) -> pd.DataFrame:
    end = datetime.utcnow()
    start = end - timedelta(days=days * 2)  # buffer for weekends/holidays
    df = yf.download(
        ticker.upper(),
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        auto_adjust=True,
        progress=False,
    )
    if df.empty:
        raise ValueError(f"No price data for {ticker}")
    return df.sort_index().tail(days)


def _compute_rsi(series: pd.Series, period: int = 14) -> float:
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / (loss + 1e-9)
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])


def _compute_max_drawdown(series: pd.Series) -> float:
    roll_max = series.cummax()
    drawdown = (series - roll_max) / roll_max
    return float(drawdown.min())


@mcp.tool(description="Multi-factor snapshot: return, vol, Sharpe, drawdown, RSI, avg volume")
def multifactor_snapshot(
    ctx: Optional[Context] = None,
    ticker: str = "",
    lookback_days: int = 90,
    risk_free_rate: float = 0.0,
) -> Dict[str, Any]:
    try:
        df = _fetch_history(ticker, lookback_days)
        closes = df["Close"]
        rets = closes.pct_change().dropna()

        total_return = float((closes.iloc[-1] / closes.iloc[0]) - 1)
        vol_ann = float(rets.std() * np.sqrt(252))
        excess_ret = rets.mean() * 252 - risk_free_rate
        sharpe = float(excess_ret / vol_ann) if vol_ann > 0 else 0.0
        mdd = _compute_max_drawdown(closes)
        rsi = _compute_rsi(closes)
        avg_vol = float(df["Volume"].mean()) if "Volume" in df.columns else None

        return {
            "ticker": ticker.upper(),
            "lookback_days": lookback_days,
            "return_pct": round(total_return * 100, 2),
            "vol_annualized": round(vol_ann, 4),
            "sharpe": round(sharpe, 3),
            "max_drawdown_pct": round(mdd * 100, 2),
            "rsi_14": round(rsi, 2),
            "avg_volume": avg_vol,
        }
    except Exception as e:
        return {"error": str(e), "ticker": ticker.upper(), "lookback_days": lookback_days}


@mcp.tool(description="Custom factors: configurable momentum windows and rolling vol")
def custom_factors(
    ctx: Optional[Context] = None,
    ticker: str = "",
    momentum_days: int = 20,
    long_momentum_days: int = 60,
    vol_window: int = 20,
) -> Dict[str, Any]:
    try:
        df = _fetch_history(ticker, max(momentum_days, long_momentum_days, vol_window, 30))
        closes = df["Close"]
        result: Dict[str, Any] = {"ticker": ticker.upper()}

        def pct_over(days: int) -> float:
            if days <= 0 or len(closes) < days + 1:
                return float("nan")
            return float((closes.iloc[-1] / closes.iloc[-days - 1]) - 1)

        result[f"momentum_{momentum_days}d_pct"] = round(pct_over(momentum_days) * 100, 2)
        result[f"momentum_{long_momentum_days}d_pct"] = round(pct_over(long_momentum_days) * 100, 2)
        rets = closes.pct_change().dropna()
        vol = float(rets.tail(vol_window).std() * np.sqrt(252)) if len(rets) >= vol_window else float("nan")
        result[f"vol_annualized_{vol_window}d"] = round(vol, 4) if np.isfinite(vol) else None

        return result
    except Exception as e:
        return {"error": str(e), "ticker": ticker.upper(), "momentum_days": momentum_days, "long_momentum_days": long_momentum_days, "vol_window": vol_window}


@mcp.tool(description="Risk metrics: VaR percentile, max drawdown, beta vs benchmark")
def risk_metrics(
    ctx: Optional[Context] = None,
    ticker: str = "",
    benchmark: str = "SPY",
    lookback_days: int = 90,
    var_percentile: float = 5.0,
) -> Dict[str, Any]:
    try:
        df = _fetch_history(ticker, lookback_days)
        closes = df["Close"]
        rets = closes.pct_change().dropna()

        var = float(np.percentile(rets, var_percentile)) if len(rets) > 0 else float("nan")
        mdd = _compute_max_drawdown(closes)

        beta = None
        try:
            bench = _fetch_history(benchmark, lookback_days)
            bench_rets = bench["Close"].pct_change().dropna()
            joined = pd.concat([rets, bench_rets], axis=1, join="inner").dropna()
            joined.columns = ["asset", "bench"]
            cov = joined.cov().iloc[0, 1]
            var_bench = joined["bench"].var()
            beta_val = cov / var_bench if var_bench > 0 else float("nan")
            beta = round(float(beta_val), 3) if np.isfinite(beta_val) else None
        except Exception:
            beta = None

        return {
            "ticker": ticker.upper(),
            "benchmark": benchmark.upper(),
            "lookback_days": lookback_days,
            "var_pct": round(var * 100, 2) if np.isfinite(var) else None,
            "max_drawdown_pct": round(mdd * 100, 2),
            "beta_vs_benchmark": beta,
            "note": "VaR is a simple historical percentile; use with caution.",
        }
    except Exception as e:
        return {"error": str(e), "ticker": ticker.upper(), "benchmark": benchmark.upper(), "lookback_days": lookback_days}

if __name__ == "__main__":
    mcp.run()
