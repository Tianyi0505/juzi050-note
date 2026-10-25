package handler

import (
	"log"
	"strings"
	"time"

	"campus-express/internal/db"
	"campus-express/internal/model"

	"github.com/gin-gonic/gin"
)

// CreateParcel 包裹入库（工作人员录入，系统生成取件码并"发送"取件通知）
func CreateParcel(c *gin.Context) {
	if !RequireStaff(c) {
		return
	}
	var req struct {
		TrackingNo    string `json:"trackingNo" binding:"required,max=50"`
		CompanyCode   string `json:"companyCode" binding:"max=10"`
		ReceiverName  string `json:"receiverName" binding:"max=20"`
		ReceiverPhone string `json:"receiverPhone" binding:"required,len=11,numeric"`
		StationID     uint   `json:"stationId" binding:"required"`
		ShelfCode     string `json:"shelfCode" binding:"max=20"`
		Remark        string `json:"remark" binding:"max=200"`
	}
	if !BindJSON(c, &req) {
		return
	}
	// 快递公司传 code，不传中文：白名单校验后再落库，避免"顺丰""顺丰速运"这类脏数据
	if req.CompanyCode != "" && !model.ValidCompanyCode(req.CompanyCode) {
		Fail(c, 400, "快递公司只能是 "+strings.Join(model.CompanyCodes, "、")+" 之一")
		return
	}

	// 入库前确认驿站存在且正常营业
	var station model.Station
	if err := db.DB.First(&station, req.StationID).Error; err != nil {
		Fail(c, 400, "驿站不存在")
		return
	}
	if station.Status != 1 {
		Fail(c, 400, "该驿站已停用，不能入库")
		return
	}

	// 同一运单号不能重复入库，避免学生看到两条一样的包裹
	var exists model.Parcel
	if err := db.DB.Where("tracking_no = ? AND status <> ?", req.TrackingNo, model.ParcelReturned).
		Order("id DESC").First(&exists).Error; err == nil {
		Fail(c, 400, "该运单号已入库，取件码为 "+exists.PickupCode)
		return
	}

	p := model.Parcel{
		TrackingNo:    req.TrackingNo,
		CompanyCode:   req.CompanyCode,
		ReceiverName:  req.ReceiverName,
		ReceiverPhone: req.ReceiverPhone,
		StationID:     req.StationID,
		ShelfCode:     req.ShelfCode,
		PickupCode:    uniquePickupCode(),
		Status:        model.ParcelPending,
		InboundTime:   time.Now().Truncate(time.Second),
		OperatorID:    CurrentUser(c).ID,
		Remark:        req.Remark,
	}
	if err := db.DB.Create(&p).Error; err != nil {
		Fail(c, 500, "入库失败："+err.Error())
		return
	}

	// 取件通知（课程设计不接短信网关，用日志模拟）
	log.Printf("【取件通知】%s 的包裹 %s 已到达「%s」，取件码 %s",
		p.ReceiverPhone, p.TrackingNo, station.Name, p.PickupCode)

	p.StationName = station.Name
	p.Company = model.CompanyName(p.CompanyCode)
	OK(c, p)
}

// uniquePickupCode 生成一个未使用的 6 位取件码
func uniquePickupCode() string {
	for i := 0; i < 20; i++ {
		code := randCode()
		var count int64
		db.DB.Model(&model.Parcel{}).
			Where("pickup_code = ? AND status IN (0,2)", code).Count(&count)
		if count == 0 {
			return code
		}
	}
	return randCode()
}

// fillStationNames 给列表补上驿站名称，避免前端为每条记录再查一次驿站
func fillStationNames(list []model.Parcel) {
	if len(list) == 0 {
		return
	}
	var stations []model.Station
	db.DB.Find(&stations)
	names := make(map[uint]string, len(stations))
	for _, s := range stations {
		names[s.ID] = s.Name
	}
	for i := range list {
		list[i].StationName = names[list[i].StationID]
		list[i].Company = model.CompanyName(list[i].CompanyCode)
	}
}

