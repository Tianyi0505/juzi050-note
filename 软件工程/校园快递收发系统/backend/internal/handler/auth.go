package handler

import (
	"campus-express/internal/db"
	"campus-express/internal/model"
	"campus-express/internal/session"

	"github.com/gin-gonic/gin"
)

// Register 学生注册（注册成功直接返回登录态）
func Register(c *gin.Context) {
	var req struct {
		Phone    string `json:"phone" binding:"required,len=11,numeric"`
		Password string `json:"password" binding:"required,min=6,max=20"`
		Name     string `json:"name" binding:"max=20"`
	}
	if !BindJSON(c, &req) {
		return
	}

	var count int64
	db.DB.Model(&model.User{}).Where("phone = ?", req.Phone).Count(&count)
	if count > 0 {
		Fail(c, 400, "该手机号已注册")
		return
	}

	u := model.User{
		Phone:    req.Phone,
		Password: hashPassword(req.Password),
		Name:     req.Name,
		Role:     model.RoleUser,
		Status:   1,
	}
	if err := db.DB.Create(&u).Error; err != nil {
		Fail(c, 500, "注册失败："+err.Error())
		return
	}
	sid, err := session.Create(u.ID)
	if err != nil {
		Fail(c, 500, "注册失败：创建会话失败")
		return
	}
	setSessionCookie(c, sid)
	OK(c, gin.H{"user": u})
}

// Login 登录
func Login(c *gin.Context) {
	var req struct {
		Phone    string `json:"phone" binding:"required"`
		Password string `json:"password" binding:"required"`
	}
	if !BindJSON(c, &req) {
		return
	}

	var u model.User
	if err := db.DB.Where("phone = ?", req.Phone).First(&u).Error; err != nil {
		Fail(c, 400, "账号不存在")
		return
	}
	if !checkPassword(u.Password, req.Password) {
		Fail(c, 400, "密码错误")
		return
	}
	if u.Status != 1 {
		Fail(c, 403, "账号已被禁用")
		return
	}

	sid, err := session.Create(u.ID)
	if err != nil {
		Fail(c, 500, "登录失败：创建会话失败")
		return
	}
	setSessionCookie(c, sid)
	OK(c, gin.H{"user": u})
}

// Logout 退出登录：删除 Redis 会话并清除 Cookie
func Logout(c *gin.Context) {
	if sid := CurrentSession(c); sid != "" {
		session.Destroy(sid)
	}
	clearSessionCookie(c)
	OK(c, nil)
}

// Me 当前登录用户信息
func Me(c *gin.Context) {
	OK(c, CurrentUser(c))
}

// UpdateMe 修改自己的资料
func UpdateMe(c *gin.Context) {
	u := CurrentUser(c)
	var req struct {
		Name  string `json:"name" binding:"max=20"`
		Phone string `json:"phone" binding:"omitempty,len=11,numeric"`
	}
	if !BindJSON(c, &req) {
		return
	}
	if req.Phone != "" && req.Phone != u.Phone {
		var count int64
		db.DB.Model(&model.User{}).Where("phone = ? AND id <> ?", req.Phone, u.ID).Count(&count)
		if count > 0 {
			Fail(c, 400, "该手机号已被占用")
			return
		}
		u.Phone = req.Phone
	}
	if req.Name != "" {
		u.Name = req.Name
	}
	if err := db.DB.Save(u).Error; err != nil {
		Fail(c, 500, "保存失败")
		return
	}
	OK(c, u)
}

// UpdateMyPassword 修改自己的密码
func UpdateMyPassword(c *gin.Context) {
	u := CurrentUser(c)
	var req struct {
		OldPassword string `json:"oldPassword" binding:"required"`
		NewPassword string `json:"newPassword" binding:"required,min=6,max=20"`
	}
	if !BindJSON(c, &req) {
		return
	}
	if !checkPassword(u.Password, req.OldPassword) {
		Fail(c, 400, "原密码不正确")
		return
	}
	u.Password = hashPassword(req.NewPassword)
	db.DB.Save(u)
	// 改密后让当前会话失效，要求重新登录
	if sid := CurrentSession(c); sid != "" {
		session.Destroy(sid)
	}
	clearSessionCookie(c)
	OK(c, nil)
}
