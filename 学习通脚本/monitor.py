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

滑块验证码 + 显式 examcheck 请求：
  - 独立自检：--captcha-check [--captcha-count N]，只请求验证码服务，不访问考试或账户接口。
  - 流程：get/conf 取服务器时间 → 按官方前端派生 captchaKey/取图 token/iv →
    get/verification/image 的 token + imageVerificationVo.{shadeImage,cutoutImage} →
    check/verification/result；仅 result===true 且 extraData.validate 绑定本挑战才通过。
    失败重取新挑战，不复用已消费的 token，也不输出 token/validate。
  - 定位优先级：手动 captcha_x → 去描边的归一化像素匹配 → DeepSeek 视觉兜底。
    x 是透明滑块整图层的横向位移，不是可见缺口左缘或手柄中心；标准主题宽 320px。
    不做无依据的整列梯度猜测。低纹理、重复纹理和不匹配的图层返回失败。
  - 本地 JPEG/PNG 匹配需要可选 Pillow：python -m pip install -r requirements-captcha.txt；
    不安装时仅支持标准库 PNG 解码，JPEG 会尝试视觉兜底。常规通知监控仍只用标准库。
  - 视觉模型走 OpenAI 兼容的 /chat/completions，只发验证码图片，不带学习通 Cookie。
    captcha_vision="off" 可关闭视觉兜底；验证码图片落盘到被忽略的 captcha/ 便于核对。
  - 视觉凭据由环境加载，不写 config.json：VISION_API_KEY（或 DEEPSEEK_API_KEY）；
    默认 https://api.deepseek.com + deepseek-flash；可用 VISION_BASE_URL / VISION_MODEL 覆盖。
    --vision-check 仅验证视觉接口和合成图片，不能证明真实验证码通过。
  - 旧命令 --exam-submit 保留兼容，只显式调用、不参与监控；它会访问考试页及 examcheck，
    根据需要验证滑块并传回服务端 validate。examcheck 的最终业务语义未核实，
    status=true 只报告该接口通过，绝不据此宣称已交卷；过期/结束立即停止。
    不要为测试验证码而运行此命令。

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
  python monitor.py --captcha-check                         # 独立真实滑块验证，不访问考试
  python monitor.py --captcha-check --captcha-count 5        # 连续自检 5 组（最多 20 组）
  python monitor.py --vision-check                          # 仅自检视觉 API 和合成图片
  python monitor.py --exam-submit <考试页URL>                # 旧命令：显式请求 examcheck，非验证码自检
  python monitor.py --exam-submit <考试页URL> --exam-x 170   # 手动指定协议位移（不是可见左缘）

依赖：常规监控只用标准库；本地 JPEG 匹配建议安装 requirements-captcha.txt。

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
import hashlib
import io
import math
import uuid
import zlib
import struct
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
LOG_MAX_BYTES = 2 * 1024 * 1024  # 日志最多保留最近 2 MiB，避免全文件扫描导致内存峰值
SEEN_KEEP = 5000              # 只保留最近 5000 个已见通知 ID，限制常驻内存

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
    # ---- 考试交卷 + 滑块验证码（详见 exam_submit / captcha_solve）----
    "captcha_version": "1.1.22",
    "captcha_dir": "captcha",      # 验证码图片落盘目录（相对脚本目录）
    "captcha_scale": 1.0,          # 非标准主题的额外位移比例；标准 320px 主题保持 1，不影响手动 x
    "captcha_x": None,             # 手动协议位移；仅调试用，新挑战通常需要不同 x
    "captcha_max_try": 3,          # 每次调用最多获取的新挑战数
    # 像素匹配优先；视觉模型只作兜底（.env 填 VISION_API_KEY 默认走 DeepSeek）
    "captcha_vision": "auto",      # auto=本地无法匹配时调用；off=只用本地算法
    "vision_base_url": "",         # 留空= https://api.deepseek.com（非私密，可写这里）
    "vision_model": "",            # 留空= deepseek-flash（也可在 .env 里用 VISION_MODEL 覆盖）
    "captcha_vision_timeout": 25,  # 视觉接口超时（秒）
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
_LOG_LOCK = threading.RLock()
_CONSOLE_IDLE_LEN = 0  # 控制台心跳只占一行，避免滚屏累积


def _format_log_line(*args):
    ts = datetime.now().strftime("%H:%M:%S")
    return f"[{ts}] " + " ".join(str(a) for a in args)


def _write_log_line(line):
    with _LOG_LOCK:
        if LOGF is not None:
            try:
                LOGF.write(line + "\n")
                LOGF.flush()
            except Exception:
                pass
        trim_log(MONITOR_LOG_PATH)


def log(*args):
    global _CONSOLE_IDLE_LEN
    line = _format_log_line(*args)
    with _LOG_LOCK:
        if _CONSOLE_IDLE_LEN:
            print()  # 结束上一条原位更新的心跳行
            _CONSOLE_IDLE_LEN = 0
        print(line, flush=True)
        _write_log_line(line)


