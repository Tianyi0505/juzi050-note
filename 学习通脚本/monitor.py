#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
学习通 · 新通知监听自动打开脚本（getNewNotices 为主 + 完整列表兜底 + 自动登录）
================================================================================
目标：轮询学习通收件箱，发现新发布的课堂练习/作业后，自动在浏览器中打开跳转链接。
      若登录会话(cookie)失效/临近过期，自动用已保存的账号密码重新登录并刷新会话，
      从而无需人工干预长期常驻运行。

接口与策略（实测结论）：
  - 新通知接口：notice.chaoxing.com/pc/notice/getNewNotices （POST, body: lastValue=<游标>）
      · 无新规时返回 {"status":true,"objs":"<32位hex游标>"} —— objs 即当前同步游标，无数组。
      · 「有新规」的真实返回结构本次未能抓到样本，代码已兼容 objs 为数组 / 单独 notices 字段。
  - 完整列表接口：notice.chaoxing.com/pc/notice/getNoticeList （二者底层同源，结构大致相同）
      · 返回 notices（可能为 list，或 {lastPage,lastGetId,list:[...]}），每项含 attachment(JSON 字符串)，
        其中 att_web.url 即跳转链接；att_web.examOrWork：work=作业/练习，exam=考试。

核心策略（按你的要求）：
  1. 主用 getNewNotices（只取游标之后的新通知，最轻量）。
  2. 当 getNewNotices 取不到新规（返回纯游标/空数组/解析失败）时，回退到完整列表 getNoticeList。
  3. 用「上一次的最新值」（最近一次见到的最大 insertTime，毫秒）做缓存：
     - 首次运行只缓存该最新值、不打开任何历史通知；
     - 之后每轮：完整列表兜底时，只打开 insertTime 严格大于缓存最新值的项（即“只打开更新的链接”）；
     - 每轮结束把缓存最新值推进到本轮见到的最大 insertTime。
  4. uuid 去重（seen.json）作为兜底，防止同一通知被重复打开。

会话维护（自动登录）：
  - 私密凭据（account / password / cookie）与个人信息统一放在「个人任务/.env」，不进 config.json，避免提交泄露。
  - 每次请求前检查 p_auth_token 的 JWT 过期时间；若距过期不足 jwt_refresh_buffer_days 天，先自动登录刷新。
  - 若某次 API 返回“未登录/会话失效”，自动登录一次并重试。
  - 登录：用 TransferKey 对账号密码做 AES-CBC 加密（IV=key），POST passport2.chaoxing.com/fanyalogin，
    从响应 Set-Cookie 重建 cookie 并持久化到 cookies.json（不写回 config.json，避免泄露私密）。

类型判定：att_web.examOrWork == "work" 视为作业/课堂练习（默认只开这类）；"exam" 为考试；
          funConfig.funTag==1 的「作业结束提醒」等提醒类默认跳过（config.exclude_reminders）。

作业保活（keepalive）：
  - 每次自动打开一条「作业」后，脚本会 GET 该入口、跟随跳转到 doWork 页，
    从页面表单里解析出 courseId/classId/cpi/workRelationId/workAnswerId/standardEnc/enc_work/
    totalQuestionNum 以及每道题的 answertype/answer，然后每隔 keepalive_interval 秒
    POST 一次页面自带的保存接口 /mooc-ans/work/addStudentWorkNewWeb?...&saveStatus=1。
  - 等价于「在页面上每分钟自动点一次保存」，用于维持作答会话、防止答题记录被判超时。
  - 答案按页面当前渲染值原样回传（keepalive_carry_answers=false 则只发表单结构、不带答案）。
  - 考试类（exam）不保活；任务落盘到 keepalive.json，进程重启后自动恢复。
  - 停止条件：后端提示已提交/已结束/已截止、连续失败 keepalive_max_fail 次、或超过 keepalive_max_hours。

用法：
  python monitor.py                # 持续监控，发现新作业自动打开（含自动登录兜底 + 作业保活）
  python monitor.py --new-once     # 查一次新通知并列出（不循环、不打开；取不到新规时预览列表里更新的项）
  python monitor.py --once         # （调试）查完整列表并列出所有匹配项（不循环、不打开）
  python monitor.py --dry-run      # 循环监控但不真正打开浏览器（仅打印将打开的链接）
  python monitor.py --seed         # 重置状态：清空游标/最新值/已见，下次运行只缓存、不打开旧通知
  python monitor.py --login        # 立即用 account/password 手动触发一次登录，刷新 cookie 并退出
  python monitor.py --check        # 健康检查：输出 HEALTHY / UNHEALTHY（含原因），并以退出码 0/1 表示；供看门狗调用
  python monitor.py --stop         # 按 PID 文件结束旧实例（看门狗重启前调用，避免多开）
  python monitor.py --keepalive <作业入口URL>   # 手工对某个作业开始保活（调试用，前台跑）

依赖：仅 Python 标准库（urllib / json / webbrowser / time / os / signal / datetime / base64 / re）。

重要：
  - 私密凭据（账号密码、cookie）已统一移到「个人任务/.env」，并被 .gitignore 忽略，请勿提交到 git、勿泄露。
    config.json 仅保留非私密的运行参数。
