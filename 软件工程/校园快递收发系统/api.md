# 校园快递收发系统 · 接口文档

本文件列出后端的全部 39 个接口。
本文件按 ASD-STE100 简化技术英语的写作规则编写。
规则：一句一个意思。使用主动语态。一步一个动作。术语统一。
术语定义见 [[README]] 第 2 节。

## 1. 基础约定

| 项目 | 规则 |
| --- | --- |
| 服务地址 | `http://localhost:8080` |
| 请求格式 | `application/json`。UTF-8 编码。 |
| 时间格式 | RFC3339。例如 `2026-10-25T19:54:22+08:00`。时区为北京时间。 |
| 登录凭证 | 登录接口下发 `session_id` Cookie。属性为 HttpOnly、SameSite=Lax。 |
| 会话存储 | 会话数据存 Redis。键名 `campus:sess:<session_id>`。值为用户编号。 |
| 会话有效期 | 2 小时。每次请求自动续期。 |
| 前端要求 | 浏览器自动携带 Cookie。跨域请求必须带 `credentials: 'include'`。 |
| HTTP 状态码 | 固定 `200`。业务结果看响应体的 `code`。 |

### 1.1 响应结构

所有接口返回同一结构。

```json
{
  "code": 200,
  "msg": "success",
  "data": {}
}
```

| `code` | 含义 | 处理方式 |
| --- | --- | --- |
| `200` | 成功 | 读取 `data`。 |
| `400` | 参数错误或业务校验失败 | 显示 `msg`。 |
| `401` | 未登录，或会话失效 | 跳转登录页。 |
| `403` | 角色无权限，或账号被禁用 | 显示 `msg`。 |
| `404` | 数据不存在 | 显示 `msg`。 |
| `500` | 服务端异常 | 提示稍后重试。 |

### 1.2 分页

请求参数：

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `page` | int | 否 | 1 | 页码。小于 1 时按 1 处理。 |
| `size` | int | 否 | 10 | 每页条数。大于 100 时按 10 处理。 |

分页接口的 `data`：

```json
{
  "total": 26,
  "list": []
}
```

### 1.3 角色

| 角色 | 名称 | 权限 |
| --- | --- | --- |
| `USER` | 学生 | 个人中心、我的包裹、公告、驿站列表。 |
| `STAFF` | 工作人员 | 上述权限。加包裹入库、查询、核销、退回、取件记录、统计。 |
| `ADMIN` | 管理员 | 上述权限。加用户管理、驿站管理、公告管理、删除包裹。 |

### 1.4 接口总览

