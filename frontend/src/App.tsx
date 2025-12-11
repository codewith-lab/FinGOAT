import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import type { ChangeEvent, FormEvent } from 'react'
import './App.css'
import { TradingAnalysis } from './components/TradingAnalysis'
import { AgentResultsModule } from './components/AgentResultsModule'
import type { AgentStageKey } from './components/agentStages'
import type { AnalysisTask } from './services/tradingService'

type AuthMode = 'login' | 'register'
type View = 'auth' | 'home'
type Theme = 'light' | 'dark'

type ThemeContextValue = {
  theme: Theme
  toggleTheme: () => void
}

const ThemeContext = createContext<ThemeContextValue>({
  theme: 'light',
  toggleTheme: () => { },
})

const ThemeToggleButton = () => {
  const { theme, toggleTheme } = useContext(ThemeContext)
  return (
    <button type="button" className="theme-toggle" onClick={toggleTheme} aria-label="Toggle theme">
      {theme === 'light' ? (
        <svg viewBox="0 0 24 24" role="presentation" width="18" height="18">
          <path
            d="M21 13.5A8.5 8.5 0 0 1 10.5 3 6.5 6.5 0 1 0 21 13.5Z"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          />
        </svg>
      ) : (
        <svg viewBox="0 0 24 24" role="presentation" width="18" height="18">
          <circle cx="12" cy="12" r="4.5" fill="none" stroke="currentColor" strokeWidth="2" />
          <path d="M12 2v2M12 20v2M4 12H2M22 12h-2M5 5l-1.5-1.5M20.5 20.5 19 19M5 19l-1.5 1.5M20.5 3.5 19 5" stroke="currentColor" strokeWidth="2" />
        </svg>
      )}
    </button>
  )
}

const PanelIcon = ({ type }: { type: 'config' | 'chat' | 'news' }) => {
  const icon = {
    config: (
      <>
        <circle cx="16" cy="16" r="6.5" fill="none" strokeWidth="2" />
        <path d="M8 16h16M12 10h8M12 22h8" strokeWidth="2" strokeLinecap="round" />
      </>
    ),
    chat: (
      <>
        <path
          d="M7 9h18v11H17l-5.5 4v-4H7z"
          fill="none"
          strokeWidth="2"
          strokeLinejoin="round"
        />
        <circle cx="12" cy="14" r="1" fill="currentColor" />
        <circle cx="16" cy="14" r="1" fill="currentColor" />
        <circle cx="20" cy="14" r="1" fill="currentColor" />
      </>
    ),
    news: (
      <>
        <rect x="9" y="7" width="14" height="18" rx="3" fill="none" strokeWidth="2" />
        <path d="M12 11h8M12 15h8M12 19h5" strokeWidth="2" strokeLinecap="round" />
      </>
    ),
  }[type]

  return (
    <span className="panel-icon" aria-hidden="true">
      <svg viewBox="0 0 32 32" role="presentation" stroke="currentColor" fill="none">
        {icon}
      </svg>
    </span>
  )
}

const TOKEN_STORAGE_KEY = 'fingoat_token'
const API_BASE_URL =
  import.meta.env.VITE_API_URL?.replace(/\/$/, '') || 'http://localhost:3000'

const initialForm = {
  username: '',
  password: '',
  confirmPassword: '',
}

const NAV_LINKS = [
  { label: 'Dashboard', status: 'Live' },
  { label: 'Markets', status: 'TODO' },
  { label: 'Portfolio', status: 'TODO' },
  { label: 'History', status: 'TODO' },
] as const

const getStoredTheme = (): Theme => {
  if (typeof window === 'undefined') {
    return 'light'
  }
  const stored = localStorage.getItem('fingoat_theme')
  return stored === 'dark' ? 'dark' : 'light'
}

