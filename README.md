# FinGOAT

```bash
go mod init github.com/JerryLinyx/FinGOAT
go get -u github.com/gin-gonic/gin
go get github.com/spf13/viper
go get -u gorm.io/gorm
go get -u gorm.io/driver/postgres
go get -u google.golang.org/grpc
go get -u golang.org/x/crypto/bcrypt
go get github.com/golang-jwt/jwt/v5
go get -u github.com/go-redis/redis
```
```bash
docker pull postgres:15.14-alpine3.21

docker run --name pgsql --restart=always -d -p 5432:5432 -v /opt/pgsql/data:/var/lib/postgresql/data --shm-size=10g -e POSTGRES_USER=root  -e POSTGRES_PASSWORD=2233 postgres:15.14-alpine3.21

docker run --name fingoat-pg \
  --restart=unless-stopped \
  -d -p 5432:5432 \
  -v pgdata:/var/lib/postgresql/data \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=2233 \
  -e POSTGRES_DB=fingoat_db \
  postgres:15.14-alpine3.21
```

```bash
docker run -d \
  --name fingoat-redis \
  -p 6379:6379 \
  -v redisdata:/data \
  redis:7.2
```