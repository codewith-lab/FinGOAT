import time
import json


def create_risk_manager(llm, memory):
    def risk_manager_node(state) -> dict:

        company_name = state["company_of_interest"]
        risk_debate_state = state["risk_debate_state"]
        market_research_report = state["market_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        sentiment_report = state["sentiment_report"]
        valuation_report = state["valuation_report"]
        investment_plan = state["investment_plan"]

        pm_conflict = "unknown"
        pm_bull = "unknown"
        pm_bear = "unknown"
        pm_base_conviction = "0.5 (default)"
        pm_direction = "Hold"
        investment_plan_str = ""

        # Try to parse the PM Engine output so we can give the LLM concrete numbers
        if isinstance(investment_plan, str):
            investment_plan_str = investment_plan
            try:
                plan_obj = json.loads(investment_plan)
            except Exception:
                plan_obj = None
        elif isinstance(investment_plan, dict):
            plan_obj = investment_plan
            try:
                investment_plan_str = json.dumps(investment_plan)
            except Exception:
                investment_plan_str = str(investment_plan)
        else:
            plan_obj = None

        if isinstance(plan_obj, dict):
            pm_conflict_val = plan_obj.get("summary", {}).get("conflict_level")
            pm_bull_val = plan_obj.get("summary", {}).get("bullish_strength")
            pm_bear_val = plan_obj.get("summary", {}).get("bearish_strength")
            pm_dir_val = plan_obj.get("pm_direction") or plan_obj.get("pm_recommendation")
            if isinstance(pm_conflict_val, (int, float)):
                pm_conflict = float(pm_conflict_val)
            if isinstance(pm_bull_val, (int, float)):
                pm_bull = float(pm_bull_val)
            if isinstance(pm_bear_val, (int, float)):
                pm_bear = float(pm_bear_val)
            if isinstance(pm_dir_val, str) and pm_dir_val.strip():
                pm_direction = pm_dir_val.strip()
            if isinstance(pm_bull, (int, float)) and isinstance(pm_bear, (int, float)):
                pm_base_conviction_val = max(pm_bull, pm_bear)
                pm_base_conviction = pm_base_conviction_val
        if isinstance(pm_base_conviction, str):
            pm_base_conviction = 0.5

        curr_situation = f"{market_research_report}\n\n{sentiment_report}\n\n{news_report}\n\n{fundamentals_report}"
        past_memories = memory.get_memories(curr_situation, n_matches=2)

        past_memory_str = ""
        for i, rec in enumerate(past_memories, 1):
            past_memory_str += rec["recommendation"] + "\n\n"

        prompt = f"""You are the Risk Manager for a single-stock review. Evaluate risks and adjust the PM Engine conviction using the required formula. Use only the provided evidence.

PM Engine summary (use as priors):
- Bullish strength: {pm_bull}
- Bearish strength: {pm_bear}
- Conflict level (D): {pm_conflict}
- Base conviction from PM Engine (C_PM): {pm_base_conviction}
- PM recommendation (do NOT change it): {pm_direction}
- Full PM Engine output: {investment_plan_str}

Risk evaluation requirements (cover all):
1) Company-Specific Risk → Rate Low/Medium/High; produce risk factor R_c in [0,1]. Consider volatility, beta, balance sheet (debt vs cash), earnings stability, news controversy/headlines, analyst disagreement (conflict score).
2) Valuation Uncertainty → Based on DCF sensitivity to WACC/terminal value, range of fair values, input accuracy. Output valuation_uncertainty score in [0,1].
3) Sentiment & Narrative Risk → Consider negative news cycles, insider selling, regulatory/litigation risk, social sentiment volatility. Output sentiment risk score in [0,1].
4) Macro / Sector Volatility → Sector volatility, macro alignment, and near-term events (CPI, FOMC, earnings). Output macro risk warning (or 'None').
5) Disagreement Among Analysts → Use conflict score: D = conflict_level if present; otherwise infer from PM outputs.

Single-Stock Risk Adjustment Formula (apply every factor above):
C_final = C_PM * (1 - company_specific_risk) * (1 - Valuation_Uncertainty) * (1 - sentiment_risk) * (1 - macro_risk) * (1 - D)
- D = disagreement/conflict factor in [0,1] (use conflict_level; otherwise infer divergence across analysts).
- Use C_PM = max(bullish_strength, bearish_strength) when available; otherwise pick a justified base conviction.
- Keep all values between 0 and 1; round to two decimals where reasonable.

Data you can use:
- Market/Technical: {market_research_report}
- Social/Sentiment: {sentiment_report}
- News: {news_report}
- Fundamentals: {fundamentals_report}
- Valuation: {valuation_report}
- Past lessons: {past_memory_str}

Return STRICT JSON only (no markdown) in this shape:
{{
  "risk_level": "<Low|Medium|High>",
  "original_conviction": <float>,
  "adjusted_conviction": <float>,
  "risk_factor_rc": <float>,
  "risk_factor_rm": <float>,
  "disagreement": <float>,
  "valuation_uncertainty": <float>,
  "sentiment_risk_score": <float>,
  "macro_risk_warning": "<string or 'None'>",
  "final_recommendation": "<Buy|Hold|Sell>",
  "risk_factors": {{
    "company_specific": "",
    "volatility_risk": "",
    "valuation_uncertainty": "",
    "sentiment_risk": "",
    "analyst_disagreement": ""
  }},
  "recommendation_adjustment": "",
  "explanation": ""
}}

- Set risk_level based on adjusted_conviction and the assessed risks.
- final_recommendation MUST equal the PM recommendation: {pm_direction}. Do not change Buy/Hold/Sell, only adjust conviction.
- Make recommendation_adjustment explicit (e.g., de-risk to Hold, trim size) but keep final_recommendation unchanged.
- For each entry in risk_factors, include a brief rationale explaining why that factor/score was assigned.
- Be concise; no extra commentary outside the JSON."""

        response = llm.invoke(prompt)
        draft = response.content or ""

        reflection_prompt = f"""You are a verifier for the Risk Manager output. Check that the JSON is complete, consistent with the provided inputs, and all numeric fields are in [0,1] where applicable.

Inputs you must respect:
- Bullish strength: {pm_bull}
- Bearish strength: {pm_bear}
- Conflict level (D): {pm_conflict}
- Base conviction C_PM: {pm_base_conviction}

Rules:
- Keep the structure exactly as specified earlier (risk_level, original_conviction, adjusted_conviction, risk_factor_rc, risk_factor_rm, disagreement, valuation_uncertainty, sentiment_risk_score, macro_risk_warning, final_recommendation, risk_factors, recommendation_adjustment, explanation).
- final_recommendation MUST equal the PM recommendation: {pm_direction}. Do not change Buy/Hold/Sell.
- If any field is missing or obviously inconsistent, fix it.
- Clamp all numeric values to [0,1], round to two decimals where reasonable.
- Return ONLY the corrected JSON (no markdown, no extra text).

Draft JSON to correct:
{draft}
"""

        try:
            reflection = llm.invoke(reflection_prompt)
            final_output = reflection.content or draft
        except Exception:
            final_output = draft

        # Normalize to a dict (avoid markdown/escaped JSON from LLM)
        decision_dict: Dict[str, Any]
        parsed = None
        try:
            parsed = json.loads(final_output)
        except Exception:
            parsed = None

        if isinstance(parsed, dict):
            decision_dict = parsed
        else:
            # Fallback: use the draft JSON (already a dict) or wrap in a minimal structure
            try:
                draft_parsed = json.loads(draft)
                decision_dict = draft_parsed if isinstance(draft_parsed, dict) else {}
            except Exception:
                decision_dict = {}

        # Ensure required fields are present
        decision_dict["final_recommendation"] = pm_direction
        if "adjusted_conviction" not in decision_dict and "conviction" not in decision_dict:
            decision_dict["adjusted_conviction"] = pm_base_conviction

        final_output = decision_dict

        new_risk_debate_state = {
            "judge_decision": final_output,
            "history": "",
            "risky_history": "",
            "safe_history": "",
            "neutral_history": "",
            "latest_speaker": "Judge",
            "current_risky_response": "",
            "current_safe_response": "",
            "current_neutral_response": "",
            "count": 0,
        }

        return {
            "risk_debate_state": new_risk_debate_state,
            "final_trade_decision": final_output,
        }

    return risk_manager_node