// decorateParcel 补齐单条包裹不落库的展示字段：公司中文名 + 驿站名称
func decorateParcel(p *model.Parcel) {
	p.Company = model.CompanyName(p.CompanyCode)
	var station model.Station
	if db.DB.First(&station, p.StationID).Error == nil {
		p.StationName = station.Name
	}
}

// validParcelStatus 校验状态取值
func validParcelStatus(s string) bool {
	return s == "0" || s == "1" || s == "2" || s == "3"
}

// ListParcels 包裹分页查询（工作人员 / 管理员）
func ListParcels(c *gin.Context) {
	if !RequireStaff(c) {
		return
	}
	page, size := pageParams(c)
	q := db.DB.Model(&model.Parcel{})

	if v := c.Query("status"); v != "" {
		if !validParcelStatus(v) {
			Fail(c, 400, "状态只能是 0（待取件）/ 1（已取件）/ 2（超期）/ 3（已退回）")
			return
		}
		q = q.Where("status = ?", v)
	}
	if v := c.Query("stationId"); v != "" {
		q = q.Where("station_id = ?", v)
	}
	if v := c.Query("companyCode"); v != "" {
		if !model.ValidCompanyCode(v) {
			Fail(c, 400, "快递公司只能是 "+strings.Join(model.CompanyCodes, "、")+" 之一")
			return
		}
		q = q.Where("company_code = ?", v)
	} else if v := c.Query("company"); v != "" {
		// 兼容旧参数：允许直接传中文公司名，后端翻成 code 再查
		q = q.Where("company_code = ?", model.CompanyCodeOf(v))
	}
	if v := c.Query("phone"); v != "" {
		q = q.Where("receiver_phone = ?", v)
	}
	if v := c.Query("keyword"); v != "" {
		like := "%" + v + "%"
		q = q.Where("tracking_no LIKE ? OR receiver_name LIKE ? OR receiver_phone LIKE ? OR pickup_code LIKE ?",
			like, like, like, like)
	}
	if v := c.Query("startTime"); v != "" {
		if t, ok := parseDate(v); ok {
			q = q.Where("inbound_time >= ?", t)
		}
	}
	if v := c.Query("endTime"); v != "" {
		if t, ok := parseDate(v); ok {
			q = q.Where("inbound_time < ?", t.AddDate(0, 0, 1))
		}
	}

	var total int64
	q.Count(&total)
	var list []model.Parcel
	q.Order("id DESC").Offset((page - 1) * size).Limit(size).Find(&list)
	fillStationNames(list)
	OK(c, pageData(total, list))
}

// GetParcel 包裹详情
func GetParcel(c *gin.Context) {
	id, ok := pathID(c)
	if !ok {
		return
	}
	var p model.Parcel
	if err := db.DB.First(&p, id).Error; err != nil {
		Fail(c, 404, "包裹不存在")
		return
	}
	decorateParcel(&p)
	OK(c, p)
}

// UpdateParcel 修改包裹信息（工作人员 / 管理员）
func UpdateParcel(c *gin.Context) {
	if !RequireStaff(c) {
		return
	}
	id, ok := pathID(c)
	if !ok {
		return
	}
	var p model.Parcel
	if err := db.DB.First(&p, id).Error; err != nil {
		Fail(c, 404, "包裹不存在")
		return
	}
	// 已取件、已退回是终态，不再允许修改
	if !model.CanEdit(p.Status) {
		Fail(c, 400, "已取件或已退回的包裹不能修改")
		return
	}

	var req struct {
		CompanyCode   string `json:"companyCode" binding:"max=10"`
		ReceiverName  string `json:"receiverName" binding:"max=20"`
		ReceiverPhone string `json:"receiverPhone" binding:"omitempty,len=11,numeric"`
		StationID     uint   `json:"stationId"`
		ShelfCode     string `json:"shelfCode" binding:"max=20"`
		Remark        string `json:"remark" binding:"max=200"`
	}
	if !BindJSON(c, &req) {
		return
	}
	if req.CompanyCode != "" && !model.ValidCompanyCode(req.CompanyCode) {
		Fail(c, 400, "快递公司只能是 "+strings.Join(model.CompanyCodes, "、")+" 之一")
		return
	}
	if req.StationID > 0 && !stationExists(req.StationID) {
		Fail(c, 400, "驿站不存在")
		return
	}

	if req.CompanyCode != "" {
		p.CompanyCode = req.CompanyCode
	}
	if req.ReceiverName != "" {
		p.ReceiverName = req.ReceiverName
	}
	if req.ReceiverPhone != "" {
		p.ReceiverPhone = req.ReceiverPhone
	}
	if req.StationID > 0 {
		p.StationID = req.StationID
	}
	if req.ShelfCode != "" {
		p.ShelfCode = req.ShelfCode
	}
	p.Remark = req.Remark
	p.OperatorID = CurrentUser(c).ID
	if err := db.DB.Save(&p).Error; err != nil {
		Fail(c, 500, "保存失败")
		return
	}
	decorateParcel(&p)
	OK(c, p)
}

