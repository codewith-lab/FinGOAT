import { useEffect, useMemo, useState } from 'react'
import type { AnalysisTask } from '../services/tradingService'
import {
  AGENT_STAGES,
  buildStageProgress,
  firstStageWithContent,
  type AgentStageKey,
} from './agentStages'

interface AgentResultsModuleProps {
  task?: AnalysisTask | null
  selectedStageKey?: AgentStageKey | null
  onStageChange?: (stage: AgentStageKey) => void
}

const formatContent = (value: unknown) => {
  if (value === null || value === undefined) return null
  if (typeof value === 'object') {
    try {
      return JSON.stringify(value, null, 2)
    } catch {
      return String(value)
    }
  }
  return String(value)
}

const formatDuration = (seconds?: number) => {
  if (seconds === undefined) return ''
  if (seconds < 10) return `${seconds.toFixed(1)}s`
  if (seconds < 60) return `${Math.round(seconds)}s`
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}m ${s}s`
}

const clipText = (value: unknown, max = 180) => {
  if (value === null || value === undefined) return ''
  const str = String(value).replace(/\s+/g, ' ').trim()
  if (str.length <= max) return str
  return `${str.slice(0, max - 1)}…`
}

type ParsedTable = { headers: string[]; rows: string[][] }

const parseMarkdownTable = (table?: string | null): ParsedTable | null => {
  if (!table) return null
  const lines = table
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.startsWith('|') && line.includes('|'))
  if (lines.length < 2) return null

  const toCells = (line: string) =>
    line
      .replace(/^\|/, '')
      .replace(/\|$/, '')
      .split('|')
      .map((cell) => cell.trim())

  const headers = toCells(lines[0])
  const dataLines = lines.slice(2) // skip separator
  const rows = dataLines.map((line) => toCells(line))
  return { headers, rows }
}

type ChartPoint = { x: number; y: number; label?: string }
type ChartSeries = { name: string; points: ChartPoint[] }

const toNumber = (val: unknown): number | null => {
  if (typeof val === 'number' && !Number.isNaN(val)) return val
  if (typeof val === 'string') {
    const n = Number(val)
    return Number.isFinite(n) ? n : null
  }
  return null
}

const extractSeries = (content: unknown): ChartSeries[] => {
  if (!content || typeof content !== 'object') return []
  const obj = content as Record<string, any>
  const candidates: any[] = []

  if (Array.isArray(obj.prices)) candidates.push({ name: 'Price', data: obj.prices })
  if (obj.market_data && Array.isArray(obj.market_data.prices)) {
    candidates.push({ name: 'Price', data: obj.market_data.prices })
  }
  if (obj.price_series && Array.isArray(obj.price_series)) {
    candidates.push({ name: 'Price', data: obj.price_series })
  }

  if (candidates.length === 0 && Array.isArray(content)) {
    candidates.push({ name: 'Series', data: content })
  }

  const parsed: ChartSeries[] = []

  for (const candidate of candidates) {
    const data = candidate.data as any[]
    if (!Array.isArray(data) || data.length < 2) continue

    const points: ChartPoint[] = data
      .map((item, idx) => {
        if (typeof item === 'number') return { x: idx, y: item }
        if (typeof item !== 'object' || item === null) return null
        const value =
          toNumber((item as any).close ?? (item as any).price ?? (item as any).value ?? (item as any).y) ??
          (Array.isArray(item) ? toNumber(item[1]) : null)
        const xVal =
          toNumber((item as any).timestamp ?? (item as any).time ?? (item as any).date ?? (item as any).x) ??
          (Array.isArray(item) ? toNumber(item[0]) : null) ??
          idx
        if (value === null || xVal === null) return null
        return { x: xVal, y: value, label: (item as any).date ?? (item as any).timestamp ?? (item as any).time }
      })
      .filter(Boolean) as ChartPoint[]

    if (points.length < 2) continue
    parsed.push({ name: candidate.name ?? 'Series', points })
  }

  return parsed
}

const renderLineChart = (series: ChartSeries[]) => {
  if (series.length === 0) return null

  const allPoints = series.flatMap((s) => s.points)
  const xs = allPoints.map((p) => p.x)
  const ys = allPoints.map((p) => p.y)
  const minX = Math.min(...xs)
  const maxX = Math.max(...xs)
  const minY = Math.min(...ys)
  const maxY = Math.max(...ys)
  const padY = (maxY - minY || 1) * 0.1
  const yMin = minY - padY
  const yMax = maxY + padY
  const width = 100
  const height = 60

  const scaleX = (x: number) => ((x - minX) / (maxX - minX || 1)) * width
  const scaleY = (y: number) => height - ((y - yMin) / (yMax - yMin || 1)) * height

  const palette = ['#2563eb', '#22c55e', '#f59e0b', '#a855f7']

  return (
    <div className="agent-chart">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Price/indicator chart">
        {series.map((s, idx) => {
          const path = s.points
            .map((p, i) => `${i === 0 ? 'M' : 'L'} ${scaleX(p.x).toFixed(2)} ${scaleY(p.y).toFixed(2)}`)
            .join(' ')
          return (
            <path
              key={s.name}
              d={path}
              fill="none"
              stroke={palette[idx % palette.length]}
              strokeWidth={1.8}
              strokeLinejoin="round"
            />
          )
        })}
      </svg>
      <div className="agent-chart__legend">
        {series.map((s, idx) => (
          <span key={s.name} className="agent-chart__legend-item">
            <span
              className="agent-chart__legend-swatch"
              style={{ backgroundColor: palette[idx % palette.length] }}
              aria-hidden="true"
            />
            {s.name}
          </span>
        ))}
      </div>
    </div>
  )
}

type StructuredAnalystOutput = {
  analyst: string
  recommendation: 'Buy' | 'Hold' | 'Sell'
  conviction: number
  conviction_category?: 'Low' | 'Medium' | 'High' | string
  evidence_strength: number
  signal_clarity: number
  data_quality: number
  uncertainty_penalty: number
  key_factors: string[]
  risks: string[]
  overall_comment: string
  time_horizon: string
  confidence_level: 'Low' | 'Medium' | 'High'
  data_sources: string[]
}

type AnalystAggregation = {
  module: string
  summary: {
    overall_signal: string
    bullish_strength: number
    bearish_strength: number
    conflict_level: number
    interpretation: string
  }
  bullish_indicators: { indicator: string; source_analyst: string; conviction: number }[]
  bearish_indicators: { indicator: string; source_analyst: string; conviction: number }[]
  conflicting_indicators: {
    topic: string
    bullish_evidence: string
    bearish_evidence: string
    analysts_involved: string[]
  }[]
  pm_direction?: 'Buy' | 'Hold' | 'Sell'
  pm_composite_score?: number
  pm_base_conviction?: number
  pm_threshold?: number
  hold_strength?: number
  pm_inputs?: {
    analyst: string
    recommendation: 'Buy' | 'Hold' | 'Sell'
    conviction: number
    weight: number
    signal: number
  }[]
}

type RiskReview = {
  risk_level: 'Low' | 'Medium' | 'High' | string
  adjusted_conviction: number
  original_conviction: number
  risk_factor_rc: number
  risk_factor_rm: number
  disagreement: number
  valuation_reliability: number
  sentiment_risk_score: number
  macro_risk_warning: string
  risk_factors: {
    company_specific?: string
    volatility_risk?: string
    valuation_uncertainty?: string
    sentiment_risk?: string
    analyst_disagreement?: string
  }
  recommendation_adjustment?: string
  explanation?: string
}

const parseAnalystOutput = (content: unknown): StructuredAnalystOutput | null => {
  const normalizeRec = (val: unknown): StructuredAnalystOutput['recommendation'] | null => {
    if (typeof val !== 'string') return null
    const lower = val.trim().toLowerCase()
    if (lower === 'buy') return 'Buy'
    if (lower === 'sell') return 'Sell'
    if (lower === 'hold') return 'Hold'
    return null
  }

  const normalizeConfidence = (val: unknown): StructuredAnalystOutput['confidence_level'] | null => {
    if (typeof val !== 'string') return null
    const lower = val.trim().toLowerCase()
    if (lower === 'low') return 'Low'
    if (lower === 'medium') return 'Medium'
    if (lower === 'high') return 'High'
    return null
  }

  const maybeObj =
    typeof content === 'string'
      ? (() => {
          try {
            return JSON.parse(content)
          } catch {
            return null
          }
        })()
      : typeof content === 'object' && content !== null
        ? content
        : null

  if (!maybeObj) return null
  const requiredKeys: (keyof StructuredAnalystOutput)[] = [
    'analyst',
    'recommendation',
    'conviction',
    'key_factors',
    'risks',
    'overall_comment',
    'time_horizon',
    'confidence_level',
    'data_sources',
  ]
  if (!requiredKeys.every((k) => k in maybeObj)) return null

  const recommendation = normalizeRec((maybeObj as any).recommendation)
  const confidenceLevel = normalizeConfidence((maybeObj as any).confidence_level)
  if (!recommendation || !confidenceLevel) return null


  const toNum = (v: unknown): number => {
    const n = Number(v)
    return Number.isFinite(n) ? n : 0
  }

  const conviction = Number((maybeObj as any).conviction) || 0
  let evidence_strength = toNum((maybeObj as any).evidence_strength)
  let signal_clarity = toNum((maybeObj as any).signal_clarity)
  let data_quality = toNum((maybeObj as any).data_quality)
  let uncertainty_penalty = toNum((maybeObj as any).uncertainty_penalty)

  const allZero =
    evidence_strength === 0 &&
    signal_clarity === 0 &&
    data_quality === 0 &&
    uncertainty_penalty === 0
  if (allZero && conviction > 0) {
    evidence_strength = conviction
    signal_clarity = conviction
    data_quality = conviction
    uncertainty_penalty = Math.max(0, Math.min(1, 1 - conviction))
  }

  return {
    analyst: String((maybeObj as any).analyst || ''),
    recommendation,
    conviction,
    evidence_strength,
    signal_clarity,
    data_quality,
    uncertainty_penalty,
    key_factors: Array.isArray((maybeObj as any).key_factors) ? (maybeObj as any).key_factors : [],
    risks: Array.isArray((maybeObj as any).risks) ? (maybeObj as any).risks : [],
    overall_comment: String((maybeObj as any).overall_comment ?? ''),
    time_horizon: String((maybeObj as any).time_horizon ?? ''),
    confidence_level: confidenceLevel,
    data_sources: Array.isArray((maybeObj as any).data_sources) ? (maybeObj as any).data_sources : [],
  } as StructuredAnalystOutput
}

const parseAggregation = (content: unknown): AnalystAggregation | null => {
  const maybeObj =
    typeof content === 'string'
      ? (() => {
          try {
            return JSON.parse(content)
          } catch {
            return null
          }
        })()
      : typeof content === 'object' && content !== null
        ? content
        : null
  if (!maybeObj || typeof (maybeObj as any).module !== 'string') return null
  if ((maybeObj as any).module !== 'AnalystAggregation') return null
  return maybeObj as AnalystAggregation
}

const parseRiskReview = (content: unknown): RiskReview | null => {
  const maybeObj =
    typeof content === 'string'
      ? (() => {
          try {
            return JSON.parse(content)
          } catch {
            return null
          }
        })()
      : typeof content === 'object' && content !== null
        ? content
        : null
  if (!maybeObj) return null
  const required = ['risk_level', 'adjusted_conviction', 'original_conviction', 'risk_factor_rc', 'risk_factor_rm']
  if (!required.every((k) => k in (maybeObj as any))) return null
  return maybeObj as RiskReview
}

export function AgentResultsModule({ task, selectedStageKey, onStageChange }: AgentResultsModuleProps) {
  const stages = useMemo(() => buildStageProgress(task), [task])
  const defaultStage = useMemo(
    () => selectedStageKey ?? firstStageWithContent(stages) ?? AGENT_STAGES[0]?.key,
    [stages, selectedStageKey],
  )

  const [selected, setSelected] = useState<AgentStageKey>(
    defaultStage ?? AGENT_STAGES[0].key,
  )
  const [factorsOpen, setFactorsOpen] = useState(true)
  const [risksOpen, setRisksOpen] = useState(true)

  const keyOutputs = useMemo(() => {
    const fromTask = task?.key_outputs as Record<string, any> | undefined
    const fromReport =
      (task as any)?.analysis_report?.__key_outputs as Record<string, any> | undefined
    return fromTask || fromReport || {}
  }, [task])

  useEffect(() => {
    if (selectedStageKey && stages.find((s) => s.key === selectedStageKey)) {
      setSelected(selectedStageKey)
    } else if (defaultStage) {
      setSelected(defaultStage)
    } else if (stages[0]) {
      setSelected(stages[0].key)
    }
  }, [defaultStage, stages, task?.task_id, selectedStageKey])

  useEffect(() => {
    onStageChange?.(selected)
  }, [onStageChange, selected])

  useEffect(() => {
    // Reset collapsibles when switching stages
    setFactorsOpen(true)
    setRisksOpen(true)
  }, [selected])

  const selectedStage = useMemo(
    () => stages.find((stage) => stage.key === selected) ?? stages[0],
    [stages, selected],
  )
  const selectedKeyOutput = useMemo(() => {
    if (!selectedStage) return undefined
    return keyOutputs[selectedStage.key] as { summary_table?: string; transaction_proposal?: string } | undefined
  }, [keyOutputs, selectedStage])
  const rawContent = selectedStage?.content
  const currentContent = formatContent(rawContent)
  const summaryTable = selectedKeyOutput?.summary_table
  const transactionProposal = selectedKeyOutput?.transaction_proposal
  const parsedTable = parseMarkdownTable(summaryTable)
  const selectedLabel = selectedStage?.displayLabel || selectedStage?.label
  const chartSeries = useMemo(() => extractSeries(rawContent), [rawContent])
  const structuredAnalyst = useMemo(() => parseAnalystOutput(rawContent), [rawContent])
  const aggregation = useMemo(() => parseAggregation(rawContent), [rawContent])
  const riskReview = useMemo(() => parseRiskReview(rawContent), [rawContent])

  if (!task) {
    return <p className="news-placeholder">No agent outputs yet. Run an analysis to view results.</p>
  }

  const renderContent = () => {
    if (!currentContent) {
      return <p className="news-placeholder">No content available for this agent yet.</p>
    }

    if (typeof rawContent === 'string') {
      return (
        <div className="agent-results__content agent-results__content--scroll">
          <pre>{rawContent}</pre>
        </div>
      )
    }

    return (
      <div className="agent-results__content agent-results__content--scroll">
        <pre>{currentContent}</pre>
      </div>
    )
  }

  return (
    <div className="agent-results">
        <div className="agent-results__panel">
        <div className="agent-results__panel-header">
          <h4 className="agent-results__title">{transactionProposal || selectedLabel || 'Agent Output'}</h4>
        </div>

        {parsedTable && (
          <div className="agent-summary-card">
            <div className="agent-summary-card__title">Key Summary</div>
            <div className="agent-summary-card__table" role="table">
              <div className="agent-summary-card__header" role="row">
                {parsedTable.headers.map((h, idx) => (
                  <div key={idx} className="agent-summary-card__cell agent-summary-card__cell--head" role="columnheader">
                    {h}
                  </div>
                ))}
              </div>
              <div className="agent-summary-card__body">
                {parsedTable.rows.map((row, ridx) => (
                  <div key={ridx} className="agent-summary-card__row" role="row">
                    {row.map((cell, cidx) => (
                      <div key={cidx} className="agent-summary-card__cell" role="cell">
                        {cell}
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {aggregation && (
          <div className="agent-structured-card">
            <div className="agent-structured-card__header">
              <div>
                <p className="agent-structured-card__eyebrow">
                  {aggregation.summary.overall_signal.toLowerCase() === 'mixed'
                    ? 'PM Engine'
                    : aggregation.summary.overall_signal}
                </p>
                <h5 className="agent-structured-card__title">
                  {aggregation.pm_direction
                    ? aggregation.pm_direction
                    : 'PM Engine'}
                </h5>
                <div className="agent-structured-card__inline-metrics">
                  {aggregation.pm_direction && (
                    <span className="agent-structured-card__badge-text">
                      {aggregation.pm_base_conviction !== undefined
                        ? `Base Conv ${aggregation.pm_base_conviction.toFixed(2)}`
                        : aggregation.pm_direction}
                    </span>
                  )}
                  <div className="agent-structured-card__mini-metrics">
                    <span>Bull {aggregation.summary.bullish_strength.toFixed(2)}</span>
                    <span>Bear {aggregation.summary.bearish_strength.toFixed(2)}</span>
                    {aggregation.hold_strength !== undefined && (
                      <span>Hold {aggregation.hold_strength.toFixed(2)}</span>
                    )}
                    <span>Conflict {aggregation.summary.conflict_level.toFixed(2)}</span>
                  </div>
                </div>
              </div>
            </div>
            <div className="agent-structured-card__grid">
              <div className="agent-collapsible">
                <p className="agent-structured-card__label">Bullish Indicators</p>
                <ul className="agent-structured-card__list">
                  {aggregation.bullish_indicators.map((item, idx) => (
                    <li key={idx}>
                      <strong>{item.source_analyst}</strong>: {item.indicator} ({item.conviction.toFixed(2)})
                    </li>
                  ))}
                </ul>
              </div>
              <div className="agent-collapsible">
                <p className="agent-structured-card__label">Bearish Indicators</p>
                <ul className="agent-structured-card__list">
                  {aggregation.bearish_indicators.map((item, idx) => (
                    <li key={idx}>
                      <strong>{item.source_analyst}</strong>: {item.indicator} ({item.conviction.toFixed(2)})
                    </li>
                  ))}
                </ul>
              </div>
            </div>
            {aggregation.conflicting_indicators?.length ? (
              <div className="agent-conflict">
                <p className="agent-structured-card__label">Conflicting Topics</p>
                <div className="agent-conflict-list">
                  {aggregation.conflicting_indicators.map((item, idx) => (
                    <div key={idx} className="agent-conflict-item">
                      <div className="agent-conflict-topic">{clipText(item.topic, 140)}</div>
                      <div className="agent-conflict-evidence">
                        <span className="agent-conflict-badge">Bullish</span>
                        <span className="agent-conflict-text">{clipText(item.bullish_evidence) || 'Not provided'}</span>
                      </div>
                      <div className="agent-conflict-evidence">
                        <span className="agent-conflict-badge agent-conflict-badge--bear">Bearish</span>
                        <span className="agent-conflict-text">{clipText(item.bearish_evidence) || 'Not provided'}</span>
                      </div>
                      {item.analysts_involved?.length ? (
                        <div className="agent-conflict-analysts">Analysts: {item.analysts_involved.join(', ')}</div>
                      ) : null}
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
            <div className="agent-collapsible">
              <p className="agent-structured-card__label">Overall Comment</p>
              <p className="agent-structured-card__text">{aggregation.summary.interpretation}</p>
            </div>
          </div>
        )}

        {!aggregation && structuredAnalyst && (
          <div className="agent-structured-card">
            <div className="agent-structured-card__header">
              <div>
                <p className="agent-structured-card__eyebrow">{structuredAnalyst.analyst}</p>
                <h5 className="agent-structured-card__title">
                  {structuredAnalyst.recommendation}
                </h5>
                <div className="agent-structured-card__inline-metrics">
                  <span className="agent-structured-card__badge-text">
                    {structuredAnalyst.confidence_level} · {(structuredAnalyst.conviction * 100).toFixed(0)}%
                  </span>
                </div>
              </div>
            {structuredAnalyst.time_horizon && (
              <div className="agent-structured-card__horizon">Horizon: {structuredAnalyst.time_horizon} mo</div>
            )}
          </div>
          <div className="agent-structured-card__grid">
            <div className="agent-collapsible">
              <button
                type="button"
                className="agent-collapsible__header"
                onClick={() => setFactorsOpen((open) => !open)}
                aria-expanded={factorsOpen}
              >
                <span className="agent-structured-card__label">Key Factors</span>
                <span className={`agent-collapsible__chevron ${factorsOpen ? 'is-open' : ''}`} aria-hidden="true">▾</span>
              </button>
              {factorsOpen && (
                <ul className="agent-structured-card__list">
                  {structuredAnalyst.key_factors.map((f, idx) => (
                    <li key={idx}>{f}</li>
                  ))}
                </ul>
              )}
            </div>
            <div className="agent-collapsible">
              <button
                type="button"
                className="agent-collapsible__header"
                onClick={() => setRisksOpen((open) => !open)}
                aria-expanded={risksOpen}
              >
                <span className="agent-structured-card__label">Risks</span>
                <span className={`agent-collapsible__chevron ${risksOpen ? 'is-open' : ''}`} aria-hidden="true">▾</span>
              </button>
              {risksOpen && (
                <ul className="agent-structured-card__list agent-structured-card__list--risk">
                  {structuredAnalyst.risks.map((r, idx) => (
                    <li key={idx}>{r}</li>
                  ))}
                </ul>
              )}
            </div>
          </div>
            {structuredAnalyst.overall_comment && structuredAnalyst.overall_comment !== 'N/A' && (
              <div className="agent-structured-card__note">
                <p className="agent-structured-card__label">Overall Comment</p>
                <p className="agent-structured-card__text">{structuredAnalyst.overall_comment}</p>
              </div>
            )}
            {structuredAnalyst.data_sources.length > 0 && (
              <div className="agent-structured-card__sources">
                {structuredAnalyst.data_sources.map((s, idx) => (
                  <span key={idx} className="agent-structured-card__chip">
                    {s}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}

        {riskReview && (
          <div className="agent-structured-card">
            <div className="agent-structured-card__header">
              <div>
                <p className="agent-structured-card__eyebrow">Risk Management</p>
                <h5 className="agent-structured-card__title">{riskReview.risk_level}</h5>
                <div className="agent-structured-card__inline-metrics">
                  <span className="agent-structured-card__badge-text">
                    Adj {(riskReview.adjusted_conviction * 100).toFixed(0)}% · Orig {(riskReview.original_conviction * 100).toFixed(0)}%
                  </span>
                </div>
              </div>
            </div>
            {riskReview.risk_factors && (
              <div className="agent-structured-card__note">
                <p className="agent-structured-card__label">Risk Factors</p>
                <ul className="agent-structured-card__list">
                  {[
                    {
                      label: 'Company',
                      value: riskReview.risk_factor_rc,
                      text: riskReview.risk_factors.company_specific,
                    },
                    {
                      label: 'Volatility',
                      value: riskReview.risk_factor_rm,
                      text: riskReview.risk_factors.volatility_risk,
                    },
                    {
                      label: 'Valuation',
                      value: riskReview.valuation_reliability,
                      text: riskReview.risk_factors.valuation_uncertainty,
                    },
                    {
                      label: 'Sentiment',
                      value: riskReview.sentiment_risk_score,
                      text: riskReview.risk_factors.sentiment_risk,
                    },
                    {
                      label: 'Disagreement',
                      value: riskReview.disagreement,
                      text: riskReview.risk_factors.analyst_disagreement,
                    },
                  ]
                    .filter((item) => item.text || item.value !== undefined)
                    .map((item, idx) => (
                      <li key={idx}>
                        <strong>
                          {item.label} {item.value !== undefined ? item.value.toFixed(2) : ''}
                        </strong>
                        {item.text ? ` — ${item.text}` : ''}
                      </li>
                    ))}
                </ul>
              </div>
            )}
            {riskReview.explanation && (
              <div className="agent-structured-card__note">
                <p className="agent-structured-card__label">Overall Comment</p>
                <p className="agent-structured-card__text">{riskReview.explanation}</p>
              </div>
            )}
          </div>
        )}

        {chartSeries.length > 0 && renderLineChart(chartSeries)}

        {!structuredAnalyst && !aggregation && !riskReview && renderContent()}
      </div>
    </div>
  )
}
