-- ---------------------------------------------------------------
-- 增量迁移：parcel.company 原文 -> parcel.company_code
--
-- 背景：快递公司改为「接口传 code、库里只存 code」，
--       中文名由后端按 model.companyNames 实时映射。
-- 适用：已经导入过旧版 campus_express.sql 的库；全新导入无需执行。
-- 执行：mysql -u root -p campus_express < db/migrate_company_code.sql
-- ---------------------------------------------------------------

-- 1. 先放宽长度，避免中文名被 VARCHAR(10) 截断
ALTER TABLE parcel MODIFY COLUMN company VARCHAR(30) DEFAULT NULL COMMENT '快递公司（待转换）';

-- 2. 原文 -> code；不在字典里的值保持原样，便于人工核查
UPDATE parcel SET company = CASE company
  WHEN '顺丰速运' THEN 'SF'
  WHEN '京东物流' THEN 'JD'
  WHEN '中通快递' THEN 'ZTO'
  WHEN '圆通速递' THEN 'YTO'
  WHEN '申通快递' THEN 'STO'
  WHEN '韵达快递' THEN 'YD'
  WHEN '极兔速递' THEN 'JTSD'
  WHEN '邮政EMS'  THEN 'EMS'
  ELSE company
END;

-- 3. 改名并加索引
ALTER TABLE parcel CHANGE COLUMN company company_code VARCHAR(10) DEFAULT NULL
  COMMENT '快递公司 code：SF 顺丰/JD 京东/ZTO 中通/YTO 圆通/STO 申通/YD 韵达/JTSD 极兔/EMS 邮政';
ALTER TABLE parcel ADD KEY idx_parcel_company (company_code);

-- 4. 核查：下面这条应返回 0 行，若仍有结果说明存在字典外的旧值
SELECT id, tracking_no, company_code FROM parcel
WHERE company_code IS NOT NULL AND company_code <> ''
  AND company_code NOT IN ('SF', 'JD', 'ZTO', 'YTO', 'STO', 'YD', 'JTSD', 'EMS');
