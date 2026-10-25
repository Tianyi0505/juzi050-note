package cache

import (
	"context"
	"log"
	"os"
	"strconv"
	"time"

	"github.com/redis/go-redis/v9"
)

// RDB 全局 Redis 客户端
var RDB *redis.Client

// Init 连接 Redis，存放登录会话。
// 连接信息可用环境变量覆盖：REDIS_ADDR / REDIS_PASSWORD / REDIS_DB
func Init() {
	addr := envOr("REDIS_ADDR", "127.0.0.1:6379")
	password := os.Getenv("REDIS_PASSWORD")
	dbIndex, _ := strconv.Atoi(envOr("REDIS_DB", "0"))

	RDB = redis.NewClient(&redis.Options{
		Addr:     addr,
		Password: password,
		DB:       dbIndex,
	})

	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	if err := RDB.Ping(ctx).Err(); err != nil {
		log.Fatalf("Redis 连接失败：%v", err)
	}
	log.Println("Redis 连接成功：" + addr)
}

func envOr(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}
