// Package test 是接口级自动化测试。
// 用例编号与《测试用例.md》一一对应。
//
// 运行前准备：
//  1. 启动 MySQL 并导入 db/campus_express.sql
//  2. 启动 Redis
//  3. 在 backend 目录执行：go test ./test/ -v
//
// 连接信息用环境变量覆盖，和正式启动一致：
//
//	MYSQL_HOST MYSQL_PORT MYSQL_USER MYSQL_PASSWORD MYSQL_DB
//	REDIS_ADDR REDIS_PASSWORD REDIS_DB
package test

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"net/http/cookiejar"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"campus-express/internal/cache"
	"campus-express/internal/db"
	"campus-express/internal/router"

	"github.com/gin-gonic/gin"
)

var srv *httptest.Server

const (
	adminPhone   = "13800000000"
	staffPhone   = "13800000001"
	studentPhone = "13800000002"
	password     = "123456"
)

func TestMain(m *testing.M) {
	gin.SetMode(gin.TestMode)

	mysqlAddr := env("MYSQL_HOST", "127.0.0.1") + ":" + env("MYSQL_PORT", "3306")
	redisAddr := env("REDIS_ADDR", "127.0.0.1:6379")
	if !reachable(mysqlAddr) {
		fmt.Println("跳过测试：MySQL 未启动（" + mysqlAddr + "）")
		os.Exit(0)
	}
	if !reachable(redisAddr) {
		fmt.Println("跳过测试：Redis 未启动（" + redisAddr + "）")
		os.Exit(0)
	}

	db.Init()
	cache.Init()
	srv = httptest.NewServer(router.Setup())

	code := m.Run()
	srv.Close()
	os.Exit(code)
}