| 序号 | 方法 | 路径 | 说明 | 角色 |
| --- | --- | --- | --- | --- |
| 1 | POST | `/api/auth/register` | 学生注册 | 公开 |
| 2 | POST | `/api/auth/login` | 登录 | 公开 |
| 3 | POST | `/api/auth/logout` | 退出登录 | 登录 |
| 4 | GET | `/api/auth/me` | 查看当前用户 | 登录 |
| 5 | PUT | `/api/auth/me` | 修改个人资料 | 登录 |
| 6 | PUT | `/api/auth/password` | 修改自己的密码 | 登录 |
| 7 | GET | `/api/users` | 用户分页查询 | 管理员 |
| 8 | POST | `/api/users` | 新增用户 | 管理员 |
| 9 | GET | `/api/users/{id}` | 用户详情 | 管理员 |
| 10 | PUT | `/api/users/{id}` | 修改用户 | 管理员 |
| 11 | PUT | `/api/users/{id}/status` | 启用或禁用用户 | 管理员 |
| 12 | PUT | `/api/users/{id}/password` | 重置密码 | 管理员 |
| 13 | DELETE | `/api/users/{id}` | 删除用户 | 管理员 |
| 14 | GET | `/api/stations` | 驿站列表 | 登录 |
| 15 | POST | `/api/stations` | 新增驿站 | 管理员 |
| 16 | GET | `/api/stations/{id}` | 驿站详情 | 登录 |
| 17 | PUT | `/api/stations/{id}` | 修改驿站 | 管理员 |
| 18 | DELETE | `/api/stations/{id}` | 删除驿站 | 管理员 |
| 19 | GET | `/api/parcels` | 包裹分页查询 | 工作人员 |
| 20 | POST | `/api/parcels` | 包裹入库 | 工作人员 |
| 21 | GET | `/api/parcels/{id}` | 包裹详情 | 登录 |
| 22 | PUT | `/api/parcels/{id}` | 修改包裹 | 工作人员 |
| 23 | DELETE | `/api/parcels/{id}` | 删除包裹 | 管理员 |
| 24 | POST | `/api/parcels/{id}/pickup` | 按编号核销取件 | 工作人员 |
| 25 | POST | `/api/parcels/{id}/return` | 退回包裹 | 工作人员 |
| 26 | GET | `/api/my/parcels` | 我的包裹 | 登录 |
| 27 | GET | `/api/pickup/{code}` | 按取件码查包裹 | 工作人员 |
| 28 | POST | `/api/pickup` | 按取件码核销取件 | 工作人员 |
| 29 | GET | `/api/pickup-records` | 取件记录查询 | 工作人员 |
| 30 | GET | `/api/notices` | 公告分页查询 | 登录 |
| 31 | POST | `/api/notices` | 发布公告 | 管理员 |
| 32 | GET | `/api/notices/{id}` | 公告详情 | 登录 |
| 33 | PUT | `/api/notices/{id}` | 修改公告 | 管理员 |
| 34 | DELETE | `/api/notices/{id}` | 删除公告 | 管理员 |
| 35 | GET | `/api/stats/overview` | 数据概览 | 工作人员 |
| 36 | GET | `/api/stats/company` | 快递公司分布 | 工作人员 |
| 37 | GET | `/api/stats/station` | 驿站包裹量 | 工作人员 |
| 38 | GET | `/api/stats/trend` | 近 N 天趋势 | 工作人员 |
| 39 | GET | `/api/ping` | 健康检查 | 公开 |

说明：表中「工作人员」包含管理员。「登录」表示任意已登录用户。

### 1.5 前端接入示例

浏览器自动携带 Cookie。前端只需要打开凭证选项。

```javascript
// 登录
await fetch('http://localhost:8080/api/auth/login', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  credentials: 'include',
  body: JSON.stringify({ phone: '13800000002', password: '123456' })
})

// 后续请求
await fetch('http://localhost:8080/api/my/parcels', {
  credentials: 'include'
})
```

前后端同域部署时，`credentials` 可以省略。

## 2. 数据结构

### 2.1 User 用户

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | int | 主键。 |
| `phone` | string | 手机号。登录账号。 |
| `name` | string | 姓名。 |
| `role` | string | `USER`、`STAFF` 或 `ADMIN`。 |
| `stationId` | int / null | 所属驿站。只有工作人员有值。 |
| `status` | int | `1` 正常。`0` 禁用。 |
| `createTime` | string | 注册时间。 |

系统不返回 `password` 字段。

### 2.2 Station 驿站

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | int | 主键。 |
| `name` | string | 驿站名称。 |
| `address` | string | 详细地址。 |
| `manager` | string | 负责人。 |
| `phone` | string | 联系电话。 |
| `openTime` | string | 营业开始时间。格式 `HH:mm`。 |
| `closeTime` | string | 营业结束时间。格式 `HH:mm`。 |
| `status` | int | `1` 营业。`0` 停用。 |
| `createTime` | string | 创建时间。 |

