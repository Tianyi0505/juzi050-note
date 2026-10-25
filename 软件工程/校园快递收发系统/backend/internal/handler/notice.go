package handler

import (
	"campus-express/internal/db"
	"campus-express/internal/model"

	"github.com/gin-gonic/gin"
)

// ListNotices 公告分页查询
func ListNotices(c *gin.Context) {
	page, size := pageParams(c)
	q := db.DB.Model(&model.Notice{})
	if v := c.Query("keyword"); v != "" {
		q = q.Where("title LIKE ?", "%"+v+"%")
	}
	var total int64
	q.Count(&total)
	var list []model.Notice
	q.Order("id DESC").Offset((page - 1) * size).Limit(size).Find(&list)
	OK(c, pageData(total, list))
}

// GetNotice 公告详情
func GetNotice(c *gin.Context) {
	id, ok := pathID(c)
	if !ok {
		return
	}
	var n model.Notice
	if err := db.DB.First(&n, id).Error; err != nil {
		Fail(c, 404, "公告不存在")
		return
	}
	OK(c, n)
}

// CreateNotice 发布公告（管理员）
func CreateNotice(c *gin.Context) {
	if !RequireAdmin(c) {
		return
	}
	var req struct {
		Title   string `json:"title" binding:"required,max=100"`
		Content string `json:"content" binding:"max=2000"`
	}
	if !BindJSON(c, &req) {
		return
	}
	n := model.Notice{Title: req.Title, Content: req.Content, Publisher: CurrentUser(c).Name}
	if err := db.DB.Create(&n).Error; err != nil {
		Fail(c, 500, "发布失败")
		return
	}
	OK(c, n)
}

// UpdateNotice 修改公告（管理员）
func UpdateNotice(c *gin.Context) {
	if !RequireAdmin(c) {
		return
	}
	id, ok := pathID(c)
	if !ok {
		return
	}
	var n model.Notice
	if err := db.DB.First(&n, id).Error; err != nil {
		Fail(c, 404, "公告不存在")
		return
	}
	var req struct {
		Title   string `json:"title" binding:"max=100"`
		Content string `json:"content" binding:"max=2000"`
	}
	if !BindJSON(c, &req) {
		return
	}
	if req.Title != "" {
		n.Title = req.Title
	}
	n.Content = req.Content
	db.DB.Save(&n)
	OK(c, n)
}

// DeleteNotice 删除公告（管理员）
func DeleteNotice(c *gin.Context) {
	if !RequireAdmin(c) {
		return
	}
	id, ok := pathID(c)
	if !ok {
		return
	}
	if err := db.DB.Delete(&model.Notice{}, id).Error; err != nil {
		Fail(c, 500, "删除失败")
		return
	}
	OK(c, nil)
}
