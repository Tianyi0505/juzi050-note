package handler

import (
	"time"

	"campus-express/internal/db"
	"campus-express/internal/model"

	"github.com/gin-gonic/gin"
)

// stationExists 判断驿站是否存在
func stationExists(id uint) bool {
	var count int64
	db.DB.Model(&model.Station{}).Where("id = ?", id).Count(&count)
	return count > 0
}

// validClock 校验 HH:mm 格式
func validClock(s string) bool {
	if s == "" {
		return true
	}
	_, err := time.Parse("15:04", s)
	return err == nil
}

// stationReq 驿站新增 / 修改的请求体
type stationReq struct {
	StationName string `json:"name" binding:"required,max=50"`
	Address   string `json:"address" binding:"max=100"`
	Manager   string `json:"manager" binding:"max=20"`
	Phone     string `json:"phone" binding:"omitempty,len=11,numeric"`
	OpenTime  string `json:"openTime" binding:"omitempty,max=5"`
	CloseTime string `json:"closeTime" binding:"omitempty,max=5"`
	Status    *int   `json:"status" binding:"omitempty,oneof=0 1"`
}

// ListStations 驿站列表（不分页，登录即可查看）
func ListStations(c *gin.Context) {
	q := db.DB.Model(&model.Station{})
	if v := c.Query("status"); v != "" {
		q = q.Where("status = ?", v)
	}
	var list []model.Station
	q.Order("id").Find(&list)
	OK(c, list)
}

// GetStation 驿站详情
func GetStation(c *gin.Context) {
	id, ok := pathID(c)
	if !ok {
		return
	}
	var s model.Station
	if err := db.DB.First(&s, id).Error; err != nil {
		Fail(c, 404, "驿站不存在")
		return
	}
	OK(c, s)
}

// CreateStation 新增驿站（管理员）
func CreateStation(c *gin.Context) {
	if !RequireAdmin(c) {
		return
	}
	var req stationReq
	if !BindJSON(c, &req) {
		return
	}
	if !validClock(req.OpenTime) || !validClock(req.CloseTime) {
		Fail(c, 400, "营业时间格式必须是 HH:mm")
		return
	}
	// 未传 status 时默认营业
	wantStatus := 1
	if req.Status != nil {
		wantStatus = *req.Status
	}
	s := model.Station{
		Name:      req.StationName,
		Address:   req.Address,
		Manager:   req.Manager,
		Phone:     req.Phone,
		OpenTime:  req.OpenTime,
		CloseTime: req.CloseTime,
		Status:    wantStatus,
	}
	if err := db.DB.Create(&s).Error; err != nil {
		Fail(c, 500, "新增失败："+err.Error())
		return
	}
	// GORM 插入时会跳过零值字段，status=0 需要单独更新一次
	if wantStatus == 0 {
		db.DB.Model(&s).Update("status", 0)
	}
	OK(c, s)
}

// UpdateStation 修改驿站（管理员）
func UpdateStation(c *gin.Context) {
	if !RequireAdmin(c) {
		return
	}
	id, ok := pathID(c)
	if !ok {
		return
	}
	var s model.Station
	if err := db.DB.First(&s, id).Error; err != nil {
		Fail(c, 404, "驿站不存在")
		return
	}
	var req stationReq
	if !BindJSON(c, &req) {
		return
	}
	if !validClock(req.OpenTime) || !validClock(req.CloseTime) {
		Fail(c, 400, "营业时间格式必须是 HH:mm")
		return
	}
	s.Name = req.StationName
	s.Address = req.Address
	s.Manager = req.Manager
	s.Phone = req.Phone
	s.OpenTime = req.OpenTime
	s.CloseTime = req.CloseTime
	if req.Status != nil {
		s.Status = *req.Status
	}
	if err := db.DB.Save(&s).Error; err != nil {
		Fail(c, 500, "保存失败")
		return
	}
	OK(c, s)
}

// DeleteStation 删除驿站（管理员）
func DeleteStation(c *gin.Context) {
	if !RequireAdmin(c) {
		return
	}
	id, ok := pathID(c)
	if !ok {
		return
	}
	var count int64
	db.DB.Model(&model.Parcel{}).Where("station_id = ?", id).Count(&count)
	if count > 0 {
		Fail(c, 400, "该驿站下还有包裹，不能删除")
		return
	}
	if err := db.DB.Delete(&model.Station{}, id).Error; err != nil {
		Fail(c, 500, "删除失败")
		return
	}
	OK(c, nil)
}
