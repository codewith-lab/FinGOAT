import json
from mcp_server import pm_directional_score


def create_research_manager(llm, memory):
    def research_manager_node(state) -> dict:
        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        valuation_report = state["valuation_report"]

        curr_situation = (
            f"{market_research_report}\n\n{sentiment_report}\n\n{news_report}\n\n{fundamentals_report}\n\n{valuation_report}"
        )
        past_memories = memory.get_memories(curr_situation, n_matches=2)
        past_memory_str = "\n".join(rec["recommendation"] for rec in past_memories)

        def _extract_analyst(report_raw, name):
            try:
                obj = json.loads(report_raw) if isinstance(report_raw, str) else report_raw
            except Exception:
                obj = None
            if not isinstance(obj, dict):
                return None
            rec = obj.get("recommendation")
            conviction = obj.get("conviction")
            if rec is None or conviction is None:
                return None
            try:
                conviction = float(conviction)
            except Exception:
                return None
            return {
                "analyst": name,
                "recommendation": rec,
                "conviction": conviction,
            }

        analysts_for_pm = []
        for name, report in [
            ("Technical", market_research_report),
            ("Social/Sentiment", sentiment_report),
            ("News", news_report),
            ("Fundamental", fundamentals_report),
            ("Valuation", valuation_report),
        ]:
            parsed = _extract_analyst(report, name)
            if parsed:
                analysts_for_pm.append(parsed)
  
        pm_result = pm_directional_score(None, analysts=analysts_for_pm)
        try:
            pm_result_str = json.dumps(pm_result)
        except Exception:
            pm_result_str = str(pm_result)

        prompt = f"""You are the PM Engine, aggregating analyst outputs into a single JSON. Use ONLY the provided analyst reports (market/technical, social/sentiment, news, fundamentals, valuation).

Return JSON exactly in this schema (no markdown, no extra text):
{{ 
  "module": "AnalystAggregation",
  "summary": {{
    "overall_signal": "<Bullish | Bearish | Mixed>",
    "bullish_strength": 0.0,
    "bearish_strength": 0.0,
    "conflict_level": 0.0,
    "interpretation": ""
  }},
  "bullish_indicators": [{{"indicator": "", "source_analyst": "", "conviction": 0.0}}, ...],
  "bearish_indicators": [{{"indicator": "", "source_analyst": "", "conviction": 0.0}}, ...],
  "conflicting_indicators": [
    {{
      "topic": "",
      "bullish_evidence": "",
      "bearish_evidence": "",
      "analysts_involved": ["", ""]
    }}
  ],
  "pm_direction": "<Buy|Hold|Sell>",
  "pm_composite_score": 0.0,
  "pm_base_conviction": 0.0,
  "pm_threshold": 0.33,
  "pm_inputs": [
    {{"analyst": "", "recommendation": "<Buy|Hold|Sell>", "conviction": 0.0, "weight": 0.0, "signal": 0.0}}
  ]
}}

 Instructions:
 - Derive bullish/bearish strengths in [0,1] from analyst convictions; conflict_level in [0,1] based on divergence.
 - For PM inputs, extract each analyst's recommendation and conviction; if missing, infer conservatively. Set weights w_i in [0,1] (default equal weights) with Σ w_i = 1.
 - Prefer using MCP/math tools for arithmetic; otherwise use the simple rule: map recommendation to s_i (Buy=+1, Hold=+0.2, Sell=-1), compute S = (Σ w_i * c_i * s_i) / (Σ w_i * c_i) (if denominator=0, set S=0), threshold θ=0.33 → pm_direction (Buy if S ≥ θ; Sell if S ≤ -θ; else Hold). Output pm_composite_score=S, pm_threshold=θ.
 - PM base conviction C_PM = max(bullish_strength, bearish_strength); cap to [0,1], round to two decimals. Output pm_base_conviction=C_PM.
 - Use this precomputed PM scoring (from the MCP tool) as your primary calculation and reflect it in the output: {pm_result_str}
 - Interpretation must explain why views align/conflict.
 - Use at least 2 bullish_indicators and 2 bearish_indicators when present.
 - Use past reflections if relevant: {past_memory_str}

Analyst reports to ingest:
- Market/Technical: {market_research_report}
- Social/Sentiment: {sentiment_report}
- News: {news_report}
- Fundamentals: {fundamentals_report}
- Valuation: {valuation_report}
"""

        response = llm.invoke(prompt)
        raw = response.content or ""

        aggregation_obj = None
        try:
            aggregation_obj = json.loads(raw)
        except Exception:
            aggregation_obj = None

        if isinstance(aggregation_obj, dict):
            summary = aggregation_obj.get("summary", {}) or {}
            aggregation_obj["summary"] = summary
            if "bullish_strength" in pm_result:
                summary["bullish_strength"] = pm_result.get("bullish_strength", summary.get("bullish_strength", 0.0))
            if "bearish_strength" in pm_result:
                summary["bearish_strength"] = pm_result.get("bearish_strength", summary.get("bearish_strength", 0.0))
            if "hold_strength" in pm_result:
                aggregation_obj["hold_strength"] = pm_result.get("hold_strength")
            aggregation_obj["pm_direction"] = pm_result.get("pm_direction")
            aggregation_obj["pm_composite_score"] = pm_result.get("pm_composite_score")
            aggregation_obj["pm_base_conviction"] = pm_result.get("pm_base_conviction")
            aggregation_obj["pm_threshold"] = pm_result.get("pm_threshold")
            aggregation_obj["pm_inputs"] = pm_result.get("pm_inputs")
            try:
                aggregation = json.dumps(aggregation_obj)
            except Exception:
                aggregation = raw
        else:
            aggregation = raw

        new_investment_debate_state = {
            "judge_decision": aggregation,
            "history": "",
            "bear_history": "",
            "bull_history": "",
            "current_response": aggregation,
            "count": 0,
        }

        return {
            "investment_debate_state": new_investment_debate_state,
            "investment_plan": aggregation,
        }

    return research_manager_node