### 2.3 Parcel 包裹

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | int | 主键。 |
| `trackingNo` | string | 运单号。 |
| `company` | string | 快递公司。 |
| `receiverName` | string | 收件人姓名。 |
| `receiverPhone` | string | 收件人手机号。 |
| `stationId` | int | 存放驿站。 |
| `shelfCode` | string | 货架号。 |
| `pickupCode` | string | 6 位取件码。入库时自动生成。 |
| `status` | int | `0` 待取件。`1` 已取件。`2` 超期。`3` 已退回。 |
| `inboundTime` | string | 入库时间。 |
| `pickupTime` | string / null | 取件时间。 |
| `operatorId` | int | 最后操作人。 |
| `remark` | string | 备注。 |

### 2.4 PickupRecord 取件记录

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | int | 主键。 |
| `parcelId` | int | 包裹编号。 |
| `trackingNo` | string | 运单号。 |
| `pickupCode` | string | 取件码。 |
| `receiverPhone` | string | 收件人手机号。 |
| `pickupType` | int | `1` 本人取件。`2` 代取。 |
| `pickerName` | string | 取件人姓名。 |
| `operatorId` | int | 核销操作人。 |
| `pickupTime` | string | 取件时间。 |
| `remark` | string | 备注。 |

### 2.5 Notice 公告

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | int | 主键。 |
| `title` | string | 标题。 |
| `content` | string | 内容。 |
| `publisher` | string | 发布人。取当前登录用户的姓名。 |
| `createTime` | string | 发布时间。 |

## 3. 校验与状态规则

### 3.1 参数校验

框架按结构体 `binding` 标签自动校验。校验不通过返回 `400`。

| 字段 | 规则 |
| --- | --- |
| 手机号 | 必填。11 位。纯数字。 |
| 密码 | 必填。6 到 20 位。 |
| 姓名 | 最多 20 字。 |
| 角色 | `USER`、`STAFF`、`ADMIN` 三选一。 |
| 用户状态 | `0` 或 `1`。 |
| 运单号 | 必填。最多 50 字。 |
| 快递公司 | 最多 30 字。 |
| 货架号 | 最多 20 字。 |
| 备注 | 最多 200 字。 |
| 驿站名称 | 必填。最多 50 字。 |
| 营业时间 | `HH:mm`。 |
| 取件码 | 6 位数字。 |
| 取件方式 | `1` 或 `2`。 |
| 公告标题 | 必填。最多 100 字。 |
| 公告内容 | 最多 2000 字。 |

### 3.2 包裹状态流转

| 当前状态 | 允许的操作 | 结果 | 拒绝时的提示 |
| --- | --- | --- | --- |
| 无 | 入库 | 待取件 | 驿站不存在：`驿站不存在`。驿站停用：`该驿站已停用，不能入库`。 |
| 待取件 | 核销 | 已取件 | — |
| 超期 | 核销 | 已取件 | — |
| 待取件 | 退回 | 已退回 | — |
| 超期 | 退回 | 已退回 | — |
| 待取件 | 修改 | 状态不变 | — |
| 超期 | 修改 | 状态不变 | — |
| 已取件 | 核销 | 拒绝 | `该包裹已取件，不能重复核销`。 |
| 已取件 | 退回 | 拒绝 | `该包裹已取件，不能退回`。 |
| 已取件 | 修改 | 拒绝 | `已取件或已退回的包裹不能修改`。 |
| 已退回 | 核销 | 拒绝 | `该包裹已退回，不能取件`。 |
| 已退回 | 退回 | 拒绝 | `该包裹已退回，不能重复退回`。 |
| 已退回 | 修改 | 拒绝 | `已取件或已退回的包裹不能修改`。 |

### 3.3 用户状态

| 当前状态 | 操作 | 结果 |
| --- | --- | --- |
| 正常 | 禁用 | 该用户不能再登录。已登录请求返回 `403 账号已被禁用`。 |
| 禁用 | 启用 | 该用户可以登录。 |
| — | 禁用自己 | 拒绝，返回 `400 不能禁用自己`。 |
| — | 删除自己 | 拒绝，返回 `400 不能删除自己`。 |

