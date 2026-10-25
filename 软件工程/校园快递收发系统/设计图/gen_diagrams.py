# -*- coding: utf-8 -*-
"""生成课程设计所需的四张图（程序流程图算两个模块，共 5 张 PNG）。

用法（任意目录执行都可以）：
    python 设计图/gen_diagrams.py
输出写到 设计图/ 目录。
"""
import math
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# 项目根目录：校园快递收发系统
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "设计图"
S = 2

_fc = {}


def find_font(bold=False):
    """按顺序找一款中文字体，找不到就报错。"""
    names = ["msyhbd.ttc", "msyhbd.ttf"] if bold else ["msyh.ttc", "msyh.ttf"]
    names += ["simhei.ttf", "simsun.ttc"]
    dirs = [
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
        Path("/usr/share/fonts/truetype/wqy"),
        Path("/usr/share/fonts/opentype/noto"),
        Path("/System/Library/Fonts"),
    ]
    for d in dirs:
        for name in names:
            if (d / name).exists():
                return str(d / name)
    raise SystemExit("找不到中文字体，请在 find_font() 里补充字体路径")


REG = find_font()
BOLD = find_font(True)


def F(size, bold=False):
    key = (size, bold)
    if key not in _fc:
        _fc[key] = ImageFont.truetype(BOLD if bold else REG, int(size * S))
    return _fc[key]


