import type { AnalysisTask } from '../services/tradingService'

export type AgentStageKey =
  | 'market_report'
  | 'sentiment_report'
  | 'news_report'
  | 'fundamentals_report'
  | 'investment_plan'
  | 'valuation_report'
  | 'risk_debate_state'
  | 'final_trade_decision'

export type StageStatus = 'pending' | 'processing' | 'completed' | 'failed'

export type AgentStage = {
  key: AgentStageKey
  label: string
  description?: string
}

export type StageProgress = AgentStage & {
  status: StageStatus
  displayLabel?: string
  summary: string | null
  content: unknown
  hasContent: boolean
  durationSeconds?: number
}

export const PARALLEL_ANALYST_STAGE_KEYS: AgentStageKey[] = [
  'market_report',
  'sentiment_report',
  'news_report',
  'fundamentals_report',
  'valuation_report',
]

const PARALLEL_ANALYST_STAGE_SET = new Set<AgentStageKey>(PARALLEL_ANALYST_STAGE_KEYS)

export const AGENT_STAGES: AgentStage[] = [
  { key: 'market_report', label: 'Technical' },
  { key: 'sentiment_report', label: 'Social Media' },
  { key: 'news_report', label: 'News' },
  { key: 'fundamentals_report', label: 'Fundamentals' },
  { key: 'valuation_report', label: 'Valuation' },
  { key: 'investment_plan', label: 'PM Engine' },
  { key: 'final_trade_decision', label: 'Risk Management' },
]

const SEQUENTIAL_STAGE_KEYS: AgentStageKey[] = AGENT_STAGES
  .map((stage) => stage.key)
  .filter((key) => !PARALLEL_ANALYST_STAGE_SET.has(key))

const hasValue = (value: unknown): boolean => {
  const isMeaningfulObject = (obj: Record<string, unknown>): boolean => {
    const entries = Object.entries(obj)
    if (entries.length === 0) return false
    return entries.some(([, v]) => hasValue(v))
  }

  if (value === null || value === undefined) return false
  if (typeof value === 'string') return value.trim().length > 0
  if (typeof value === 'number') return value !== 0
  if (typeof value === 'boolean') return value
  if (Array.isArray(value)) return value.length > 0
  if (typeof value === 'object') return isMeaningfulObject(value as Record<string, unknown>)
  return true
}

export const parseAnalysisReport = (
  task?: AnalysisTask | null,
): Record<string, unknown> | null => {
  if (!task) return null
  const rawTask = task as any
  const raw = rawTask.analysis_report ?? rawTask.decision?.analysis_report
  if (!raw) return null

  if (typeof raw === 'string') {
    try {
      return JSON.parse(raw) as Record<string, unknown>
    } catch {
      return null
    }
  }

  if (typeof raw === 'object') {
    return raw as Record<string, unknown>
  }

  return null
}

export const summarizeContent = (data: unknown): string | null => {
  if (!hasValue(data)) return null
  if (typeof data === 'string') {
    const trimmed = data.trim()
    return trimmed.length > 180 ? `${trimmed.slice(0, 180)}…` : trimmed
  }
  if (typeof data === 'object') {
    try {
      const json = JSON.stringify(data, null, 2)
      return json.length > 180 ? `${json.slice(0, 180)}…` : json
    } catch {
      return null
    }
  }
  return String(data)
}

export const buildStageProgress = (task?: AnalysisTask | null): StageProgress[] => {
  const baseStatus = task?.status ?? 'pending'
  const report = parseAnalysisReport(task) ?? {}
  const stageTimes =
    ((task as any)?.stage_times as Record<string, number> | undefined) ||
    ((report as any)?.__stage_times as Record<string, number> | undefined)
  const firstMissingSequentialKey = SEQUENTIAL_STAGE_KEYS.find((key) => !hasValue((report as any)[key]))
  const parallelStagesCompleted = PARALLEL_ANALYST_STAGE_KEYS.every((key) => hasValue((report as any)[key]))

  return AGENT_STAGES.map((stage) => {
    const content = report[stage.key]
    const hasContent = hasValue(content)
    const isParallelAnalyst = PARALLEL_ANALYST_STAGE_SET.has(stage.key)
    const displayLabel = stage.label
    const stageStarted = stageTimes?.[stage.key] !== undefined

    let status: StageStatus = 'pending'
    if (baseStatus === 'failed') {
      status = 'failed'
    } else if (hasContent) {
      status = 'completed'
    } else if (baseStatus === 'processing') {
      if (isParallelAnalyst) {
        status = 'processing'
      } else {
        const isCurrentSequentialTarget = stage.key === firstMissingSequentialKey
        const canStartSequential = parallelStagesCompleted || stageStarted
        status = canStartSequential && (isCurrentSequentialTarget || stageStarted) ? 'processing' : 'pending'
      }
    } else if (baseStatus === 'completed') {
      status = 'pending'
    }

    return {
      ...stage,
      status,
      displayLabel,
      summary: summarizeContent(content),
      content,
      hasContent,
      durationSeconds: stageTimes?.[stage.key],
    }
  })
}

export const firstStageWithContent = (stages: StageProgress[]): AgentStageKey | undefined => {
  const found = stages.find((stage) => stage.hasContent)
  return found?.key
}