## 4. 登录与个人中心

### 4.1 学生注册

`POST /api/auth/register`
无需登录。

| 参数 | 类型 | 必填 | 规则 | 说明 |
| --- | --- | --- | --- | --- |
| `phone` | string | 是 | 11 位数字 | 手机号。作为登录账号。 |
| `password` | string | 是 | 6 到 20 位 | 密码。系统用 bcrypt 存储。 |
| `name` | string | 否 | 最多 20 字 | 姓名。 |

```json
// 请求
{ "phone": "13800000009", "password": "123456", "name": "王五" }

// 响应
{
  "code": 200,
  "msg": "success",
  "data": {
    "user": {
      "id": 5, "phone": "13800000009", "name": "王五", "role": "USER",
      "stationId": null, "status": 1, "createTime": "2026-10-25T19:54:22+08:00"
    }
  }
}
```

错误：

| 情况 | 返回 |
| --- | --- |
| 手机号不是 11 位 | `400 手机号长度必须为 11 位` |
| 手机号含字母 | `400 手机号只能是数字` |
| 密码少于 6 位 | `400 密码不能小于 6` |
| 手机号已存在 | `400 该手机号已注册` |

### 4.2 登录

`POST /api/auth/login`
无需登录。

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `phone` | string | 是 | 手机号。 |
| `password` | string | 是 | 密码。 |

响应同注册接口。

错误：

| 情况 | 返回 |
| --- | --- |
| 手机号不存在 | `400 账号不存在` |
| 密码错误 | `400 密码错误` |
| 账号被禁用 | `403 账号已被禁用` |

### 4.3 退出登录

`POST /api/auth/logout`
需要登录。

服务端删除 Redis 中的会话，并清除 Cookie。
旧 Cookie 立即失效。

### 4.4 查看当前用户

`GET /api/auth/me`
需要登录。

```json
{
  "code": 200,
  "msg": "success",
  "data": {
    "id": 3, "phone": "13800000002", "name": "张三", "role": "USER",
    "stationId": null, "status": 1, "createTime": "2026-10-25T19:54:05+08:00"
  }
}
```

### 4.5 修改个人资料

`PUT /api/auth/me`
需要登录。

| 参数 | 类型 | 必填 | 规则 | 说明 |
| --- | --- | --- | --- | --- |
| `name` | string | 否 | 最多 20 字 | 姓名。 |
| `phone` | string | 否 | 11 位数字 | 手机号。系统检查是否被占用。 |

返回修改后的用户。

错误：`400 该手机号已被占用`。

### 4.6 修改自己的密码

`PUT /api/auth/password`
需要登录。

| 参数 | 类型 | 必填 | 规则 | 说明 |
| --- | --- | --- | --- | --- |
| `oldPassword` | string | 是 | — | 原密码。 |
| `newPassword` | string | 是 | 6 到 20 位 | 新密码。 |

错误：`400 原密码不正确`、`400 密码不能小于 6`。

修改成功后服务端删除当前会话，并清除 Cookie。用户必须重新登录。

## 5. 用户管理

全部接口需要管理员角色。非管理员返回 `403 仅管理员可操作`。

### 5.1 用户分页查询

`GET /api/users`

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `page` | int | 否 | 页码。 |
| `size` | int | 否 | 每页条数。 |
| `keyword` | string | 否 | 手机号或姓名。模糊匹配。 |
| `role` | string | 否 | `USER`、`STAFF`、`ADMIN`。 |
| `status` | int | 否 | `1` 正常。`0` 禁用。 |

### 5.2 新增用户

`POST /api/users`
用于创建工作人员和管理员。

| 参数 | 类型 | 必填 | 规则 | 说明 |
| --- | --- | --- | --- | --- |
| `phone` | string | 是 | 11 位数字 | 手机号。 |
| `password` | string | 是 | 6 到 20 位 | 初始密码。 |
| `name` | string | 否 | 最多 20 字 | 姓名。 |
| `role` | string | 否 | 三选一 | 默认 `USER`。 |
| `stationId` | int | 条件必填 | 驿站必须存在 | 角色为 `STAFF` 时必填。 |

