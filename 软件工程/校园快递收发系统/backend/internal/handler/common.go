package handler

import (
	"crypto/rand"
	"errors"
	"fmt"
	"io"
	"log"
	"math/big"
	"net/http"
	"strconv"
	"strings"
	"time"

	"campus-express/internal/db"
	"campus-express/internal/model"
	"campus-express/internal/session"

	"github.com/gin-gonic/gin"
	"github.com/go-playground/validator/v10"
	"golang.org/x/crypto/bcrypt"
)

// Response 统一响应结构
type Response struct {
	Code int         `json:"code"`
	Msg  string      `json:"msg"`
	Data interface{} `json:"data"`
}

// OK 成功响应
func OK(c *gin.Context, data interface{}) {
	c.JSON(http.StatusOK, Response{Code: 200, Msg: "success", Data: data})
}

// Fail 业务失败响应（HTTP 状态码统一 200，用 code 区分）
func Fail(c *gin.Context, code int, msg string) {
	c.JSON(http.StatusOK, Response{Code: code, Msg: msg})
}

// ---------------------------------------------------------------
// 登录态：Cookie 存 session_id，会话数据存 Redis
// ---------------------------------------------------------------

// setSessionCookie 写入会话 Cookie
func setSessionCookie(c *gin.Context, sid string) {
	c.SetSameSite(http.SameSiteLaxMode)
	c.SetCookie(session.CookieName, sid, int(session.TTL.Seconds()), "/", "", false, true)
}

// clearSessionCookie 清除会话 Cookie
func clearSessionCookie(c *gin.Context) {
	c.SetSameSite(http.SameSiteLaxMode)
	c.SetCookie(session.CookieName, "", -1, "/", "", false, true)
}

// Auth 登录校验中间件：读 Cookie，查 Redis，续期
func Auth() gin.HandlerFunc {
	return func(c *gin.Context) {
		sid, err := c.Cookie(session.CookieName)
		if err != nil || sid == "" {
			Fail(c, 401, "未登录或登录已失效")
			c.Abort()
			return
		}
		uid, ok := session.UserID(sid)
		if !ok {
			Fail(c, 401, "未登录或登录已失效")
			c.Abort()
			return
		}

		var u model.User
		if err := db.DB.First(&u, uid).Error; err != nil {
			session.Destroy(sid)
			Fail(c, 401, "用户不存在")
			c.Abort()
			return
		}
		if u.Status != 1 {
			Fail(c, 403, "账号已被禁用")
			c.Abort()
			return
		}

		session.Refresh(sid) // 每次请求续期
		c.Set("user", &u)
		c.Set("sessionId", sid)
		c.Next()
	}
}

// CurrentSession 取当前会话 id
func CurrentSession(c *gin.Context) string {
	v, _ := c.Get("sessionId")
	s, _ := v.(string)
	return s
}

// CurrentUser 取当前登录用户
func CurrentUser(c *gin.Context) *model.User {
	v, _ := c.Get("user")
	u, _ := v.(*model.User)
	return u
}

// RequireAdmin 仅管理员可操作
func RequireAdmin(c *gin.Context) bool {
	if CurrentUser(c).Role != "ADMIN" {
		Fail(c, 403, "仅管理员可操作")
		return false
	}
	return true
}

// RequireStaff 管理员或驿站工作人员可操作
func RequireStaff(c *gin.Context) bool {
	if r := CurrentUser(c).Role; r != "ADMIN" && r != "STAFF" {
		Fail(c, 403, "仅驿站工作人员可操作")
		return false
	}
	return true
}

// ---------------------------------------------------------------
// 参数绑定与校验：校验规则写在结构体 tag 上，错误信息统一翻译成中文
// ---------------------------------------------------------------

// 字段名 -> 中文提示
var fieldNames = map[string]string{
	"Phone": "手机号", "Password": "密码", "OldPassword": "原密码", "NewPassword": "新密码",
	"Name": "姓名", "Role": "角色", "StationID": "驿站", "Status": "状态",
	"Title": "标题", "Content": "内容",
	"TrackingNo": "运单号", "CompanyCode": "快递公司", "ReceiverName": "收件人姓名",
	"ReceiverPhone": "收件人手机号", "ShelfCode": "货架号", "Remark": "备注",
	"PickupCode": "取件码", "PickerName": "取件人", "PickupType": "取件方式",
	"StationName": "驿站名称", "Address": "地址", "Manager": "负责人", "OpenTime": "营业开始时间", "CloseTime": "营业结束时间",
}

// BindJSON 绑定并校验 JSON 请求体
func BindJSON(c *gin.Context, obj interface{}) bool {
	if err := c.ShouldBindJSON(obj); err != nil {
		Fail(c, 400, bindMsg(err))
		return false
	}
	return true
}

// BindOptionalJSON 绑定可选请求体，允许 body 为空
func BindOptionalJSON(c *gin.Context, obj interface{}) bool {
	if err := c.ShouldBindJSON(obj); err != nil && !errors.Is(err, io.EOF) {
		Fail(c, 400, bindMsg(err))
		return false
	}
	return true
}

// bindMsg 把校验错误翻译成中文提示
func bindMsg(err error) string {
	var ve validator.ValidationErrors
	if !errors.As(err, &ve) || len(ve) == 0 {
		return "请求参数格式错误"
	}
	f := ve[0]
	name := fieldNames[f.Field()]
	if name == "" {
		name = f.Field()
	}
	switch f.Tag() {
	case "required":
		return name + "不能为空"
	case "len":
		return fmt.Sprintf("%s长度必须为 %s 位", name, f.Param())
	case "min":
		return fmt.Sprintf("%s不能小于 %s", name, f.Param())
	case "max":
		return fmt.Sprintf("%s不能超过 %s", name, f.Param())
	case "oneof":
		return fmt.Sprintf("%s只能是 %s", name, strings.Join(strings.Fields(f.Param()), " / "))
	case "numeric":
		return name + "只能是数字"
	default:
		return name + "格式不正确"
	}
}

// ---------------------------------------------------------------
// 通用小工具
// ---------------------------------------------------------------

// hashPassword bcrypt 加密
func hashPassword(pwd string) string {
	b, err := bcrypt.GenerateFromPassword([]byte(pwd), bcrypt.DefaultCost)
	if err != nil {
		log.Printf("密码加密失败：%v", err)
	}
	return string(b)
}

// checkPassword bcrypt 校验
func checkPassword(hash, pwd string) bool {
	return bcrypt.CompareHashAndPassword([]byte(hash), []byte(pwd)) == nil
}

// pageParams 取分页参数，默认第 1 页、每页 10 条
func pageParams(c *gin.Context) (page, size int) {
	page, _ = strconv.Atoi(c.DefaultQuery("page", "1"))
	size, _ = strconv.Atoi(c.DefaultQuery("size", "10"))
	if page < 1 {
		page = 1
	}
	if size < 1 || size > 100 {
		size = 10
	}
	return
}

// pageData 分页返回结构
func pageData(total int64, list interface{}) gin.H {
	return gin.H{"total": total, "list": list}
}

// parseDate 解析 yyyy-MM-dd
func parseDate(s string) (time.Time, bool) {
	t, err := time.ParseInLocation("2006-01-02", s, time.Local)
	return t, err == nil
}

// randCode 生成 6 位数字取件码
func randCode() string {
	n, err := rand.Int(rand.Reader, big.NewInt(900000))
	if err != nil {
		return "000000"
	}
	return strconv.FormatInt(n.Int64()+100000, 10)
}