"""

import os
import sys
import re
import json
import time
import signal
import base64
import threading
import webbrowser
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
SEEN_PATH = os.path.join(BASE_DIR, "seen.json")
STATE_PATH = os.path.join(BASE_DIR, "state.json")      # {cursor, latest_time, latest_uuid}
CURSOR_PATH = os.path.join(BASE_DIR, "cursor.json")    # 仅用于首次迁移
MONITOR_LOG_PATH = os.path.join(BASE_DIR, "monitor.log")
COOKIES_JSON_PATH = os.path.join(BASE_DIR, "cookies.json")  # 自动登录后的最新 cookie
PID_PATH = os.path.join(BASE_DIR, "monitor.pid")            # 健康检查的 PID 文件
KEEPALIVE_PATH = os.path.join(BASE_DIR, "keepalive.json")   # 作业保活任务（跨进程重启恢复）
HEALTH_STALE_SEC = 10 * 60   # 日志超过该秒数未更新视为“不健康”（看门狗阈值）
IDLE_MARKER = "本次无新"      # 这类轮询心跳日志视为“不重要”，只保留最近若干条
IDLE_KEEP = 20

# --------------------------------------------------------------------------
# .env 加载（账号密码/cookie 等私密凭据统一放 .env，不进 config.json，避免提交泄露）
# --------------------------------------------------------------------------
def load_env():
    """读取 .env，返回 {KEY: VALUE}。

    查找顺序：BASE_DIR/.env（本目录，优先级高）→ 个人任务/.env（vault 根目录，隐私信息统一存放处）。
    OS 环境变量优先于文件内容。
    """
    env = {}
    paths = [
        os.path.join(BASE_DIR, ".env"),
        os.path.join(os.path.dirname(BASE_DIR), "个人任务", ".env"),
    ]
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip()
                    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
                        v = v[1:-1]
                    env.setdefault(k, v)   # 先读到的优先，后面的文件只补缺
        except FileNotFoundError:
            continue
    # OS 环境变量优先（便于 CI / 临时覆盖）
    for k in list(env):
        if k in os.environ:
            env[k] = os.environ[k]
    return env


ENV = load_env()   # 模块加载时读取一次 .env

# 登录相关常量
LOGIN_URL = "https://passport2.chaoxing.com/fanyalogin"
DEFAULT_TRANSFER_KEY = "u2oh6Vu^HWe4_AES"   # 学习通登录 JS 中硬编码的 AES key（同时作 IV）

DEFAULTS = {
    "cookie": "",
    "account": "",
    "password": "",
    "login_url": LOGIN_URL,
    "transfer_key": DEFAULT_TRANSFER_KEY,
    "jwt_refresh_buffer_days": 1,
    "new_notice_api": "https://notice.chaoxing.com/pc/notice/getNewNotices",
    "inbox_list_api": "https://notice.chaoxing.com/pc/notice/getNoticeList",
    "referer": "https://notice.chaoxing.com/pc/notice/myNotice",
    "match_mode": "homework",     # homework / exam / both / any_url
    "exclude_reminders": True,    # True 时跳过 funTag==1 的“作业结束提醒”等提醒类通知
    "check_keyword": "",          # 非空时，标题/正文需包含该关键词才打开
    "only_unread": False,
    "refresh_interval": 30,
    "max_open_per_cycle": 5,
    "year": "auto",
    # ---- 作业保留活：打开的 doWork 页面每隔 keepalive_interval 秒 POST 一次保存接口 ----
    "keepalive_enabled": True,
    "keepalive_interval": 60,          # 秒；每分钟保存一次（与页面自动保存同源接口）
    "keepalive_max_hours": 12,         # 单个作业最多保活多久（小时），到期自动停止
    "keepalive_max_fail": 5,           # 连续失败这么多次就停止并告警
    "keepalive_carry_answers": True,   # True=把页面里已保存的答案原样回传；False=只发表单结构
    "request_body_template": (
        "type=2&notice_type=&lastValue=&sort=&folderUUID=&kw=&startTime=&endTime="
        "&gKw=&gName=&year={YEAR}&tag=&fidsCode=&queryFolderNoticePrevYear=0"
        "&filterSenderPuids=&filterTags="
    ),
    "headless": False,
}

HEADERS = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Origin": "https://notice.chaoxing.com",
    "X-Requested-With": "XMLHttpRequest",
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36 Edg/155.0.0.0"),
    "sec-ch-ua": '"Microsoft Edge";v="155", "Chromium";v="155", "Not(A:Brand";v="24"',
    "sec-ch-ua-platform": '"Windows"',
}

_label_map = {
    "homework": "课堂练习/作业",
    "exam": "考试",
    "both": "作业或考试",
    "any_url": "通知链接",
}


# --------------------------------------------------------------------------
# 运行时 cookie 管理（字典 jar，跨请求保持，含自动登录后写入的会话）
# --------------------------------------------------------------------------
_JAR = {}            # 运行时 cookie 字典；启动时由 config/cookies.json 初始化
_JAR_DIRTY = False


def init_jar(cfg):
    """初始化 _JAR：在 cookies.json 与 .env 的 CHAO_XING_COOKIE 之间，选择有效期更晚（更新鲜）的会话；
    这样既能让“用户手动粘贴的新 cookie”立即生效，又能让自动登录刷新的 cookie 持续保鲜。
    最后兼容旧 config.cookie。"""
    global _JAR
    sources = []  # [(label, cookie_str)]
    if os.path.exists(COOKIES_JSON_PATH):
        try:
            d = json.load(open(COOKIES_JSON_PATH, encoding="utf-8"))
            if d.get("cookie"):
                sources.append(("cookies.json", d["cookie"]))
        except Exception:
            pass
    env_cookie = ENV.get("CHAO_XING_COOKIE")
    if env_cookie:
        sources.append((".env", env_cookie))
    cfg_cookie = cfg.get("cookie", "")
    if cfg_cookie:
        sources.append(("config.json", cfg_cookie))
    if not sources:
        _JAR = {}
        log("⚠️ 无任何 cookie 来源，将尝试用账号密码自动登录。")
        return
    def _exp(c):
        e = jwt_exp(c)
        return e if e else 0
    best_label, best_cookie = max(sources, key=lambda s: _exp(s[1]))
    _JAR = parse_cookie_string(best_cookie)
    exp = _exp(best_cookie)
    if exp:
        log(f"使用 cookie 来源：{best_label}（有效期至 "
            f"{datetime.fromtimestamp(exp).strftime('%Y-%m-%d %H:%M')}）")
    else:
        log(f"使用 cookie 来源：{best_label}（无 JWT，无法判断有效期）")


def parse_cookie_string(s):
    jar = {}
    if not s:
        return jar
    for part in s.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            jar[k.strip()] = v.strip()
    return jar


def jar_to_header(jar):
    return "; ".join(f"{k}={v}" for k, v in jar.items())


_SAVE_ERR_LAST = {}   # {path: 上次报错时间}：同一文件写失败 10 分钟内只提示一次，避免刷屏


def _save_json(path, obj, what):
    """原子写 JSON（tmp + replace）；失败按文件节流记日志。"""
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        _SAVE_ERR_LAST.pop(path, None)
        return True
    except Exception as e:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        if time.time() - _SAVE_ERR_LAST.get(path, 0) > 600:
            _SAVE_ERR_LAST[path] = time.time()
            log(f"⚠️ 保存 {what} 失败：{e}（同一文件 10 分钟内不再重复提示）")
        return False


def update_jar_from_response(jar, resp):
    try:
        for c in (resp.headers.get_all("Set-Cookie") or []):
            pair = c.split(";", 1)[0].strip()
            if "=" in pair:
                k, v = pair.split("=", 1)
                jar[k.strip()] = v.strip()
    except Exception:
        pass


def persist_jar():
    global _JAR_DIRTY
    if _save_json(COOKIES_JSON_PATH,
                  {"cookie": jar_to_header(_JAR),
                   "updated": datetime.now().isoformat(timespec="seconds")},
                  "cookies.json"):
        _JAR_DIRTY = False


def jwt_exp(cookie):
    """从 cookie 的 p_auth_token(JWT) 解出 exp（秒）；解析失败返回 None。"""
    m = re.search(r"p_auth_token=([^;]+)", cookie or "")
    if not m:
        return None
    token = m.group(1)
    parts = token.split(".")
    if len(parts) != 3:
        return None
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return None
    return data.get("exp")


def cookie_expiring(cookie, buffer_days=1):
    """JWT 距过期不足 buffer_days 天 → True（需要刷新）。无法解析则不强制刷新。"""
    exp = jwt_exp(cookie)
    if exp is None:
        return False
    return (exp - time.time()) <= buffer_days * 86400


def is_session_invalid(parsed, raw, status):
    """粗略判断 API 响应是否表示“未登录/会话失效”。"""
    if status in (401, 403):
        return True
    if isinstance(parsed, dict):
        if parsed.get("status") is False:
            return True
        msg = " ".join(str(parsed.get(k, "")) for k in ("msg", "msg2", "errorMsg", "message"))
        if ("登录" in msg) or ("not login" in msg.lower()) or parsed.get("needLogin"):
            return True
        return False
    # 非 JSON：可能是登录页 HTML 或被拦截
    if raw and ("<html" in raw.lower() or "login" in raw.lower()):
        return True
    return False


# --------------------------------------------------------------------------
# 纯 Python AES-128-CBC（用于登录密码加密，零依赖）
# --------------------------------------------------------------------------
_AES_SBOX = [
    0x63, 0x7c, 0x77, 0x7b, 0xf2, 0x6b, 0x6f, 0xc5, 0x30, 0x01, 0x67, 0x2b, 0xfe, 0xd7, 0xab, 0x76,
    0xca, 0x82, 0xc9, 0x7d, 0xfa, 0x59, 0x47, 0xf0, 0xad, 0xd4, 0xa2, 0xaf, 0x9c, 0xa4, 0x72, 0xc0,
    0xb7, 0xfd, 0x93, 0x26, 0x36, 0x3f, 0xf7, 0xcc, 0x34, 0xa5, 0xe5, 0xf1, 0x71, 0xd8, 0x31, 0x15,
    0x04, 0xc7, 0x23, 0xc3, 0x18, 0x96, 0x05, 0x9a, 0x07, 0x12, 0x80, 0xe2, 0xeb, 0x27, 0xb2, 0x75,
    0x09, 0x83, 0x2c, 0x1a, 0x1b, 0x6e, 0x5a, 0xa0, 0x52, 0x3b, 0xd6, 0xb3, 0x29, 0xe3, 0x2f, 0x84,
    0x53, 0xd1, 0x00, 0xed, 0x20, 0xfc, 0xb1, 0x5b, 0x6a, 0xcb, 0xbe, 0x39, 0x4a, 0x4c, 0x58, 0xcf,
    0xd0, 0xef, 0xaa, 0xfb, 0x43, 0x4d, 0x33, 0x85, 0x45, 0xf9, 0x02, 0x7f, 0x50, 0x3c, 0x9f, 0xa8,
    0x51, 0xa3, 0x40, 0x8f, 0x92, 0x9d, 0x38, 0xf5, 0xbc, 0xb6, 0xda, 0x21, 0x10, 0xff, 0xf3, 0xd2,
    0xcd, 0x0c, 0x13, 0xec, 0x5f, 0x97, 0x44, 0x17, 0xc4, 0xa7, 0x7e, 0x3d, 0x64, 0x5d, 0x19, 0x73,
    0x60, 0x81, 0x4f, 0xdc, 0x22, 0x2a, 0x90, 0x88, 0x46, 0xee, 0xb8, 0x14, 0xde, 0x5e, 0x0b, 0xdb,
    0xe0, 0x32, 0x3a, 0x0a, 0x49, 0x06, 0x24, 0x5c, 0xc2, 0xd3, 0xac, 0x62, 0x91, 0x95, 0xe4, 0x79,
    0xe7, 0xc8, 0x37, 0x6d, 0x8d, 0xd5, 0x4e, 0xa9, 0x6c, 0x56, 0xf4, 0xea, 0x65, 0x7a, 0xae, 0x08,
    0xba, 0x78, 0x25, 0x2e, 0x1c, 0xa6, 0xb4, 0xc6, 0xe8, 0xdd, 0x74, 0x1f, 0x4b, 0xbd, 0x8b, 0x8a,
    0x70, 0x3e, 0xb5, 0x66, 0x48, 0x03, 0xf6, 0x0e, 0x61, 0x35, 0x57, 0xb9, 0x86, 0xc1, 0x1d, 0x9e,
    0xe1, 0xf8, 0x98, 0x11, 0x69, 0xd9, 0x8e, 0x94, 0x9b, 0x1e, 0x87, 0xe9, 0xce, 0x55, 0x28, 0xdf,
    0x8c, 0xa1, 0x89, 0x0d, 0xbf, 0xe6, 0x42, 0x68, 0x41, 0x99, 0x2d, 0x0f, 0xb0, 0x54, 0xbb, 0x16,
]

_AES_RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36]


def _aes_key_expansion(key):
    """AES-128：16 字节 key → 176 字节轮密钥（44 words）。"""
    Nk, Nr = 4, 10
    w = [list(key[4 * i:4 * i + 4]) for i in range(Nk)]
    for i in range(Nk, 4 * (Nr + 1)):
        temp = list(w[i - 1])
        if i % Nk == 0:
            temp = temp[1:] + temp[:1]            # RotWord
            temp = [_AES_SBOX[b] for b in temp]    # SubWord
            temp[0] ^= _AES_RCON[i // Nk - 1]
        w.append([w[i - Nk][j] ^ temp[j] for j in range(4)])
    out = []
    for word in w:
        out.extend(word)
    return out


def _aes_xtime(a):
    a <<= 1
    if a & 0x100:
        a ^= 0x11b
    return a & 0xff


def _aes_encrypt_block(block, rk):
    # 状态：state[row][col]，输入按列主序填充
    state = [[block[r + 4 * c] for c in range(4)] for r in range(4)]

    def add_round_key(rnd):
        for c in range(4):
            for r in range(4):
                state[r][c] ^= rk[rnd * 16 + c * 4 + r]

    add_round_key(0)
    for rnd in range(1, 10):
        for r in range(4):
            for c in range(4):
                state[r][c] = _AES_SBOX[state[r][c]]
        for r in range(1, 4):
            state[r] = state[r][r:] + state[r][:r]
        for c in range(4):
            a = [state[r][c] for r in range(4)]
            state[0][c] = _aes_xtime(a[0]) ^ (_aes_xtime(a[1]) ^ a[1]) ^ a[2] ^ a[3]
            state[1][c] = a[0] ^ _aes_xtime(a[1]) ^ (_aes_xtime(a[2]) ^ a[2]) ^ a[3]
            state[2][c] = a[0] ^ a[1] ^ _aes_xtime(a[2]) ^ (_aes_xtime(a[3]) ^ a[3])
            state[3][c] = (_aes_xtime(a[0]) ^ a[0]) ^ a[1] ^ a[2] ^ _aes_xtime(a[3])
        add_round_key(rnd)
    for r in range(4):
        for c in range(4):
            state[r][c] = _AES_SBOX[state[r][c]]
    for r in range(1, 4):
        state[r] = state[r][r:] + state[r][:r]
    add_round_key(10)

    out = bytearray(16)
    for r in range(4):
        for c in range(4):
            out[r + 4 * c] = state[r][c]
    return bytes(out)


def aes_cbc_encrypt(key, data):
    """AES-128-CBC（IV=key），PKCS7 填充，返回 base64 字符串。key 须 16 字节。"""
    assert len(key) == 16, "AES key 必须为 16 字节"
    padlen = 16 - (len(data) % 16)
    data = data + bytes([padlen]) * padlen
    rk = _aes_key_expansion(key)
    iv = key
    prev = iv
    out = bytearray()
    for i in range(0, len(data), 16):
        block = bytes(x ^ y for x, y in zip(data[i:i + 16], prev))
        enc = _aes_encrypt_block(block, rk)
        out.extend(enc)
        prev = enc
    return base64.b64encode(bytes(out)).decode("ascii")


# --------------------------------------------------------------------------
# 自动登录
# --------------------------------------------------------------------------
def do_login(cfg):
    """用 account/password 走 fanyalogin 登录，成功返回刷新后的 cookie 字符串，失败返回 None。"""
    uname = (cfg.get("account") or "").strip()
    pwd = cfg.get("password") or ""
    if not uname or not pwd:
        log("⚠️ 个人任务/.env 缺少 CHAO_XING_ACCOUNT / CHAO_XING_PASSWORD，无法自动登录。"
            "请补充账号密码，或在 .env 填入 CHAO_XING_COOKIE。")
        return None
    key = (cfg.get("transfer_key") or DEFAULT_TRANSFER_KEY).encode("utf-8")
    enc_u = aes_cbc_encrypt(key, uname.encode("utf-8"))
    enc_p = aes_cbc_encrypt(key, pwd.encode("utf-8"))

    body = urllib.parse.urlencode({
        "fid": "-1",
        "uname": enc_u,
        "password": enc_p,
        "refer": "http://i.chaoxing.com",
        "t": "true",
        "forbidotherlogin": "0",
        "validate": "",
        "doubleFactorLogin": "0",
        "independentId": "0",
        "independentNameId": "0",
    })
    _strip_proxy()
    req = urllib.request.Request(cfg.get("login_url", LOGIN_URL),
                                 data=body.encode("utf-8"), method="POST")
    req.add_header("User-Agent", HEADERS["User-Agent"])
    req.add_header("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8")
    req.add_header("Accept", "application/json, text/plain, */*")
    req.add_header("Origin", "https://passport2.chaoxing.com")
    req.add_header("Referer", "https://passport2.chaoxing.com/login")
    req.add_header("X-Requested-With", "XMLHttpRequest")

    try:
        r = urllib.request.urlopen(req, timeout=20)
        raw = r.read().decode("utf-8", "ignore")
        try:
            j = json.loads(raw)
        except Exception:
            j = {}
        if j.get("status") is True:
            jar = {}
            for c in (r.headers.get_all("Set-Cookie") or []):
                pair = c.split(";", 1)[0].strip()
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    jar[k.strip()] = v.strip()
            cookie = jar_to_header(jar)
            if not cookie:
                log("⚠️ 登录成功但未能提取到 cookie。")
                return None
            save_cookies_json(cookie)
            log("✅ 自动登录成功，已刷新会话 cookie（写入 cookies.json）。")
            return cookie
        else:
            msg = j.get("msg2") or j.get("msg") or raw[:200]
            log(f"⚠️ 自动登录失败：{msg}")
            if j.get("needVcode") or j.get("needValidate") or ("验证码" in str(msg)):
                log("⚠️ 登录需要验证码，无法自动完成。请手动登录后更新 config.json 的 cookie。")
            return None
    except urllib.error.HTTPError as e:
        log(f"登录 HTTP 错误 {e.code}：{e.read().decode('utf-8', 'ignore')[:300]}")
        return None
    except Exception as e:
        log(f"登录请求失败：{e}")
        return None


def save_cookies_json(cookie):
    _save_json(COOKIES_JSON_PATH,
               {"cookie": cookie,
                "updated": datetime.now().isoformat(timespec="seconds")},
               "cookies.json")


# --------------------------------------------------------------------------
# 日志
# --------------------------------------------------------------------------
LOGF = None  # 由 main() 打开为 monitor.log 的追加句柄；脚本自己管理该文件


def log(*args):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] " + " ".join(str(a) for a in args)
    print(line, flush=True)  # 同时输出到控制台/后台捕获，便于实时查看
    if LOGF is not None:
        try:
            LOGF.write(line + "\n")
            LOGF.flush()
        except Exception:
            pass


def trim_log(path, marker, keep):
    """保留所有重要日志，仅把含 marker 的“不重要”日志裁到最近 keep 条（保序）。"""
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except Exception:
        return
    idle_pos = [i for i, l in enumerate(lines) if marker in l]
    excess = len(idle_pos) - keep
    if excess <= 0:
        return
    drop = set(idle_pos[:excess])
    kept = [l for i, l in enumerate(lines) if i not in drop]
    try:
        with open(path, "w", encoding="utf-8") as f:
            if kept:
                f.write("\n".join(kept) + "\n")
    except Exception:
        pass


def log_idle(*args):
    """不重要日志：记录后把同类旧行裁到最近 IDLE_KEEP 条。"""
    log(*args)
    trim_log(MONITOR_LOG_PATH, IDLE_MARKER, IDLE_KEEP)


# --------------------------------------------------------------------------
# 配置 & 状态
# --------------------------------------------------------------------------
def load_config():
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception as e:
            log("读取 config.json 失败，使用默认值:", e)
    # 私密凭据从 .env 注入（不写入 config.json，避免提交泄露）
    if ENV.get("CHAO_XING_ACCOUNT"):
        cfg["account"] = ENV["CHAO_XING_ACCOUNT"]
    if "CHAO_XING_PASSWORD" in ENV:
        cfg["password"] = ENV["CHAO_XING_PASSWORD"]
    # 校验能否拿到 cookie：.env 的 CHAO_XING_COOKIE / cookies.json / 账号密码自动登录
    have_cookie_source = bool(ENV.get("CHAO_XING_COOKIE")) or os.path.exists(COOKIES_JSON_PATH)
    have_login = bool(cfg.get("account")) and bool(cfg.get("password"))
    if not have_cookie_source and not have_login:
        log("⚠️ 未找到任何 cookie 来源，且 .env 缺少账号密码："
            "请检查 学习通脚本/.env（CHAO_XING_ACCOUNT / CHAO_XING_PASSWORD / CHAO_XING_COOKIE）。")
        sys.exit(1)
    return cfg


def load_seen():
    if os.path.exists(SEEN_PATH):
        try:
            with open(SEEN_PATH, encoding="utf-8") as f:
                return set(json.load(f).get("uuids", []))
        except Exception:
            pass
    return set()


def save_seen(seen):
    _save_json(SEEN_PATH,
               {"uuids": sorted(seen),
                "updated": datetime.now().isoformat(timespec="seconds")},
               "seen.json")


def load_state():
    """state: {cursor, latest_time, latest_uuid}。首次从旧 cursor.json 迁移 cursor。"""
    if os.path.exists(STATE_PATH):
        try:
            st = json.load(open(STATE_PATH, encoding="utf-8"))
            if isinstance(st, dict):
                st.setdefault("cursor", None)
                st.setdefault("latest_time", None)
                st.setdefault("latest_uuid", None)
                return st
        except Exception:
            pass
    cursor = None
    if os.path.exists(CURSOR_PATH):
        try:
            cursor = json.load(open(CURSOR_PATH, encoding="utf-8")).get("cursor")
        except Exception:
            pass
    return {"cursor": cursor, "latest_time": None, "latest_uuid": None}


def save_state(state):
    state = dict(state)
    state["updated"] = datetime.now().isoformat(timespec="seconds")
    _save_json(STATE_PATH, state, "state.json")


_SEEN_GLOBAL = set()


# --------------------------------------------------------------------------
# 网络请求（带自动登录兜底）
# --------------------------------------------------------------------------
def _strip_proxy():
    for p in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
              "ALL_PROXY", "all_proxy"):
        os.environ.pop(p, None)


def _post_meta(url, body, cfg):
    """发起 POST，返回 (parsed_dict, raw_text, status)。同时用响应 Set-Cookie 更新 _JAR。"""
    _strip_proxy()
    req = urllib.request.Request(url, data=body.encode("utf-8"), method="POST")
    for k, v in HEADERS.items():
        req.add_header(k, v)
    req.add_header("Cookie", jar_to_header(_JAR))
    req.add_header("Referer", cfg.get("referer") or url)
    try:
        r = urllib.request.urlopen(req, timeout=20)
        raw = r.read().decode("utf-8", "ignore")
        update_jar_from_response(_JAR, r)
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {}
        return parsed, raw, r.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "ignore")
        update_jar_from_response(_JAR, e)
        return {}, raw, e.code
    except Exception as e:
        log(f"请求失败：{e}")
        return {}, "", 0


def safe_fetch(url, body, cfg):
    """带自动登录重试的 API 请求。返回 parsed_dict。"""
    global _JAR
    # 0) 若完全没有 cookie，先尝试用账号密码自动登录
    if not _JAR:
        log("⚠️ 当前无 cookie，先尝试自动登录…")
        nc = do_login(cfg)
        if nc:
            _JAR = parse_cookie_string(nc)
            persist_jar()
    # 1)  proactive：cookie 临近过期则先刷新
    if cookie_expiring(jar_to_header(_JAR), cfg.get("jwt_refresh_buffer_days", 1)):
        log("⚠️ cookie 临近过期，尝试自动登录刷新…")
        nc = do_login(cfg)
        if nc:
            _JAR = parse_cookie_string(nc)
            persist_jar()
    # 2)  actual request
    parsed, raw, status = _post_meta(url, body, cfg)
    # 3)  reactive：若会话失效，登录一次后重试
    if is_session_invalid(parsed, raw, status):
        log("⚠️ 会话失效/未登录，尝试自动登录…")
        nc = do_login(cfg)
        if nc:
            _JAR = parse_cookie_string(nc)
            persist_jar()
            parsed, raw, status = _post_meta(url, body, cfg)
    return parsed


def fetch_new(cursor, cfg):
    """请求新通知接口。返回解析后的 dict。"""
    body = "lastValue=" + (cursor or "")
    return safe_fetch(cfg["new_notice_api"], body, cfg)


def fetch_list(cfg):
    """请求完整列表接口。"""
    year = cfg["year"]
    if year == "auto":
        year = str(datetime.now().year)
    body = cfg["request_body_template"].replace("{YEAR}", year)
    return safe_fetch(cfg["inbox_list_api"], body, cfg)


# --------------------------------------------------------------------------
# 解析 & 匹配
# --------------------------------------------------------------------------
def stable_id(item):
    return (item.get("uuid")
            or item.get("idCode")
            or f"{item.get('insertTime')}_{item.get('title')}")


def parse_time(v):
    """insertTime 为 epoch 毫秒字符串，转 float 便于比较；无法解析返回 None。"""
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


def _item_fun_tag(item):
    """从 extendParam.cparams 里取 funConfig.funTag（比 attachment 上的更可靠）。"""
    ep = item.get("extendParam") or {}
    cp = ep.get("cparams")
    if isinstance(cp, str):
        try:
            cp = json.loads(cp)
        except Exception:
            cp = None
    if isinstance(cp, dict):
        ft = cp.get("funConfig", {}).get("funTag")
        if ft is not None:
            return ft
    att = item.get("attachment")
    try:
        atts = json.loads(att) if isinstance(att, str) else att
    except Exception:
        atts = None
    if isinstance(atts, list):
        for a in atts:
            if "funTag" in a:
                return a.get("funTag")
    return None


def find_target_url(item, cfg):
    """从一个通知条目里找出应当打开的跳转 URL（没有则返回 None）。

    类型判定依据 att_web.examOrWork：work=作业/练习，exam=考试。
    funConfig.funTag==1 为“作业结束提醒”等提醒类（默认跳过）。
    """
    att = item.get("attachment")
    if not att:
        return None
    try:
        atts = json.loads(att) if isinstance(att, str) else att
    except Exception:
        return None
    if not isinstance(atts, list):
        return None

    mode = cfg.get("match_mode", "homework")
    exclude_reminders = cfg.get("exclude_reminders", True)
    fun_tag = _item_fun_tag(item)
    is_reminder = (fun_tag == 1)

    for a in atts:
        web = a.get("att_web") or {}
        url = (web.get("url") or "").strip()
        if not url:
            continue
        eow = (web.get("examOrWork") or "").lower()
        if eow:
            is_homework = (eow == "work")
            is_exam = (eow == "exam")
        else:
            is_homework = ("/work/view" in url)
            is_exam = ("examapi" in url.lower()) or ("intoexamorwork" in url)

        want = False
        if mode == "homework":
            want = is_homework
        elif mode == "exam":
            want = is_exam
        elif mode == "both":
            want = is_homework or is_exam
        elif mode == "any_url":
            want = True

        if want and not (exclude_reminders and is_reminder):
            return url
    return None


def match_keyword(item, kw):
    if not kw:
        return True
    hay = " ".join(str(item.get(k, "")) for k in
                   ("title", "content", "rtf_content", "createrName"))
    return kw in hay


def collect_targets(notices, cfg):
    """从“通知数组”中提取匹配目标，返回 [{"sid","title","url","time"}, ...]。"""
    if not isinstance(notices, list):
        return []
    out = []
    for it in notices:
        if not isinstance(it, dict):
            continue
        if cfg.get("only_unread") and str(it.get("isread", "0")) not in ("0", "false", "", "False"):
            continue
        url = find_target_url(it, cfg)
        if not url:
            continue
        if not match_keyword(it, cfg.get("check_keyword", "")):
            continue
        out.append({"sid": stable_id(it),
                    "title": it.get("title", ""),
                    "url": url,
                    "time": parse_time(it.get("insertTime"))})
    return out


def parse_new(resp):
    """解析 getNewNotices 响应。返回 (notices列表, next_cursor)。"""
    if not isinstance(resp, dict):
        return [], None
    objs = resp.get("objs")
    cursor = objs if isinstance(objs, str) else None
    if isinstance(objs, list):
        notices = objs
    else:
        notices = None
        for k in ("notices", "list", "data", "newNotices", "items"):
            v = resp.get(k)
            if isinstance(v, list):
                notices = v
                break
    notices = notices or []
    if cursor is None:
        cursor = resp.get("lastValue") or resp.get("cursor") or resp.get("syncKey")
    return notices, cursor


def get_notice_list(data):
    """从完整列表响应里取到真正的通知数组（兼容 list 或 {list:[...]}）。"""
    ns = data.get("notices") if isinstance(data, dict) else None
    if isinstance(ns, list):
        return ns
    if isinstance(ns, dict):
        lst = ns.get("list")
        if isinstance(lst, list):
            return lst
    return []


# --------------------------------------------------------------------------
# 子命令
# --------------------------------------------------------------------------
def do_new_once(cfg):
    state = load_state()
    resp = fetch_new(state.get("cursor"), cfg)
    notices, new_cursor = parse_new(resp)
    if new_cursor:
        save_state({**state, "cursor": new_cursor})
    log(f"getNewNotices 返回 {len(notices)} 条通知")
    ts = collect_targets(notices, cfg)
    if not ts:
        log("getNewNotices 取不到新规/无法解析 → 预览完整列表里「比已缓存最新值更新」的项：")
        data = fetch_list(cfg)
        notices2 = get_notice_list(data)
        ts = collect_targets(notices2, cfg)
        prev = state.get("latest_time")
        if prev is not None:
            ts = [t for t in ts if (t["time"] or 0) > prev]
        elif not state.get("latest_time") and state.get("latest_uuid") is None:
            log("（尚未缓存最新值；首次运行请用 monitor.py 自动 seed，或先 --seed）")
    log(f"其中匹配（{_label_map.get(cfg['match_mode'],'通知')}）共 {len(ts)} 条：")
    for t in ts:
        print(f"  - {t['title']}\n    {t['url']}")
    log("（--new-once 模式：不循环、不打开）")
    persist_jar()


def do_once(cfg):
    data = fetch_list(cfg)
    notices = get_notice_list(data)
    if not notices:
        log("⚠️ 未拿到 notices，cookie 可能已过期或接口变更。原始返回见下：")
        log(json.dumps(data, ensure_ascii=False)[:800])
        return
    ts = collect_targets(notices, cfg)
    log(f"完整列表共 {len(notices)} 条通知；匹配 {len(ts)} 条：")
    for t in ts:
        print(f"  - {t['title']}\n    {t['url']}")
    log("（--once 模式：不循环、不打开）")
    persist_jar()


def do_login_cmd(cfg):
    log("手动触发登录…")
    nc = do_login(cfg)
    if nc:
        global _JAR
        _JAR = parse_cookie_string(nc)
        persist_jar()
        exp = jwt_exp(nc)
        if exp:
            log(f"新会话有效期至：{datetime.fromtimestamp(exp).strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        log("登录未成功，详见上方日志。")


def do_seed(cfg):
    save_state({"cursor": None, "latest_time": None, "latest_uuid": None})
    save_seen(set())
    log("已重置状态：游标/最新值/已见集合均已清空。下次运行会先缓存最新值，不打开历史通知。")


def do_keepalive_cmd(cfg, url):
    """手工对某个作业入口开始保活（前台跑，Ctrl+C 退出）。"""
    if not url:
        log("用法：python monitor.py --keepalive <作业入口URL>")
        return
    start_keepalive(url, cfg, "手动保活")
    with _KA_LOCK:
        running = [t for t in _KA_TASKS if t["status"] == "running"]
    if not running:
        log("没有启动任何保活任务（原因见上）。")
        return
    log(f"保活任务运行中（{len(running)} 个），Ctrl+C 退出…")
    try:
        while True:
            time.sleep(10)
    except KeyboardInterrupt:
        log("已退出保活。")


# --------------------------------------------------------------------------
# 健康检查 & 看门狗辅助（供「每小时监控+自动重启」调用）
# --------------------------------------------------------------------------
def write_pid():
    try:
        with open(PID_PATH, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except Exception:
        pass


def read_pid():
    try:
        with open(PID_PATH, encoding="utf-8") as f:
            v = f.read().strip()
        return int(v) if v.isdigit() else None
    except Exception:
        return None


def _pid_alive(pid):
    """跨进程存活探测在沙箱/不同会话下不可靠（OpenProcess 失败误判），故本脚本不再依赖它做健康判定。
    仅保留为信息用途。"""
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError as e:
        if getattr(e, "winerror", None) == 87:   # 参数错误 ⇒ 进程不存在（也可能跨会话探测受限）
            return False
        return True
    except Exception:
        return False


# 单实例互斥端口（TCP 自锁，OS 级可靠，避免跨会话多开）
LOCK_PORT = 45123


def acquire_instance_lock():
    """尝试占用 127.0.0.1:LOCK_PORT 作为单实例锁；若已被占用说明已有实例在跑，返回 False。"""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    try:
        s.bind(("127.0.0.1", LOCK_PORT))
        s.listen(1)
        return s   # 持有该 socket 即锁（进程退出自动释放）
    except OSError:
        return None


def do_check(_cfg=None):
    """健康检查：日志新鲜度 + state.json 是否还能落盘（跨会话可靠）。
    打印 HEALTHY / UNHEALTHY:<原因>，并以退出码 0/1 表示。看门狗据此决定是否重启。"""
    reasons = []
    try:
        mtime = os.path.getmtime(MONITOR_LOG_PATH)
        fresh = (time.time() - mtime) <= HEALTH_STALE_SEC
    except OSError:
        fresh = False
    if not fresh:
        reasons.append(f"monitor.log 超过 {HEALTH_STALE_SEC // 60} 分钟未更新")
    # 状态文件写不进去（沙箱禁写/磁盘只读）时，日志照常更新但游标不推进 → 会重复打开
    try:
        st = json.load(open(STATE_PATH, encoding="utf-8"))
        upd = datetime.fromisoformat(st["updated"])
        if (datetime.now() - upd).total_seconds() > HEALTH_STALE_SEC:
            reasons.append(f"state.json 超过 {HEALTH_STALE_SEC // 60} 分钟未更新（可能无法写盘）")
    except Exception:
        reasons.append("state.json 读取失败")
    pid = read_pid()
    if not reasons:
        print(f"HEALTHY pid={pid} log_fresh=yes")
        sys.exit(0)
    print(f"UNHEALTHY: " + "; ".join(reasons) + f" (pid={pid})")
    sys.exit(1)


def do_daemon():
    """以“脱离父会话”的独立进程启动一个监控实例，父进程立即返回。
    用于看门狗/计划任务拉起，避免实例随调用方会话退出或继承其沙箱限制。"""
    import subprocess
    flags = 0
    if os.name == "nt":
        flags = 0x00000008 | 0x00000200   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    with open(os.devnull, "w") as devnull:
        p = subprocess.Popen([sys.executable, os.path.abspath(__file__)],
                             cwd=BASE_DIR,
                             stdin=subprocess.DEVNULL,
                             stdout=devnull,
                             stderr=subprocess.STDOUT,
                             creationflags=flags,
                             close_fds=True)
    log(f"已在后台启动监控实例 pid={p.pid}（脱离当前会话）")


def do_stop():
    """按 PID 文件结束旧实例（看门狗重启前调用，避免多开）。"""
    pid = read_pid()
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            log(f"已向 pid={pid} 发送 SIGTERM。")
        except OSError as e:
            if getattr(e, "winerror", None) == 87:
                log(f"pid={pid} 不存在（无需停止）。")
            else:
                log(f"停止 pid={pid} 失败: {e}")
    else:
        log("未找到 PID 文件，无需停止。")


# --------------------------------------------------------------------------
# 作业保活（keepalive）
#   对脚本打开过的 doWork 页面，每隔 keepalive_interval 秒 POST 一次页面自带的
#   保存接口 /mooc-ans/work/addStudentWorkNewWeb?...&saveStatus=1，
#   等价于在页面上“再点一次保存”，用来维持作答会话/答题记录不被判超时。
#   请求参数全部从 doWork 页表单里解析，答案按页面当前渲染值原样回传。
# --------------------------------------------------------------------------
KA_END_WORDS = ("已提交", "已交卷", "已结束", "已截止", "不能重复", "不存在", "没有权限", "已过期")
_KA_TASKS = []          # 运行中的保活任务
_KA_LOCK = threading.Lock()
_KA_THREAD = None


def _html_hidden(html, *names):
    """从 HTML 里取隐藏域 value（按 id 或 name 匹配）。"""
    for n in names:
        for pat in (r'id="%s"[^>]*value="([^"]*)"' % n,
                    r'name="%s"[^>]*value="([^"]*)"' % n):
            mm = re.search(pat, html)
            if mm:
                return mm.group(1)
    return ""


def _ka_parse(html, final_url, cfg):
    """解析 doWork 页 → 保活任务（不含运行态字段）。解析失败返回 (None, 原因)。"""
    if "/work/dowork" not in final_url:
        return None, f"未跳转到 doWork 页（{final_url[:100]}）"
    mf = re.search(r'<form[^>]*id="submitForm"[^>]*action="([^"]+)"', html)
    if not mf:
        mf = re.search(r'<form[^>]*action="([^"]*addStudentWorkNewWeb[^"]*)"', html)
    if not mf:
        return None, "页面里找不到 submitForm/保存接口地址"

    action = mf.group(1).replace("&amp;", "&")
    post_url = urllib.parse.urljoin(final_url, action)
    # 页面 JS 在提交时追加的参数（与原 curl 一致）
    post_url += ("&" if "?" in post_url else "?") + "pyFlag=1&ua=pc&formType=post&saveStatus=1&version=1"

    fields = {
        "courseId": _html_hidden(html, "courseId"),
        "classId": _html_hidden(html, "classId"),
        "knowledgeid": _html_hidden(html, "knowledgeId"),
        "cpi": _html_hidden(html, "cpi"),
        "workRelationId": _html_hidden(html, "workId"),
        "workAnswerId": _html_hidden(html, "answerId"),
        "jobid": _html_hidden(html, "jobid"),
        "standardEnc": _html_hidden(html, "standardEnc"),
        "enc_work": _html_hidden(html, "enc_work"),
        "totalQuestionNum": _html_hidden(html, "totalQuestionNum"),
        "pyFlag": "1",
        "mooc2": _html_hidden(html, "mooc2") or "1",
        "randomOptions": _html_hidden(html, "randomOptions") or "false",
        "workTimesEnc": _html_hidden(html, "workTimesEnc"),
    }
    for k in ("courseId", "classId", "cpi", "workRelationId", "workAnswerId", "standardEnc"):
        if not fields.get(k):
            return None, f"缺少关键字段 {k}"

    qids = list(dict.fromkeys(re.findall(r'name="answertype(\d+)"', html)))
    fields["answerwqbid"] = "".join(q + "," for q in qids)

    if cfg.get("keepalive_carry_answers", True):
        for q in qids:
            t = re.search(r'name="answertype%s"[^>]*value="([^"]*)"' % q, html)
            fields["answertype" + q] = (t.group(1) if t else "")
            mt = re.search(r'<textarea[^>]*name="answer%s"[^>]*>(.*?)</textarea>' % q, html, re.S)
            if mt:
                fields["answer" + q] = mt.group(1)
                continue
            # 选择题：取选中项的 value（解析不出就留空，不会覆盖成乱码）
            val = ""
            for mi in re.finditer(r'<input[^>]*name="answer%s"[^>]*>' % q, html):
                tag = mi.group(0)
                if re.search(r'checked', tag):
                    mv = re.search(r'value="([^"]*)"', tag)
                    val = mv.group(1) if mv else ""
                    break
            fields["answer" + q] = val

    title_m = re.search(r'<h2[^>]*class="[^"]*mark_title[^"]*"[^>]*>(.*?)</h2>', html, re.S)
    title = re.sub(r"<[^>]+>", "", title_m.group(1)).strip() if title_m else ""

    return {
        "work_url": None,               # 由调用方填
        "dowork_url": final_url,
        "post_url": post_url,
        "title": title,
        "work_id": fields["workRelationId"],
        "answer_id": fields["workAnswerId"],
        "qids": qids,
        "fields": fields,
    }, ""


def _ka_add(task, cfg, work_url, title=""):
    """把任务加入保活队列（同 workId 幂等），并确保后台线程已启动。"""
    global _KA_THREAD
    task["work_url"] = work_url
    task["title"] = task.get("title") or title
    task["started"] = time.time()
    task["last_post"] = 0.0
    task["ok"] = 0
    task["fail"] = 0
    task["status"] = "running"
    task["last_msg"] = ""
    with _KA_LOCK:
        for t in _KA_TASKS:
            if t["work_id"] == task["work_id"] and t["status"] == "running":
                return False
        _KA_TASKS.append(task)
    if _KA_THREAD is None or not _KA_THREAD.is_alive():
        _KA_THREAD = threading.Thread(target=_ka_worker, args=(cfg,), daemon=True,
                                      name="keepalive")
        _KA_THREAD.start()
    return True


def _ka_do_post(task, cfg):
    """发一次保存请求，返回 (是否成功, 提示信息)。"""
    _strip_proxy()
    body = urllib.parse.urlencode(task["fields"]).encode("utf-8")
    req = urllib.request.Request(task["post_url"], data=body, method="POST")
    req.add_header("User-Agent", HEADERS["User-Agent"])
    req.add_header("Accept", "application/json, text/javascript, */*; q=0.01")
    req.add_header("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8")
    req.add_header("Origin", "https://mooc1-api.chaoxing.com")
    req.add_header("Referer", task["dowork_url"])
    req.add_header("X-Requested-With", "XMLHttpRequest")
    req.add_header("Cookie", jar_to_header(_JAR))
    try:
        r = urllib.request.urlopen(req, timeout=20)
        raw = r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    try:
        j = json.loads(raw)
    except Exception:
        return False, f"返回非 JSON（{raw[:80]}）"
    if j.get("status") is True:
        return True, j.get("msg") or "保存成功"
    msg = str(j.get("msg") or j.get("errorMsg") or raw[:100])
    return False, msg


def _ka_worker(cfg):
    """后台线程：按间隔逐个任务发保存请求。"""
    interval = max(10, int(cfg.get("keepalive_interval", 60)))
    while True:
        time.sleep(2)
        now = time.time()
        with _KA_LOCK:
            snapshot = list(_KA_TASKS)
        for t in snapshot:
            if t["status"] != "running":
                continue
            if now - t["last_post"] < interval:
                continue
            if now - t["started"] > cfg.get("keepalive_max_hours", 12) * 3600:
                t["status"] = "stopped"
                log(f"⏱ 保活到期自动停止：{t['title'] or t['work_id']}")
                _ka_persist()
                continue
            # 保活与主循环共用 cookie：登录刷新后自动跟上，不在这里触发登录
            ok, msg = _ka_do_post(t, cfg)
            t["last_post"] = time.time()
            t["last_msg"] = msg
            if ok:
                t["ok"] += 1
                t["fail"] = 0
                if t["ok"] == 1:
                    log(f"⏱ 作业保活已开始（每 {interval} 秒保存一次）：{t['title'] or t['work_id']}")
                elif t["ok"] % 30 == 0:
                    log(f"⏱ 保活正常：{t['title'] or t['work_id']} 已保存 {t['ok']} 次")
            else:
                t["fail"] += 1
                bad = any(w in msg for w in KA_END_WORDS)
                if bad:
                    t["status"] = "stopped"
                    log(f"⏱ 保活停止（{t['title'] or t['work_id']}）：{msg}")
                    _ka_persist()
                elif t["fail"] >= cfg.get("keepalive_max_fail", 5):
                    t["status"] = "stopped"
                    log(f"⚠️ 保活连续失败 {t['fail']} 次，已停止：{t['title'] or t['work_id']}（{msg}）")
                    _ka_persist()
                else:
                    log(f"⚠️ 保活保存失败（第 {t['fail']} 次）：{msg}")


def _ka_persist():
    """把“还在保活”的任务落盘，进程重启后可恢复。"""
    try:
        with _KA_LOCK:
            items = [{"work_url": t["work_url"], "title": t.get("title", ""),
                      "started": t["started"]}
                     for t in _KA_TASKS if t["status"] == "running"]
        with open(KEEPALIVE_PATH, "w", encoding="utf-8") as f:
            json.dump({"tasks": items,
                       "updated": datetime.now().isoformat(timespec="seconds")},
                      f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def start_keepalive(work_url, cfg, title=""):
    """对一个刚打开的作业入口做保活：解析 doWork 页 → 入队。
    失败只记日志，不影响主监控。"""
    if not cfg.get("keepalive_enabled", True):
        return
    if "workOrExam=exam" in (work_url or ""):
        return  # 考试页不保活（有自己的倒计时，重复保存无意义）
    try:
        _strip_proxy()
        req = urllib.request.Request(work_url, method="GET")
        req.add_header("User-Agent", HEADERS["User-Agent"])
        req.add_header("Referer", "https://notice.chaoxing.com/pc/notice/myNotice")
        req.add_header("Cookie", jar_to_header(_JAR))
        r = urllib.request.urlopen(req, timeout=20)
        html = r.read().decode("utf-8", "ignore")
        final_url = r.geturl()
    except Exception as e:
        log(f"⚠️ 保活：无法打开作业页面（{title or work_url}）：{type(e).__name__}: {e}")
        return
    task, err = _ka_parse(html, final_url, cfg)
    if not task:
        log(f"⚠️ 保活跳过（{title or work_url}）：{err}")
        return
    if _ka_add(task, cfg, work_url, title):
        log(f"⏱ 已接管作业保活：{task['title'] or title or task['work_id']}"
            f"（共 {len(task['qids'])} 题，间隔 {cfg.get('keepalive_interval', 60)} 秒）")
        _ka_persist()


def restore_keepalive(cfg):
    """进程启动时恢复上次未结束的保活任务。"""
    if not cfg.get("keepalive_enabled", True) or not os.path.exists(KEEPALIVE_PATH):
        return
    try:
        d = json.load(open(KEEPALIVE_PATH, encoding="utf-8"))
    except Exception:
        return
    items = d.get("tasks") or []
    if not items:
        return
    log(f"恢复 {len(items)} 个保活任务…")
    for it in items:
        if it.get("work_url"):
            start_keepalive(it["work_url"], cfg, it.get("title", ""))


# --------------------------------------------------------------------------
# 主监控循环
# --------------------------------------------------------------------------
def _advance_latest(state, notices):
    """把 state.latest_time / latest_uuid 推进到本轮见到的最大 insertTime。"""
    items = [it for it in notices if isinstance(it, dict)]
    times = [parse_time(it.get("insertTime")) for it in items]
    times = [x for x in times if x is not None]
    if not times:
        return
    cur_max = max(times)
    if state.get("latest_time") is None or cur_max > state["latest_time"]:
        state["latest_time"] = cur_max
        newest = max(items, key=lambda it: parse_time(it.get("insertTime")) or -1)
        state["latest_uuid"] = stable_id(newest)


def run_monitor(cfg, dry_run=False):
    global _SEEN_GLOBAL
    state = load_state()
    seen = load_seen()
    _SEEN_GLOBAL = seen
    label = _label_map.get(cfg["match_mode"], "通知")
    first_run = state.get("latest_time") is None
    exp = jwt_exp(jar_to_header(_JAR))
    if exp:
        log(f"当前会话有效期至：{datetime.fromtimestamp(exp).strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"开始监控（getNewNotices 为主，列表兜底；间隔 {cfg['refresh_interval']} 秒，Ctrl+C 退出）…")
    write_pid()  # 写入 PID 供看门狗健康检查/停止使用
    restore_keepalive(cfg)  # 恢复上次未结束的作业保活任务

    while True:
        try:
            resp = fetch_new(state.get("cursor"), cfg)
            notices, new_cursor = parse_new(resp)
            source = "getNewNotices"
            if new_cursor:
                state["cursor"] = new_cursor
            if not notices:
                # 取不到新规 → 回退完整列表
                data = fetch_list(cfg)
                notices = get_notice_list(data)
                source = "getNoticeList(兜底)"

            targets = collect_targets(notices, cfg)
            prev_latest = state.get("latest_time")

            if first_run:
                # 首次：仅缓存最新值，不打开任何历史通知
                _advance_latest(state, notices)
                first_run = False
                save_state(state)
                log(f"首次运行：已缓存最新值（insertTime≈{int(prev_latest) if prev_latest else state.get('latest_time')}），"
                    f"之后只打开更新的链接。")
                persist_jar()
                time.sleep(cfg["refresh_interval"])
                continue

            # 选出本轮回要打开的新项
            new_items = []
            for t in targets:
                if t["sid"] in seen:
                    continue
                # 完整列表兜底时，只打开严格比缓存最新值更新的项
                if source == "getNoticeList(兜底)" and prev_latest is not None \
                        and (t["time"] or 0) <= prev_latest:
                    continue
                new_items.append(t)

            if new_items:
                log(f"发现 {len(new_items)} 条新{label}（来源 {source}）：")
                for t in new_items[: cfg["max_open_per_cycle"]]:
                    log(f"  → {t['title']}\n    {t['url']}")
                    if not dry_run:
                        try:
                            webbrowser.open(t["url"])
                        except Exception as e:
                            log("  打开浏览器失败：", e)
                        # 打开后接管保活：每分钟对 doWork 页发一次保存请求
                        start_keepalive(t["url"], cfg, t["title"])
                    seen.add(t["sid"])
                save_seen(seen)
            else:
                log_idle(f"本次无新{label}（来源 {source}，返回 {len(notices)} 条通知）。")

            # 推进缓存最新值到本轮最大值（含全部通知，不只匹配项）
            _advance_latest(state, notices)
            save_state(state)
            persist_jar()
        except Exception as e:
            import traceback
            log("本轮出错（已跳过，继续监控）：", e)
            try:
                log(traceback.format_exc().splitlines()[-3:])
            except Exception:
                pass
        time.sleep(cfg["refresh_interval"])


def handle_sig(signum, frame):
    save_seen(_SEEN_GLOBAL)
    persist_jar()
    log("已保存进度，退出。")
    try:
        if os.path.exists(PID_PATH):
            os.remove(PID_PATH)
    except Exception:
        pass
    if LOGF is not None:
        try:
            LOGF.close()
        except Exception:
            pass
    sys.exit(0)


def main():
    global LOGF
    args = set(sys.argv[1:])
    # 健康检查/停止不需要联网与 cookie，优先处理
    if "--check" in args:
        do_check()
        return
    if "--stop" in args:
        do_stop()
        return
    if "--daemon" in args:
        do_daemon()
        return

    cfg = load_config()
    # 单实例互斥：占用 127.0.0.1:LOCK_PORT，已被占用则退出（避免跨会话多开）
    lock_sock = acquire_instance_lock()
    if lock_sock is None:
        # 不写日志（可能是正常重复启动），仅打印提示
        print(f"已有 monitor.py 实例在运行（端口 {LOCK_PORT} 被占用），本次退出。")
        sys.exit(0)
    signal.signal(signal.SIGINT, handle_sig)
    if hasattr(signal, "SIGTERM"):
        try:
            signal.signal(signal.SIGTERM, handle_sig)
        except Exception:
            pass
    try:
        LOGF = open(MONITOR_LOG_PATH, "a", encoding="utf-8", buffering=1)
    except Exception:
        LOGF = None

    # 初始化 cookie jar（优先 cookies.json，其次 .env 的 CHAO_XING_COOKIE，最后 config.cookie）
    init_jar(cfg)

    try:
        if "--seed" in args:
            do_seed(cfg)
            return
        if "--login" in args:
            do_login_cmd(cfg)
            return
        if "--new-once" in args:
            do_new_once(cfg)
            return
        if "--once" in args:
            do_once(cfg)
            return
        if "--keepalive" in args:
            i = sys.argv.index("--keepalive")
            do_keepalive_cmd(cfg, sys.argv[i + 1] if len(sys.argv) > i + 1 else "")
            return
        dry = "--dry-run" in args
        run_monitor(cfg, dry_run=dry)
    except Exception:
        import traceback
        log("未捕获异常，脚本退出：\n" + traceback.format_exc())
        raise
    finally:
        if LOGF is not None:
            try:
                LOGF.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
