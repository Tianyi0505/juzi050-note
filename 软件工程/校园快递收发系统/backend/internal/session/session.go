package session

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"strconv"
	"time"

	"campus-express/internal/cache"
)

// CookieName 会话 Cookie 的名称
const CookieName = "session_id"

// TTL 会话有效期。每次请求会续期。
const TTL = 2 * time.Hour

func key(sid string) string {
	return "campus:sess:" + sid
}

// Create 生成会话 id 并写入 Redis
func Create(uid uint) (string, error) {
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	sid := hex.EncodeToString(b)
	if err := cache.RDB.Set(context.Background(), key(sid), uid, TTL).Err(); err != nil {
		return "", err
	}
	return sid, nil
}

// UserID 按会话 id 查用户 id
func UserID(sid string) (uint, bool) {
	if sid == "" {
		return 0, false
	}
	v, err := cache.RDB.Get(context.Background(), key(sid)).Result()
	if err != nil {
		return 0, false
	}
	id, err := strconv.ParseUint(v, 10, 64)
	if err != nil {
		return 0, false
	}
	return uint(id), true
}

// Refresh 续期
func Refresh(sid string) {
	cache.RDB.Expire(context.Background(), key(sid), TTL)
}

// Destroy 删除会话（退出登录）
func Destroy(sid string) {
	cache.RDB.Del(context.Background(), key(sid))
}
