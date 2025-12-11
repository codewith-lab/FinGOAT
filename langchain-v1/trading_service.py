"""
TradingAgents FastAPI Microservice

This service provides REST API endpoints for the TradingAgents multi-agent trading framework.
It allows the Go backend to request trading analysis and recommendations.
"""

import os
import sys
import uuid
import logging
import asyncio
import re
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple, Set
from enum import Enum

from fastapi import FastAPI, HTTPException, BackgroundTasks, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
from dotenv import load_dotenv

# Add TradingAgents to path
TRADING_AGENTS_PATH = os.path.join(os.path.dirname(__file__), "..", "TradingAgents")
sys.path.insert(0, TRADING_AGENTS_PATH)

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="TradingAgents Microservice",
    description="Multi-agent LLM financial trading analysis service",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory task storage (could be replaced with Redis in production)
analysis_tasks: Dict[str, Dict[str, Any]] = {}


# ======================== Models ========================

class TaskStatus(str, Enum):
    """Analysis task status"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class TradingAction(str, Enum):
    """Trading action types"""
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class LLMConfig(BaseModel):
    """LLM configuration"""
    deep_think_llm: str = Field(default="gpt-4o-mini", description="Deep thinking LLM model")
    quick_think_llm: str = Field(default="gpt-4o-mini", description="Quick thinking LLM model")
    max_debate_rounds: int = Field(default=1, ge=1, le=5, description="Maximum debate rounds")
    max_risk_discuss_rounds: int = Field(default=1, ge=1, le=5, description="Maximum risk discussion rounds")
    provider: str = Field(default="openai", description="LLM provider identifier")
    base_url: Optional[str] = Field(default=None, description="Override LLM base URL (for OpenAI-compatible endpoints)")
    api_key: Optional[str] = Field(default=None, description="Optional override for provider API key")


class DataVendorConfig(BaseModel):
    """Data vendor configuration"""
    core_stock_apis: str = Field(default="yfinance", description="Stock data provider")
    technical_indicators: str = Field(default="yfinance", description="Technical indicators provider")
    fundamental_data: str = Field(default="alpha_vantage", description="Fundamental data provider")
    news_data: str = Field(default="alpha_vantage", description="News data provider")


class AnalysisRequest(BaseModel):
    """Request model for trading analysis"""
    ticker: str = Field(..., description="Stock ticker symbol", example="NVDA")
    date: str = Field(..., description="Analysis date in YYYY-MM-DD format", example="2024-05-10")
    llm_config: Optional[LLMConfig] = Field(default=None, description="LLM configuration")
    data_vendor_config: Optional[DataVendorConfig] = Field(default=None, description="Data vendor configuration")
    
    @validator('ticker')
    def validate_ticker(cls, v):
        if not v or len(v) > 10:
            raise ValueError('Ticker must be between 1 and 10 characters')
        return v.upper()
    
    @validator('date')
    def validate_date(cls, v):
        try:
            datetime.strptime(v, '%Y-%m-%d')
        except ValueError:
            raise ValueError('Date must be in YYYY-MM-DD format')
        return v


class BatchAnalysisRequest(BaseModel):
    """Request model for batch analysis"""
    requests: List[AnalysisRequest] = Field(..., description="List of analysis requests")
    
    @validator('requests')
    def validate_batch_size(cls, v):
        if len(v) > 10:
            raise ValueError('Batch size cannot exceed 10 requests')
        return v


class AgentInsight(BaseModel):
    """Individual agent analysis result"""
    agent_type: str
    analysis: str
    confidence: Optional[float] = None


class DecisionReasoning(BaseModel):
    """Trading decision reasoning"""
    fundamental_analysis: Optional[Dict[str, Any]] = None
    sentiment_analysis: Optional[Dict[str, Any]] = None
    technical_analysis: Optional[Dict[str, Any]] = None
    news_analysis: Optional[Dict[str, Any]] = None
    risk_assessment: Optional[Dict[str, Any]] = None
    researcher_debate: Optional[Dict[str, Any]] = None


class TradingDecision(BaseModel):
    """Trading decision output"""
    action: str = Field(..., description="Trading action: BUY, SELL, or HOLD")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score")
    position_size: Optional[int] = Field(default=None, description="Recommended position size")
    reasoning: Optional[DecisionReasoning] = None
    raw_decision: Optional[Dict[str, Any]] = None

class AgentKeyOutput(BaseModel):
    """Structured key outputs extracted from agent content"""
    summary_table: Optional[str] = Field(default=None, description="Primary summary table in markdown")
    transaction_proposal: Optional[str] = Field(default=None, description="Final transaction proposal label")


class AnalysisResponse(BaseModel):
    """Response model for analysis result"""
    task_id: str
    status: TaskStatus
    ticker: str
    date: str
    decision: Optional[TradingDecision] = None
    analysis_report: Optional[Dict[str, Any]] = None  # Complete analysis from all agents
    key_outputs: Optional[Dict[str, AgentKeyOutput]] = None
    stage_times: Optional[Dict[str, float]] = None
    error: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None
    processing_time_seconds: Optional[float] = None


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    service: str
    version: str
    timestamp: str


# ======================== Helper Functions ========================

PARALLEL_ANALYST_STAGES = {
    "market_report",
    "sentiment_report",
    "news_report",
    "fundamentals_report",
    "valuation_report",  # Valuation runs in parallel with other analysts
}

STAGE_ORDER = [
    "market_report",
    "sentiment_report",
    "news_report",
    "fundamentals_report",
    "valuation_report",
    "investment_plan",
    "risk_debate_state",
    "final_trade_decision",
]

# Map graph node labels -> stage keys for timing
NODE_STAGE_MAP = {
    "market_start": "market_report",
    "social_start": "sentiment_report",
    "news_start": "news_report",
    "fundamentals_start": "fundamentals_report",
    "valuation_start": "valuation_report",  # Valuation runs in parallel
    "research_manager": "investment_plan",
    "risky_analyst": "risk_debate_state",
    "neutral_analyst": "risk_debate_state",
    "safe_analyst": "risk_debate_state",
    "risk_judge": "final_trade_decision",
}


def _has_meaningful_content(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, (list, dict)):
        return len(value) > 0
    return True

def build_config(request: AnalysisRequest) -> Dict[str, Any]:
    """Build TradingAgents configuration from request"""
    config = DEFAULT_CONFIG.copy()
    
    # Update LLM config if provided
    if request.llm_config:
        config["deep_think_llm"] = request.llm_config.deep_think_llm
        config["quick_think_llm"] = request.llm_config.quick_think_llm
        config["max_debate_rounds"] = request.llm_config.max_debate_rounds
        config["max_risk_discuss_rounds"] = request.llm_config.max_risk_discuss_rounds
        config["llm_provider"] = request.llm_config.provider
        if request.llm_config.base_url:
            config["backend_url"] = request.llm_config.base_url
        if request.llm_config.api_key:
            config["llm_api_key"] = request.llm_config.api_key
    
    # Update data vendor config if provided
    if request.data_vendor_config:
        config["data_vendors"] = {
            "core_stock_apis": request.data_vendor_config.core_stock_apis,
            "technical_indicators": request.data_vendor_config.technical_indicators,
            "fundamental_data": request.data_vendor_config.fundamental_data,
            "news_data": request.data_vendor_config.news_data,
        }
    
    return config

def extract_summary_table(text: str) -> Optional[str]:
    """Extract the first markdown table block from text"""
    lines = [ln.rstrip() for ln in text.splitlines()]
    tables = []
    current: List[str] = []
    for line in lines:
        if line.strip().startswith("|") and "|" in line.strip()[1:]:
            current.append(line)
        else:
            if len(current) >= 2:
                tables.append("\n".join(current))
            current = []
    if len(current) >= 2:
        tables.append("\n".join(current))
    return tables[0] if tables else None


def extract_transaction_proposal(text: str) -> Optional[str]:
    """Extract final transaction proposal label from text"""
    match = re.search(r"FINAL\s+(?:TRANSACTION|TRADE)\s+PROPOSAL[:\s\-]*\*{0,2}([A-Z\s]+)\*?", text, re.IGNORECASE)
    if match:
        proposal = match.group(1).strip(" *").strip()
        if proposal:
            return proposal.upper()
    return None


def extract_decision_info(decision_data: Any) -> TradingDecision:
    """Extract and structure trading decision information"""
    
    # Handle case where decision is a string (common TradingAgents output)
    if isinstance(decision_data, str):
        # Try to parse JSON first
        try:
            parsed = json.loads(decision_data)
            decision_data = parsed  # fall through to dict handling below
        except Exception:
            decision_text = decision_data.upper()
            # Prefer explicit "final" markers before generic word presence to avoid false matches
            action = "HOLD"
            final_match = re.search(
                r"(FINAL\s+(?:TRANSACTION|TRADE)\s+PROPOSAL|FINAL\s+DECISION|RECOMMENDATION)[:\s\*]*\**(BUY|SELL|HOLD)\**",
                decision_text,
                re.IGNORECASE,
            )
            if final_match:
                action = final_match.group(2).upper()
            else:
                # Fallback: look for standalone BUY/SELL/HOLD tokens and pick the first found in priority order
                for token in ["BUY", "SELL", "HOLD"]:
                    if re.search(rf"\b{token}\b", decision_text):
                        action = token
                        break
            
            # Estimate confidence based on explicit numbers or language strength
            confidence: Optional[float] = None
            percent_match = re.search(r"CONFIDENCE[:\s]*([0-9]+(?:\.[0-9]+)?)\s*%?", decision_data, re.IGNORECASE)
            if percent_match:
                try:
                    value = float(percent_match.group(1))
                    confidence = value / 100 if value > 1 else value
                except ValueError:
                    confidence = None

            if confidence is None:
                baseline = 0.6  # neutral default
                if any(word in decision_text for word in ["STRONG", "HIGHLY", "VERY", "COMPELLING", "CONFIDENT"]):
                    baseline += 0.2
                if any(word in decision_text for word in ["WEAK", "CAUTIOUS", "UNCERTAIN", "RISKY", "DOUBTFUL"]):
                    baseline -= 0.2
                confidence = max(0.1, min(0.95, baseline))
            
            return TradingDecision(
                action=action,
                confidence=confidence,
                raw_decision={"decision_text": decision_data}
            )
    
    # Handle case where decision is a dict
    elif isinstance(decision_data, dict):
        action = decision_data.get("final_recommendation") or decision_data.get("action", "HOLD")
        # Prefer adjusted_conviction, then conviction, then confidence; default 0.5
        confidence = decision_data.get("adjusted_conviction", None)
        if confidence is None:
            confidence = decision_data.get("conviction", None)
        if confidence is None:
            confidence = decision_data.get("confidence", 0.5)
        try:
            confidence = float(confidence)
        except Exception:
            confidence = 0.5
        
        return TradingDecision(
            action=action,
            confidence=confidence,
            position_size=decision_data.get("position_size"),
            raw_decision=decision_data
        )
    
    # Fallback
    else:
        logger.warning(f"Unexpected decision format: {type(decision_data)}")
        return TradingDecision(
            action="HOLD",
            confidence=0.0,
            raw_decision={"raw": str(decision_data)}
        )


def extract_analysis_report(state: Any) -> Tuple[Dict[str, Any], Dict[str, AgentKeyOutput]]:
    """Extract complete analysis report from TradingAgents state along with key outputs"""
    report: Dict[str, Any] = {}
    key_outputs: Dict[str, AgentKeyOutput] = {}
    
    try:
        if isinstance(state, dict):
            report = {
                "market_report": state.get("market_report"),
                "sentiment_report": state.get("sentiment_report"),
                "news_report": state.get("news_report"),
                "fundamentals_report": state.get("fundamentals_report"),
                "valuation_report": state.get("valuation_report"),
                "investment_plan": state.get("investment_plan"),
                "risk_debate_state": state.get("risk_debate_state"),
                "final_trade_decision": state.get("final_trade_decision"),
                # legacy fields kept for backward compatibility
                "fundamental_analysis": state.get("fundamental_analysis"),
                "sentiment_analysis": state.get("sentiment_analysis"),
                "technical_analysis": state.get("technical_analysis"),
                "news_analysis": state.get("news_analysis"),
                "bull_researcher": state.get("bull_researcher"),
                "bear_researcher": state.get("bear_researcher"),
                "trader_analysis": state.get("trader_analysis"),
                "risk_assessment": state.get("risk_assessment"),
                "portfolio_manager": state.get("portfolio_manager"),
                "messages": state.get("messages"),
                "raw_state": state
            }

            # Derive key outputs for string-based reports
            for stage_key, content in list(report.items()):
                if not content or not isinstance(content, str):
                    continue
                summary_table = extract_summary_table(content) or None
                transaction_proposal = extract_transaction_proposal(content) or None
                if summary_table or transaction_proposal:
                    key_outputs[stage_key] = AgentKeyOutput(
                        summary_table=summary_table,
                        transaction_proposal=transaction_proposal
                    )

            # Remove None values from main report
            report = {k: v for k, v in report.items() if v is not None}

            # Embed key outputs for clients that only read analysis_report
            if key_outputs:
                report["__key_outputs"] = {k: v.dict(exclude_none=True) for k, v in key_outputs.items()}
        else:
            report = {"raw_state": str(state)}
    except Exception as e:
        logger.error(f"Error extracting analysis report: {e}")
        report = {"error": str(e), "raw_state": str(state)}
    
    return report, {k: v for k, v in key_outputs.items()}


async def run_analysis_async(task_id: str, request: AnalysisRequest):
    """Run trading analysis (background task) with incremental updates"""
    try:
        logger.info(f"Starting analysis for task {task_id}: {request.ticker} on {request.date}")
        
        # Update task status
        analysis_tasks[task_id]["status"] = TaskStatus.PROCESSING
        stage_times: Dict[str, float] = {}
        state_accumulator: Dict[str, Any] = {}

        start_time = datetime.now()
        
        # Build configuration
        config = build_config(request)
        
        # Initialize TradingAgents
        ta = TradingAgentsGraph(debug=False, config=config)

        # Build initial state/args so we can stream updates
        init_state = ta.propagator.create_initial_state(request.ticker, request.date)
        graph_args = ta.propagator.get_graph_args()
        last_state: Any = None

        async def run_and_stream():
            nonlocal last_state
            async for chunk in ta.graph.astream(init_state, **graph_args):
                if isinstance(chunk, dict):
                    state_accumulator.update(chunk)
                    last_state = dict(state_accumulator)
                else:
                    last_state = chunk
                analysis_report, key_outputs = extract_analysis_report(last_state)
                now = datetime.now()
                elapsed = (now - start_time).total_seconds()

                if isinstance(analysis_report, dict):
                    analysis_report["__total_elapsed"] = elapsed
                    # Simple timing extraction: get start/end for each stage from timing markers
                    stage_starts: Dict[str, float] = {}
                    stage_ends: Dict[str, float] = {}
                    
                    # Extract timing markers from state
                    for k, v in list(last_state.items()):
                        if isinstance(k, str) and k.startswith("__stage_starts."):
                            node = k.split(".", 1)[1]
                            stage = NODE_STAGE_MAP.get(node)
                            if stage:
                                try:
                                    start_ts = float(v) - start_time.timestamp()
                                    # For parallel analyst stages, each node maps to unique stage - use directly
                                    # For non-parallel stages, take earliest start
                                    if stage not in stage_starts or (stage in PARALLEL_ANALYST_STAGES and NODE_STAGE_MAP.get(node) == stage):
                                        stage_starts[stage] = start_ts
                                    elif stage not in PARALLEL_ANALYST_STAGES and start_ts < stage_starts.get(stage, float('inf')):
                                        stage_starts[stage] = start_ts
                                except Exception:
                                    pass
                        elif isinstance(k, str) and k.startswith("__stage_ends."):
                            node = k.split(".", 1)[1]
                            stage = NODE_STAGE_MAP.get(node)
                            if stage:
                                try:
                                    end_ts = float(v) - start_time.timestamp()
                                    # For parallel analyst stages, each node maps to unique stage - use directly
                                    # For non-parallel stages, take latest end
                                    if stage not in stage_ends or (stage in PARALLEL_ANALYST_STAGES and NODE_STAGE_MAP.get(node) == stage):
                                        stage_ends[stage] = end_ts
                                    elif stage not in PARALLEL_ANALYST_STAGES and end_ts > stage_ends.get(stage, 0):
                                        stage_ends[stage] = end_ts
                                except Exception:
                                    pass
                    
                    # Calculate durations: end - start (non-cumulative, independent per stage)
                    for stage_key in STAGE_ORDER:
                        start_ts = stage_starts.get(stage_key)
                        end_ts = stage_ends.get(stage_key)
                        
                        if start_ts is not None and end_ts is not None:
                            # Simple calculation: duration = end - start
                            stage_times[stage_key] = max(end_ts - start_ts, 0.0)
                        elif start_ts is not None and _has_meaningful_content(analysis_report.get(stage_key)):
                            # If we have start but no end yet, and content exists, estimate duration
                            # This allows showing progress during processing
                            estimated_duration = max(elapsed - start_ts, 0.0)
                            stage_times[stage_key] = estimated_duration

                    analysis_report["__stage_times"] = stage_times.copy()
                    
                    # Debug log timing info
                    if stage_times:
                        logger.debug(f"[Timing Update] stage_times={stage_times}, starts={stage_starts}, ends={stage_ends}")
                    
                analysis_tasks[task_id].update({
                    "status": TaskStatus.PROCESSING,
                    "analysis_report": analysis_report,
                    "key_outputs": {k: v.dict(exclude_none=True) for k, v in key_outputs.items()} or None,
                    "stage_times": stage_times.copy() if stage_times else None,
                    "updated_at": datetime.now().isoformat()
                })
            return last_state

        final_state = await run_and_stream()
        if final_state is None:
            raise RuntimeError("Analysis pipeline produced no state")

        decision = final_state.get("final_trade_decision")
        end_time = datetime.now()
        processing_time = (end_time - start_time).total_seconds()

        # Extract decision information
        trading_decision = extract_decision_info(decision)

        # Extract complete analysis report from state
        analysis_report, key_outputs = extract_analysis_report(final_state)
        total_elapsed = (end_time - start_time).total_seconds()
        
        if isinstance(analysis_report, dict):
            # Final timing extraction from final state
            stage_starts: Dict[str, float] = {}
            stage_ends: Dict[str, float] = {}
            
            # Extract all timing markers from final state
            for k, v in list(final_state.items()):
                if isinstance(k, str) and k.startswith("__stage_starts."):
                    node = k.split(".", 1)[1]
                    stage = NODE_STAGE_MAP.get(node)
                    if stage:
                        try:
                            start_ts = float(v) - start_time.timestamp()
                            if stage not in stage_starts or (stage in PARALLEL_ANALYST_STAGES and NODE_STAGE_MAP.get(node) == stage):
                                stage_starts[stage] = start_ts
                            elif stage not in PARALLEL_ANALYST_STAGES and start_ts < stage_starts.get(stage, float('inf')):
                                stage_starts[stage] = start_ts
                        except Exception:
                            pass
                elif isinstance(k, str) and k.startswith("__stage_ends."):
                    node = k.split(".", 1)[1]
                    stage = NODE_STAGE_MAP.get(node)
                    if stage:
                        try:
                            end_ts = float(v) - start_time.timestamp()
                            if stage not in stage_ends or (stage in PARALLEL_ANALYST_STAGES and NODE_STAGE_MAP.get(node) == stage):
                                stage_ends[stage] = end_ts
                            elif stage not in PARALLEL_ANALYST_STAGES and end_ts > stage_ends.get(stage, 0):
                                stage_ends[stage] = end_ts
                        except Exception:
                            pass
            
            # Calculate final durations: end - start (simple, non-cumulative)
            for stage_key in STAGE_ORDER:
                if not _has_meaningful_content(analysis_report.get(stage_key)):
                    continue
                    
                start_ts = stage_starts.get(stage_key)
                end_ts = stage_ends.get(stage_key)
                
                if start_ts is not None and end_ts is not None:
                    # Simple calculation: duration = end - start
                    stage_times[stage_key] = max(end_ts - start_ts, 0.0)
                elif start_ts is not None:
                    # Fallback: if we have start but no end, use total_elapsed - start_ts
                    stage_times[stage_key] = max(total_elapsed - start_ts, 0.0)
                # If no timing data, skip (don't set duration)

            analysis_report["__stage_times"] = stage_times.copy()
            analysis_report["__total_elapsed"] = total_elapsed

        # Ensure stage_times is always a dict
        if not stage_times:
            stage_times = {}

        # Update task with results
        analysis_tasks[task_id].update({
            "status": TaskStatus.COMPLETED,
            "decision": trading_decision,
            "analysis_report": analysis_report,
            "key_outputs": {k: v.dict(exclude_none=True) for k, v in key_outputs.items()} or None,
            "stage_times": stage_times,
            "completed_at": end_time.isoformat(),
            "processing_time_seconds": processing_time
        })

        logger.info(f"Completed analysis for task {task_id} in {processing_time:.2f}s")
        
    except Exception as e:
        logger.error(f"Error in analysis task {task_id}: {str(e)}", exc_info=True)
        analysis_tasks[task_id].update({
            "status": TaskStatus.FAILED,
            "error": str(e),
            "completed_at": datetime.now().isoformat()
        })


# ======================== API Endpoints ========================

@app.get("/", response_model=Dict[str, str])
async def root():
    """Root endpoint"""
    return {
        "service": "TradingAgents Microservice",
        "version": "1.0.0",
        "docs": "/docs"
    }


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    return HealthResponse(
        status="healthy",
        service="tradingagents-service",
        version="1.0.0",
        timestamp=datetime.now().isoformat()
    )


@app.post("/api/v1/analyze", response_model=AnalysisResponse, status_code=status.HTTP_202_ACCEPTED)
async def analyze_stock(request: AnalysisRequest, background_tasks: BackgroundTasks):
    """
    Initiate trading analysis for a stock
    
    This endpoint starts an asynchronous analysis task and returns immediately.
    Use the task_id to check the status and retrieve results.
    """
    task_id = str(uuid.uuid4())
    
    # Create task record
    analysis_tasks[task_id] = {
        "task_id": task_id,
        "status": TaskStatus.PENDING,
        "ticker": request.ticker,
        "date": request.date,
        "created_at": datetime.now().isoformat(),
        "decision": None,
        "analysis_report": None,
        "key_outputs": None,
        "stage_times": None,
        "error": None,
        "completed_at": None,
        "processing_time_seconds": None
    }
    
    # Add background task
    background_tasks.add_task(lambda: asyncio.run(run_analysis_async(task_id, request)))
    
    return AnalysisResponse(**analysis_tasks[task_id])


@app.post("/api/v1/analyze/sync", response_model=AnalysisResponse)
async def analyze_stock_sync(request: AnalysisRequest):
    """
    Synchronous trading analysis (blocking)
    
    This endpoint waits for the analysis to complete before returning.
    Use this for testing or when immediate results are needed.
    Warning: May take several minutes to complete.
    """
    task_id = str(uuid.uuid4())
    
    # Create task record
    analysis_tasks[task_id] = {
        "task_id": task_id,
        "status": TaskStatus.PENDING,
        "ticker": request.ticker,
        "date": request.date,
        "created_at": datetime.now().isoformat(),
        "decision": None,
        "analysis_report": None,
        "key_outputs": None,
        "stage_times": None,
        "error": None,
        "completed_at": None,
        "processing_time_seconds": None
    }
    
    # Run analysis synchronously
    await run_analysis_async(task_id, request)
    
    return AnalysisResponse(**analysis_tasks[task_id])


@app.get("/api/v1/analysis/{task_id}", response_model=AnalysisResponse)
async def get_analysis_result(task_id: str):
    """Get analysis result by task ID"""
    if task_id not in analysis_tasks:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found"
        )
    
    return AnalysisResponse(**analysis_tasks[task_id])


@app.get("/api/v1/tasks")
async def list_tasks(limit: int = 10):
    """List recent analysis tasks"""
    tasks = list(analysis_tasks.values())[-limit:]
    return {
        "tasks": tasks,
        "total": len(tasks)
    }


@app.delete("/api/v1/analysis/{task_id}")
async def delete_task(task_id: str):
    """Delete an analysis task"""
    if task_id not in analysis_tasks:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found"
        )
    
    del analysis_tasks[task_id]
    return {"message": f"Task {task_id} deleted"}


@app.get("/api/v1/config", response_model=Dict[str, Any])
async def get_default_config():
    """Get default TradingAgents configuration"""
    return {
        "llm_config": {
            "deep_think_llm": DEFAULT_CONFIG["deep_think_llm"],
            "quick_think_llm": DEFAULT_CONFIG["quick_think_llm"],
            "max_debate_rounds": DEFAULT_CONFIG["max_debate_rounds"],
            "max_risk_discuss_rounds": DEFAULT_CONFIG["max_risk_discuss_rounds"]
        },
        "data_vendors": DEFAULT_CONFIG["data_vendors"]
    }


# ======================== Run Server ========================

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("TRADING_SERVICE_PORT", "8001"))
    
    logger.info(f"Starting TradingAgents microservice on port {port}")
    
    uvicorn.run(
        "trading_service:app",
        host="0.0.0.0",
        port=port,
        reload=True,
        log_level="info"
    )
