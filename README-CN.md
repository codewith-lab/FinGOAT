# FinGOAT: 基于图结构的智能代理金融交易系统

[English](./README.md) | [中文](./README-CN.md)

FinGOAT 是一个全栈金融智能系统，融合了实时数据采集、图结构知识建模以及智能 Agent 决策流程。
系统采用 Go 后端（Gin + GORM + PostgreSQL + Redis）和 Vite 驱动的 TypeScript/React 前端。

## 快速开始

### 后端配置 (Gin+GORM+PostgreSQL+Redis+Viper+JWT+Docker)

#### 安装依赖
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

#### 启动 PostgreSQL
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
#### 启动 Redis
```bash
docker run -d \
  --name fingoat-redis \
  -p 6379:6379 \
  -v redisdata:/data \
  redis:7.2
```
### 前端配置 (TypeScript+Vite+React)
```bash
npm create vite@latest frontend

cd frontend
npm run build
npm run dev
```

#### 界面展示
![](assets/login.png)

![](assets/dashboard.png)