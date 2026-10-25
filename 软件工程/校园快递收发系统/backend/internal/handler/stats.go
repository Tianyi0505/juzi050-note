package handler

import (
	"strconv"
	"time"

	"campus-express/internal/db"
	"campus-express/internal/model"

	"github.com/gin-gonic/gin"
)

// nameNum 统计通用结构：名称 + 数量
type nameNum struct {
	Name string `json:"name"`
	Num  int64  `json:"num"`
}

// Overview 数据概览：包裹状态分布 + 今日进出港 + 用户/驿站数量
func Overview(c *gin.Context) {
	if !RequireStaff(c) {
		return
	}
	var total, pending, picked, expired, returned, todayInbound, todayPicked, userCount, stationCount int64
	db.DB.Model(&model.Parcel{}).Count(&total)
	db.DB.Model(&model.Parcel{}).Where("status = ?", 0).Count(&pending)
	db.DB.Model(&model.Parcel{}).Where("status = ?", 1).Count(&picked)
	db.DB.Model(&model.Parcel{}).Where("status = ?", 2).Count(&expired)
	db.DB.Model(&model.Parcel{}).Where("status = ?", 3).Count(&returned)

	now := time.Now()
	start := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, now.Location())
	db.DB.Model(&model.Parcel{}).Where("inbound_time >= ?", start).Count(&todayInbound)
	db.DB.Model(&model.Parcel{}).Where("pickup_time >= ?", start).Count(&todayPicked)
	db.DB.Model(&model.User{}).Count(&userCount)
	db.DB.Model(&model.Station{}).Count(&stationCount)

	OK(c, gin.H{
		"parcelTotal":  total,
		"pendingCount": pending,
		"pickedCount":  picked,
		"expiredCount": expired,
		"returnedCount": returned,
		"todayInbound": todayInbound,
		"todayPicked":  todayPicked,
		"userCount":    userCount,
		"stationCount": stationCount,
	})
}

// CompanyStats 各快递公司包裹量
func CompanyStats(c *gin.Context) {
	if !RequireStaff(c) {
		return
	}
	var rows []nameNum
	db.DB.Model(&model.Parcel{}).
		Select("company AS name, COUNT(*) AS num").
		Group("company").Order("num DESC").Scan(&rows)
	OK(c, rows)
}

// StationStats 各驿站包裹量
func StationStats(c *gin.Context) {
	if !RequireStaff(c) {
		return
	}
	var rows []nameNum
	db.DB.Table("station AS s").
		Select("s.name AS name, COUNT(p.id) AS num").
		Joins("LEFT JOIN parcel p ON p.station_id = s.id").
		Group("s.id, s.name").Order("num DESC").Scan(&rows)
	OK(c, rows)
}

// TrendStats 最近 N 天入库 / 取件趋势（按天分组交给 MySQL 做）
func TrendStats(c *gin.Context) {
	if !RequireStaff(c) {
		return
	}
	days, _ := strconv.Atoi(c.DefaultQuery("days", "7"))
	if days < 1 || days > 30 {
		days = 7
	}

	type item struct {
		Date    string `json:"date"`
		Inbound int64  `json:"inbound"`
		Picked  int64  `json:"picked"`
	}
	type row struct {
		Date string
		Num  int64
	}

	now := time.Now()
	start := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, now.Location()).
		AddDate(0, 0, -(days - 1))

	var inRows []row
	db.DB.Model(&model.Parcel{}).
		Select("DATE_FORMAT(inbound_time, '%Y-%m-%d') AS date, COUNT(*) AS num").
		Where("inbound_time >= ?", start).Group("date").Scan(&inRows)

	var pickRows []row
	db.DB.Model(&model.Parcel{}).
		Select("DATE_FORMAT(pickup_time, '%Y-%m-%d') AS date, COUNT(*) AS num").
		Where("pickup_time >= ?", start).Group("date").Scan(&pickRows)

	inMap := make(map[string]int64, len(inRows))
	for _, r := range inRows {
		inMap[r.Date] = r.Num
	}
	pickMap := make(map[string]int64, len(pickRows))
	for _, r := range pickRows {
		pickMap[r.Date] = r.Num
	}

	list := make([]item, 0, days)
	for i := 0; i < days; i++ {
		d := start.AddDate(0, 0, i).Format("2006-01-02")
		list = append(list, item{Date: d, Inbound: inMap[d], Picked: pickMap[d]})
	}
	OK(c, list)
}
