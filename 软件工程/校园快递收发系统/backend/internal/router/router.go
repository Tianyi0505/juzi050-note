package router

import (
	"time"

	"campus-express/internal/handler"

	"github.com/gin-contrib/cors"
	"github.com/gin-gonic/gin"
)

// Setup 注册全部接口路由
func Setup() *gin.Engine {
	r := gin.New()
	r.Use(gin.Logger(), gin.Recovery(), cors.New(cors.Config{
		// 会话放在 Cookie 里，必须允许携带凭证，因此不能使用 AllowAllOrigins
		AllowOriginFunc:  func(origin string) bool { return true },
		AllowMethods:     []string{"GET", "POST", "PUT", "DELETE", "OPTIONS"},
		AllowHeaders:     []string{"Content-Type"},
		AllowCredentials: true,
		MaxAge:           12 * time.Hour,
	}))

	// 不需要登录的接口
	r.GET("/api/ping", func(c *gin.Context) { handler.OK(c, "pong") })
	r.POST("/api/auth/login", handler.Login)
	r.POST("/api/auth/register", handler.Register)

	api := r.Group("/api", handler.Auth())
	{
		// 登录与个人中心
		api.POST("/auth/logout", handler.Logout)
		api.GET("/auth/me", handler.Me)
		api.PUT("/auth/me", handler.UpdateMe)
		api.PUT("/auth/password", handler.UpdateMyPassword)

		// 用户管理（管理员）
		api.GET("/users", handler.ListUsers)
		api.POST("/users", handler.CreateUser)
		api.GET("/users/:id", handler.GetUser)
		api.PUT("/users/:id", handler.UpdateUser)
		api.PUT("/users/:id/status", handler.UpdateUserStatus)
		api.PUT("/users/:id/password", handler.ResetUserPassword)
		api.DELETE("/users/:id", handler.DeleteUser)

		// 驿站管理
		api.GET("/stations", handler.ListStations)
		api.POST("/stations", handler.CreateStation)
		api.GET("/stations/:id", handler.GetStation)
		api.PUT("/stations/:id", handler.UpdateStation)
		api.DELETE("/stations/:id", handler.DeleteStation)

		// 包裹业务
		api.GET("/parcels", handler.ListParcels)
		api.POST("/parcels", handler.CreateParcel)
		api.GET("/parcels/:id", handler.GetParcel)
		api.PUT("/parcels/:id", handler.UpdateParcel)
		api.DELETE("/parcels/:id", handler.DeleteParcel)
		api.POST("/parcels/:id/pickup", handler.PickupParcel)
		api.POST("/parcels/:id/return", handler.ReturnParcel)

		// 我的包裹（学生）
		api.GET("/my/parcels", handler.MyParcels)

		// 取件码查询与核销（工作人员）
		api.GET("/pickup/:code", handler.ParcelByCode)
		api.POST("/pickup", handler.PickupByCode)

		// 取件记录
		api.GET("/pickup-records", handler.ListPickupRecords)

		// 公告
		api.GET("/notices", handler.ListNotices)
		api.POST("/notices", handler.CreateNotice)
		api.GET("/notices/:id", handler.GetNotice)
		api.PUT("/notices/:id", handler.UpdateNotice)
		api.DELETE("/notices/:id", handler.DeleteNotice)

		// 数据统计
		api.GET("/stats/overview", handler.Overview)
		api.GET("/stats/company", handler.CompanyStats)
		api.GET("/stats/station", handler.StationStats)
		api.GET("/stats/trend", handler.TrendStats)
	}

	return r
}