class Canvas:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.img = Image.new("RGB", (int(w * S), int(h * S)), "#FFFFFF")
        self.d = ImageDraw.Draw(self.img)

    # ---------- 文本 ----------
    def wrap(self, text, size, max_w, bold):
        f = F(size, bold)
        out = []
        for para in text.split("\n"):
            cur = ""
            for ch in para:
                if self.d.textlength(cur + ch, font=f) <= max_w * S or not cur:
                    cur += ch
                else:
                    out.append(cur)
                    cur = ch
            out.append(cur)
        return out

    def text_block(self, cx, cy, text, size=19, bold=False, color="#1F2937",
                   max_w=380, gap=1.35):
        lines = self.wrap(text, size, max_w, bold)
        f = F(size, bold)
        lh = size * gap * S
        total = lh * len(lines)
        y = cy * S - total / 2 + lh / 2
        for line in lines:
            self.d.text((cx * S, y), line, font=f, fill=color, anchor="mm")
            y += lh

    # ---------- 图形 ----------
    def box(self, cx, cy, w, h, text, size=19, fill="#FFFFFF", outline="#2563EB",
            color="#1F2937", radius=10, bold=False, role=None, role_color=None,
            border=2):
        x0, y0, x1, y1 = (cx - w / 2) * S, (cy - h / 2) * S, (cx + w / 2) * S, (cy + h / 2) * S
        self.d.rounded_rectangle([x0, y0, x1, y1], radius=radius * S, fill=fill,
                                 outline=outline, width=int(border * S))
        if role:
            self.d.text((x0 + 11 * S, y0 + 8 * S), role, font=F(12, True), fill=role_color, anchor="lt")
            self.text_block(cx, cy + 9, text, size, bold, color, w - 30)
        else:
            self.text_block(cx, cy, text, size, bold, color, w - 30)

    def pill(self, cx, cy, w, h, text, size=19, fill="#ECFDF5", outline="#059669",
             color="#065F46", bold=True):
        x0, y0, x1, y1 = (cx - w / 2) * S, (cy - h / 2) * S, (cx + w / 2) * S, (cy + h / 2) * S
        self.d.rounded_rectangle([x0, y0, x1, y1], radius=(h / 2) * S, fill=fill,
                                 outline=outline, width=int(2 * S))
        self.text_block(cx, cy, text, size, bold, color, w - 30)

    def diamond(self, cx, cy, w, h, text, size=17, fill="#FFF7ED", outline="#EA580C",
                color="#7C2D12"):
        pts = [(cx * S, (cy - h / 2) * S), ((cx + w / 2) * S, cy * S),
               (cx * S, (cy + h / 2) * S), ((cx - w / 2) * S, cy * S)]
        self.d.polygon(pts, fill=fill, outline=outline, width=int(2 * S))
        self.text_block(cx, cy, text, size, False, color, w - 55)

    # ---------- 连线 ----------
    def _seg(self, p1, p2, color, width, dash):
        if not dash:
            self.d.line([(p1[0] * S, p1[1] * S), (p2[0] * S, p2[1] * S)],
                        fill=color, width=int(width * S))
            return
        x1, y1 = p1[0] * S, p1[1] * S
        x2, y2 = p2[0] * S, p2[1] * S
        dist = math.hypot(x2 - x1, y2 - y1)
        if dist == 0:
            return
        step = 9 * S
        n = int(dist // step)
        dx, dy = (x2 - x1) / dist, (y2 - y1) / dist
        for i in range(0, n, 2):
            sx, sy = x1 + dx * step * i, y1 + dy * step * i
            ex, ey = x1 + dx * step * min(i + 1, n), y1 + dy * step * min(i + 1, n)
            self.d.line([(sx, sy), (ex, ey)], fill=color, width=int(width * S))

    def _head(self, p_from, p_to, color, width):
        x1, y1 = p_from[0] * S, p_from[1] * S
        x2, y2 = p_to[0] * S, p_to[1] * S
        ang = math.atan2(y2 - y1, x2 - x1)
        size = 11 * S
        p1 = (x2, y2)
        p2 = (x2 - size * math.cos(ang - 0.42), y2 - size * math.sin(ang - 0.42))
        p3 = (x2 - size * math.cos(ang + 0.42), y2 - size * math.sin(ang + 0.42))
        self.d.polygon([p1, p2, p3], fill=color)

    def arrow(self, pts, color="#475569", width=1.8, dash=False):
        for i in range(len(pts) - 1):
            self._seg(pts[i], pts[i + 1], color, width, dash)
        self._head(pts[-2], pts[-1], color, width)

    def label(self, x, y, text, size=15, color="#475569", bold=False, anchor="mm",
              bg="#FFFFFF"):
        f = F(size, bold)
        w = self.d.textlength(text, font=f) / S
        h = size * 1.5
        self.d.rectangle([(x - w / 2 - 4) * S, (y - h / 2) * S, (x + w / 2 + 4) * S, (y + h / 2) * S],
                         fill=bg)
        self.d.text((x * S, y * S), text, font=f, fill=color, anchor=anchor)

    def title(self, text, sub=None):
        self.text_block(self.w / 2, 46, text, 27, True, "#111827", self.w - 120)
        if sub:
            self.text_block(self.w / 2, 82, sub, 14, False, "#6B7280", self.w - 120)

    def save(self, name):
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / name
        self.img.save(path, "PNG")
        print("saved", path.relative_to(ROOT), self.img.size)


# 角色配色
ROLE = {
    "学生": ("#DBEAFE", "#1D4ED8", "#EFF6FF"),
    "工作人员": ("#DCFCE7", "#15803D", "#F0FDF4"),
    "系统": ("#F3E8FF", "#7E22CE", "#FAF5FF"),
}
ERR_BOX = ("#FEF2F2", "#DC2626", "#991B1B")


def role_box(c, cx, cy, w, h, text, who, size=19):
    fill, border, light = ROLE[who]
    c.box(cx, cy, w, h, text, size=size, fill="#FFFFFF", outline=border,
          role=who, role_color=border, color="#1F2937")


def err_box(c, cx, cy, w, h, text, size=17):
    fill, border, color = ERR_BOX
    c.box(cx, cy, w, h, text, size=size, fill=fill, outline=border, color=color)


# ---------------------------------------------------------------- 图 1 业务流程图
def business_flow():
    W, H = 1560, 2170
    c = Canvas(W, H)
    c.title("图 1  校园快递收发业务流程图", "按角色标注：蓝色=学生，绿色=工作人员，紫色=系统")

    MX, MW, MH = 470, 470, 82
    EX, EW, EH = 1150, 380, 72

    y = 175
    c.pill(MX, y, 300, 58, "开始：快递到达校园")

    y += 118
    c.arrow([(MX, y - 88), (MX, y - MH / 2)])
    role_box(c, MX, y, MW, MH, "驿站收件，核对运单号", "工作人员")

    steps = [
        ("录入运单号、收件人手机号、货架号", "工作人员"),
        ("校验角色、参数与驿站状态", "系统"),
    ]
    for text, who in steps:
        y += MH + 54
        c.arrow([(MX, y - MH / 2 - 54), (MX, y - MH / 2)])
        role_box(c, MX, y, MW, MH, text, who)

    # 决策 1：校验通过
    y += 120
    c.arrow([(MX, y - 121), (MX, y - 62)])
    c.diamond(MX, y, 300, 118, "校验通过？")
    err_box(c, EX, y, EW, EH, "返回 400：角色或参数不合法")
    c.arrow([(MX + 150, y), (EX - EW / 2, y)])
    c.label(MX + 220, y - 16, "否")
    c.label(MX + 34, y + 84, "是")

    # 生成取件码
    y += 150
    c.arrow([(MX, y - 150), (MX, y - MH / 2)])
    role_box(c, MX, y, MW, MH, "生成 6 位取件码，状态置为待取件", "系统")

    y += MH + 54
    c.arrow([(MX, y - MH / 2 - 54), (MX, y - MH / 2)])
    role_box(c, MX, y, MW, MH, "发送取件通知（日志模拟短信）", "系统")

    y += MH + 54
    c.arrow([(MX, y - MH / 2 - 54), (MX, y - MH / 2)])
    role_box(c, MX, y, MW, MH, "查看「我的包裹」与取件码", "学生")

    y += MH + 54
    c.arrow([(MX, y - MH / 2 - 54), (MX, y - MH / 2)])
    role_box(c, MX, y, MW, MH, "到驿站出示取件码", "学生")

    y += MH + 54
    c.arrow([(MX, y - MH / 2 - 54), (MX, y - MH / 2)])
    role_box(c, MX, y, MW, MH, "扫描或输入取件码", "工作人员")

    # 决策 2：状态可核销
    y += 122
    c.arrow([(MX, y - 122), (MX, y - 62)])
    c.diamond(MX, y, 300, 118, "状态为待取件或超期？")
    err_box(c, EX, y, EW, EH, "拒绝核销：包裹已取件或已退回")
    c.arrow([(MX + 150, y), (EX - EW / 2, y)])
    c.label(MX + 215, y - 16, "否")
    c.label(MX + 34, y + 86, "是")

    y += 150
    c.arrow([(MX, y - 150), (MX, y - MH / 2)])
    role_box(c, MX, y, MW, MH, "状态改为已取件，记录取件时间与操作人", "系统")

    y += MH + 54
    c.arrow([(MX, y - MH / 2 - 54), (MX, y - MH / 2)])
    role_box(c, MX, y, MW, MH, "写入取件记录（本人取件或代取）", "系统")

    y += MH + 54
    c.arrow([(MX, y - MH / 2 - 54), (MX, y - MH / 2)])
    role_box(c, MX, y, MW, MH, "包裹交给取件人", "工作人员")

    y += 118
    c.arrow([(MX, y - 78), (MX, y - 30)])
    c.pill(MX, y, 260, 58, "结束")

    # 右侧：超期与退回分支
    c.d.text((1080 * S, 1660 * S), "旁路：超期与退回", font=F(15, True), fill="#6B7280", anchor="mm")
    by = 1730
    role_box(c, 1080, by, 360, 78, "入库超 72 小时，定时任务标记超期", "系统", size=16)
    c.arrow([(1080, by + 39), (1080, by + 96)])
    role_box(c, 1080, by + 135, 360, 78, "学生仍未取件，工作人员退回快递公司", "工作人员", size=16)
    c.arrow([(1080, by + 174), (1080, by + 231)])
    c.box(1080, by + 265, 300, 52, "状态改为已退回", size=16, fill="#F3F4F6",
          outline="#6B7280", color="#374151")

    c.save("1-业务流程图.png")


# ---------------------------------------------------------------- 图 2 模块结构图
def module_tree():
    W, H = 2180, 900
    c = Canvas(W, H)
    c.title("图 2  系统模块结构图", "后端按业务拆分为 6 个模块，共 39 个接口")

    RX, RY = W / 2, 150
    c.box(RX, RY, 460, 74, "校园快递收发系统（后端）", size=22, bold=True,
          fill="#1D4ED8", outline="#1E40AF", color="#FFFFFF")

    mods = [
        ("认证与用户", ["学生注册", "登录与退出", "个人中心", "用户管理"]),
        ("驿站管理", ["驿站查询", "新增驿站", "修改驿站", "删除驿站"]),
        ("包裹管理", ["包裹入库", "包裹查询", "取件核销", "包裹退回", "取件记录", "超期处理"]),
        ("公告管理", ["发布公告", "修改公告", "删除公告", "公告浏览"]),
        ("数据统计", ["数据概览", "公司分布", "驿站分布", "取件趋势"]),
        ("基础支撑", ["参数校验", "统一响应", "会话鉴权", "跨域配置"]),
    ]
    n = len(mods)
    box_w, gap = 300, 42
    total = n * box_w + (n - 1) * gap
    start = (W - total) / 2 + box_w / 2
    xs = [start + i * (box_w + gap) for i in range(n)]

    bus_y = 232
    c._seg((RX, RY + 37), (RX, bus_y), "#64748B", 1.8, False)
    c._seg((xs[0], bus_y), (xs[-1], bus_y), "#64748B", 1.8, False)

    for x, (name, items) in zip(xs, mods):
        c._seg((x, bus_y), (x, 262), "#64748B", 1.8, False)
        c.box(x, 300, box_w, 66, name, size=20, bold=True, fill="#DBEAFE",
              outline="#2563EB", color="#1E3A8A")
        spine_x = x - box_w / 2 + 26
        y = 400
        c._seg((x, 333), (x, y - 30), "#94A3B8", 1.4, False)
        for k, it in enumerate(items):
            c._seg((x, y - 30), (spine_x, y - 30), "#94A3B8", 1.4, False)
            c._seg((spine_x, y - 30), (spine_x, y + 24), "#94A3B8", 1.4, False)
            c._seg((spine_x, y + 24), (x - box_w / 2 + 40, y + 24), "#94A3B8", 1.4, False)
            c.box(x + 18, y + 24, box_w - 44, 48, it, size=16, fill="#FFFFFF",
                  outline="#93C5FD", color="#1F2937", radius=8, border=1.5)
            y += 68

    c.text_block(W / 2, H - 46, "说明：模块之间通过 handler 层调用，公共能力放在 handler/common.go 与 internal 下的 db、cache、session 包。",
                 14, False, "#6B7280", W - 200)
    c.save("2-模块结构图.png")


# ---------------------------------------------------------------- 图 3 / 4 程序流程图
def flowchart(title, sub, nodes, name, H):
    W = 1420
    c = Canvas(W, H)
    c.title(title, sub)
    MX, MW = 470, 470
    EX, EW = 1090, 380

    y = 160
    kind, text = nodes[0]
    c.pill(MX, y, 260, 56, text)
    prev_bottom = y + 28
    prev_kind = "start"

    for kind, text in nodes[1:]:
        gap = {"end": 112, "step": 104, "sys": 104, "dec": 154}[kind]
        if kind in ("step", "sys") and prev_kind == "dec":
            gap = 128
        y += gap

        if kind == "end":
            c.arrow([(MX, prev_bottom), (MX, y - 28)])
            c.pill(MX, y, 240, 56, text)
            prev_bottom = y + 28
        elif kind in ("step", "sys"):
            c.arrow([(MX, prev_bottom), (MX, y - 38)])
            if kind == "sys":
                c.box(MX, y, MW, 76, text, size=18, fill="#F5F3FF", outline="#7E22CE",
                      color="#4C1D95")
            else:
                c.box(MX, y, MW, 76, text, size=18, fill="#FFFFFF", outline="#2563EB",
                      color="#1F2937")
            prev_bottom = y + 38
        else:
            question, err_text = text.split("|", 1)
            c.arrow([(MX, prev_bottom), (MX, y - 56)])
            c.diamond(MX, y, 400, 112, question)
            c.arrow([(MX + 200, y), (EX - EW / 2, y)])
            c.label(MX + 268, y - 15, "否")
            c.label(MX + 33, y + 74, "是")
            err_box(c, EX, y, EW, 76, err_text)
            prev_bottom = y + 56
        prev_kind = kind

    c.save(name)


def flow_inbound():
    nodes = [
        ("start", "开始"),
        ("step", "接收包裹入库请求（JSON 请求体）"),
        ("dec", "是工作人员或管理员？|403 仅驿站工作人员可操作"),
        ("dec", "必填参数是否齐全？|400 运单号或收件人手机号不能为空"),
        ("dec", "驿站是否存在？|400 驿站不存在"),
        ("dec", "驿站是否营业？|400 该驿站已停用，不能入库"),
        ("sys", "生成未被占用的 6 位取件码"),
        ("sys", "写入包裹记录：状态=待取件，记录入库时间与操作人"),
        ("sys", "输出取件通知日志（模拟短信通知）"),
        ("step", "返回包裹数据（含取件码）"),
        ("end", "结束"),
    ]
    flowchart("图 3  程序流程图：包裹入库", "对应 internal/handler/parcel.go 的 CreateParcel",
              nodes, "3-程序流程图-包裹入库.png", 1560)


def flow_pickup():
    nodes = [
        ("start", "开始"),
        ("step", "接收核销请求（包裹编号或 6 位取件码）"),
        ("dec", "是工作人员或管理员？|403 仅驿站工作人员可操作"),
        ("step", "查询包裹（按编号，或按取件码查待取件与超期记录）"),
        ("dec", "包裹是否存在？|404 包裹不存在"),
        ("dec", "状态为待取件或超期？|400 已取件不能重复核销，已退回不能取件"),
        ("sys", "状态改为已取件，记录取件时间与操作人"),
        ("sys", "写入取件记录：取件人、取件方式（本人或代取）"),
        ("step", "返回取件记录"),
        ("end", "结束"),
    ]
    flowchart("图 4  程序流程图：取件核销", "对应 internal/handler/parcel.go 的 doPickup",
              nodes, "4-程序流程图-取件核销.png", 1400)


# ---------------------------------------------------------------- 图 5 E-R 图
def er_diagram():
    W, H = 1700, 940
    c = Canvas(W, H)
    c.title("图 5  数据库 E-R 图", "5 张表：用户、驿站、包裹、取件记录、公告")

    ent = {
        "用户": (330, 420, "sys_user", "id(PK) phone name role\nstation_id(FK) status"),
        "驿站": (330, 760, "station", "id(PK) name address\nmanager phone status"),
        "包裹": (990, 540, "parcel", "id(PK) tracking_no receiver_phone\nstation_id(FK) pickup_code status"),
        "取件记录": (1500, 780, "pickup_record", "id(PK) parcel_id(FK)\npickup_type picker_name pickup_time"),
        "公告": (990, 175, "notice", "id(PK) title publisher\ncreate_time"),
    }
    for name, (x, y, table, fields) in ent.items():
        c.box(x, y - 27, 300, 42, f"{name}（{table}）", size=18, bold=True,
              fill="#EFF6FF", outline="#1D4ED8", color="#1E3A8A", radius=8)
        c.box(x, y + 27, 300, 64, fields, size=13, fill="#FFFFFF", outline="#93C5FD",
              color="#475569", radius=8, border=1.5)

    def rel(cx, cy, text):
        c.diamond(cx, cy, 156, 88, text, size=16, fill="#FEF3C7", outline="#D97706",
                  color="#78350F")

    def card(x, y, t):
        c.label(x, y, t, 15, "#334155", True)

    # 用户(N) -属于-> 驿站(1)
    rel(330, 590, "属于")
    c.arrow([(330, 476), (330, 546)], "#64748B", 1.6)
    c.arrow([(330, 634), (330, 704)], "#64748B", 1.6)
    card(292, 505, "N")
    card(292, 690, "1")

    # 用户(1) -收取-> 包裹(N)
    rel(660, 485, "收取")
    c.arrow([(480, 410), (582, 462)], "#64748B", 1.6)
    c.arrow([(738, 508), (840, 530)], "#64748B", 1.6)
    card(516, 412, "1")
    card(846, 512, "N")

    # 驿站(1) -存放-> 包裹(N)
    rel(660, 655, "存放")
    c.arrow([(480, 760), (582, 690)], "#64748B", 1.6)
    c.arrow([(738, 632), (840, 585)], "#64748B", 1.6)
    card(516, 762, "1")
    card(846, 600, "N")

    # 包裹(1) -产生-> 取件记录(N)
    rel(1250, 670, "产生")
    c.arrow([(1140, 560), (1172, 630)], "#64748B", 1.6)
    c.arrow([(1328, 700), (1350, 752)], "#64748B", 1.6)
    card(1150, 570, "1")
    card(1362, 736, "N")

    # 用户(1) -发布-> 公告(N)
    rel(660, 238, "发布")
    c.arrow([(468, 390), (582, 285)], "#64748B", 1.6)
    c.arrow([(738, 212), (840, 186)], "#64748B", 1.6)
    card(508, 350, "1")
    card(846, 186, "N")

    c.text_block(W / 2, H - 42,
                 "说明：PK 为主键，FK 为外键。包裹按 receiver_phone 关联用户；取件记录通过 parcel_id 关联包裹，operator_id 记录操作人。",
                 14, False, "#6B7280", W - 160)
    c.save("5-E-R图.png")


if __name__ == "__main__":
    business_flow()
    module_tree()
    flow_inbound()
    flow_pickup()
    er_diagram()