// DeleteParcel 删除包裹（管理员）
func DeleteParcel(c *gin.Context) {
	if !RequireAdmin(c) {
		return
	}
	id, ok := pathID(c)
	if !ok {
		return
	}
	if err := db.DB.Delete(&model.Parcel{}, id).Error; err != nil {
		Fail(c, 500, "删除失败")
		return
	}
	OK(c, nil)
}

// MyParcels 我的包裹（按当前用户手机号查）
func MyParcels(c *gin.Context) {
	page, size := pageParams(c)
	u := CurrentUser(c)
	q := db.DB.Model(&model.Parcel{}).Where("receiver_phone = ?", u.Phone)
	if v := c.Query("status"); v != "" {
		if !validParcelStatus(v) {
			Fail(c, 400, "状态只能是 0（待取件）/ 1（已取件）/ 2（超期）/ 3（已退回）")
			return
		}
		q = q.Where("status = ?", v)
	}
	var total int64
	q.Count(&total)
	var list []model.Parcel
	q.Order("id DESC").Offset((page - 1) * size).Limit(size).Find(&list)
	fillStationNames(list)
	OK(c, pageData(total, list))
}

// ParcelByCode 按取件码查询待取包裹
func ParcelByCode(c *gin.Context) {
	code := c.Param("code")
	if len(code) != 6 {
		Fail(c, 400, "取件码必须是 6 位数字")
		return
	}
	var p model.Parcel
	if err := db.DB.Where("pickup_code = ? AND status IN (0,2)", code).
		Order("id DESC").First(&p).Error; err != nil {
		Fail(c, 404, "取件码无效或该包裹已取走")
		return
	}
	decorateParcel(&p)
	OK(c, p)
}

// PickupParcel 按包裹 id 核销取件（工作人员扫码/点选）
func PickupParcel(c *gin.Context) {
	if !RequireStaff(c) {
		return
	}
	id, ok := pathID(c)
	if !ok {
		return
	}
	var p model.Parcel
	if err := db.DB.First(&p, id).Error; err != nil {
		Fail(c, 404, "包裹不存在")
		return
	}
	var req pickupReq
	if !BindOptionalJSON(c, &req) {
		return
	}
	rec, success := doPickup(c, &p, req)
	if !success {
		return
	}
	OK(c, rec)
}

// PickupByCode 按取件码核销取件
func PickupByCode(c *gin.Context) {
	if !RequireStaff(c) {
		return
	}
	var req struct {
		PickupCode string `json:"pickupCode" binding:"required,len=6,numeric"`
		PickerName string `json:"pickerName" binding:"max=20"`
		PickupType int    `json:"pickupType" binding:"omitempty,oneof=1 2"`
	}
	if !BindJSON(c, &req) {
		return
	}
	var p model.Parcel
	if err := db.DB.Where("pickup_code = ? AND status IN (0,2)", req.PickupCode).
		Order("id DESC").First(&p).Error; err != nil {
		Fail(c, 404, "取件码无效或该包裹已取走")
		return
	}
	rec, success := doPickup(c, &p, pickupReq{PickerName: req.PickerName, PickupType: req.PickupType})
	if !success {
		return
	}
	OK(c, rec)
}