错误：

| 情况 | 返回 |
| --- | --- |
| 手机号已存在 | `400 该手机号已存在` |
| 角色非法 | `400 角色只能是 USER / STAFF / ADMIN` |
| 工作人员没传驿站 | `400 工作人员必须指定所属驿站` |
| 驿站不存在 | `400 驿站不存在` |

### 5.3 用户详情

`GET /api/users/{id}`

错误：`404 用户不存在`。

### 5.4 修改用户

`PUT /api/users/{id}`

| 参数 | 类型 | 必填 | 规则 | 说明 |
| --- | --- | --- | --- | --- |
| `name` | string | 否 | 最多 20 字 | 姓名。 |
| `role` | string | 否 | 三选一 | 角色。 |
| `stationId` | int | 否 | 驿站必须存在 | 所属驿站。不传则清空。 |

规则：角色改为 `STAFF` 时必须传 `stationId`。

### 5.5 启用或禁用用户

`PUT /api/users/{id}/status?status=0`

| 参数 | 类型 | 必填 | 规则 | 说明 |
| --- | --- | --- | --- | --- |
| `status` | int | 是 | `0` 或 `1` | `0` 禁用。`1` 正常。 |

错误：

| 情况 | 返回 |
| --- | --- |
| 状态不是 0 或 1 | `400 状态只能是 0（禁用）或 1（正常）` |
| 不传状态 | 同上 |
| 禁用自己 | `400 不能禁用自己` |

### 5.6 重置密码

`PUT /api/users/{id}/password`

| 参数 | 类型 | 必填 | 规则 | 说明 |
| --- | --- | --- | --- | --- |
| `password` | string | 否 | 6 到 20 位 | 新密码。不传则重置为 `123456`。 |

### 5.7 删除用户

`DELETE /api/users/{id}`

错误：`400 不能删除自己`。

## 6. 驿站管理

### 6.1 驿站列表

`GET /api/stations?status=1`
需要登录。不分页。

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `status` | int | 否 | `1` 营业。`0` 停用。 |

### 6.2 新增驿站

`POST /api/stations`
需要管理员角色。

| 参数 | 类型 | 必填 | 规则 | 说明 |
| --- | --- | --- | --- | --- |
| `name` | string | 是 | 最多 50 字 | 驿站名称。 |
| `address` | string | 否 | 最多 100 字 | 地址。 |
| `manager` | string | 否 | 最多 20 字 | 负责人。 |
| `phone` | string | 否 | 11 位数字 | 联系电话。 |
| `openTime` | string | 否 | `HH:mm` | 营业开始时间。 |
| `closeTime` | string | 否 | `HH:mm` | 营业结束时间。 |
| `status` | int | 否 | `0` 或 `1` | 默认 `1` 营业。 |

错误：

| 情况 | 返回 |
| --- | --- |
| 名称为空 | `400 驿站名称不能为空` |
| 时间格式错误 | `400 营业时间格式必须是 HH:mm` |

### 6.3 驿站详情

`GET /api/stations/{id}`
需要登录。

错误：`404 驿站不存在`。

### 6.4 修改驿站

`PUT /api/stations/{id}`
需要管理员角色。参数同新增。接口整体覆盖字段。

### 6.5 删除驿站

`DELETE /api/stations/{id}`
需要管理员角色。

错误：`400 该驿站下还有包裹，不能删除`。

## 7. 包裹业务

### 7.1 包裹入库

`POST /api/parcels`
需要工作人员或管理员角色。