function App() {
  const [theme, setTheme] = useState<Theme>(getStoredTheme)
  const [mode, setMode] = useState<AuthMode>('login')
  const [view, setView] = useState<View>('auth')
  const [form, setForm] = useState(initialForm)
  const [showPassword, setShowPassword] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [latestTask, setLatestTask] = useState<AnalysisTask | null>(null)
  const controlsBarRef = useRef<HTMLDivElement | null>(null)
  const [controlsContainer, setControlsContainer] = useState<HTMLDivElement | null>(null)
  const [selectedStageKey, setSelectedStageKey] = useState<AgentStageKey | null>(null)
  const llmProvider = 'openai'
  const llmModel = 'gpt-4o-mini'
  const llmBaseUrl = 'https://api.openai.com/v1'

  useEffect(() => {
    localStorage.setItem('fingoat_theme', theme)
  }, [theme])



  const toggleTheme = useCallback(() => {
    setTheme((prev) => (prev === 'light' ? 'dark' : 'light'))
  }, [])

  useEffect(() => {
    if (localStorage.getItem(TOKEN_STORAGE_KEY)) {
      setView('home')
    }
  }, [])

  useEffect(() => {
    setControlsContainer(controlsBarRef.current)
  }, [view])

  const subtitle = useMemo(() => {
    if (mode === 'login') {
      return 'Please enter your credentials to sign in.'
    }
    return 'Create an account to start orchestrating trades.'
  }, [mode])

  const loadPreviousAnalyses = () => {
    // Placeholder - handled by TradingAnalysis component
  }

  const resetSession = useCallback((message?: string) => {
    localStorage.removeItem(TOKEN_STORAGE_KEY)
    setForm(initialForm)
    setView('auth')
    setMode('login')
    setShowPassword(false)
    setSuccess('')
    setError(message ?? '')
  }, [])

  const handleInputChange = (event: ChangeEvent<HTMLInputElement>): void => {
    const { name, value } = event.target
    setForm((prev) => ({ ...prev, [name]: value }))
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (loading) return

    setError('')
    setSuccess('')

    if (!form.username.trim() || !form.password) {
      setError('Please fill in both username and password.')
      return
    }

    if (mode === 'register') {
      if (form.password.length < 8) {
        setError('Password must be at least 8 characters long.')
        return
      }
      if (form.password !== form.confirmPassword) {
        setError('Passwords do not match.')
        return
      }
    }

    const payload = {
      username: form.username.trim(),
      password: form.password,
    }
    const endpoint = mode === 'login' ? '/api/auth/login' : '/api/auth/register'

    try {
      setLoading(true)
      const response = await fetch(`${API_BASE_URL}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })

      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        const message =
          typeof data?.error === 'string'
            ? data.error
            : 'Unable to process your request. Please try again.'
        setError(message)
        return
      }

      if (typeof data?.token === 'string') {
        localStorage.setItem(TOKEN_STORAGE_KEY, data.token)
        setSuccess(mode === 'login' ? 'Welcome back!' : 'Account created.')
        setTimeout(() => setView('home'), 400)
      } else {
        setError('The server response did not include a token.')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unexpected error occurred.')
    } finally {
      setLoading(false)
    }
  }

  const handleModeChange = (nextMode: AuthMode) => {
    setMode(nextMode)
    setError('')
    setSuccess('')
    setForm(initialForm)
  }

  const handleLogout = () => {
    resetSession()
  }

  const togglePasswordVisibility = () => {
    setShowPassword((prev) => !prev)
  }

  const dashboardView = (
    <div className="dashboard">
      <header className="top-nav">
        <div className="brand">
          <div className="brand-mark">FG</div>
          <div className="brand-copy">
            <strong>FinGOAT</strong>
          </div>
        </div>
        <nav className="nav-links">
          {NAV_LINKS.map(({ label }) => (
            <button
              key={label}
              type="button"
              className={`nav-link ${label === 'Dashboard' ? 'active' : ''}`}
              disabled={label !== 'Dashboard'}
            >
              {label}
            </button>
          ))}
        </nav>
        <div className="nav-actions">
          <ThemeToggleButton />
          <button type="button" className="logout-btn" onClick={handleLogout}>
            Logout
          </button>
        </div>
      </header>

      <div className="todo-strip-divider" aria-hidden="true" />

      <div className="analysis-control-bar" ref={controlsBarRef} />

      <main className="dashboard-grid">
        <section className="panel ai-panel">
          <div className="panel-heading">
            <PanelIcon type="chat" />
            <div>
              <p className="panel-label">Stock Analysis</p>
              <h2>Status Tracking</h2>
            </div>
            <button type="button" className="panel-action" onClick={loadPreviousAnalyses}>
              Refresh
            </button>
          </div>

          <div className="panel-body scrollable">
            <TradingAnalysis
              onSessionExpired={resetSession}
              llmProvider={llmProvider}
              llmModel={llmModel}
              llmBaseUrl={llmBaseUrl}
              onTaskUpdate={setLatestTask}
              controlsContainer={controlsContainer}
              selectedStageKey={selectedStageKey}
              onStageSelect={setSelectedStageKey}
            />
          </div>
        </section>

        <section className="panel news-panel">
          <div className="panel-heading">
            <PanelIcon type="news" />
            <div>
              <p className="panel-label">Agent Results</p>
              <h2>Key Outputs</h2>
            </div>
          </div>

          <div className="panel-body scrollable key-outputs-body">
            <AgentResultsModule
              task={latestTask}
              selectedStageKey={selectedStageKey || undefined}
              onStageChange={setSelectedStageKey}
            />
          </div>
        </section>

      </main>
    </div>
  )

  const authView = (
    <div className="auth-page">
      <div className="glow glow-left" />
      <div className="glow glow-right" />
      <section className="auth-panel">
        <div className="auth-tabs">
          {(['login', 'register'] as AuthMode[]).map((tab) => (
            <button
              key={tab}
              type="button"
              className={`auth-tab ${mode === tab ? 'active' : ''}`}
              onClick={() => handleModeChange(tab)}
              disabled={mode === tab}
            >
              {tab === 'login' ? 'Login' : 'Register'}
            </button>
          ))}
        </div>

        <header className="auth-header">
          <h1>{mode === 'login' ? 'Welcome Back' : 'Create Account'}</h1>
          <p>{subtitle}</p>
        </header>

        <form className="auth-form" onSubmit={handleSubmit}>
          <label className="field-label" htmlFor="username">
            Username
          </label>
          <input
            id="username"
            name="username"
            type="text"
            placeholder="Enter your username"
            value={form.username}
            onChange={handleInputChange}
            autoComplete="username"
          />

          <label className="field-label" htmlFor="password">
            Password
          </label>
          <div className="password-field">
            <input
              id="password"
              name="password"
              type={showPassword ? 'text' : 'password'}
              placeholder="Enter your password"
              value={form.password}
              onChange={handleInputChange}
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            />
            <button
              type="button"
              aria-label={showPassword ? 'Hide password' : 'Show password'}
              className="ghost-btn"
              onClick={togglePasswordVisibility}
            >
              {showPassword ? 'Hide' : 'Show'}
            </button>
          </div>

          {mode === 'register' && (
            <>
              <label className="field-label" htmlFor="confirmPassword">
                Confirm password
              </label>
              <input
                id="confirmPassword"
                name="confirmPassword"
                type={showPassword ? 'text' : 'password'}
                placeholder="Re-enter your password"
                value={form.confirmPassword}
                onChange={handleInputChange}
                autoComplete="new-password"
              />
            </>
          )}

          {error && <div className="banner banner-error">{error}</div>}
          {success && <div className="banner banner-success">{success}</div>}

          <button type="submit" className="primary-btn" disabled={loading}>
            {loading ? 'Please wait…' : mode === 'login' ? 'Login' : 'Register'}
          </button>
        </form>

        <footer className="auth-footer">
          {mode === 'login' ? (
            <>
              Don&apos;t have an account?{' '}
              <button
                type="button"
                className="link-btn"
                onClick={() => handleModeChange('register')}
              >
                Register
              </button>
            </>
          ) : (
            <>
              Already onboard?{' '}
              <button
                type="button"
                className="link-btn"
                onClick={() => handleModeChange('login')}
              >
                Login
              </button>
            </>
          )}
        </footer>
      </section>
    </div>
  )

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme }}>
      <div className={`app theme-${theme}`}>{view === 'home' ? dashboardView : authView}</div>
    </ThemeContext.Provider>
  )
}

export default App
