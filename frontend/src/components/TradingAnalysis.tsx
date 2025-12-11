import { useState, useCallback, useEffect, useMemo, useRef } from 'react'
import { createPortal } from 'react-dom'
import type { ChangeEvent, FormEvent } from 'react'
import { tradingService, type AnalysisTask } from '../services/tradingService'
import {
    buildStageProgress,
} from './agentStages'
import type { AgentStageKey } from './agentStages'
import '../TradingAnalysis.css'

interface TradingAnalysisProps {
    onSessionExpired?: () => void
    llmProvider: string
    llmModel: string
    llmBaseUrl?: string
    onTaskUpdate?: (task: AnalysisTask | null) => void
    controlsContainer?: HTMLElement | null
    selectedStageKey?: AgentStageKey | null
    onStageSelect?: (stage: AgentStageKey) => void
}

export function TradingAnalysis({ onSessionExpired, llmProvider, llmModel, llmBaseUrl, onTaskUpdate, controlsContainer, selectedStageKey, onStageSelect }: TradingAnalysisProps) {
    const [ticker, setTicker] = useState('')
    const [selectedModel, setSelectedModel] = useState(llmModel)
    const [date, setDate] = useState(() => {
        const today = new Date()
        return today.toISOString().split('T')[0]
    })
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState('')
    const [currentTask, setCurrentTask] = useState<AnalysisTask | null>(null)
    const [previousAnalyses, setPreviousAnalyses] = useState<AnalysisTask[]>([])
    const [elapsedSeconds, setElapsedSeconds] = useState<number>(0)
    const frozenElapsedRef = useRef<number | null>(null)
    const frozenTaskIdRef = useRef<string | null>(null)

    // Fetch previous analyses on mount
    useEffect(() => {
        loadPreviousAnalyses()
    }, [])

    const loadPreviousAnalyses = useCallback(async () => {
        try {
            const result = await tradingService.listAnalyses()
            setPreviousAnalyses(result.tasks.slice(0, 5)) // Show last 5
        } catch (err) {
            // Silent fail for now
            console.error('Failed to load previous analyses:', err)
        }
    }, [])

    const handleTickerChange = (e: ChangeEvent<HTMLInputElement>) => {
        setTicker(e.target.value.toUpperCase())
    }

    const handleDateChange = (e: ChangeEvent<HTMLInputElement>) => {
        setDate(e.target.value)
    }

    useEffect(() => {
        setSelectedModel(llmModel)
    }, [llmModel])

    const modelOptions = useMemo(() => {
        const defaults = [llmModel, 'gpt-4o', 'gpt-4o-mini', 'gpt-4o-mini-2024-07-18', 'claude-3-5-sonnet', 'claude-3-haiku', 'llama-3.1-70b']
        return Array.from(new Set(defaults.filter(Boolean)))
    }, [llmModel])

    const handleSubmit = async (e: FormEvent) => {
        e.preventDefault()

        if (!ticker.trim()) {
            setError('Please enter a stock ticker')
            return
        }

        if (!date) {
            setError('Please select a date')
            return
        }

        setError('')
        setLoading(true)
        setCurrentTask(null)
        onTaskUpdate?.(null)

        try {
            // Submit analysis request
            const llmConfig = {
                provider: llmProvider,
                base_url: llmBaseUrl || undefined,
                quick_think_llm: selectedModel,
                deep_think_llm: selectedModel,
            }
            const task = await tradingService.requestAnalysis(ticker.trim(), date, llmConfig)
            setCurrentTask(task)
            onTaskUpdate?.(task)

            // Start polling for results
            await tradingService.pollAnalysisResult(
                task.task_id,
                (updatedTask) => {
                    setCurrentTask(updatedTask)
                    onTaskUpdate?.(updatedTask)
                },
                120, // allow longer-running jobs
                3000 // poll every 3 seconds for fresher UI updates
            )

            // Reload previous analyses
            loadPreviousAnalyses()
        } catch (err) {
            const message = err instanceof Error ? err.message : 'Failed to analyze stock'
            setError(message)

            if (message.includes('401') || message.includes('Session')) {
                onSessionExpired?.()
            }
        } finally {
            setLoading(false)
        }
    }

    const formatConfidence = (confidence?: number) => {
        if (confidence === undefined) return 'N/A'
        return `${(confidence * 100).toFixed(1)}%`
    }

    const formatElapsed = (seconds: number) => {
        if (seconds < 10) return `${seconds.toFixed(1)}s`
        if (seconds < 60) return `${Math.round(seconds)}s`
        const m = Math.floor(seconds / 60)
        const s = Math.floor(seconds % 60)
        return `${m}m ${s}s`
    }

    // Track elapsed time while processing
    useEffect(() => {
        const task = currentTask
        if (!task) {
            setElapsedSeconds(0)
            frozenElapsedRef.current = null
            frozenTaskIdRef.current = null
            return
        }

        // For completed or failed tasks, freeze the elapsed time (only calculate once per task)
        if (task.status === 'completed' || task.status === 'failed') {
            // If we've already frozen the elapsed time for this task, don't recalculate
            if (frozenTaskIdRef.current === task.task_id && frozenElapsedRef.current !== null) {
                // Value is already frozen, no need to update
                return
            }

            let finalElapsed = 0
            
            // Use processing_time_seconds if available
            if (typeof task.processing_time_seconds === 'number' && task.processing_time_seconds > 0) {
                finalElapsed = task.processing_time_seconds
            }
            // Otherwise, calculate from CreatedAt to completed_at if available
            else if (task.completed_at && task.CreatedAt) {
                const startTime = new Date(task.CreatedAt).getTime()
                const endTime = new Date(task.completed_at).getTime()
                finalElapsed = Math.max(0, (endTime - startTime) / 1000)
            }
            // Last resort: if we have a frozen value from before, use it; otherwise 0
            else {
                finalElapsed = frozenElapsedRef.current !== null ? frozenElapsedRef.current : 0
            }
            
            // Freeze the value for this task
            frozenElapsedRef.current = finalElapsed
            frozenTaskIdRef.current = task.task_id
            setElapsedSeconds(finalElapsed)
            return
        }

        // Reset frozen state when task is not completed/failed
        if (frozenTaskIdRef.current !== task.task_id) {
            frozenElapsedRef.current = null
            frozenTaskIdRef.current = null
        }

        // Only run the timer for processing tasks
        if (task.status !== 'processing') {
            return
        }

        // Calculate elapsed time from CreatedAt
        const startedAt = task.CreatedAt ? new Date(task.CreatedAt).getTime() : Date.now()
        const tick = () => {
            const now = Date.now()
            setElapsedSeconds(Math.max(0, (now - startedAt) / 1000))
        }
        tick()
        const id = window.setInterval(tick, 1000)
        return () => window.clearInterval(id)
    }, [currentTask?.task_id, currentTask?.status, currentTask?.processing_time_seconds, currentTask?.completed_at, currentTask?.CreatedAt])

    const getStatusColor = (status: string) => {
        switch (status) {
            case 'completed':
                return '#22c55e'
            case 'failed':
                return '#ef4444'
            case 'processing':
                return '#3b82f6'
            default:
                return '#6b7280'
        }
    }

    const getDecisionColor = (action?: string) => {
        switch (action) {
            case 'BUY':
                return '#10b981'
            case 'SELL':
                return '#ef4444'
            case 'HOLD':
                return '#f59e0b'
            default:
                return '#6b7280'
        }
    }

    const renderStageProgress = (task: AnalysisTask | null) => {
        if (!task) return null
        const stages = buildStageProgress(task)
        return (
            <div className="stage-progress">
                <div className="stage-progress__lane">
                    <div className="stage-progress__lane-header">Agent Progress</div>
                    <div className="stage-progress__list">
                        {stages.map((stage) => {
                            const badgeText =
                                stage.status === 'completed'
                                    ? 'COMPLETED'
                                    : stage.status.toUpperCase()
                            return (
                                <button
                                    key={stage.key}
                                    type="button"
                                    className={`stage-card stage-card--${stage.status} ${selectedStageKey === stage.key ? 'stage-card--active' : ''}`}
                                    onClick={() => onStageSelect?.(stage.key)}
                                >
                                    <div className="stage-progress__status">
                                        <span className={`stage-badge stage-badge--${stage.status}`}>
                                            {badgeText}
                                        </span>
                                        <span className="stage-progress__label">{stage.displayLabel || stage.label}</span>
                                        {stage.durationSeconds !== undefined && (
                                            <span className="stage-progress__duration">
                                                ⏱ {formatElapsed(stage.durationSeconds)}
                                            </span>
                                        )}
                                    </div>
                                </button>
                            )
                        })}
                    </div>
                </div>
            </div>
        )
    }

    const toolbar = (
        <div className="analysis-toolbar-wrapper">
            <form onSubmit={handleSubmit} className="analysis-toolbar">
                <div className="toolbar-actions">
                    <button
                        type="submit"
                        className="analyze-button"
                        disabled={loading || !ticker.trim()}
                    >
                        {loading ? (
                            <>
                                <span className="button-spinner"></span>
                                Analyzing...
                            </>
                        ) : (
                            'Analyze'
                        )}
                    </button>
                </div>
                <div className="toolbar-left">
                    <label htmlFor="ticker">Stock</label>
                    <input
                        id="ticker"
                        type="text"
                        placeholder="e.g., AAPL"
                        value={ticker}
                        onChange={handleTickerChange}
                        disabled={loading}
                        maxLength={10}
                        style={{ textTransform: 'uppercase' }}
                    />
                    <label htmlFor="model">Model</label>
                    <select
                        id="model"
                        value={selectedModel}
                        onChange={(e) => setSelectedModel(e.target.value)}
                        disabled={loading}
                    >
                        {modelOptions.map((opt: string) => (
                            <option key={opt} value={opt}>
                                {opt}
                            </option>
                        ))}
                    </select>
                    <label htmlFor="date">Date</label>
                    <input
                        id="date"
                        type="date"
                        value={date}
                        onChange={handleDateChange}
                        disabled={loading}
                        max={new Date().toISOString().split('T')[0]}
                    />
                </div>
            </form>
            {error && <div className="form-error">{error}</div>}
        </div>
    )

    const toolbarNode = controlsContainer ? createPortal(toolbar, controlsContainer) : toolbar

    return (
        <>
            {toolbarNode}
            <div className="trading-analysis-container">
                {currentTask && (
                    <div className="analysis-header">
                        <div className="analysis-header__info">
                            <h3>{currentTask.ticker}</h3>
                            {currentTask.decision && (
                                <span
                                    className="decision-action"
                                    style={{ color: getDecisionColor(currentTask.decision.action) }}
                                >
                                    {currentTask.decision.action}
                                    {typeof currentTask.decision.confidence === 'number' && (
                                        <span className="decision-action__conf">
                                            {' '}
                                            · {(currentTask.decision.confidence * 100).toFixed(0)}%
                                        </span>
                                    )}
                                </span>
                            )}
                        </div>
                        <div className="analysis-header__status">
                            <span
                                className="status-badge"
                                style={{ backgroundColor: getStatusColor(currentTask.status) }}
                            >
                                {currentTask.status.toUpperCase()}
                            </span>
                            {elapsedSeconds > 0 && (
                                <span className="status-elapsed">⏱ {formatElapsed(elapsedSeconds)}</span>
                            )}
                        </div>
                    </div>
                )}

                {currentTask && (
                    <div className="analysis-grid">
                        <section className="analysis-panel status-panel">
                            <h4 className="panel-heading-tight">Status</h4>
                            {renderStageProgress(currentTask)}
                        </section>
                    </div>
                )}

                {previousAnalyses.length > 0 && !loading && !currentTask && (
                    <div className="previous-analyses">
                        <h4>Recent Analyses</h4>
                        <div className="analyses-list">
                            {previousAnalyses.map((task) => (
                                <div key={task.task_id} className="analysis-item">
                                    <div className="item-header">
                                        <strong>{task.ticker}</strong>
                                        <span style={{ color: getStatusColor(task.status), fontSize: '0.85em' }}>
                                            {task.status}
                                        </span>
                                    </div>
                                    {task.decision && (
                                        <div className="item-decision">
                                            <span style={{ color: getDecisionColor(task.decision.action) }}>
                                                {task.decision.action}
                                            </span>
                                            <span>{formatConfidence(task.decision.confidence)}</span>
                                        </div>
                                    )}
                                    <div className="item-meta-row">
                                        <span className="item-date">{new Date(task.CreatedAt).toLocaleString()}</span>
                                        {task.llm_provider && (
                                            <span className="item-provider">
                                                {task.llm_provider}{task.llm_model ? ` / ${task.llm_model}` : ''}
                                            </span>
                                        )}
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                )}
            </div>
        </>
    )
}