| 参数 | 类型 | 必填 | 规则 | 说明 |
| --- | --- | --- | --- | --- |
| `trackingNo` | string | 是 | 最多 50 字 | 运单号。 |
| `receiverPhone` | string | 是 | 11 位数字 | 收件人手机号。 |
| `stationId` | int | 是 | 驿站必须存在且营业 | 存放驿站。 |
| `receiverName` | string | 否 | 最多 20 字 | 收件人姓名。 |
| `company` | string | 否 | 最多 30 字 | 快递公司。 |
| `shelfCode` | string | 否 | 最多 20 字 | 货架号。 |
| `remark` | string | 否 | 最多 200 字 | 备注。 |

系统做三件事：

1. 生成 6 位取件码。
2. 把状态设为 `0` 待取件。
3. 输出一条取件通知日志。系统不接短信网关。

```json
// 响应 data
{
  "id": 5, "trackingNo": "SF9988776655", "company": "顺丰速运",
  "receiverName": "张三", "receiverPhone": "13800000002", "stationId": 1,
  "shelfCode": "C-05", "pickupCode": "709615", "status": 0,
  "inboundTime": "2026-10-25T19:54:22+08:00", "pickupTime": null,
  "operatorId": 2, "remark": "测试入库"
}
```

错误：

| 情况 | 返回 |
| --- | --- |
| 缺运单号 | `400 运单号不能为空` |
| 缺收件人手机号 | `400 收件人手机号不能为空` |
| 缺驿站 | `400 驿站不能为空` |
| 驿站不存在 | `400 驿站不存在` |
| 驿站已停用 | `400 该驿站已停用，不能入库` |
| 学生调用 | `403 仅驿站工作人员可操作` |

### 7.2 包裹分页查询

`GET /api/parcels`
需要工作人员或管理员角色。

| 参数 | 类型 | 必填 | 规则 | 说明 |
| --- | --- | --- | --- | --- |
| `page` | int | 否 | — | 页码。 |
| `size` | int | 否 | — | 每页条数。 |
| `status` | int | 否 | `0` 到 `3` | 包裹状态。 |
| `stationId` | int | 否 | — | 按驿站过滤。 |
| `company` | string | 否 | — | 按快递公司过滤。 |
| `phone` | string | 否 | — | 收件人手机号。精确匹配。 |
| `keyword` | string | 否 | — | 运单号、收件人、手机号、取件码。模糊匹配。 |
| `startTime` | string | 否 | `yyyy-MM-dd` | 入库开始日期。 |
| `endTime` | string | 否 | `yyyy-MM-dd` | 入库结束日期。含当天。 |

错误：`400 状态只能是 0（待取件）/ 1（已取件）/ 2（超期）/ 3（已退回）`。

### 7.3 包裹详情

`GET /api/parcels/{id}`
需要登录。

错误：`404 包裹不存在`。

### 7.4 修改包裹

`PUT /api/parcels/{id}`
需要工作人员或管理员角色。
只有待取件和超期的包裹可以修改。

| 参数 | 类型 | 必填 | 规则 | 说明 |
| --- | --- | --- | --- | --- |
| `company` | string | 否 | 最多 30 字 | 快递公司。 |
| `receiverName` | string | 否 | 最多 20 字 | 收件人姓名。 |
| `receiverPhone` | string | 否 | 11 位数字 | 收件人手机号。 |
| `stationId` | int | 否 | 驿站必须存在 | 存放驿站。 |
| `shelfCode` | string | 否 | 最多 20 字 | 货架号。换货架时使用。 |
| `remark` | string | 否 | 最多 200 字 | 备注。传空字符串则清空。 |

错误：

| 情况 | 返回 |
| --- | --- |
| 包裹已取件或已退回 | `400 已取件或已退回的包裹不能修改` |
| 驿站不存在 | `400 驿站不存在` |

### 7.5 删除包裹

`DELETE /api/parcels/{id}`
需要管理员角色。

### 7.6 按编号核销取件

`POST /api/parcels/{id}/pickup`
需要工作人员或管理员角色。

