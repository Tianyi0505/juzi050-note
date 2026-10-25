package handler

import (
	"strconv"

	"campus-express/internal/db"
	"campus-express/internal/model"

	"github.com/gin-gonic/gin"
)

// pathID 解析路径上的 :id
func pathID(c *gin.Context) (uint, bool) {
	id, err := strconv.Atoi(c.Param("id"))
	if err != nil || id <= 0 {
		Fail(c, 400, "id 不合法")
		return 0, false
	}
	return uint(id), true
}

// ListUsers 用户分页查询（管理员）
func ListUsers(c *gin.Context) {
	if !RequireAdmin(c) {
		return
	}
	page, size := pageParams(c)
	q := db.DB.Model(&model.User{})
	if v := c.Query("keyword"); v != "" {
		like := "%" + v + "%"
		q = q.Where("phone LIKE ? OR name LIKE ?", like, like)
	}
	if v := c.Query("role"); v != "" {
		q = q.Where("role = ?", v)
	}
	if v := c.Query("status"); v != "" {
		q = q.Where("status = ?", v)
	}

	var total int64
	q.Count(&total)
	var list []model.User
	q.Order("id").Offset((page - 1) * size).Limit(size).Find(&list)
	OK(c, pageData(total, list))
}

// GetUser 用户详情（管理员）
func GetUser(c *gin.Context) {
	if !RequireAdmin(c) {
		return
	}
	id, ok := pathID(c)
	if !ok {
		return
	}
	var u model.User
	if err := db.DB.First(&u, id).Error; err != nil {
		Fail(c, 404, "用户不存在")
		return
	}
	OK(c, u)
}

// CreateUser 新增用户 / 工作人员 / 管理员（管理员）
func CreateUser(c *gin.Context) {
	if !RequireAdmin(c) {
		return
	}
	var req struct {
		Phone     string `json:"phone" binding:"required,len=11,numeric"`
		Password  string `json:"password" binding:"required,min=6,max=20"`
		Name      string `json:"name" binding:"max=20"`
		Role      string `json:"role" binding:"omitempty,oneof=USER STAFF ADMIN"`
		StationID *uint  `json:"stationId"`
	}
	if !BindJSON(c, &req) {
		return
	}
	if req.Role == "" {
		req.Role = model.RoleUser
	}
	// 工作人员必须绑定一个存在的驿站
	if req.Role == model.RoleStaff {
		if req.StationID == nil {
			Fail(c, 400, "工作人员必须指定所属驿站")
			return
		}
		if !stationExists(*req.StationID) {
			Fail(c, 400, "驿站不存在")
			return
		}
	}

	var count int64
	db.DB.Model(&model.User{}).Where("phone = ?", req.Phone).Count(&count)
	if count > 0 {
		Fail(c, 400, "该手机号已存在")
		return
	}
	u := model.User{
		Phone:     req.Phone,
		Password:  hashPassword(req.Password),
		Name:      req.Name,
		Role:      req.Role,
		StationID: req.StationID,
		Status:    1,
	}
	if err := db.DB.Create(&u).Error; err != nil {
		Fail(c, 500, "新增失败："+err.Error())
		return
	}
	OK(c, u)
}

// UpdateUser 修改用户（管理员）
func UpdateUser(c *gin.Context) {
	if !RequireAdmin(c) {
		return
	}
	id, ok := pathID(c)
	if !ok {
		return
	}
	var u model.User
	if err := db.DB.First(&u, id).Error; err != nil {
		Fail(c, 404, "用户不存在")
		return
	}
	var req struct {
		Name      string `json:"name" binding:"max=20"`
		Role      string `json:"role" binding:"omitempty,oneof=USER STAFF ADMIN"`
		StationID *uint  `json:"stationId"`
	}
	if !BindJSON(c, &req) {
		return
	}
	if req.Role == model.RoleStaff {
		if req.StationID == nil {
			Fail(c, 400, "工作人员必须指定所属驿站")
			return
		}
		if !stationExists(*req.StationID) {
			Fail(c, 400, "驿站不存在")
			return
		}
	}
	if req.Name != "" {
		u.Name = req.Name
	}
	if req.Role != "" {
		u.Role = req.Role
	}
	u.StationID = req.StationID
	if err := db.DB.Save(&u).Error; err != nil {
		Fail(c, 500, "保存失败")
		return
	}
	OK(c, u)
}

// UpdateUserStatus 启用 / 禁用用户（管理员）
func UpdateUserStatus(c *gin.Context) {
	if !RequireAdmin(c) {
		return
	}
	id, ok := pathID(c)
	if !ok {
		return
	}
	var q struct {
		Status *int `form:"status" binding:"required,oneof=0 1"`
	}
	if err := c.ShouldBindQuery(&q); err != nil {
		Fail(c, 400, "状态只能是 0（禁用）或 1（正常）")
		return
	}
	if id == CurrentUser(c).ID && *q.Status == 0 {
		Fail(c, 400, "不能禁用自己")
		return
	}
	if err := db.DB.Model(&model.User{}).Where("id = ?", id).Update("status", *q.Status).Error; err != nil {
		Fail(c, 500, "操作失败")
		return
	}
	OK(c, nil)
}

// ResetUserPassword 重置密码（管理员），不传则重置为 123456
func ResetUserPassword(c *gin.Context) {
	if !RequireAdmin(c) {
		return
	}
	id, ok := pathID(c)
	if !ok {
		return
	}
	var req struct {
		Password string `json:"password" binding:"omitempty,min=6,max=20"`
	}
	if !BindOptionalJSON(c, &req) {
		return
	}
	if req.Password == "" {
		req.Password = "123456"
	}
	if err := db.DB.Model(&model.User{}).Where("id = ?", id).
		Update("password", hashPassword(req.Password)).Error; err != nil {
		Fail(c, 500, "重置失败")
		return
	}
	OK(c, nil)
}

// DeleteUser 删除用户（管理员）
func DeleteUser(c *gin.Context) {
	if !RequireAdmin(c) {
		return
	}
	id, ok := pathID(c)
	if !ok {
		return
	}
	if id == CurrentUser(c).ID {
		Fail(c, 400, "不能删除自己")
		return
	}
	if err := db.DB.Delete(&model.User{}, id).Error; err != nil {
		Fail(c, 500, "删除失败")
		return
	}
	OK(c, nil)
}
