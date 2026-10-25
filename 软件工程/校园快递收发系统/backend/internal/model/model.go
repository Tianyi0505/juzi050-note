package model

import "time"

// 用户角色
const (
	RoleUser  = "USER"  // 学生 / 教职工
	RoleStaff = "STAFF" // 驿站工作人员
	RoleAdmin = "ADMIN" // 管理员
)

// 包裹状态：0 待取件 -> 1 已取件 / 3 已退回，0 超 72 小时 -> 2 超期
const (
	ParcelPending  = 0
	ParcelPicked   = 1
	ParcelExpired  = 2
	ParcelReturned = 3
)

// CanPickup 只有待取件、超期的包裹可以核销取件
func CanPickup(status int) bool {
	return status == ParcelPending || status == ParcelExpired
}

// CanReturn 只有待取件、超期的包裹可以退回
func CanReturn(status int) bool {
	return status == ParcelPending || status == ParcelExpired
}

// CanEdit 已取件、已退回的包裹不再允许修改
func CanEdit(status int) bool {
	return status == ParcelPending || status == ParcelExpired
}

// User 用户表：学生 / 驿站工作人员 / 管理员
type User struct {
	ID         uint      `gorm:"primaryKey" json:"id"`
	Phone      string    `gorm:"size:20;uniqueIndex;not null" json:"phone"`
	Password   string    `gorm:"size:64;not null" json:"-"`
	Name       string    `gorm:"size:50" json:"name"`
	Role       string    `gorm:"size:20;not null;default:USER" json:"role"` // USER / STAFF / ADMIN
	StationID  *uint     `json:"stationId"`                                 // 工作人员所属驿站
	Status     int       `gorm:"not null;default:1" json:"status"`          // 1 正常 0 禁用
	CreateTime time.Time `gorm:"autoCreateTime" json:"createTime"`
}

func (User) TableName() string { return "sys_user" }

// Station 驿站表：校内快递代收点
type Station struct {
	ID         uint      `gorm:"primaryKey" json:"id"`
	Name       string    `gorm:"size:50;not null" json:"name"`
	Address    string    `gorm:"size:100" json:"address"`
	Manager    string    `gorm:"size:50" json:"manager"`
	Phone      string    `gorm:"size:20" json:"phone"`
	OpenTime   string    `gorm:"size:10" json:"openTime"`
	CloseTime  string    `gorm:"size:10" json:"closeTime"`
	Status     int       `gorm:"not null;default:1" json:"status"` // 1 营业 0 停用
	CreateTime time.Time `gorm:"autoCreateTime" json:"createTime"`
}

func (Station) TableName() string { return "station" }

// Parcel 包裹表
type Parcel struct {
	ID            uint       `gorm:"primaryKey" json:"id"`
	TrackingNo    string     `gorm:"size:50;not null" json:"trackingNo"`
	Company       string     `gorm:"size:30" json:"company"`
	ReceiverName  string     `gorm:"size:50" json:"receiverName"`
	ReceiverPhone string     `gorm:"size:20;not null;index" json:"receiverPhone"`
	StationID     uint       `json:"stationId"`
	ShelfCode     string     `gorm:"size:20" json:"shelfCode"`
	PickupCode    string     `gorm:"size:10;index" json:"pickupCode"`
	Status        int        `gorm:"not null;default:0" json:"status"` // 0 待取件 1 已取件 2 超期 3 已退回
	InboundTime   time.Time  `json:"inboundTime"`
	PickupTime    *time.Time `json:"pickupTime"`
	OperatorID    uint       `json:"operatorId"`
	Remark        string     `gorm:"size:200" json:"remark"`

	// 以下字段不落库，查询时补上，方便前端直接展示
	StationName string `gorm:"-" json:"stationName"`
}

func (Parcel) TableName() string { return "parcel" }

// PickupRecord 取件记录表
type PickupRecord struct {
	ID            uint      `gorm:"primaryKey" json:"id"`
	ParcelID      uint      `gorm:"not null;index" json:"parcelId"`
	TrackingNo    string    `gorm:"size:50" json:"trackingNo"`
	PickupCode    string    `gorm:"size:10" json:"pickupCode"`
	ReceiverPhone string    `gorm:"size:20" json:"receiverPhone"`
	PickupType    int       `gorm:"not null;default:1" json:"pickupType"` // 1 本人 2 代取
	PickerName    string    `gorm:"size:50" json:"pickerName"`
	OperatorID    uint      `json:"operatorId"`
	PickupTime    time.Time `json:"pickupTime"`
	Remark        string    `gorm:"size:200" json:"remark"`
}

func (PickupRecord) TableName() string { return "pickup_record" }

// Notice 公告表
type Notice struct {
	ID         uint      `gorm:"primaryKey" json:"id"`
	Title      string    `gorm:"size:100;not null" json:"title"`
	Content    string    `gorm:"type:text" json:"content"`
	Publisher  string    `gorm:"size:50" json:"publisher"`
	CreateTime time.Time `gorm:"autoCreateTime" json:"createTime"`
}

func (Notice) TableName() string { return "notice" }