| 参数 | 类型 | 必填 | 规则 | 说明 |
| --- | --- | --- | --- | --- |
| `pickerName` | string | 否 | 最多 20 字 | 取件人。不传则用收件人姓名。 |
| `pickupType` | int | 否 | `1` 或 `2` | `1` 本人。`2` 代取。默认 `1`。 |

请求体可以为空。

```json
// 响应 data：取件记录
{
  "id": 2, "parcelId": 5, "trackingNo": "SF9988776655", "pickupCode": "709615",
  "receiverPhone": "13800000002", "pickupType": 1, "pickerName": "张三",
  "operatorId": 2, "pickupTime": "2026-10-25T19:54:22+08:00", "remark": ""
}
```

错误：

| 情况 | 返回 |
| --- | --- |
| 包裹不存在 | `404 包裹不存在` |
| 已取件 | `400 该包裹已取件，不能重复核销` |
| 已退回 | `400 该包裹已退回，不能取件` |
| 取件方式非法 | `400 取件方式只能是 1 / 2` |

### 7.7 退回包裹

`POST /api/parcels/{id}/return`
需要工作人员或管理员角色。
只有待取件和超期的包裹可以退回。

| 参数 | 类型 | 必填 | 规则 | 说明 |
| --- | --- | --- | --- | --- |
| `remark` | string | 否 | 最多 200 字 | 退回原因。 |

返回修改后的包裹。

错误：

| 情况 | 返回 |
| --- | --- |
| 已取件 | `400 该包裹已取件，不能退回` |
| 已退回 | `400 该包裹已退回，不能重复退回` |

### 7.8 我的包裹

`GET /api/my/parcels`
需要登录。
系统按当前用户的手机号查询。

| 参数 | 类型 | 必填 | 规则 | 说明 |
| --- | --- | --- | --- | --- |
| `page` | int | 否 | — | 页码。 |
| `size` | int | 否 | — | 每页条数。 |
| `status` | int | 否 | `0` 到 `3` | 包裹状态。 |

### 7.9 按取件码查包裹

`GET /api/pickup/{code}`
需要工作人员或管理员角色。
接口只查待取件和超期的包裹。

错误：

| 情况 | 返回 |
| --- | --- |
| 取件码不是 6 位 | `400 取件码必须是 6 位数字` |
| 取件码不存在或包裹已取走 | `404 取件码无效或该包裹已取走` |

### 7.10 按取件码核销取件

`POST /api/pickup`
需要工作人员或管理员角色。

| 参数 | 类型 | 必填 | 规则 | 说明 |
| --- | --- | --- | --- | --- |
| `pickupCode` | string | 是 | 6 位数字 | 取件码。 |
| `pickerName` | string | 否 | 最多 20 字 | 取件人。 |
| `pickupType` | int | 否 | `1` 或 `2` | 取件方式。 |

响应为取件记录。字段见 7.6。

### 7.11 取件记录查询

`GET /api/pickup-records`
需要工作人员或管理员角色。

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `page` | int | 否 | 页码。 |
| `size` | int | 否 | 每页条数。 |
| `phone` | string | 否 | 收件人手机号。 |
| `keyword` | string | 否 | 运单号或取件人。模糊匹配。 |
| `startTime` | string | 否 | 取件开始日期。 |
| `endTime` | string | 否 | 取件结束日期。含当天。 |

## 8. 公告

### 8.1 公告分页查询

`GET /api/notices`
需要登录。按发布时间倒序。

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `page` | int | 否 | 页码。 |
| `size` | int | 否 | 每页条数。 |
| `keyword` | string | 否 | 标题。模糊匹配。 |

### 8.2 公告详情

`GET /api/notices/{id}`
需要登录。

错误：`404 公告不存在`。

### 8.3 发布公告

`POST /api/notices`
需要管理员角色。

| 参数 | 类型 | 必填 | 规则 | 说明 |
| --- | --- | --- | --- | --- |
| `title` | string | 是 | 最多 100 字 | 标题。 |
| `content` | string | 否 | 最多 2000 字 | 内容。 |

