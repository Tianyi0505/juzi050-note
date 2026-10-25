-- =============================================================
-- 校园快递收发系统 数据库脚本（MySQL 8.0）
-- 用法：mysql -u root -p < campus_express.sql
-- 默认密码均为 123456（bcrypt 存储）
-- =============================================================

DROP DATABASE IF EXISTS campus_express;
CREATE DATABASE campus_express DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
USE campus_express;

-- 统一使用北京时间，避免容器默认 UTC 造成入库时间偏差
SET time_zone = '+08:00';

-- -------------------------------------------------------------
-- 1. 用户表（学生 / 驿站工作人员 / 管理员）
-- -------------------------------------------------------------
CREATE TABLE sys_user (
  id          BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
  phone       VARCHAR(20)  NOT NULL COMMENT '手机号，登录账号',
  password    VARCHAR(64)  NOT NULL COMMENT '密码，bcrypt 加密',
  name        VARCHAR(50)  DEFAULT NULL COMMENT '姓名',
  role        VARCHAR(20)  NOT NULL DEFAULT 'USER' COMMENT '角色：USER 学生 / STAFF 驿站工作人员 / ADMIN 管理员',
  station_id  BIGINT       DEFAULT NULL COMMENT '所属驿站，工作人员才有值',
  status      INT          NOT NULL DEFAULT 1 COMMENT '状态：1 正常 0 禁用',
  create_time DATETIME     DEFAULT CURRENT_TIMESTAMP COMMENT '注册时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_user_phone (phone)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户表';

-- -------------------------------------------------------------
-- 2. 驿站表（校内快递代收点）
-- -------------------------------------------------------------
CREATE TABLE station (
  id          BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
  name        VARCHAR(50)  NOT NULL COMMENT '驿站名称',
  address     VARCHAR(100) DEFAULT NULL COMMENT '详细地址',
  manager     VARCHAR(50)  DEFAULT NULL COMMENT '负责人',
  phone       VARCHAR(20)  DEFAULT NULL COMMENT '联系电话',
  open_time   VARCHAR(10)  DEFAULT NULL COMMENT '营业开始时间',
  close_time  VARCHAR(10)  DEFAULT NULL COMMENT '营业结束时间',
  status      INT          NOT NULL DEFAULT 1 COMMENT '状态：1 营业 0 停用',
  create_time DATETIME     DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='驿站表';

-- -------------------------------------------------------------
-- 3. 包裹表（核心业务表）
-- -------------------------------------------------------------
CREATE TABLE parcel (
  id             BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
  tracking_no    VARCHAR(50)  NOT NULL COMMENT '快递运单号',
  company_code   VARCHAR(10)  DEFAULT NULL COMMENT '快递公司 code：SF 顺丰/JD 京东/ZTO 中通/YTO 圆通/STO 申通/YD 韵达/JTSD 极兔/EMS 邮政',
  receiver_name  VARCHAR(50)  DEFAULT NULL COMMENT '收件人姓名',
  receiver_phone VARCHAR(20)  NOT NULL COMMENT '收件人手机号',
  station_id     BIGINT       DEFAULT NULL COMMENT '存放驿站',
  shelf_code     VARCHAR(20)  DEFAULT NULL COMMENT '货架号',
  pickup_code    VARCHAR(10)  DEFAULT NULL COMMENT '取件码',
  status         INT          NOT NULL DEFAULT 0 COMMENT '状态：0 待取件 1 已取件 2 超期 3 已退回',
  inbound_time   DATETIME     DEFAULT CURRENT_TIMESTAMP COMMENT '入库时间',
  pickup_time    DATETIME     DEFAULT NULL COMMENT '取件时间',
  operator_id    BIGINT       DEFAULT NULL COMMENT '最后操作人',
  remark         VARCHAR(200) DEFAULT NULL COMMENT '备注',
  PRIMARY KEY (id),
  KEY idx_parcel_phone (receiver_phone),
  KEY idx_parcel_code (pickup_code),
  KEY idx_parcel_status (status),
  KEY idx_parcel_company (company_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='包裹表';

-- -------------------------------------------------------------
-- 4. 取件记录表
-- -------------------------------------------------------------
CREATE TABLE pickup_record (
  id             BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
  parcel_id      BIGINT       NOT NULL COMMENT '包裹 id',
  tracking_no    VARCHAR(50)  DEFAULT NULL COMMENT '运单号（冗余，方便查询）',
  pickup_code    VARCHAR(10)  DEFAULT NULL COMMENT '取件码',
  receiver_phone VARCHAR(20)  DEFAULT NULL COMMENT '收件人手机号',
  pickup_type    INT          NOT NULL DEFAULT 1 COMMENT '取件方式：1 本人取件 2 代取',
  picker_name    VARCHAR(50)  DEFAULT NULL COMMENT '取件人姓名',
  operator_id    BIGINT       DEFAULT NULL COMMENT '核销操作人',
  pickup_time    DATETIME     DEFAULT CURRENT_TIMESTAMP COMMENT '取件时间',
  remark         VARCHAR(200) DEFAULT NULL COMMENT '备注',
  PRIMARY KEY (id),
  KEY idx_record_parcel (parcel_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='取件记录表';

-- -------------------------------------------------------------
-- 5. 公告表
-- -------------------------------------------------------------
CREATE TABLE notice (
  id          BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
  title       VARCHAR(100) NOT NULL COMMENT '标题',
  content     TEXT COMMENT '内容',
  publisher   VARCHAR(50)  DEFAULT NULL COMMENT '发布人',
  create_time DATETIME     DEFAULT CURRENT_TIMESTAMP COMMENT '发布时间',
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='公告表';

-- =============================================================
-- 初始化数据
-- =============================================================

INSERT INTO station (id, name, address, manager, phone, open_time, close_time, status) VALUES
(1, '东区菜鸟驿站', '东区宿舍 3 号楼一层', '王强', '13900000001', '08:00', '20:00', 1),
(2, '西区快递服务中心', '西区食堂旁 100 米', '李娜', '13900000002', '09:00', '19:30', 1);

INSERT INTO sys_user (id, phone, password, name, role, station_id, status) VALUES
(1, '13800000000', '$2a$10$fCkfrqyRSMRa6Vec.Zdfw.OkoZVsODz9m8k5a8G5YFSiR6V93hW9O', '系统管理员', 'ADMIN', NULL, 1),
(2, '13800000001', '$2a$10$fCkfrqyRSMRa6Vec.Zdfw.OkoZVsODz9m8k5a8G5YFSiR6V93hW9O', '王强', 'STAFF', 1, 1),
(3, '13800000002', '$2a$10$fCkfrqyRSMRa6Vec.Zdfw.OkoZVsODz9m8k5a8G5YFSiR6V93hW9O', '张三', 'USER', NULL, 1),
(4, '13800000003', '$2a$10$fCkfrqyRSMRa6Vec.Zdfw.OkoZVsODz9m8k5a8G5YFSiR6V93hW9O', '李四', 'USER', NULL, 1);

INSERT INTO parcel (id, tracking_no, company_code, receiver_name, receiver_phone, station_id, shelf_code, pickup_code, status, inbound_time, pickup_time, operator_id, remark) VALUES
(1, 'SF1234567890', 'SF', '张三', '13800000002', 1, 'A-01', '318026', 0, NOW(), NULL, 2, '文件袋'),
(2, 'YT9876543210', 'YTO', '李四', '13800000003', 1, 'A-02', '540917', 0, NOW(), NULL, 2, NULL),
(3, 'JD5555666677', 'JD', '张三', '13800000002', 2, 'B-03', '702614', 1, NOW(), NOW(), 2, '已本人取件'),
(4, 'ZT1111222233', 'ZTO', '李四', '13800000003', 2, 'B-04', '265083', 2, DATE_SUB(NOW(), INTERVAL 5 DAY), NULL, 2, '超期未取');

INSERT INTO pickup_record (parcel_id, tracking_no, pickup_code, receiver_phone, pickup_type, picker_name, operator_id, pickup_time, remark) VALUES
(3, 'JD5555666677', '702614', '13800000002', 1, '张三', 2, NOW(), '本人取件');

INSERT INTO notice (title, content, publisher) VALUES
('东区菜鸟驿站营业时间调整', '自本周起东区菜鸟驿站营业时间调整为 08:00 - 20:00，请同学们合理安排取件时间。', '系统管理员'),
('超期包裹处理说明', '包裹入库后 72 小时未取将标记为超期，超过 7 天未取的包裹统一退回寄件人。', '系统管理员');