def trim_log(path, max_bytes=LOG_MAX_BYTES):
    """只在超限时保留日志尾部，避免每轮把完整日志读入内存。"""
    global LOGF
    temp_path = f"{path}.{os.getpid()}.tmp"
    reopen_log = False
    with _LOG_LOCK:
        try:
            if os.path.getsize(path) <= max_bytes:
                return
            reopen_log = LOGF is not None
            if reopen_log:
                try:
                    LOGF.flush()
                except Exception:
                    pass
                try:
                    LOGF.close()
                except Exception:
                    pass
                LOGF = None
            with open(path, "rb") as f:
                f.seek(-max_bytes, os.SEEK_END)
                tail = f.read(max_bytes)
            boundary = tail.find(b"\n")
            tail = tail[boundary + 1:] if boundary >= 0 else b""
            with open(temp_path, "wb") as f:
                f.write(tail)
            os.replace(temp_path, path)
        except Exception:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                pass
        finally:
            if reopen_log:
                try:
                    LOGF = open(path, "a", encoding="utf-8", buffering=1)
                except Exception:
                    LOGF = None


def log_idle(*args):
    """记录心跳并在控制台原位更新同一行；日志文件按大小限制。"""
    global _CONSOLE_IDLE_LEN
    line = _format_log_line(*args)
    with _LOG_LOCK:
        _write_log_line(line)
        if sys.stdout.isatty():
            padding = max(0, _CONSOLE_IDLE_LEN - len(line))
            print("\r" + line + " " * padding, end="", flush=True)
            _CONSOLE_IDLE_LEN = len(line)


# --------------------------------------------------------------------------
# 配置 & 状态
# --------------------------------------------------------------------------
def load_config(require_auth=True):
    """自检只读非认证配置；监控和业务命令默认仍要求账户来源。"""
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception as e:
            log("读取 config.json 失败，使用默认值:", e)
    if not require_auth:
        return cfg
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
                uuids = json.load(f).get("uuids", [])
            if isinstance(uuids, list):
                # dict 保留插入顺序，超限时可优先淘汰较早的 ID。
                if len(uuids) > SEEN_KEEP:
                    uuids = uuids[-SEEN_KEEP:]
                    _save_json(SEEN_PATH,
                               {"uuids": uuids,
                                "updated": datetime.now().isoformat(timespec="seconds")},
                               "seen.json")
                return dict.fromkeys(uuids, None)
        except Exception:
            pass
    return {}


