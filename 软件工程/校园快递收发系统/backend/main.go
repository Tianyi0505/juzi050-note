package main

import (
	"log"
	"os"
	"time"

	"campus-express/internal/db"
	"campus-express/internal/model"
	"campus-express/internal/router"
)

func main() {
	db.Init()
	go expireJob()

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}
	log.Printf("校园快递收发系统后端已启动：http://localhost:%s", port)
	if err := router.Setup().Run(":" + port); err != nil {
		log.Fatal(err)
	}
}

// expireJob 每 10 分钟把超过 72 小时未取的包裹标记为超期
func expireJob() {
	check := func() {
		deadline := time.Now().Add(-72 * time.Hour)
		res := db.DB.Model(&model.Parcel{}).
			Where("status = ? AND inbound_time < ?", 0, deadline).
			Update("status", 2)
		if res.RowsAffected > 0 {
			log.Printf("超期处理：%d 个包裹已标记为超期", res.RowsAffected)
		}
	}
	check()
	ticker := time.NewTicker(10 * time.Minute)
	for range ticker.C {
		check()
	}
}
