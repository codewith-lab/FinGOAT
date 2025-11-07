# FinGOAT: Financial Graph-Orchestrated Agentic Trading

[English](./README.md) | [中文](./README-CN.md)

FinGOAT is a full-stack financial intelligence system that combines real-time data ingestion, graph-structured knowledge modeling, and agentic decision workflows.
The stack includes a Go backend (Gin + GORM + PostgreSQL + Redis) and a TypeScript/React frontend built with Vite.

## Getting Started

### Backend Setup (Gin+GORM+PostgreSQL+Redis+Viper+JWT+Docker)

#### Install dependencies
```bash
go mod init github.com/JerryLinyx/FinGOAT

go get -u github.com/gin-gonic/gin
go get github.com/spf13/viper
go get -u gorm.io/gorm
go get -u gorm.io/driver/postgres
go get -u google.golang.org/grpc
go get -u golang.org/x/crypto/bcrypt
go get github.com/golang-jwt/jwt/v5
go get -u github.com/go-redis/redis/v8
go get github.com/gin-contrib/cors

go mod tidy
```

#### Start PostgreSQL
```bash
docker pull postgres:15.14-alpine3.21

docker run --name fingoat-pg \
  --restart=unless-stopped \
  -d -p 5432:5432 \
  -v pgdata:/var/lib/postgresql/data \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=2233 \
  -e POSTGRES_DB=fingoat_db \
  postgres:15.14-alpine3.21
```
#### Start Redis
```bash
docker run -d \
  --name fingoat-redis \
  -p 6379:6379 \
  -v redisdata:/data \
  redis:7.2
```
### Frontend Setup (TypeScript+Vite+React)
```bash
npm create vite@latest frontend

cd frontend
npm run build
npm run dev
```

#### Screenshots
![](static/login.png)

![](static/dashboard.png)


## FinGOAT Functional TODO List

| Name | Task | Status |
|------|------|---------|
| PostgreSQL & Redis Containers | Database and cache services via Docker | ✅ Completed |
| Go Backend Scaffold | Gin + GORM + Viper basic setup | ✅ Completed |
| React Frontend Scaffold | Vite + TypeScript project initialized | ✅ Completed |
| Environment Config | `.env` and Viper-based configuration management | ✅ Completed |
| Authentication Layer | JWT-based auth with Casbin RBAC integration | ⚙️ In Progress |
| API Structure | REST/gRPC routing, middleware, error handling | ⚙️ In Progress |
| Message Queue | Implement Redis Stream for event publishing/subscription | ⚙️ In Progress  |
| Schema Design | Define tables for users, assets, signals, portfolios, and events | ⚙️ In Progress  |
| Data Access Layer | Repositories for CRUD operations via GORM | ⚙️ In Progress |
| Logging & Monitoring | Basic structured logging, extendable to OpenTelemetry | ☐ Pending |
| MCP Core | Event dispatcher coordinating Fundamental, Macro, Quant agents | ☐ Pending |
| Fundamental Agent | Parse earnings, balance sheets, and valuation metrics | ☐ Pending |
| Macro Agent | Analyze macroeconomic variables and policy signals | ☐ Pending |
| Quant Agent | Compute statistical and sentiment-based indicators | ☐ Pending |
| Agent Aggregator | Combine multi-agent results via confidence/voting | ☐ Pending |
| Prompt Templates | Define meta-prompts for agent coordination and reasoning | ☐ Pending |
| Evaluation Logger | Store agent outputs and prompt-response pairs for analysis | ☐ Pending |
| MVO Optimizer | Implement mean–variance optimization (µᵀw − λwᵀΣw) | ☐ Pending |
| Risk Personalization | Adjustable risk aversion parameter per user | ☐ Pending |
| Backtesting Engine | Simulate rebalancing and evaluate portfolio performance | ☐ Pending |
| Transaction Cost Model | (Future) include slippage and cost in optimization | ☐ Future Feature |
| Event Source Detection | Detect volatility spikes, macro news, and user-defined triggers | ☐ Pending |
| Event Dispatch | Push events through Redis Stream to MCP and agents | ☐ Pending |
| Real-Time Stream | WebSocket/SSE to deliver updates to frontend dashboard | ☐ Pending |
| Auth Pages | Login, register, password reset with backend JWT link | ⚙️ In Progress |
| Dashboard | Show portfolio summary, agent outputs, and alerts | ☐ Pending |
| Watchlist | Add/remove stocks and monitor live price updates | ☐ Pending |
| Portfolio Visualization | Charts for allocation, performance, and risk metrics | ☐ Pending |
| Agent Rationales UI | Explain reasoning and confidence of each agent | ☐ Pending |
| Notification Center | Event-driven alerts for rebalancing or market signals | ☐ Pending |
| Settings Panel | User-configurable watchlists and risk preferences | ☐ Pending |
| Tracing | OpenTelemetry + Jaeger integration | ☐ Pending |
| Metrics | Prometheus + Grafana monitoring setup | ☐ Pending |
| Docker Compose | Unified orchestration for backend, agents, DB, Redis, frontend | ⚙️ In Progress  |
| CI/CD | GitHub Actions for lint, test, and deploy | ☐ Pending |
| Security Hardening | Input validation, rate limiting, HTTPS-ready | ⚙️ In Progress |