def save_seen(seen):
    uuids = list(seen) if not isinstance(seen, dict) else list(seen.keys())
    _save_json(SEEN_PATH,
               {"uuids": uuids[-SEEN_KEEP:],
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
        # 已停止的任务仍持有整份答案表单；从全局队列移除，避免长期运行时累积。
        with _KA_LOCK:
            _KA_TASKS[:] = [task for task in _KA_TASKS if task["status"] == "running"]


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
# 滑块验证码。协议依据 https://captcha.chaoxing.com/load.min.js：
#   get/conf → 按服务器时间生成本轮参数 → get/verification/image
#   → shadeImage/cutoutImage → check/verification/result → extraData.validate
# x 是整张透明滑块图层的水平位移，不是缺口可见左缘，也不是鼠标手柄坐标。
# 验证码测试不需要登录态，也不调用任何考试接口。
# --------------------------------------------------------------------------
CAPTCHA_BASE = "https://captcha.chaoxing.com/captcha"
CAPTCHA_VERSION = "1.1.22"
EXAM_CAPTCHA_ID = "Ew0z9skxsLzVKQjmeObQiRVLxkxbPkRF"
EXAM_CHECK_PATH = "/exam-ans/exam/test/examcheck"
CAPTCHA_REFERER = "https://mooc1-api.chaoxing.com/exam-ans/exam/test/examcode/examnotes"


def _is_exam_url(url):
    """仅允许明确的 HTTPS 考试主机，避免把账户 Cookie 发给任意链接。"""
    try:
        p = urllib.parse.urlsplit(url)
        return (p.scheme == "https" and p.hostname in ("mooc1-api.chaoxing.com", "mooc1.chaoxing.com")
                and p.port in (None, 443) and p.username is None and p.password is None)
    except (TypeError, ValueError):
        return False


class _ExamRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _is_exam_url(newurl):
            raise ValueError("考试页跳转到不受支持的地址，已阻止转发 Cookie；请检查链接或刷新登录。")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _http_get(url, referer="", timeout=20):
    """GET 考试文本并更新 _JAR；初始目标与每次重定向都限制在考试主机。"""
    if not _is_exam_url(url):
        raise ValueError("仅支持 HTTPS 学习通考试主机，未发送账户 Cookie。")
    _strip_proxy()
    req = urllib.request.Request(url, method="GET")
    req.add_header("User-Agent", HEADERS["User-Agent"])
    req.add_header("Accept", "*/*")
    req.add_header("Accept-Language", "zh-CN,zh;q=0.9,en;q=0.8")
    req.add_header("Cookie", jar_to_header(_JAR))
    if referer:
        req.add_header("Referer", referer)
    r = urllib.request.build_opener(_ExamRedirectHandler()).open(req, timeout=timeout)
    raw = r.read().decode("utf-8", "ignore")
    update_jar_from_response(_JAR, r)
    return raw, r.geturl()


def _http_bytes(url, referer="", timeout=20):
    """GET 二进制。验证码图片在 captcha-b.chaoxing.com 上是公开静态资源，刻意不带 cookie。"""
    _strip_proxy()
    req = urllib.request.Request(url, method="GET")
    req.add_header("User-Agent", HEADERS["User-Agent"])
    req.add_header("Accept", "*/*")
    if referer:
        req.add_header("Referer", referer)
    r = urllib.request.urlopen(req, timeout=timeout)
    return r.read()


def _jsonp(raw):
    """解析 `cb({...})` / `cb({...});` / 纯 JSON；失败返回 None。"""
    s = (raw or "").strip()
    m = re.match(r"^[\w$.\-\[\]]+\s*\((.*)\)\s*;?\s*$", s, re.S)
    if m:
        s = m.group(1)
    try:
        return json.loads(s)
    except Exception:
        return None


def _qs(params):
    """拼查询串；冒号不转义（验证码 token 形如 md5:过期毫秒，服务端按冒号切分）。"""
    return "&".join(f"{k}={urllib.parse.quote(str(v), safe=':')}"
                    for k, v in params.items() if v is not None)


def _find_field(obj, *names):
    """在嵌套 dict/list 里按名字（忽略大小写）找第一个非空标量值。"""
    want = {n.lower() for n in names}
    stack = [obj]
    while stack:
        cur = stack.pop(0)
        if isinstance(cur, dict):
            for k, v in cur.items():
                if k.lower() in want and not isinstance(v, (dict, list)) and v not in (None, ""):
                    return v
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)
    return None


def _first_str(obj, *names):
    v = _find_field(obj, *names)
    return v if isinstance(v, str) and v else ""


def _need_captcha(data):
    """业务响应是否在索要验证码。"""
    if not isinstance(data, dict):
        return False
    for k in ("needVcode", "needValidate", "needCaptcha"):
        v = _find_field(data, k)
        if v not in (None, "") and str(v).lower() not in ("0", "false"):
            return True
    if _find_field(data, "captchaKey") and _find_field(data, "captchaId"):
        return True
    msg = str(_find_field(data, "msg", "errorMsg", "message") or "")
    return ("验证码" in msg) or ("验证失败" in msg)


def _exam_result_tag(data, raw=""):
    """examcheck 响应：ok 只表示该接口通过，不等于最终交卷。"""
    if not isinstance(data, dict):
        return "unknown"
    text = " ".join(str(data.get(k) or "") for k in ("msg", "message", "errorMsg"))
    if any(k in text for k in ("过期", "已结束", "已截止", "时间已到", "未开始", "不允许")):
        return "over"
    if _need_captcha(data):
        return "captcha"
    if any(k in text for k in ("已交卷", "已提交", "已经提交", "重复提交")):
        return "done"
    flags = [data.get(k) for k in ("status", "result", "success") if k in data]
    if any(v is True for v in flags) and not any(v is False for v in flags):
        return "ok"
    return "unknown"


def _captcha_call(path, params, referer, version=CAPTCHA_VERSION):
    """验证码服务不带账户 Cookie；只接受 JSON 对象响应。"""
    q = dict(params)
    q.update({"callback": "cx_captcha_function", "version": version,
              "_": str(int(time.time() * 1000))})
    raw = _http_bytes(f"{CAPTCHA_BASE}/{path}?{_qs(q)}", referer).decode("utf-8", "replace")
    data = _jsonp(raw)
    return (data if isinstance(data, dict) else {}), raw


def _captcha_parameters(cap_id, server_time, typ="slide"):
    """与官方前端一致；每个挑战使用独立 key、取图 token 和 iv。"""
    stamp = str(int(server_time))

    def md5(text):
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    key = md5(stamp + str(uuid.uuid4()))
    token = md5(stamp + cap_id + typ + key) + ":" + str(int(stamp) + 300000)
    iv = md5(cap_id + typ + str(int(time.time() * 1000)) + str(uuid.uuid4()))
    return {"captchaId": cap_id, "type": typ, "captchaKey": key, "token": token, "iv": iv}


def _captcha_validate(data, cap_id, challenge_token):
    """只接受 result===true 和服务端实际下发、绑定本挑战的 validate。"""
    if not isinstance(data, dict) or data.get("result") is not True:
        return ""
    if data.get("error") not in (None, 0, "0"):
        return ""
    extra = data.get("extraData")
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except (TypeError, ValueError):
            return ""
    value = extra.get("validate") if isinstance(extra, dict) else None
    expected = f"validate_{cap_id}_{challenge_token}"
    return value if isinstance(value, str) and value == expected else ""


def _b64_image(v):
    """base64（可带 data: 前缀）→ bytes；不像图片则返回空。"""
    if not isinstance(v, str) or len(v) < 64:
        return b""
    s = v.split(",", 1)[1] if v.startswith("data:") else v
    try:
        blob = base64.b64decode(s + "=" * (-len(s) % 4))
    except Exception:
        return b""
    return blob


def _image_bytes(v, referer=""):
    """get 下发的图片：base64 / data: 前缀 / http(s) URL 三种都取成字节。"""
    if isinstance(v, str) and v.startswith(("http://", "https://")):
        try:
            return _http_bytes(v, referer=referer)
        except Exception as e:
            log(f"⚠️ 下载验证码图片失败：{type(e).__name__}: {str(e)[:120]}")
            return b""
    return _b64_image(v)


def _png_decode(data):
    """最小 PNG 解码（8 位、非隔行、灰度/RGB/调色板/RGBA）。

    返回 (宽, 高, [(r,g,b), ...], [alpha, ...])；不支持就返回 None。
    只用标准库，避免为了滑块识别引入 Pillow 依赖。
    """
    if not data or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    pos, w, h, depth, color = 8, 0, 0, 8, 6
    palette, transparency, idat = b"", b"", []
    while pos + 12 <= len(data):
        ln = int.from_bytes(data[pos:pos + 4], "big")
        if pos + ln + 12 > len(data):
            return None
        typ = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + ln]
        pos += ln + 12
        if typ == b"IHDR":
            if ln != 13:
                return None
            w = int.from_bytes(body[0:4], "big")
            h = int.from_bytes(body[4:8], "big")
            depth, color = body[8], body[9]
            if body[12]:           # 隔行扫描（Adam7）不支持
                return None
        elif typ == b"PLTE":
            palette = body
        elif typ == b"tRNS":
            transparency = body
        elif typ == b"IDAT":
            idat.append(body)
        elif typ == b"IEND":
            break
    ch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color)
    if depth != 8 or not ch or w <= 0 or h <= 0:
        return None
    try:
        raw = zlib.decompress(b"".join(idat))
    except Exception:
        return None
    stride = w * ch
    if len(raw) < (stride + 1) * h:
        return None
    prev = bytearray(stride)
    px, alpha, i = [], [], 0
    for _ in range(h):
        f = raw[i]
        line = bytearray(raw[i + 1:i + 1 + stride])
        i += stride + 1
        if f == 1:                                  # Sub
            for x in range(ch, stride):
                line[x] = (line[x] + line[x - ch]) & 0xFF
        elif f == 2:                                # Up
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 0xFF
        elif f == 3:                                # Average
            for x in range(stride):
                a = line[x - ch] if x >= ch else 0
                line[x] = (line[x] + ((a + prev[x]) >> 1)) & 0xFF
        elif f == 4:                                # Paeth
            for x in range(stride):
                a = line[x - ch] if x >= ch else 0
                b = prev[x]
                c = prev[x - ch] if x >= ch else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (line[x] + pr) & 0xFF
        elif f != 0:
            return None
        prev = line
        if color == 3:                              # 调色板
            for x in range(w):
                k = line[x] * 3
                px.append((palette[k], palette[k + 1], palette[k + 2])
                          if k + 2 < len(palette) else (0, 0, 0))
                alpha.append(transparency[line[x]] if line[x] < len(transparency) else 255)
        elif color in (0, 4):                       # 灰度 / 灰度+alpha
            for x in range(w):
                g = line[x * ch]
                px.append((g, g, g))
                transparent = color == 0 and len(transparency) == 2 and g == int.from_bytes(transparency, "big")
                alpha.append(line[x * ch + 1] if color == 4 else (0 if transparent else 255))
        else:                                       # RGB / RGBA
            for x in range(w):
                o = x * ch
                rgb = (line[o], line[o + 1], line[o + 2])
                px.append(rgb)
                transparent = (color == 2 and len(transparency) == 6
                               and rgb == struct.unpack(">HHH", transparency))
                alpha.append(line[o + 3] if color == 6 else (0 if transparent else 255))
    return w, h, px, alpha