func env(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func reachable(addr string) bool {
	conn, err := net.DialTimeout("tcp", addr, 2*time.Second)
	if err != nil {
		return false
	}
	conn.Close()
	return true
}

// ---------------------------------------------------------------- 测试客户端

type client struct {
	t    *testing.T
	http *http.Client
}

func newClient(t *testing.T) *client {
	jar, _ := cookiejar.New(nil)
	return &client{t: t, http: &http.Client{Jar: jar, Timeout: 15 * time.Second}}
}

func (c *client) call(method, path string, body any) (int, http.Header, map[string]any) {
	c.t.Helper()
	var reader *bytes.Reader
	if body != nil {
		raw, _ := json.Marshal(body)
		reader = bytes.NewReader(raw)
	} else {
		reader = bytes.NewReader(nil)
	}
	req, err := http.NewRequest(method, srv.URL+path, reader)
	if err != nil {
		c.t.Fatalf("构造请求失败：%v", err)
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.http.Do(req)
	if err != nil {
		c.t.Fatalf("%s %s 请求失败：%v", method, path, err)
	}
	defer resp.Body.Close()

	out := map[string]any{}
	_ = json.NewDecoder(resp.Body).Decode(&out)
	return resp.StatusCode, resp.Header, out
}

// expect 断言业务码与提示
func (c *client) expect(method, path string, body any, wantCode int, wantMsg string) map[string]any {
	c.t.Helper()
	_, _, out := c.call(method, path, body)
	if code := bizCode(out); code != wantCode {
		c.t.Fatalf("%s %s 期望 code=%d，实际 code=%d，msg=%v", method, path, wantCode, code, out["msg"])
	}
	if wantMsg != "" {
		msg, _ := out["msg"].(string)
		if !strings.Contains(msg, wantMsg) {
			c.t.Fatalf("%s %s 期望提示包含「%s」，实际「%s」", method, path, wantMsg, msg)
		}
	}
	return out
}

func (c *client) ok(method, path string, body any) map[string]any {
	c.t.Helper()
	return c.expect(method, path, body, 200, "")
}

func bizCode(out map[string]any) int {
	if v, ok := out["code"].(float64); ok {
		return int(v)
	}
	return -1
}

func obj(out map[string]any) map[string]any {
	v, _ := out["data"].(map[string]any)
	return v
}

func arr(out map[string]any) []any {
	v, _ := out["data"].([]any)
	return v
}

func pageList(out map[string]any) []any {
	v, _ := obj(out)["list"].([]any)
	return v
}

func num(v any) int {
	f, _ := v.(float64)
	return int(f)
}

func userObj(out map[string]any) map[string]any {
	v, _ := obj(out)["user"].(map[string]any)
	return v
}

func str(v any) string {
	s, _ := v.(string)
	return s
}

// sub 把失败信息绑定到当前子测试
func (c *client) sub(t *testing.T) *client {
	c.t = t
	return c
}

// login 用手机号登录，返回带 Cookie 的客户端
func login(t *testing.T, phone string) *client {
	t.Helper()
	c := newClient(t)
	c.ok("POST", "/api/auth/login", gin.H{"phone": phone, "password": password})
	return c
}

func suffix() string {
	return fmt.Sprintf("%06d", time.Now().UnixNano()%1000000)
}

// 造一条包裹，返回 id 与取件码
func newParcel(t *testing.T, staff *client, stationID int) (int, string) {
	t.Helper()
	out := staff.ok("POST", "/api/parcels", gin.H{
		"trackingNo":    "T" + suffix(),
		"company":       "顺丰速运",
		"receiverName":  "自动化测试",
		"receiverPhone": studentPhone,
		"stationId":     stationID,
		"shelfCode":     "Z-01",
	})
	d := obj(out)
	return num(d["id"]), str(d["pickupCode"])
}

// ---------------------------------------------------------------- 模块一：认证与权限

func TestAuth(t *testing.T) {
	admin := newClient(t)

	t.Run("T01 管理员正确登录", func(t *testing.T) {
		admin.sub(t)
		status, header, out := admin.call("POST", "/api/auth/login",
			gin.H{"phone": adminPhone, "password": password})
		if status != 200 || bizCode(out) != 200 {
			t.Fatalf("登录失败：status=%d out=%v", status, out)
		}
		cookie := header.Get("Set-Cookie")
		if !strings.Contains(cookie, "session_id=") || !strings.Contains(strings.ToLower(cookie), "httponly") {
			t.Fatalf("Cookie 不符合预期：%s", cookie)
		}
	})

	t.Run("T02 密码错误", func(t *testing.T) {
		admin.sub(t)
		c := newClient(t)
		c.expect("POST", "/api/auth/login", gin.H{"phone": adminPhone, "password": "wrong"}, 400, "密码错误")
	})

	t.Run("T04 手机号不存在", func(t *testing.T) {
		admin.sub(t)
		c := newClient(t)
		c.expect("POST", "/api/auth/login", gin.H{"phone": "13800009999", "password": password}, 400, "账号不存在")
	})

	t.Run("S01 不带 Cookie 访问受保护接口", func(t *testing.T) {
		admin.sub(t)
		c := newClient(t)
		c.expect("GET", "/api/auth/me", nil, 401, "未登录或登录已失效")
	})

	t.Run("S02 伪造 Cookie", func(t *testing.T) {
		admin.sub(t)
		c := newClient(t)
		req, _ := http.NewRequest("GET", srv.URL+"/api/auth/me", nil)
		req.AddCookie(&http.Cookie{Name: "session_id", Value: "0123456789abcdef0123456789abcdef"})
		resp, err := c.http.Do(req)
		if err != nil {
			t.Fatalf("请求失败：%v", err)
		}
		defer resp.Body.Close()
		out := map[string]any{}
		_ = json.NewDecoder(resp.Body).Decode(&out)
		if bizCode(out) != 401 {
			t.Fatalf("伪造 Cookie 应返回 401，实际 %v", out["code"])
		}
	})

	t.Run("S03 学生访问管理接口", func(t *testing.T) {
		admin.sub(t)
		student := login(t, studentPhone)
		student.expect("GET", "/api/users", nil, 403, "仅管理员可操作")
	})

	t.Run("S04 退出登录后旧 Cookie 失效", func(t *testing.T) {
		admin.sub(t)
		c := login(t, staffPhone)
		c.ok("GET", "/api/parcels?page=1&size=1", nil)
		c.ok("POST", "/api/auth/logout", nil)
		c.expect("GET", "/api/parcels?page=1&size=1", nil, 401, "未登录或登录已失效")
	})

	t.Run("S05 改密后旧会话失效", func(t *testing.T) {
		admin.sub(t)
		phone := "13900" + suffix()
		c := newClient(t)
		c.ok("POST", "/api/auth/register", gin.H{"phone": phone, "password": password, "name": "改密测试"})
		c.ok("PUT", "/api/auth/password", gin.H{"oldPassword": password, "newPassword": "654321"})
		c.expect("GET", "/api/auth/me", nil, 401, "未登录或登录已失效")
	})

	t.Run("S06 禁用账号后旧会话失效", func(t *testing.T) {
		admin.sub(t)
		phone := "13901" + suffix()
		reg := newClient(t)
		out := reg.ok("POST", "/api/auth/register", gin.H{"phone": phone, "password": password, "name": "禁用测试"})
		uid := num(userObj(out)["id"])

		admin.ok("PUT", fmt.Sprintf("/api/users/%d/status?status=0", uid), nil)
		reg.expect("GET", "/api/auth/me", nil, 403, "账号已被禁用")
		admin.ok("PUT", fmt.Sprintf("/api/users/%d/status?status=1", uid), nil)
		t.Cleanup(func() { admin.ok("DELETE", fmt.Sprintf("/api/users/%d", uid), nil) })
	})

	t.Run("T03 账号被禁用后无法登录", func(t *testing.T) {
		admin.sub(t)
		phone := "13902" + suffix()
		reg := newClient(t)
		out := reg.ok("POST", "/api/auth/register", gin.H{"phone": phone, "password": password, "name": "禁用登录"})
		uid := num(userObj(out)["id"])
		admin.ok("PUT", fmt.Sprintf("/api/users/%d/status?status=0", uid), nil)

		c := newClient(t)
		c.expect("POST", "/api/auth/login", gin.H{"phone": phone, "password": password}, 403, "账号已被禁用")
		admin.ok("PUT", fmt.Sprintf("/api/users/%d/status?status=1", uid), nil)
		t.Cleanup(func() { admin.ok("DELETE", fmt.Sprintf("/api/users/%d", uid), nil) })
	})
}

// ---------------------------------------------------------------- 模块二：包裹入库

func TestParcelInbound(t *testing.T) {
	staff := login(t, staffPhone)
	student := login(t, studentPhone)

	t.Run("T07 工作人员正常入库", func(t *testing.T) {
		student.sub(t)
		staff.sub(t)
		id, code := newParcel(t, staff, 1)
		if id == 0 || len(code) != 6 {
			t.Fatalf("入库结果不符合预期：id=%d code=%s", id, code)
		}
		t.Cleanup(func() { staff.call("POST", fmt.Sprintf("/api/parcels/%d/return", id), nil) })
	})

	t.Run("T08 连续入库取件码不重复", func(t *testing.T) {
		student.sub(t)
		staff.sub(t)
		codes := map[string]bool{}
		for i := 0; i < 5; i++ {
			_, code := newParcel(t, staff, 1)
			if codes[code] {
				t.Fatalf("取件码重复：%s", code)
			}
			codes[code] = true
		}
	})

	t.Run("V01 缺少运单号", func(t *testing.T) {
		student.sub(t)
		staff.sub(t)
		staff.expect("POST", "/api/parcels",
			gin.H{"receiverPhone": studentPhone, "stationId": 1}, 400, "运单号不能为空")
	})

	t.Run("V02 手机号不是 11 位", func(t *testing.T) {
		student.sub(t)
		staff.sub(t)
		staff.expect("POST", "/api/parcels",
			gin.H{"trackingNo": "V002", "receiverPhone": "138", "stationId": 1}, 400, "收件人手机号长度必须为 11 位")
	})

	t.Run("V03 缺少驿站", func(t *testing.T) {
		student.sub(t)
		staff.sub(t)
		staff.expect("POST", "/api/parcels",
			gin.H{"trackingNo": "V003", "receiverPhone": studentPhone}, 400, "驿站不能为空")
	})

	t.Run("V04 驿站不存在", func(t *testing.T) {
		student.sub(t)
		staff.sub(t)
		staff.expect("POST", "/api/parcels",
			gin.H{"trackingNo": "V004", "receiverPhone": studentPhone, "stationId": 9999}, 400, "驿站不存在")
	})

	t.Run("V05 驿站已停用", func(t *testing.T) {
		student.sub(t)
		staff.sub(t)
		admin := login(t, adminPhone)
		out := admin.ok("POST", "/api/stations", gin.H{"name": "停用测试点" + suffix(), "status": 0})
		sid := num(obj(out)["id"])
		t.Cleanup(func() { admin.ok("DELETE", fmt.Sprintf("/api/stations/%d", sid), nil) })

		staff.expect("POST", "/api/parcels",
			gin.H{"trackingNo": "V005", "receiverPhone": studentPhone, "stationId": sid}, 400, "该驿站已停用，不能入库")
	})

	t.Run("V06 学生调用入库接口", func(t *testing.T) {
		student.sub(t)
		staff.sub(t)
		student.expect("POST", "/api/parcels",
			gin.H{"trackingNo": "V006", "receiverPhone": studentPhone, "stationId": 1}, 403, "仅驿站工作人员可操作")
	})
}

// ---------------------------------------------------------------- 模块三：包裹查询

func TestParcelQuery(t *testing.T) {
	staff := login(t, staffPhone)
	student := login(t, studentPhone)

	tracking := "Q" + suffix()
	staff.ok("POST", "/api/parcels", gin.H{
		"trackingNo": tracking, "company": "圆通速递", "receiverName": "查询测试",
		"receiverPhone": studentPhone, "stationId": 1, "shelfCode": "Q-01",
	})

	t.Run("T13 按状态查待取件", func(t *testing.T) {
		student.sub(t)
		staff.sub(t)
		for _, item := range pageList(staff.ok("GET", "/api/parcels?status=0&page=1&size=20", nil)) {
			if status := num(item.(map[string]any)["status"]); status != 0 {
				t.Fatalf("状态过滤失效：%d", status)
			}
		}
	})

	t.Run("T14 按运单号模糊查询", func(t *testing.T) {
		student.sub(t)
		staff.sub(t)
		list := pageList(staff.ok("GET", "/api/parcels?keyword="+tracking, nil))
		if len(list) == 0 {
			t.Fatalf("关键词查询无结果：%s", tracking)
		}
	})

	t.Run("T15 按手机号精确查询", func(t *testing.T) {
		student.sub(t)
		staff.sub(t)
		for _, item := range pageList(staff.ok("GET", "/api/parcels?phone="+studentPhone, nil)) {
			if phone := str(item.(map[string]any)["receiverPhone"]); phone != studentPhone {
				t.Fatalf("手机号过滤失效：%s", phone)
			}
		}
	})

	t.Run("T16 按驿站与日期组合查询", func(t *testing.T) {
		student.sub(t)
		staff.sub(t)
		today := time.Now().Format("2006-01-02")
		out := staff.ok("GET", "/api/parcels?stationId=1&startTime="+today+"&endTime="+today, nil)
		if len(pageList(out)) == 0 {
			t.Fatal("按驿站与日期查询无结果")
		}
	})

	t.Run("T17 学生查我的包裹", func(t *testing.T) {
		student.sub(t)
		staff.sub(t)
		for _, item := range pageList(student.ok("GET", "/api/my/parcels", nil)) {
			if phone := str(item.(map[string]any)["receiverPhone"]); phone != studentPhone {
				t.Fatalf("我的包裹混入其他号码：%s", phone)
			}
		}
	})

	t.Run("T18 状态参数非法", func(t *testing.T) {
		student.sub(t)
		staff.sub(t)
		staff.expect("GET", "/api/parcels?status=9", nil, 400, "状态只能是")
	})

	t.Run("V07 取件码位数不对", func(t *testing.T) {
		student.sub(t)
		staff.sub(t)
		staff.expect("GET", "/api/pickup/123", nil, 400, "取件码必须是 6 位数字")
	})

	t.Run("V08 取件码不存在", func(t *testing.T) {
		student.sub(t)
		staff.sub(t)
		staff.expect("GET", "/api/pickup/000000", nil, 404, "取件码无效")
	})
}

// ---------------------------------------------------------------- 模块四：取件核销与退回

func TestPickup(t *testing.T) {
	staff := login(t, staffPhone)

	t.Run("T19 按取件码核销", func(t *testing.T) {
		staff.sub(t)
		_, code := newParcel(t, staff, 1)
		out := staff.ok("POST", "/api/pickup", gin.H{"pickupCode": code, "pickupType": 1})
		d := obj(out)
		if num(d["pickupType"]) != 1 || num(d["parcelId"]) == 0 {
			t.Fatalf("取件记录不符合预期：%v", d)
		}
	})

	t.Run("T20 代取核销", func(t *testing.T) {
		staff.sub(t)
		_, code := newParcel(t, staff, 1)
		d := obj(staff.ok("POST", "/api/pickup",
			gin.H{"pickupCode": code, "pickupType": 2, "pickerName": "代取人"}))
		if num(d["pickupType"]) != 2 || str(d["pickerName"]) != "代取人" {
			t.Fatalf("代取记录不符合预期：%v", d)
		}
	})

	t.Run("T21 按包裹编号核销", func(t *testing.T) {
		staff.sub(t)
		id, _ := newParcel(t, staff, 1)
		staff.ok("POST", fmt.Sprintf("/api/parcels/%d/pickup", id), gin.H{"pickupType": 1})
		d := obj(staff.ok("GET", fmt.Sprintf("/api/parcels/%d", id), nil))
		if num(d["status"]) != 1 {
			t.Fatalf("核销后状态应为 1，实际 %v", d["status"])
		}
	})

	t.Run("T22 退回待取件包裹", func(t *testing.T) {
		staff.sub(t)
		id, _ := newParcel(t, staff, 1)
		d := obj(staff.ok("POST", fmt.Sprintf("/api/parcels/%d/return", id), gin.H{"remark": "测试退回"}))
		if num(d["status"]) != 3 {
			t.Fatalf("退回后状态应为 3，实际 %v", d["status"])
		}
	})

	t.Run("T23 修改包裹货架号", func(t *testing.T) {
		staff.sub(t)
		id, _ := newParcel(t, staff, 1)
		d := obj(staff.ok("PUT", fmt.Sprintf("/api/parcels/%d", id), gin.H{"shelfCode": "Z-99"}))
		if str(d["shelfCode"]) != "Z-99" {
			t.Fatalf("货架号未更新：%v", d["shelfCode"])
		}
	})

	t.Run("T24 查询取件记录", func(t *testing.T) {
		staff.sub(t)
		out := staff.ok("GET", "/api/pickup-records?phone="+studentPhone+"&page=1&size=5", nil)
		if len(pageList(out)) == 0 {
			t.Fatal("取件记录为空")
		}
	})

	t.Run("V09 重复核销", func(t *testing.T) {
		staff.sub(t)
		_, code := newParcel(t, staff, 1)
		staff.ok("POST", "/api/pickup", gin.H{"pickupCode": code})
		staff.expect("POST", "/api/pickup", gin.H{"pickupCode": code}, 404, "取件码无效或该包裹已取走")
	})

	t.Run("V10 核销已退回包裹", func(t *testing.T) {
		staff.sub(t)
		id, code := newParcel(t, staff, 1)
		staff.ok("POST", fmt.Sprintf("/api/parcels/%d/return", id), nil)
		staff.expect("POST", "/api/pickup", gin.H{"pickupCode": code}, 404, "取件码无效或该包裹已取走")
		staff.expect("POST", fmt.Sprintf("/api/parcels/%d/pickup", id), nil, 400, "该包裹已退回，不能取件")
	})

	t.Run("V11 修改已取件包裹", func(t *testing.T) {
		staff.sub(t)
		id, _ := newParcel(t, staff, 1)
		staff.ok("POST", fmt.Sprintf("/api/parcels/%d/pickup", id), nil)
		staff.expect("PUT", fmt.Sprintf("/api/parcels/%d", id), gin.H{"shelfCode": "Z-88"},
			400, "已取件或已退回的包裹不能修改")
	})

	t.Run("V12 退回已取件包裹", func(t *testing.T) {
		staff.sub(t)
		id, _ := newParcel(t, staff, 1)
		staff.ok("POST", fmt.Sprintf("/api/parcels/%d/pickup", id), nil)
		staff.expect("POST", fmt.Sprintf("/api/parcels/%d/return", id), nil, 400, "该包裹已取件，不能退回")
	})

	t.Run("V13 取件方式非法", func(t *testing.T) {
		staff.sub(t)
		_, code := newParcel(t, staff, 1)
		staff.expect("POST", "/api/pickup", gin.H{"pickupCode": code, "pickupType": 3}, 400,
			"取件方式只能是 1 / 2")
	})
}

// ---------------------------------------------------------------- 模块五：驿站管理

func TestStation(t *testing.T) {
	admin := login(t, adminPhone)
	name := "自动化驿站" + suffix()

	var sid int
	t.Run("T25 新增驿站", func(t *testing.T) {
		admin.sub(t)
		out := admin.ok("POST", "/api/stations", gin.H{
			"name": name, "address": "测试楼 1 号", "manager": "测试员",
			"phone": "13700000000", "openTime": "08:00", "closeTime": "20:00",
		})
		sid = num(obj(out)["id"])
		if sid == 0 {
			t.Fatal("新增驿站未返回 id")
		}
	})

	t.Run("T26 修改驿站", func(t *testing.T) {
		admin.sub(t)
		admin.ok("PUT", fmt.Sprintf("/api/stations/%d", sid), gin.H{
			"name": name, "address": "测试楼 2 号", "manager": "测试员",
			"phone": "13700000000", "openTime": "09:00", "closeTime": "19:00", "status": 1,
		})
		d := obj(admin.ok("GET", fmt.Sprintf("/api/stations/%d", sid), nil))
		if str(d["address"]) != "测试楼 2 号" {
			t.Fatalf("地址未更新：%v", d["address"])
		}
	})

	t.Run("T27 删除空驿站", func(t *testing.T) {
		admin.sub(t)
		admin.ok("DELETE", fmt.Sprintf("/api/stations/%d", sid), nil)
		admin.expect("GET", fmt.Sprintf("/api/stations/%d", sid), nil, 404, "驿站不存在")
	})

	t.Run("T28 删除有包裹的驿站", func(t *testing.T) {
		admin.sub(t)
		admin.expect("DELETE", "/api/stations/1", nil, 400, "该驿站下还有包裹")
	})

	t.Run("V14 驿站名称为空", func(t *testing.T) {
		admin.sub(t)
		admin.expect("POST", "/api/stations", gin.H{"address": "测试"}, 400, "驿站名称不能为空")
	})

	t.Run("V15 营业时间格式错误", func(t *testing.T) {
		admin.sub(t)
		admin.expect("POST", "/api/stations", gin.H{"name": "格式测试", "openTime": "8点"},
			400, "营业时间格式必须是 HH:mm")
	})

	t.Run("V16 新建停用驿站", func(t *testing.T) {
		admin.sub(t)
		out := admin.ok("POST", "/api/stations", gin.H{"name": "停用点" + suffix(), "status": 0})
		id := num(obj(out)["id"])
		d := obj(admin.ok("GET", fmt.Sprintf("/api/stations/%d", id), nil))
		if num(d["status"]) != 0 {
			t.Fatalf("停用驿站 status 应为 0，实际 %v", d["status"])
		}
		admin.ok("DELETE", fmt.Sprintf("/api/stations/%d", id), nil)
	})
}

// ---------------------------------------------------------------- 模块六：用户管理

func TestUser(t *testing.T) {
	admin := login(t, adminPhone)
	phone := "13890" + suffix()

	var uid int
	t.Run("T29 新增工作人员", func(t *testing.T) {
		admin.sub(t)
		out := admin.ok("POST", "/api/users", gin.H{
			"phone": phone, "password": password, "name": "测试员工", "role": "STAFF", "stationId": 1,
		})
		uid = num(obj(out)["id"])
		login(t, phone)
	})

	t.Run("T30 修改角色与驿站", func(t *testing.T) {
		admin.sub(t)
		admin.ok("PUT", fmt.Sprintf("/api/users/%d", uid), gin.H{
			"name": "测试员工", "role": "STAFF", "stationId": 2,
		})
		d := obj(admin.ok("GET", fmt.Sprintf("/api/users/%d", uid), nil))
		if num(d["stationId"]) != 2 {
			t.Fatalf("驿站未更新：%v", d["stationId"])
		}
	})

	t.Run("T31 禁用与启用", func(t *testing.T) {
		admin.sub(t)
		admin.ok("PUT", fmt.Sprintf("/api/users/%d/status?status=0", uid), nil)
		c := newClient(t)
		c.expect("POST", "/api/auth/login", gin.H{"phone": phone, "password": password}, 403, "账号已被禁用")

		admin.ok("PUT", fmt.Sprintf("/api/users/%d/status?status=1", uid), nil)
		login(t, phone)
	})

	t.Run("T32 重置密码", func(t *testing.T) {
		admin.sub(t)
		admin.ok("PUT", fmt.Sprintf("/api/users/%d/password", uid), gin.H{})
		login(t, phone)
	})

	t.Run("T33 删除用户", func(t *testing.T) {
		admin.sub(t)
		admin.ok("DELETE", fmt.Sprintf("/api/users/%d", uid), nil)
		admin.expect("GET", fmt.Sprintf("/api/users/%d", uid), nil, 404, "用户不存在")
	})

	t.Run("V17 工作人员未指定驿站", func(t *testing.T) {
		admin.sub(t)
		admin.expect("POST", "/api/users",
			gin.H{"phone": "13891" + suffix(), "password": password, "role": "STAFF"},
			400, "工作人员必须指定所属驿站")
	})

	t.Run("V18 角色非法", func(t *testing.T) {
		admin.sub(t)
		admin.expect("POST", "/api/users",
			gin.H{"phone": "13892" + suffix(), "password": password, "role": "SUPER"},
			400, "角色只能是 USER / STAFF / ADMIN")
	})

	t.Run("V19 状态值非法", func(t *testing.T) {
		admin.sub(t)
		admin.expect("PUT", "/api/users/3/status?status=5", nil, 400, "状态只能是 0（禁用）或 1（正常）")
	})

	t.Run("V20 禁用自己", func(t *testing.T) {
		admin.sub(t)
		me := obj(admin.ok("GET", "/api/auth/me", nil))
		admin.expect("PUT", fmt.Sprintf("/api/users/%d/status?status=0", num(me["id"])), nil,
			400, "不能禁用自己")
	})

	t.Run("V21 手机号重复注册", func(t *testing.T) {
		admin.sub(t)
		c := newClient(t)
		c.expect("POST", "/api/auth/register", gin.H{"phone": studentPhone, "password": password},
			400, "该手机号已注册")
	})
}

// ---------------------------------------------------------------- 模块七：公告与统计

func TestNoticeAndStats(t *testing.T) {
	admin := login(t, adminPhone)
	student := login(t, studentPhone)

	var nid int
	t.Run("T34 发布公告", func(t *testing.T) {
		student.sub(t)
		admin.sub(t)
		out := admin.ok("POST", "/api/notices", gin.H{
			"title": "自动化测试公告" + suffix(), "content": "测试内容",
		})
		nid = num(obj(out)["id"])
		if str(obj(out)["publisher"]) != "系统管理员" {
			t.Fatalf("发布人应为当前用户，实际 %v", obj(out)["publisher"])
		}
	})

	t.Run("T35 修改与删除公告", func(t *testing.T) {
		student.sub(t)
		admin.sub(t)
		admin.ok("PUT", fmt.Sprintf("/api/notices/%d", nid), gin.H{"title": "已修改标题", "content": "新内容"})
		admin.ok("DELETE", fmt.Sprintf("/api/notices/%d", nid), nil)
		admin.expect("GET", fmt.Sprintf("/api/notices/%d", nid), nil, 404, "公告不存在")
	})

	t.Run("T36 学生发布公告", func(t *testing.T) {
		student.sub(t)
		admin.sub(t)
		student.expect("POST", "/api/notices", gin.H{"title": "越权"}, 403, "仅管理员可操作")
	})

	t.Run("T37 数据概览", func(t *testing.T) {
		student.sub(t)
		admin.sub(t)
		d := obj(admin.ok("GET", "/api/stats/overview", nil))
		for _, key := range []string{"parcelTotal", "pendingCount", "pickedCount", "expiredCount",
			"returnedCount", "todayInbound", "todayPicked", "userCount", "stationCount"} {
			if _, exists := d[key]; !exists {
				t.Fatalf("概览缺少字段 %s", key)
			}
		}
	})

	t.Run("T38 快递公司分布", func(t *testing.T) {
		student.sub(t)
		admin.sub(t)
		list := arr(admin.ok("GET", "/api/stats/company", nil))
		sum := 0
		for _, item := range list {
			sum += num(item.(map[string]any)["num"])
		}
		total := num(obj(admin.ok("GET", "/api/stats/overview", nil))["parcelTotal"])
		if sum != total {
			t.Fatalf("公司分布合计 %d 与包裹总数 %d 不一致", sum, total)
		}
	})

	t.Run("T39 近 7 天趋势", func(t *testing.T) {
		student.sub(t)
		admin.sub(t)
		list := arr(admin.ok("GET", "/api/stats/trend?days=7", nil))
		if len(list) != 7 {
			t.Fatalf("趋势应返回 7 条，实际 %d", len(list))
		}
	})
}
