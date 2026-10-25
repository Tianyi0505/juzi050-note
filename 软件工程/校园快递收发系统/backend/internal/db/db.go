package db

import (
	"fmt"
	"log"
	"os"

	"gorm.io/driver/mysql"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

// DB 全局数据库连接
var DB *gorm.DB

// Init 连接 MySQL。表结构以 db/campus_express.sql 为准。
// 连接信息可用环境变量覆盖：MYSQL_USER / MYSQL_PASSWORD / MYSQL_HOST / MYSQL_PORT / MYSQL_DB
func Init() {
	user := env("MYSQL_USER", "root")
	password := env("MYSQL_PASSWORD", "root")
	host := env("MYSQL_HOST", "127.0.0.1")
	port := env("MYSQL_PORT", "3306")
	name := env("MYSQL_DB", "campus_express")

	dsn := fmt.Sprintf("%s:%s@tcp(%s:%s)/%s?charset=utf8mb4&parseTime=True&loc=Local&time_zone=%%27%%2B08%%3A00%%27",
		user, password, host, port, name)

	gdb, err := gorm.Open(mysql.Open(dsn), &gorm.Config{
		Logger: logger.Default.LogMode(logger.Warn),
	})
	if err != nil {
		log.Fatalf("数据库连接失败：%v", err)
	}

	// 表结构以 db/campus_express.sql 为准，这里不再自动建表，避免改动已有表
	if err := gdb.Exec("SELECT 1 FROM sys_user LIMIT 1").Error; err != nil {
		log.Fatalf("数据表不存在，请先导入 db/campus_express.sql：%v", err)
	}

	DB = gdb
	log.Println("数据库连接成功：" + name)
}

func env(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}