发布人取当前登录用户的姓名。

错误：`400 标题不能为空`。

### 8.4 修改公告

`PUT /api/notices/{id}`
需要管理员角色。

| 参数 | 类型 | 必填 | 规则 | 说明 |
| --- | --- | --- | --- | --- |
| `title` | string | 否 | 最多 100 字 | 标题。 |
| `content` | string | 否 | 最多 2000 字 | 内容。 |

### 8.5 删除公告

`DELETE /api/notices/{id}`
需要管理员角色。

## 9. 数据统计

全部接口需要工作人员或管理员角色。

### 9.1 数据概览

`GET /api/stats/overview`

```json
{
  "code": 200,
  "msg": "success",
  "data": {
    "parcelTotal": 6, "pendingCount": 2, "pickedCount": 2, "expiredCount": 1,
    "returnedCount": 1, "todayInbound": 5, "todayPicked": 2,
    "userCount": 5, "stationCount": 3
  }
}
```

| 字段 | 说明 |
| --- | --- |
| `parcelTotal` | 包裹总数。 |
| `pendingCount` | 待取件数量。 |
| `pickedCount` | 已取件数量。 |
| `expiredCount` | 超期数量。 |
| `returnedCount` | 已退回数量。 |
| `todayInbound` | 今日入库数量。 |
| `todayPicked` | 今日取件数量。 |
| `userCount` | 用户总数。 |
| `stationCount` | 驿站总数。 |

### 9.2 快递公司分布

`GET /api/stats/company`

```json
{
  "code": 200,
  "msg": "success",
  "data": [
    { "name": "顺丰速运", "num": 2 },
    { "name": "中通快递", "num": 2 },
    { "name": "圆通速递", "num": 1 },
    { "name": "京东物流", "num": 1 }
  ]
}
```

### 9.3 驿站包裹量

`GET /api/stats/station`

返回结构同 9.2。`name` 是驿站名称。

### 9.4 近 N 天趋势

`GET /api/stats/trend?days=7`

| 参数 | 类型 | 必填 | 规则 | 说明 |
| --- | --- | --- | --- | --- |
| `days` | int | 否 | 1 到 30 | 默认 7。超出范围时按 7 处理。 |

```json
{
  "code": 200,
  "msg": "success",
  "data": [
    { "date": "2026-10-19", "inbound": 0, "picked": 0 },
    { "date": "2026-10-20", "inbound": 1, "picked": 0 }
  ]
}
```

系统按天分组。没有数据的日期返回 0。

## 10. 其他

### 10.1 健康检查

`GET /api/ping`

```json
{ "code": 200, "msg": "success", "data": "pong" }
```

### 10.2 超期检查

定时任务每 10 分钟运行一次。
任务把入库超过 72 小时且状态为待取件的包裹改为超期。
服务启动时也运行一次。

### 10.3 跨域

系统开启 CORS。允许任意来源。
允许请求头 `Content-Type`。允许携带 Cookie（`AllowCredentials`）。
允许方法 `GET`、`POST`、`PUT`、`DELETE`、`OPTIONS`。

## 11. 常见错误汇总

| 提示 | 原因 | 处理 |
| --- | --- | --- |
| `未登录或登录已失效` | 没带 Cookie，或会话已过期、已被删除 | 重新登录。 |
| `用户不存在` | 会话对应的用户已删除 | 重新登录。 |
| `账号已被禁用` | 管理员禁用了账号 | 联系管理员。 |
| `仅管理员可操作` | 角色不是 `ADMIN` | 用管理员账号。 |
| `仅驿站工作人员可操作` | 角色是 `USER` | 用工作人员账号。 |
| `id 不合法` | 路径参数不是正整数 | 检查路径。 |
| `请求参数格式错误` | 请求体不是合法 JSON | 检查请求体。 |
