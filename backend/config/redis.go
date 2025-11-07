package config

import (
	"log"

	"github.com/JerryLinyx/FinGOAT/global"
	"github.com/go-redis/redis/v8"
)

func initRedis() {
	RedisConf := AppConfig.Redis
	RedisClient := redis.NewClient(&redis.Options{
		Addr:     RedisConf.Addr,
		Password: RedisConf.Password,
		DB:       RedisConf.DB,
	})

	_, err := RedisClient.Ping(RedisClient.Context()).Result()
	if err != nil {
		log.Fatalf("Failed to connect to Redis: %v", err)
	}

	global.RedisDB = RedisClient
}