type pickupReq struct {
	PickerName string `json:"pickerName" binding:"max=20"`
	PickupType int    `json:"pickupType" binding:"omitempty,oneof=1 2"` // 1 本人 2 代取
}

// doPickup 核销取件：待取件 / 超期 -> 已取件，并写一条取件记录
func doPickup(c *gin.Context, p *model.Parcel, req pickupReq) (model.PickupRecord, bool) {
	if !model.CanPickup(p.Status) {
		if p.Status == model.ParcelPicked {
			Fail(c, 400, "该包裹已取件，不能重复核销")
		} else {
			Fail(c, 400, "该包裹已退回，不能取件")
		}
		return model.PickupRecord{}, false
	}

	now := time.Now().Truncate(time.Second)
	p.Status = model.ParcelPicked
	p.PickupTime = &now
	p.OperatorID = CurrentUser(c).ID
	db.DB.Save(p)

	if req.PickupType != 2 {
		req.PickupType = 1
	}
	if req.PickerName == "" {
		req.PickerName = p.ReceiverName
	}
	record := model.PickupRecord{
		ParcelID:      p.ID,
		TrackingNo:    p.TrackingNo,
		PickupCode:    p.PickupCode,
		ReceiverPhone: p.ReceiverPhone,
		PickupType:    req.PickupType,
		PickerName:    req.PickerName,
		OperatorID:    CurrentUser(c).ID,
		PickupTime:    now,
	}
	db.DB.Create(&record)
	return record, true
}

// ReturnParcel 包裹退回：待取件 / 超期 -> 已退回
func ReturnParcel(c *gin.Context) {
	if !RequireStaff(c) {
		return
	}
	id, ok := pathID(c)
	if !ok {
		return
	}
	var p model.Parcel
	if err := db.DB.First(&p, id).Error; err != nil {
		Fail(c, 404, "包裹不存在")
		return
	}
	if !model.CanReturn(p.Status) {
		if p.Status == model.ParcelPicked {
			Fail(c, 400, "该包裹已取件，不能退回")
		} else {
			Fail(c, 400, "该包裹已退回，不能重复退回")
		}
		return
	}

	var req struct {
		Remark string `json:"remark" binding:"max=200"`
	}
	if !BindOptionalJSON(c, &req) {
		return
	}
	p.Status = model.ParcelReturned
	p.OperatorID = CurrentUser(c).ID
	if req.Remark != "" {
		p.Remark = req.Remark
	}
	if err := db.DB.Save(&p).Error; err != nil {
		Fail(c, 500, "保存失败")
		return
	}
	decorateParcel(&p)
	OK(c, p)
}

// ListPickupRecords 取件记录分页查询（工作人员 / 管理员）
func ListPickupRecords(c *gin.Context) {
	if !RequireStaff(c) {
		return
	}
	page, size := pageParams(c)
	q := db.DB.Model(&model.PickupRecord{})
	if v := c.Query("phone"); v != "" {
		q = q.Where("receiver_phone = ?", v)
	}
	if v := c.Query("keyword"); v != "" {
		like := "%" + v + "%"
		q = q.Where("tracking_no LIKE ? OR picker_name LIKE ?", like, like)
	}
	if v := c.Query("startTime"); v != "" {
		if t, ok := parseDate(v); ok {
			q = q.Where("pickup_time >= ?", t)
		}
	}
	if v := c.Query("endTime"); v != "" {
		if t, ok := parseDate(v); ok {
			q = q.Where("pickup_time < ?", t.AddDate(0, 0, 1))
		}
	}
	var total int64
	q.Count(&total)
	var list []model.PickupRecord
	q.Order("id DESC").Offset((page - 1) * size).Limit(size).Find(&list)
	OK(c, pageData(total, list))
}