def _image_size(blob):
    """只读尺寸：PNG 看 IHDR，JPEG 扫 SOF 段。解不了像素时也能告诉模型画布多大。"""
    if not blob or len(blob) < 24:
        return None
    if blob[:8] == b"\x89PNG\r\n\x1a\n":
        w, h = struct.unpack(">II", blob[16:24])
        return (w, h) if w > 0 and h > 0 else None
    if blob[:2] != b"\xff\xd8":
        return None
    i, n = 2, len(blob)
    while i + 9 < n:
        if blob[i] != 0xFF:
            i += 1
            continue
        marker = blob[i + 1]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:   # 无长度字段
            i += 2
            continue
        seg = struct.unpack(">H", blob[i + 2:i + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                      0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h, w = struct.unpack(">HH", blob[i + 5:i + 9])
            return (w, h) if w > 0 and h > 0 else None
        i += 2 + seg
    return None


def _save_captcha_image(tag, blob, cfg):
    """把验证码图片落到 captcha/ 下，方便人工核对或手动量 x。"""
    if not blob:
        return ""
    d = cfg.get("captcha_dir") or "captcha"
    path_dir = d if os.path.isabs(d) else os.path.join(BASE_DIR, d)
    try:
        os.makedirs(path_dir, exist_ok=True)
        ext = ".jpg" if blob[:2] == b"\xff\xd8" else ".png"
        path = os.path.join(path_dir,
                            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{tag}{ext}")
        with open(path, "wb") as f:
            f.write(blob)
        return path
    except Exception as e:
        log(f"⚠️ 保存验证码图片失败：{e}")
        return ""


def _decode_image(blob):
    """可选 Pillow 支持 JPEG/完整 PNG；未安装时保留标准库 PNG 解码。"""
    try:
        from PIL import Image
    except ImportError:
        return _png_decode(blob)
    try:
        with Image.open(io.BytesIO(blob)) as image:
            image = image.convert("RGBA")
            pixels = list(image.get_flattened_data() if hasattr(image, "get_flattened_data")
                          else image.getdata())
            return (image.width, image.height, [p[:3] for p in pixels],
                    [p[3] for p in pixels])
    except (OSError, ValueError):
        return None


def _match_slider(bg, fg):
    """透明图层平移匹配，返回 (x, 相关系数)；低置信度/非等高条带返回 None。

    去掉两圈透明边界附近的描边，再做零均值归一化相关，避免黄框和缺口变暗
    干扰。保留透明留白的原始坐标，因此输出已经是协议要求的 strip 位移。
    """
    if not bg or not fg:
        return None
    w, h, px, _ = bg
    fw, fh, fpx, alpha = fg
    if fw >= w or fh != h:
        return None
    mask = {i for i, a in enumerate(alpha) if a > 128}
    for _ in range(2):
        mask = {i for i in mask if 0 < i % fw < fw - 1 and fw <= i < fw * (fh - 1)
                and all(j in mask for j in (i - 1, i + 1, i - fw, i + fw))}
    points = sorted(mask)
    if len(points) < 12:
        return None
    points = points[::max(1, (len(points) + 1199) // 1200)]
    n = len(points)
    values = [sum(fpx[i]) / 3.0 for i in points]
    mean = sum(values) / n
    centered = [v - mean for v in values]
    energy = sum(v * v for v in centered)
    if energy < n:                          # 平坦模板没有可识别的纹理
        return None
    offsets = [(i // fw) * w + i % fw for i in points]
    gray = [sum(p) / 3.0 for p in px]
    scores = []
    for x in range(w - fw + 1):
        values = [gray[i + x] for i in offsets]
        total = sum(values)
        variance = sum(v * v for v in values) - total * total / n
        if variance <= n:
            continue
        corr = sum(a * b for a, b in zip(centered, values)) / math.sqrt(energy * variance)
        scores.append((corr, x))
    if not scores:
        return None
    best, x = max(scores)
    other = max((s for s, pos in scores if abs(pos - x) > max(4, fw // 3)), default=-1.0)
    if best < 0.65 or best - other < 0.08:
        return None                         # 相似纹理重复/背景平坦时不胡猜
    return x, best


def _locate_gap(bg, fg=None):
    """返回滑块整图层的横向位移；没有匹配证据就返回 None。"""
    match = _match_slider(bg, fg)
    return match[0] if match else None


# --------------------------------------------------------------------------
# 视觉模型识别缺口位置（可选；.env 填了 VISION_API_KEY 即启用，默认走 DeepSeek）
#   只把验证码图片发给模型，绝不带学习通 cookie —— 避免登录态泄露给第三方。
# --------------------------------------------------------------------------
VISION_PROMPT = (
    "第一张是滑块验证码底图，宽 {w} 像素、高 {h} 像素，坐标从 0 开始。"
    "若附有第二张图，它是带透明留白的滑块图层，与底图纵向对齐。"
    "匹配两图的纹理，求把整个滑块图层向右平移多少像素才重合，记为 x。"
    "x 是图层位移，不是可见缺口左缘、滑块中心或鼠标手柄位置；不要忽略透明左边距。"
    "仅有底图时，返回目标缺口左缘。无法定位时返回 null。"
    '只输出一行 JSON：{{"x": 整数或null}}，不要解释。'
)


def _data_url(blob):
    mime = "image/jpeg" if blob[:2] == b"\xff\xd8" else "image/png"
    return f"data:{mime};base64," + base64.b64encode(blob).decode()


DEFAULT_VISION_BASE = "https://api.deepseek.com"
DEFAULT_VISION_MODEL = "deepseek-flash"


def _vision_config(cfg):
    """视觉模型配置；captcha_vision=off 或缺 key 时返回 None。

    base/model 默认走 DeepSeek（deepseek-flash 支持图片输入），
    所以只要在 .env 里填 VISION_API_KEY（或 DEEPSEEK_API_KEY）就能用。
    """
    if str(cfg.get("captcha_vision") or "auto").lower() == "off":
        return None

    def pick(name):                      # OS 环境变量优先，便于临时覆盖
        return (os.environ.get(name) or ENV.get(name) or "").strip()

    base = (pick("VISION_BASE_URL") or cfg.get("vision_base_url")
            or DEFAULT_VISION_BASE).rstrip("/")
    model = pick("VISION_MODEL") or cfg.get("vision_model") or DEFAULT_VISION_MODEL
    key = pick("VISION_API_KEY") or pick("DEEPSEEK_API_KEY")
    if not key:
        return None
    try:
        timeout = float(cfg.get("captcha_vision_timeout", 25) or 25)
    except (TypeError, ValueError):
        timeout = 25.0
    # deepseek-flash 是推理模型：默认先吐一大段 reasoning_content，max_tokens 一小就只剩
    # 空白 content。它认 thinking.type=disabled，关掉后 1 秒内直接给答案。
    no_thinking = urllib.parse.urlsplit(base).hostname == "api.deepseek.com" and model.startswith("deepseek")
    return {"base": base, "model": model, "key": key, "timeout": timeout,
            "no_thinking": no_thinking}


def _post_json(url, payload, headers, timeout=25):
    """POST JSON 并返回响应文本；刻意不带学习通 cookie。"""
    _strip_proxy()
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST")
    for k, v in headers.items():
        req.add_header(k, v)
    r = urllib.request.urlopen(req, timeout=timeout)
    return r.read().decode("utf-8", "ignore")


def _vision_reply_text(raw):
    """从 OpenAI 兼容响应里取 content；异常或报错返回空串。"""
    try:
        data = json.loads(raw)
    except Exception:
        return ""
    if not isinstance(data, dict) or data.get("error"):
        return ""
    choices = data.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return ""
    content = (choices[0].get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):        # 部分实现把 content 拆成段落
        return " ".join(p.get("text", "") for p in content
                        if isinstance(p, dict) and p.get("text"))
    return ""


def _x_from_text(text):
    """仅接受明确的 JSON 整数 x，绝不把解释里的候选数量当坐标。"""
    if not isinstance(text, str):
        return None
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return None
    value = data.get("x") if isinstance(data, dict) else None
    return value if type(value) is int else None


def _vision_locate_x(bg_bytes, fg_bytes, size, cfg):
    """让视觉模型看底图给出缺口 x；未配置或失败返回 None，由调用方回退本地算法。"""
    conf = _vision_config(cfg)
    if not conf or not bg_bytes:
        return None
    w = size[0] if size else 0
    h = size[1] if size else 0
    content = [{"type": "text",
                "text": VISION_PROMPT.format(w=w or "未知", h=h or "未知")},
               {"type": "image_url", "image_url": {"url": _data_url(bg_bytes)}}]
    if fg_bytes:
        content.append({"type": "image_url", "image_url": {"url": _data_url(fg_bytes)}})
    payload = {"model": conf["model"], "temperature": 0, "max_tokens": 512,
               "messages": [{"role": "user", "content": content}]}
    if conf.get("no_thinking"):
        payload["thinking"] = {"type": "disabled"}
    log(f"🧩 请求视觉模型（{conf['model']}）识别缺口位置…")
    try:
        raw = _post_json(conf["base"] + "/chat/completions", payload,
                         {"Content-Type": "application/json",
                          "Authorization": "Bearer " + conf["key"]},
                         conf["timeout"])
    except Exception as e:
        log(f"⚠️ 视觉模型调用失败：{type(e).__name__}: {str(e)[:160]}")
        return None
    text = _vision_reply_text(raw)
    if not text:
        log(f"⚠️ 视觉模型返回异常：{raw[:160]}")
        return None
    x = _x_from_text(text)
    if x is None or x < 0 or (w and x >= w):
        log(f"⚠️ 视觉模型没给出可用的 x：{text[:120]}")
        return None
    log(f"🧩 视觉模型判断缺口 x={x}（回复 {text[:60]}）")
    return x


def _probe_png(width=80, height=40):
    """造一张带缺口的灰度 PNG，供 --vision-check 自检（不依赖第三方库）。"""
    raw = bytearray()
    for y in range(height):
        raw.append(0)                       # 每行滤波方式：none
        for x in range(width):
            raw.append(30 if (40 <= x < 52 and 10 <= y < 30) else 200)

    def chunk(tag, data):
        return (len(data).to_bytes(4, "big") + tag + data
                + (zlib.crc32(tag + data) & 0xFFFFFFFF).to_bytes(4, "big"))

    ihdr = (width.to_bytes(4, "big") + height.to_bytes(4, "big")
            + bytes([8, 0, 0, 0, 0]))       # 8 位灰度，无隔行
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(raw))) + chunk(b"IEND", b""))


def captcha_solve(captcha, biz_url, cfg):
    """独立完成 slide 验证，返回服务端实际签发的完整 validate；失败返回空串。

    只需 captchaId。先取服务器时间，按官方前端派生全新取图参数；失败重取挑战，
    不复用已消费的图 token，也不把账户 Cookie 发给验证码或视觉服务。
    """
    cap_id = str(captcha.get("captchaId") or "")
    typ = str(captcha.get("type") or "slide")
    if not cap_id or typ != "slide":
        log("⚠️ 缺少 captchaId 或不是 slide 验证码，无法自动验证。")
        return ""
    base = urllib.parse.urlsplit(biz_url)
    referer = f"{base.scheme}://{base.netloc}{base.path}"
    version = cfg.get("captcha_version") or CAPTCHA_VERSION
    max_try = max(1, int(cfg.get("captcha_max_try", 3)))

    for attempt in range(1, max_try + 1):
        if attempt > 1:
            time.sleep(0.8)
        try:
            conf, _ = _captcha_call("get/conf", {"captchaId": cap_id}, referer, version)
            params = _captcha_parameters(cap_id, conf["t"], typ)
            data, _ = _captcha_call("get/verification/image", dict(params, referer=referer),
                                    referer, version)
            body = data.get("data") if isinstance(data.get("data"), dict) else data
            images = body.get("imageVerificationVo", body)
            if not isinstance(images, dict):
                raise ValueError("图片响应结构无效")
            # 字段均来自同一个响应对象，不递归混合外层业务 token/type。
            bg_value = next((images.get(k) for k in ("shadeImage", "image", "bgImage",
                             "bigImage", "backgroundImage", "backImage") if images.get(k)), None)
            fg_value = next((images.get(k) for k in ("cutoutImage", "smallImage", "sliceImage",
                             "cutImage", "sliderImage", "fgImage") if images.get(k)), None)
            challenge_token = body.get("token")
            bg_bytes = _image_bytes(bg_value, referer)
            fg_bytes = _image_bytes(fg_value, referer)
            size = _image_size(bg_bytes)
            if not isinstance(challenge_token, str) or not challenge_token or not size:
                log(f"⚠️ 取图缺少有效图片或挑战 token（第 {attempt}/{max_try} 次）。")
                continue
            bg = _decode_image(bg_bytes)
            fg = _decode_image(fg_bytes) if fg_bytes else None
            _save_captcha_image("bg", bg_bytes, cfg)
            _save_captcha_image("fg", fg_bytes, cfg)
            if not bg and bg_bytes[:2] == b"\xff\xd8":
                log("ℹ️ JPEG 本地匹配需要 Pillow：python -m pip install Pillow；本次尝试视觉兜底。")

            x = cfg.get("captcha_x")
            source = "手动指定"
            if x is None:
                x = _locate_gap(bg, fg)
                source = "像素匹配"
                if x is None:
                    x = _vision_locate_x(bg_bytes, fg_bytes, size, cfg)
                    source = "视觉模型"
                if x is not None:
                    # 官方标准主题固定 320 CSS 像素；手动 x 已是协议坐标，不重复缩放。
                    scale = 320.0 / size[0] * float(cfg.get("captcha_scale", 1.0))
                    x = int(math.floor(x * scale + 0.5))
            fg_size = _image_size(fg_bytes)
            max_x = 320 * (1 - fg_size[0] / size[0]) if fg_size else 319
            if type(x) is not int or not 0 <= x <= max_x:
                log(f"⚠️ 未能得到有效滑块位移（第 {attempt}/{max_try} 次），重取新挑战。")
                continue
            log(f"🧩 滑块 x={x}（{source}，第 {attempt}/{max_try} 次）")
            res, _ = _captcha_call("check/verification/result", {
                "captchaId": cap_id, "type": typ, "token": challenge_token,
                "coordinate": "[]", "runEnv": "10", "t": "c", "iv": params["iv"],
                "textClickArr": json.dumps([{"x": x}], separators=(",", ":")),
            }, referer, version)
            validate = _captcha_validate(res, cap_id, challenge_token)
            if validate:
                log("✅ 验证码服务端确认通过（result=true，已取得本挑战的 validate）。")
                return validate
            log(f"⚠️ 验证码未通过或缺少有效凭证（第 {attempt}/{max_try} 次）。")
        except (OSError, KeyError, TypeError, ValueError) as e:
            log(f"⚠️ 验证码请求/解析失败（{type(e).__name__}，第 {attempt}/{max_try} 次）。")
    return ""


def _exam_meta_from_page(html, url):
    """从考试页隐藏域（缺省回落到 URL query）取交卷需要的参数。"""
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)

    def pick(*names):
        for n in names:
            if q.get(n):
                return q[n][0]
        return ""

    return {
        "examId": _html_hidden(html, "examId") or pick("examId"),
        "courseId": _html_hidden(html, "courseId") or pick("courseId"),
        "classId": _html_hidden(html, "classId") or pick("classId"),
        "cpi": _html_hidden(html, "cpi") or pick("cpi"),
        "answerId": _html_hidden(html, "answerId") or pick("examAnswerId", "answerId"),
        "sdlkey": _html_hidden(html, "sdlkey"),
        "code": _html_hidden(html, "code"),
    }


def _exam_check_url(meta, biz_url, captchavalidate=""):
    """拼 examcheck 地址；把 /examcode/examnotes 换成 /examcheck。"""
    p = urllib.parse.urlsplit(biz_url)
    path = p.path
    for suffix in ("/examcode/examnotes", "/examnotes", "/examcode/"):
        if path.endswith(suffix):
            path = path[: -len(suffix)] + "/examcheck"
            break
    else:
        path = EXAM_CHECK_PATH
    return f"{p.scheme}://{p.netloc}{path}?" + _qs({
        "view": "json", "answerId": meta.get("answerId", ""),
        "examId": meta.get("examId", ""), "classId": meta.get("classId", ""),
        "courseId": meta.get("courseId", ""), "cpi": meta.get("cpi", ""),
        "code": meta.get("code", ""), "sdlkey": meta.get("sdlkey", ""),
        "facekey": "", "captchavalidate": captchavalidate, "_signcode": "",
    })


def exam_submit(exam_url, cfg, x_override=None):
    """兼容旧命令：请求 examcheck 并按需验证；返回该接口是否通过。

    业务语义未核实，不代表最终交卷。仅显式调用，不能用于验证码自检或监控循环。
    """
    if not exam_url:
        log("用法：python monitor.py --exam-submit <考试页URL> [--exam-x <滑块x>]")
        return False
    if x_override is not None:
        cfg = dict(cfg, captcha_x=x_override)
    log("开始请求 examcheck（该接口通过不代表最终交卷）。")
    try:
        html, final_url = _http_get(
            exam_url, referer="https://notice.chaoxing.com/pc/notice/myNotice")
    except Exception as e:
        log(f"⚠️ 打开考试页失败：{type(e).__name__}: {e}")
        return False
    if "passport" in final_url:
        log("⚠️ 打开考试页被跳到登录页：先跑 python monitor.py --login 刷新会话。")
        return False
    already = "/exam/test/look" in final_url
    if already:
        log("ℹ️ 已跳到答题记录页（/exam/test/look），继续查询服务端状态，不据此判定已提交。")

    meta = _exam_meta_from_page(html, final_url)
    miss = [k for k in ("examId", "courseId", "classId", "cpi", "answerId") if not meta.get(k)]
    if miss:
        log(f"⚠️ 考试页缺少参数 {miss}：可能还没点“开始考试”生成 answerId，或页面结构变了。")
        log(f"   解析结果：{meta}（页面 {len(html)} 字节，{final_url[:120]}）")
        return False
    log("考试参数：" + " ".join(f"{k}={meta[k]}" for k in
                            ("examId", "answerId", "classId", "courseId", "cpi")))

    validate = ""
    max_try = max(1, int(cfg.get("captcha_max_try", 3)))
    for attempt in range(max_try + 1):
        # 初始请求 + 每个成功凭证对应的一次最终请求；最后一次凭证也必须真正发出。
        if attempt == 0 or validate:
            url = _exam_check_url(meta, final_url, validate)
            try:
                raw, _ = _http_get(url, referer=final_url)
            except Exception as e:
                log(f"⚠️ examcheck 请求失败：{type(e).__name__}")
                return False
            data = _jsonp(raw)
            if not isinstance(data, dict):
                log("❌ examcheck 未返回 JSON 对象。")
                return False
        validate = ""
        kind = _exam_result_tag(data)
        msg = str(data.get("msg") or data.get("message") or "").strip()
        if kind == "ok":
            log("✅ examcheck 校验通过（不据此宣称最终交卷成功）。")
            return True
        if kind == "done":
            log("✅ 服务端明确提示已提交，无需重复操作。")
            return True
        if kind == "over":
            log(f"⏰ {msg or '考试已过期/已结束'}（停止请求）。")
            return False
        if kind != "captcha":
            log("❌ examcheck 未通过，且未要求滑块验证。")
            return False
        if attempt == max_try:
            break
        log(f"🧩 examcheck 需要滑块验证（第 {attempt + 1}/{max_try} 次）")
        context = data.get("captcha") or data.get("data") or data
        cap_id = context.get("captchaId") if isinstance(context, dict) else None
        captcha = {"captchaId": cap_id or EXAM_CAPTCHA_ID, "type": "slide"}
        validate = captcha_solve(captcha, final_url, dict(cfg, captcha_max_try=1))
    log("⚠️ 验证码重试次数用尽，examcheck 仍未通过。")
    return False


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
                    seen[t["sid"]] = None
                    while len(seen) > SEEN_KEEP:
                        seen.pop(next(iter(seen)))
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


def do_exam_submit_cmd():
    """CLI：--exam-submit <考试页URL> [--exam-x N]。一次性动作，不参与单实例互斥。"""
    global LOGF
    argv = sys.argv
    url, x = "", None
    i = argv.index("--exam-submit")
    if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
        url = argv[i + 1]
    if "--exam-x" in argv:
        j = argv.index("--exam-x")
        if j + 1 < len(argv):
            try:
                x = int(argv[j + 1])
            except ValueError:
                print("--exam-x 需要整数协议位移，不能填写小数或说明文字。")
                sys.exit(2)
        else:
            print("--exam-x 后缺少整数位移。")
            sys.exit(2)
    cfg = load_config()
    try:
        LOGF = open(MONITOR_LOG_PATH, "a", encoding="utf-8", buffering=1)
    except Exception:
        LOGF = None
    ok = False
    try:
        init_jar(cfg)
        ok = exam_submit(url, cfg, x)
    finally:
        if jar_to_header(_JAR):
            persist_jar()
        if LOGF is not None:
            try:
                LOGF.close()
            except Exception:
                pass
    sys.exit(0 if ok else 1)


def do_captcha_check_cmd():
    """CLI：独立验证验证码，不初始化账户会话、不请求任何考试接口。"""
    count = 1
    if "--captcha-count" in sys.argv:
        i = sys.argv.index("--captcha-count")
        try:
            count = int(sys.argv[i + 1])
        except (IndexError, ValueError):
            print("--captcha-count 需要 1 到 20 的整数。")
            sys.exit(2)
    if not 1 <= count <= 20 or "--exam-submit" in sys.argv:
        print("验证码自检最多 20 组，且不能与 --exam-submit 同时使用。")
        sys.exit(2)
    cfg = load_config(require_auth=False)
    passed = 0
    print("独立滑块验证：不携带账户 Cookie，不访问考试页或 examcheck。")
    for i in range(count):
        if i:
            time.sleep(1)
        print(f"\n--- 验证 {i + 1}/{count} ---")
        if captcha_solve({"captchaId": EXAM_CAPTCHA_ID}, CAPTCHA_REFERER, cfg):
            passed += 1
    print(f"\n服务端确认通过：{passed}/{count} 组（每组最多 {cfg.get('captcha_max_try', 3)} 次新挑战）。")
    sys.exit(0 if passed == count else 1)


def do_vision_check_cmd():
    """CLI：--vision-check。用一张合成的带缺口图片自检视觉 API 是否可用。"""
    cfg = load_config(require_auth=False)
    conf = _vision_config(cfg)
    if not conf:
        print('未启用视觉模型：请在 个人任务/.env 写一行 VISION_API_KEY（默认走 DeepSeek 的 '
              'deepseek-flash）；换别的服务再加 VISION_BASE_URL / VISION_MODEL，'
              '并确认 config.captcha_vision 不是 "off"。')
        sys.exit(1)
    print(f"视觉模型 {conf['model']} @ {conf['base']}，超时 {conf['timeout']:.0f}s")
    print("探针图 80x40，缺口左边缘在 x=40，只校验接口通不通、格式对不对。")
    x = _vision_locate_x(_probe_png(), None, (80, 40), cfg)
    if x is None:
        print("❌ 没拿到可用的 x，检查 base_url / key / model 是否为 OpenAI 兼容的图片接口。")
        sys.exit(1)
    print(f"✅ 视觉模型返回 x={x}（参考值 40，偏差 {abs(x - 40)} 像素）")
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
    # 自检不加载账户 Cookie，也不触碰考试状态。
    if "--captcha-check" in args:
        do_captcha_check_cmd()
        return
    # 兼容旧命令名；examcheck 的业务语义尚不能等同于最终交卷。
    if "--exam-submit" in args:
        do_exam_submit_cmd()
        return
    if "--vision-check" in args:
        do_vision_check_cmd()
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
