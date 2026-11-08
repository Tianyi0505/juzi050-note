# -*- coding: utf-8 -*-
"""examcheck + 滑块验证码相关离线测试（不联网、不依赖任何第三方库）。"""

import base64
import importlib.util
import json
import os
import shutil
import struct
import sys
import tempfile
import unittest
import zlib
from unittest.mock import patch
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
MONITOR_PATH = SCRIPT_DIR / "monitor.py"


def _chunk(tag, data):
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def make_png(width, height, rows, color_type=6, bit_depth=8):
    """手工拼 PNG；rows 为 [(filter, 该行原始字节)]，免去依赖 Pillow。"""
    raw = b"".join(bytes([f]) + bytes(data) for f, data in rows)
    ihdr = struct.pack(">IIBBBBB", width, height, bit_depth, color_type, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(raw)) + _chunk(b"IEND", b""))


def fake_jpeg(width, height):
    """只拼 SOI + APP0 + SOF0 的 JPEG 头，够 _image_size 读尺寸。"""
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof = (b"\xff\xc0" + struct.pack(">H", 15) + b"\x08"
           + struct.pack(">HH", height, width) + b"\x03" + b"\x01\x11\x00" * 3)
    return b"\xff\xd8" + app0 + sof + b"\xff\xd9"


def gray_png(grid, filters=None):
    """把二维灰度列表编成 8 位灰度 PNG。"""
    height, width = len(grid), len(grid[0])
    rows = []
    prev = [0] * width
    for y, row in enumerate(grid):
        f = filters[y] if filters else 0
        if f == 2:
            data = [(row[x] - prev[x]) & 0xFF for x in range(width)]
        elif f == 1:
            data = [(row[x] - (row[x - 1] if x else 0)) & 0xFF for x in range(width)]
        else:
            data = list(row)
        rows.append((f, data))
        prev = row
    return make_png(width, height, rows, color_type=0)


_MODULE = None
_TEMP = None


def load_monitor():
    """复制一份脚本到临时目录再加载，避免污染真实的 state/cookies。"""
    global _MODULE, _TEMP
    if _MODULE is not None:
        return _MODULE
    _TEMP = tempfile.TemporaryDirectory(prefix="exam-captcha-test-")
    isolated = Path(_TEMP.name) / "学习通脚本"
    isolated.mkdir()
    target = isolated / "monitor.py"
    shutil.copyfile(MONITOR_PATH, target)
    spec = importlib.util.spec_from_file_location("monitor_exam_test", str(target))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _MODULE = module
    return module


class ExamCaptchaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory(prefix="exam-captcha-tmp-")
        cls.addClassCleanup(cls.temp_dir.cleanup)
        cls.m = load_monitor()

    def setUp(self):
        # 即使 mock 漏配，也不能意外使用真实网络或账户。
        for name in ("_http_get", "_http_bytes", "_post_json"):
            p = patch.object(self.m, name, side_effect=AssertionError("离线测试禁止网络"))
            p.start()
            self.addCleanup(p.stop)

    # ---------------- 响应解析 ----------------
    def test_jsonp_accepts_callback_and_plain_json(self):
        self.assertEqual(self.m._jsonp('cx_captcha_function({"a": 1});'), {"a": 1})
        self.assertEqual(self.m._jsonp('cb[0]({"a": 2})'), {"a": 2})
        self.assertEqual(self.m._jsonp('{"a": 3}'), {"a": 3})
        self.assertIsNone(self.m._jsonp("not json"))
        self.assertIsNone(self.m._jsonp(""))

    def test_qs_keeps_colon_and_encodes_specials(self):
        q = self.m._qs({"token": "abc:1793931104910",
                        "r": "https://a.com/p",
                        "skip": None})
        self.assertIn("token=abc:1793931104910", q)
        self.assertIn("r=https:%2F%2Fa.com%2Fp", q)
        self.assertNotIn("skip", q)

    def test_find_field_walks_nested_and_ignores_case(self):
        data = {"a": [{"CaptchaId": "cid"}], "b": {"captchaKey": "key", "n": 0}}
        self.assertEqual(self.m._find_field(data, "captchaid"), "cid")
        self.assertEqual(self.m._first_str(data, "CAPTCHAKEY"), "key")
        self.assertEqual(self.m._find_field(data, "missing"), None)

    def test_need_captcha_shapes(self):
        need = self.m._need_captcha
        self.assertTrue(need({"needVcode": True}))
        self.assertTrue(need({"data": {"needVcode": "1"}}))
        self.assertTrue(need({"captchaId": "x", "captchaKey": "y"}))
        self.assertTrue(need({"msg": "请输入验证码"}))
        self.assertFalse(need({"needVcode": 0}))
        self.assertFalse(need({"status": False, "msg": "已交卷"}))
        self.assertFalse(need({"needVcode": "false"}))
        self.assertFalse(need(None))

    # ---------------- PNG 解码 ----------------
    def test_png_decode_rgba(self):
        pixels = [(255, 0, 0, 255), (0, 255, 0, 128),
                  (0, 0, 255, 255), (1, 2, 3, 0)]
        rows = []
        for y in range(2):
            data = b"".join(bytes(pixels[y * 2 + x]) for x in range(2))
            rows.append((0, data))
        got = self.m._png_decode(make_png(2, 2, rows))
        self.assertIsNotNone(got)
        w, h, px, alpha = got
        self.assertEqual((w, h), (2, 2))
        self.assertEqual(px[0], (255, 0, 0))
        self.assertEqual(px[2], (0, 0, 255))
        self.assertEqual(alpha, [255, 128, 255, 0])

    def test_png_decode_gray_with_up_and_sub_filters(self):
        grid = [[5, 6], [7, 8]]
        got = self.m._png_decode(gray_png(grid, filters=[0, 2]))
        self.assertEqual(got[0], 2)
        self.assertEqual([p[0] for p in got[2]], [5, 6, 7, 8])
        got = self.m._png_decode(gray_png(grid, filters=[0, 1]))
        self.assertEqual([p[0] for p in got[2]], [5, 6, 7, 8])

    def test_png_decode_rejects_non_png(self):
        self.assertIsNone(self.m._png_decode(b"not a png"))
        self.assertIsNone(self.m._png_decode(b""))
        self.assertIsNone(self.m._png_decode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20))

    def test_image_size_reads_png_and_jpeg_headers(self):
        m = self.m
        png = make_png(12, 7, [(0, bytes([1, 2, 3]) * 12)] * 7, color_type=2)
        self.assertEqual(m._image_size(png), (12, 7))
        self.assertEqual(m._image_size(fake_jpeg(320, 160)), (320, 160))
        self.assertIsNone(m._image_size(b"not an image"))
        self.assertIsNone(m._image_size(b""))

    # ---------------- 缺口定位 ----------------
    def test_locate_gap_finds_left_edge_of_notch(self):
        width, height, notch = 260, 60, (120, 180)
        rows = []
        for y in range(height):
            line = b""
            for x in range(width):
                inside = notch[0] <= x < notch[1] and 20 <= y < 40
                g = 0 if inside else 128
                line += bytes([g, g, g])
            rows.append((0, line))
        bg = self.m._png_decode(make_png(width, height, rows, color_type=2))
        # 没有图层匹配证据时不再靠整列梯度猜缺口。
        self.assertIsNone(self.m._locate_gap(bg))

    def test_locate_gap_uses_slider_template_when_available(self):
        width, height, left = 200, 40, 90

        def row_bytes(fn):
            return b"".join(bytes(fn(x)) for x in range(width))

        def bg_px(x, y):
            if left <= x < left + 10:
                v = ((x - left) * 47 + y * 23 + (x - left) * y * 11) % 230 + 10
            else:
                v = 0
            return (v, v, v)

        bg_rows = [(0, row_bytes(lambda x: bg_px(x, y))) for y in range(height)]
        bg = self.m._png_decode(make_png(width, height, bg_rows, color_type=2))

        fw, fh = 10, height
        fg_rows = []
        for y in range(fh):
            line = b""
            for x in range(fw):
                v = (x * 47 + y * 23 + x * y * 11) % 230 + 10
                line += bytes([v, v, v, 255])
            fg_rows.append((0, line))
        fg = self.m._png_decode(make_png(fw, fh, fg_rows, color_type=6))
        x = self.m._locate_gap(bg, fg)
        self.assertIsNotNone(x)
        self.assertLessEqual(abs(x - left), 1, "模板匹配应对齐到 %s，实际 %s" % (left, x))

    def test_locate_gap_returns_none_on_flat_image(self):
        rows = [(0, bytes([100] * 3 * 20)) for _ in range(10)]
        bg = self.m._png_decode(make_png(20, 10, rows, color_type=2))
        self.assertIsNone(self.m._locate_gap(bg))

    # ---------------- 交卷参数 ----------------
    def test_meta_prefers_hidden_inputs(self):
        html = ('<input type="hidden" id="answerId" name="answerId" value="501"/>'
                '<input type="hidden" name="examId" value="502"/>'
                '<input type="hidden" name="classId" value="503"/>'
                '<input type="hidden" name="courseId" value="504"/>'
                '<input type="hidden" name="cpi" value="505"/>')
        meta = self.m._exam_meta_from_page(
            html, "https://mooc1-api.chaoxing.com/exam-ans/exam/test/examcode/examnotes")
        self.assertEqual(meta["answerId"], "501")
        self.assertEqual(meta["examId"], "502")
        self.assertEqual(meta["cpi"], "505")

    def test_meta_falls_back_to_query(self):
        url = ("https://mooc1-api.chaoxing.com/exam-ans/exam/test/examcode/examnotes"
               "?examId=502&courseId=504&classId=503&cpi=505")
        meta = self.m._exam_meta_from_page("<html></html>", url)
        self.assertEqual(meta["examId"], "502")
        self.assertEqual(meta["classId"], "503")

    def test_exam_check_url_rewrites_path(self):
        meta = {"examId": "1", "courseId": "2", "classId": "3", "cpi": "4",
                "answerId": "5", "code": "", "sdlkey": ""}
        biz = "https://mooc1-api.chaoxing.com/exam-ans/exam/test/examcode/examnotes?x=1"
        url = self.m._exam_check_url(meta, biz, "validate_CID_TOKEN")
        self.assertTrue(url.startswith(
            "https://mooc1-api.chaoxing.com/exam-ans/exam/test/examcheck?"), url)
        self.assertNotIn("examnotes", url)
        q = dict(p.split("=", 1) for p in url.split("?", 1)[1].split("&"))
        self.assertEqual(q["view"], "json")
        self.assertEqual(q["answerId"], "5")
        self.assertEqual(q["captchavalidate"], "validate_CID_TOKEN")
        self.assertEqual(q["_signcode"], "")

    # ---------------- 边界行为 ----------------
    def test_captcha_solve_rejects_incomplete_params(self):
        self.assertEqual(self.m.captcha_solve({}, "https://a/p", {}), "")
        self.assertEqual(self.m.captcha_solve(
            {"captchaId": "id", "type": "click"}, "https://a/p", {}), "")

    def test_exam_submit_without_url_returns_false(self):
        self.assertFalse(self.m.exam_submit("", {}))

    def test_save_captcha_image_writes_file(self):
        cfg = {"captcha_dir": str(Path(self.temp_dir.name) / "captcha")}
        path = self.m._save_captcha_image(
            "bg", make_png(1, 1, [(0, bytes([0, 0, 0, 255]))]), cfg)
        self.assertTrue(path and Path(path).is_file())
        self.assertEqual(self.m._save_captcha_image("x", b"", cfg), "")

    def test_b64_image_decodes_data_url(self):
        blob = make_png(1, 1, [(0, bytes([0, 0, 0, 255]))])
        encoded = base64.b64encode(blob).decode()
        self.assertEqual(self.m._b64_image(encoded), blob)
        self.assertEqual(self.m._b64_image("data:image/png;base64," + encoded), blob)
        self.assertEqual(self.m._b64_image("short"), b"")

    def test_image_bytes_handles_url_and_base64(self):
        m = self.m
        blob = make_png(1, 1, [(0, bytes([0, 0, 0, 255]))])
        seen = []

        def fake_get(url, referer="", timeout=20):
            seen.append((url, referer))
            return blob

        old = m._http_bytes
        m._http_bytes = fake_get
        try:
            url = "https://captcha-b.chaoxing.com/slide/big/3C15.jpg?t=20763"
            self.assertEqual(m._image_bytes(url, "https://mooc1-api.chaoxing.com/"), blob)
            self.assertEqual(seen, [(url, "https://mooc1-api.chaoxing.com/")])
            # base64 走原路，不发请求
            self.assertEqual(m._image_bytes(base64.b64encode(blob).decode()), blob)
            self.assertEqual(len(seen), 1)
        finally:
            m._http_bytes = old


    @staticmethod
    def _exam_page():
        return ''.join('<input type="hidden" name="%s" value="%s"/>' % (k, v)
                       for k, v in (("answerId", "1"), ("examId", "2"), ("classId", "3"),
                                    ("courseId", "4"), ("cpi", "5")))

    def test_exam_submit_retries_with_captcha_validate(self):
        """真实响应层级的 mock：max_try=1 时最后一次凭证也必须用于 examcheck。"""
        m = self.m
        biz = "https://mooc1-api.chaoxing.com/exam-ans/exam/test/examcode/examnotes"
        calls, cap_calls = [], []
        png = base64.b64encode(gray_png([[100] * 320] * 160)).decode()

        def fake_get(url, referer="", timeout=20):
            calls.append(url)
            if "examcode/examnotes" in url:
                return self._exam_page(), url
            if "captchavalidate=validate_CID_CHALLENGE" in url:
                return '{"status":true}', url
            return ('{"status":true,"needVcode":true,"token":"OUTER","type":"exam",'
                    '"captcha":{"captchaId":"CID","type":"slide"}}'), url

        def fake_cap(path, params, referer, version):
            cap_calls.append((path, params))
            if path == "get/conf":
                return {"t": "1800000000000"}, "{}"
            if path == "get/verification/image":
                self.assertNotEqual(params["token"], "OUTER")
                self.assertEqual(params["type"], "slide")
                return {"token": "CHALLENGE", "imageVerificationVo": {"shadeImage": png}}, "{}"
            self.assertEqual(params["token"], "CHALLENGE")
            self.assertEqual(params["iv"], cap_calls[1][1]["iv"])
            return {"result": True, "error": 0,
                    "extraData": '{"validate":"validate_CID_CHALLENGE"}'}, "{}"

        cfg = {"captcha_x": 170, "captcha_max_try": 1, "captcha_dir": self.temp_dir.name}
        with patch.object(m, "_http_get", fake_get), patch.object(m, "_captcha_call", fake_cap):
            self.assertTrue(m.exam_submit(biz, cfg))
        self.assertEqual(len(calls), 3)
        self.assertIn("captchavalidate=validate_CID_CHALLENGE", calls[-1])
        self.assertEqual([p for p, _ in cap_calls],
                         ["get/conf", "get/verification/image", "check/verification/result"])
        self.assertEqual(cap_calls[-1][1]["textClickArr"], '[{"x":170}]')

    def test_exam_submit_sends_validate_even_if_only_last_attempt_succeeds(self):
        m = self.m
        calls = []

        def fake_get(url, referer="", timeout=20):
            calls.append(url)
            if "examcode/examnotes" in url:
                return self._exam_page(), url
            return ('{"status":true}' if "validate_CID_FINAL" in url
                    else '{"status":false,"needVcode":true}'), url

        with patch.object(m, "_http_get", fake_get), patch.object(
                m, "captcha_solve", side_effect=["", "", "validate_CID_FINAL"]) as solve:
            self.assertTrue(m.exam_submit(
                "https://example.com/examcode/examnotes", {"captcha_max_try": 3}))
        self.assertEqual(solve.call_count, 3)
        self.assertEqual(len(calls), 3)  # 中间验证码失败时不反复请求业务接口
        self.assertIn("validate_CID_FINAL", calls[-1])

    def test_exam_submit_stops_when_captcha_fails(self):
        m = self.m

        def fake_get(url, referer="", timeout=20):
            if "examcode/examnotes" in url:
                return self._exam_page(), url
            return '{"status": false, "needVcode": true}', url

        with patch.object(m, "_http_get", fake_get), patch.object(m, "captcha_solve", return_value="") as solve:
            self.assertFalse(m.exam_submit(
                "https://example.com/examcode/examnotes", {"captcha_max_try": 2}))
        self.assertEqual(solve.call_count, 2)
        self.assertEqual(solve.call_args.args[0], {"captchaId": m.EXAM_CAPTCHA_ID, "type": "slide"})

    def test_captcha_solve_refreshes_parameters_after_failed_check(self):
        m = self.m
        calls = []
        png = base64.b64encode(gray_png([[100] * 320] * 160)).decode()

        def fake_cap(path, params, referer, version):
            calls.append((path, params))
            n = sum(p == "get/conf" for p, _ in calls)
            if path == "get/conf":
                return {"t": 1800000000000 + n}, "{}"
            if path == "get/verification/image":
                return {"token": "IMAGE%d" % n,
                        "imageVerificationVo": {"shadeImage": png}}, "{}"
            self.assertEqual(params["token"], "IMAGE%d" % n)
            self.assertEqual(params["iv"], calls[-2][1]["iv"])
            if n == 1:
                return {"status": True, "result": False, "token": "DO_NOT_REUSE"}, "{}"
            return {"result": True, "extraData": {"validate": "validate_CID_IMAGE2"}}, "{}"

        cfg = {"captcha_x": 0, "captcha_max_try": 2, "captcha_scale": 2,
               "captcha_dir": self.temp_dir.name}
        with patch.object(m, "_captcha_call", fake_cap), patch.object(m.time, "sleep"):
            self.assertEqual(m.captcha_solve({"captchaId": "CID"}, "https://example.com/p", cfg),
                             "validate_CID_IMAGE2")
        gets = [p for path, p in calls if path == "get/verification/image"]
        self.assertNotEqual(gets[0]["captchaKey"], gets[1]["captchaKey"])
        self.assertNotEqual(gets[0]["iv"], gets[1]["iv"])
        self.assertNotEqual(gets[0]["token"], gets[1]["token"])
        self.assertEqual(calls[-1][1]["textClickArr"], '[{"x":0}]')

    def test_captcha_call_uses_cookie_free_binary_transport(self):
        m = self.m
        with patch.object(m, "_http_bytes", return_value=b'cx_captcha_function({"t":123})') as get:
            self.assertEqual(m._captcha_call("get/conf", {}, "https://example.com")[0], {"t": 123})
        self.assertIn("/captcha/get/conf?", get.call_args.args[0])
        self.assertNotIn("/v1/", get.call_args.args[0])


VISION_ENV = {"VISION_BASE_URL": "https://vision.example.com/v1/",
              "VISION_API_KEY": "sk-test",
              "VISION_MODEL": "test-vl"}


class VisionLocateTests(unittest.TestCase):
    """视觉模型识别滑块位置：全部 mock，不联网。"""

    @classmethod
    def setUpClass(cls):
        cls.m = load_monitor()

    def setUp(self):
        m = self.m
        old_env = m.ENV
        m.ENV = dict(VISION_ENV)
        self.addCleanup(setattr, m, "ENV", old_env)
        saved = {k: os.environ.pop(k) for k in
                 ("VISION_BASE_URL", "VISION_API_KEY", "VISION_MODEL",
                  "DEEPSEEK_API_KEY")
                 if k in os.environ}          # 防止本机环境变量干扰用例
        self.addCleanup(os.environ.update, saved)
        self.temp_dir = tempfile.TemporaryDirectory(prefix="vision-tmp-")
        self.addCleanup(self.temp_dir.cleanup)

    def _patch(self, name, value):
        m = self.m
        old = getattr(m, name)
        setattr(m, name, value)
        self.addCleanup(setattr, m, name, old)

    def _fake_post(self, reply):
        calls = []

        def fake(url, payload, headers, timeout=25):
            calls.append({"url": url, "payload": payload, "headers": headers})
            if isinstance(reply, Exception):
                raise reply
            return reply

        self._patch("_post_json", fake)
        return calls

    @staticmethod
    def _reply(content):
        return json.dumps({"choices": [{"message": {"content": content}}]})

    @staticmethod
    def _bg():
        return make_png(2, 2, [(0, bytes([10, 10, 10]) * 2)] * 2, color_type=2)

    def test_config_only_requires_key_and_defaults_to_deepseek(self):
        m = self.m
        self.assertIsNone(m._vision_config({"captcha_vision": "off"}))
        m.ENV = {}
        self.assertIsNone(m._vision_config({}))          # 没有 key 就不启用
        m.ENV = {"VISION_API_KEY": "sk-test"}
        conf = m._vision_config({})
        self.assertEqual(conf["base"], "https://api.deepseek.com")   # 默认 DeepSeek
        self.assertEqual(conf["model"], "deepseek-flash")
        self.assertTrue(conf["no_thinking"])                         # 关掉推理，一次返回答案
        m.ENV = dict(VISION_ENV)
        conf = m._vision_config({})
        self.assertEqual(conf["base"], "https://vision.example.com/v1")
        self.assertEqual(conf["model"], "test-vl")
        self.assertEqual(conf["key"], "sk-test")
        self.assertEqual(conf["timeout"], 25)
        self.assertFalse(conf["no_thinking"])                        # 别家不猜它的私有参数

    def test_locate_x_disables_thinking_only_on_deepseek(self):
        m = self.m
        m.ENV = {"VISION_API_KEY": "sk-test"}
        calls = self._fake_post(self._reply('{"x": 192}'))
        self.assertEqual(m._vision_locate_x(self._bg(), None, (320, 160), {}), 192)
        self.assertEqual(calls[0]["url"], "https://api.deepseek.com/chat/completions")
        self.assertEqual(calls[0]["payload"]["thinking"], {"type": "disabled"})

    def test_locate_x_posts_openai_compatible_request(self):
        m = self.m
        calls = self._fake_post(self._reply('{"x": 137}'))
        self.assertEqual(m._vision_locate_x(self._bg(), None, (260, 60), {}), 137)
        call = calls[0]
        self.assertEqual(call["url"], "https://vision.example.com/v1/chat/completions")
        self.assertEqual(call["payload"]["model"], "test-vl")
        self.assertEqual(call["headers"]["Authorization"], "Bearer sk-test")
        # 安全底线：只发验证码图片，绝不把学习通 cookie 送给第三方
        self.assertNotIn("Cookie", call["headers"])
        self.assertNotIn("thinking", call["payload"])   # 非 DeepSeek 不乱加参数
        content = call["payload"]["messages"][0]["content"]
        self.assertIn("260", content[0]["text"])
        self.assertTrue(content[1]["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_locate_x_attaches_slider_image_when_given(self):
        m = self.m
        calls = self._fake_post(self._reply('{"x": 20}'))
        fg = make_png(2, 2, [(0, bytes([200, 0, 0, 255]) * 2)] * 2)
        self.assertEqual(m._vision_locate_x(self._bg(), fg, (260, 60), {}), 20)
        content = calls[0]["payload"]["messages"][0]["content"]
        self.assertEqual(len(content), 3)               # 文字 + 底图 + 滑块图

    def test_locate_x_rejects_out_of_range_and_garbage(self):
        m = self.m
        self._fake_post(self._reply('{"x": 999}'))
        self.assertIsNone(m._vision_locate_x(self._bg(), None, (260, 60), {}))
        m._post_json = lambda *a, **k: "not json"
        self.assertIsNone(m._vision_locate_x(self._bg(), None, (260, 60), {}))
        m._post_json = lambda *a, **k: '{"choices": []}'
        self.assertIsNone(m._vision_locate_x(self._bg(), None, (260, 60), {}))
        m._post_json = lambda *a, **k: '{"error": {"message": "boom"}}'
        self.assertIsNone(m._vision_locate_x(self._bg(), None, (260, 60), {}))

    def test_locate_x_survives_http_error(self):
        m = self.m
        self._fake_post(OSError("connection reset"))
        self.assertIsNone(m._vision_locate_x(self._bg(), None, (260, 60), {}))

    def test_reply_text_handles_segmented_content(self):
        m = self.m
        raw = json.dumps({"choices": [{"message": {"content": [
            {"type": "text", "text": '{"x":'},
            {"type": "text", "text": " 42}"}]}}]})
        self.assertEqual(m._x_from_text(m._vision_reply_text(raw)), 42)

    def test_captcha_solve_prefers_pixel_match_over_vision(self):
        m = self.m
        used = []

        def fake_vision(*args, **kwargs):
            used.append("vision")
            return 111

        def fake_local(*args, **kwargs):
            used.append("local")
            return 222

        self._patch("_vision_locate_x", fake_vision)
        self._patch("_locate_gap", fake_local)
        self._run_solve(expect_x=222)
        self.assertEqual(used, ["local"])

    def test_captcha_solve_falls_back_to_vision(self):
        m = self.m
        used = []

        def fake_vision(*args, **kwargs):
            used.append("vision")
            return 111

        def fake_local(*args, **kwargs):
            used.append("local")
            return None

        self._patch("_vision_locate_x", fake_vision)
        self._patch("_locate_gap", fake_local)
        self._run_solve(expect_x=111)
        self.assertEqual(used, ["local", "vision"])

    def _run_solve(self, expect_x=111):
        m = self.m
        png = base64.b64encode(gray_png([[100] * 320] * 160)).decode()
        calls = []

        def fake_call(path, params, referer, version="1.1.22"):
            calls.append((path, params))
            if path == "get/conf":
                return {"t": 1800000000000}, "{}"
            if path == "get/verification/image":
                return {"imageVerificationVo": {"shadeImage": png}, "token": "IMGTOKEN"}, "{}"
            return {"result": True, "extraData": '{"validate":"validate_CID_IMGTOKEN"}'}, "{}"

        self._patch("_captcha_call", fake_call)
        cfg = {"captcha_dir": str(Path(self.temp_dir.name) / "captcha")}
        validate = m.captcha_solve({"captchaId": "CID"},
                                   "https://mooc1-api.chaoxing.com/exam-ans/exam/test/examcode/examnotes",
                                   cfg)
        self.assertEqual(validate, "validate_CID_IMGTOKEN")
        check = [p for path, p in calls if path == "check/verification/result"][0]
        self.assertEqual(check["textClickArr"], '[{"x":%d}]' % expect_x)


    def test_probe_png_is_decodable_and_has_notch_at_40(self):
        m = self.m
        blob = m._probe_png()
        decoded = m._png_decode(blob)
        self.assertIsNotNone(decoded)
        self.assertEqual(decoded[:2], (80, 40))
        self.assertEqual(decoded[2][10 * 80 + 40], (30, 30, 30))
        self.assertEqual(decoded[2][10 * 80 + 39], (200, 200, 200))
        self.assertIsNone(m._locate_gap(decoded))  # 没有滑块模板不能据此证明真实识别能力


    def test_exam_result_tag(self):
        m = self.m
        self.assertEqual(m._exam_result_tag({"status": True}), "ok")
        self.assertEqual(m._exam_result_tag({"msg": "您已交卷", "status": False}), "done")
        self.assertEqual(m._exam_result_tag({"msg": "提示：考试已过期", "status": False}), "over")
        self.assertEqual(m._exam_result_tag({"msg": "考试已结束", "status": False}), "over")
        self.assertEqual(m._exam_result_tag({"msg": "系统繁忙", "status": False}), "unknown")
        self.assertEqual(m._exam_result_tag(None), "unknown")
        self.assertEqual(m._exam_result_tag({"status": True, "needVcode": True}), "captcha")
        self.assertEqual(m._exam_result_tag({"status": True, "result": False}), "unknown")
        self.assertEqual(m._exam_result_tag({"status": True, "msg": "已过期"}), "over")

    def test_x_parser_rejects_unrelated_numbers_and_non_integer_answers(self):
        m = self.m
        for text in ('I see 2 candidates but cannot locate the gap', '{"x":12.5}',
                     '{"x":true}', '{"x":"12"}', '{"x":null}', '12', 'x=12'):
            self.assertIsNone(m._x_from_text(text), text)
        self.assertEqual(m._x_from_text('```json\n{"x": 12}\n```'), 12)

    def test_deepseek_options_require_exact_host(self):
        self.m.ENV = dict(VISION_ENV, VISION_BASE_URL="https://api.deepseek.com.example.org",
                          VISION_MODEL="deepseek-flash")
        self.assertFalse(self.m._vision_config({})["no_thinking"])

    def _run_exam_with_look_page(self, check_body):
        m = self.m
        calls = []
        page = ('<input type="hidden" name="answerId" value="501"/>'
                '<input type="hidden" name="examId" value="502"/>'
                '<input type="hidden" name="classId" value="503"/>'
                '<input type="hidden" name="courseId" value="504"/>'
                '<input type="hidden" name="cpi" value="505"/>')
        look = ("https://mooc1-api.chaoxing.com/exam-ans/exam/test/look?courseId=504"
                "&classId=503&examId=502&examAnswerId=501&cpi=505")

        def fake_get(url, referer="", timeout=20):
            calls.append(url)
            if "examcode/examnotes" in url:
                return page, look
            if "examcheck" in url:
                return check_body, url
            raise AssertionError("unexpected url: " + url)

        orig = m._http_get
        m._http_get = fake_get
        try:
            ok = m.exam_submit("https://mooc1-api.chaoxing.com/exam-ans/exam/test/examcode/examnotes",
                               {"captcha_max_try": 2, "captcha_dir": self.temp_dir.name})
        finally:
            m._http_get = orig
        return ok, calls

    def test_exam_submit_reports_expired_instead_of_silently_ok(self):
        """跳到 /look 也别急着说「已交卷」——服务端可能回「考试已过期」，要如实报出来。"""
        ok, calls = self._run_exam_with_look_page('{"msg":"提示：考试已过期","status":false}')
        self.assertFalse(ok)
        self.assertTrue(any("examcheck" in c for c in calls))

    def test_exam_submit_accepts_confirmed_submission_from_look_page(self):
        ok, calls = self._run_exam_with_look_page('{"msg":"已经提交","status":true}')
        self.assertTrue(ok)
        self.assertTrue(any("examcheck" in c for c in calls))


class CaptchaFlowTests(unittest.TestCase):
    """真实层级 mock、失败刷新与自检隔离；网络/文件输出默认封锁。"""

    @classmethod
    def setUpClass(cls):
        cls.m = load_monitor()
        cls.png = gray_png([[100] * 320] * 160)
        cls.encoded = base64.b64encode(cls.png).decode()

    def setUp(self):
        self.real_http_bytes = self.m._http_bytes
        self.real_http_get = self.m._http_get
        for obj, name in ((self.m, "_http_get"), (self.m, "_http_bytes"),
                          (self.m, "_post_json"), (self.m.urllib.request, "urlopen"),
                          (self.m.urllib.request, "build_opener")):
            p = patch.object(obj, name, side_effect=AssertionError("离线测试禁止联网"))
            p.start()
            self.addCleanup(p.stop)
        for obj, name in ((self.m, "log"), (self.m, "_save_captcha_image"), (self.m.time, "sleep")):
            p = patch.object(obj, name)
            p.start()
            self.addCleanup(p.stop)

    def solve_with(self, image_response, check_response, cfg=None):
        calls = []

        def fake(path, params, referer, version):
            calls.append((path, params))
            if path == "get/conf":
                return {"t": 1800000000000}, "{}"
            if path == "get/verification/image":
                return image_response, "{}"
            return check_response, "{}"

        with patch.object(self.m, "_captcha_call", fake):
            result = self.m.captcha_solve({"captchaId": "CID"}, "https://example.com/p", dict(
                {"captcha_x": 170, "captcha_max_try": 1, "captcha_vision": "off"}, **(cfg or {})))
        return result, calls

    def test_known_nested_wrapper_and_alias_background_are_reachable(self):
        for image in ({"token": "IMG", "imageVerificationVo": {"shadeImage": self.encoded}},
                      {"data": {"token": "IMG", "bgImage": self.encoded}}):
            with self.subTest(image_keys=list(image)):
                result, calls = self.solve_with(image, {
                    "result": True, "extraData": {"validate": "validate_CID_IMG"}})
                self.assertEqual(result, "validate_CID_IMG")
                self.assertEqual(calls[-1][1]["token"], "IMG")

    def test_result_true_without_bound_validate_is_failure_and_no_token_is_logged(self):
        for response in ({"status": True, "result": False, "token": "PRIVATE_TOKEN"},
                         {"result": True, "token": "PRIVATE_TOKEN"},
                         {"result": True, "extraData": {"validate": "validate_CID_OTHER"}}):
            with self.subTest(response=response):
                result, _ = self.solve_with({"token": "IMG", "bgImage": self.encoded}, response)
                self.assertEqual(result, "")
        self.assertNotIn("PRIVATE_TOKEN", str(self.m.log.call_args_list))

    def test_missing_challenge_token_never_falls_back_to_signed_request_token(self):
        result, calls = self.solve_with({"imageVerificationVo": {"shadeImage": self.encoded}}, {})
        self.assertEqual(result, "")
        self.assertEqual([p for p, _ in calls], ["get/conf", "get/verification/image"])

    def test_manual_protocol_x_is_not_scaled(self):
        result, calls = self.solve_with({"token": "IMG", "image": self.encoded}, {
            "result": True, "extraData": {"validate": "validate_CID_IMG"}}, {"captcha_scale": 3})
        self.assertEqual(result, "validate_CID_IMG")
        self.assertEqual(calls[-1][1]["textClickArr"], '[{"x":170}]')

    def test_invalid_manual_x_or_unknown_image_does_not_submit_check(self):
        for x, image in ((-1, self.encoded), (320, self.encoded), (True, self.encoded),
                         (170, "invalid")):
            with self.subTest(x=x):
                result, calls = self.solve_with({"token": "IMG", "image": image}, {}, {"captcha_x": x})
                self.assertEqual(result, "")
                self.assertNotIn("check/verification/result", [p for p, _ in calls])

    def test_low_confidence_without_vision_refreshes_new_challenges(self):
        # 纯色图既无透明模板也无纹理，不能胡猜一个可提交坐标。
        result, calls = self.solve_with({"token": "IMG", "image": self.encoded}, {},
                                        {"captcha_x": None, "captcha_max_try": 2})
        self.assertEqual(result, "")
        self.assertEqual([p for p, _ in calls], ["get/conf", "get/verification/image"] * 2)

    def test_http_bytes_does_not_attach_account_cookie(self):
        from types import SimpleNamespace
        response = SimpleNamespace(read=lambda: b"image")
        with patch.object(self.m.urllib.request, "urlopen", return_value=response) as open_url, \
                patch.object(self.m, "_JAR", {"account_session": "PRIVATE_COOKIE"}):
            self.assertEqual(self.real_http_bytes("https://captcha.example.com/image"), b"image")
        headers = dict(open_url.call_args.args[0].header_items())
        self.assertFalse(any(k.lower() == "cookie" for k in headers))
        self.assertNotIn("PRIVATE_COOKIE", str(headers))

    def test_captcha_check_cli_is_account_and_exam_isolated(self):
        with patch.object(self.m.sys, "argv", ["monitor.py", "--captcha-check", "--captcha-count", "2"]), \
                patch.object(self.m, "load_config", return_value={}), \
                patch.object(self.m, "init_jar", side_effect=AssertionError("不能加载账户会话")), \
                patch.object(self.m, "exam_submit", side_effect=AssertionError("不能触碰考试")), \
                patch.object(self.m, "captcha_solve", return_value="validate_TEST_IMG") as solve, \
                patch("builtins.print"):
            with self.assertRaises(SystemExit) as exit_info:
                self.m.main()
        self.assertEqual(exit_info.exception.code, 0)
        self.assertEqual(solve.call_count, 2)
        self.m._http_get.assert_not_called()

    def test_clean_captcha_check_needs_no_account_or_cookie_files(self):
        missing_config = str(Path(_TEMP.name) / "no-config.json")
        missing_cookies = str(Path(_TEMP.name) / "no-cookies.json")
        with patch.object(self.m.sys, "argv", ["monitor.py", "--captcha-check"]), \
                patch.object(self.m, "ENV", {}), patch.object(self.m, "CONFIG_PATH", missing_config), \
                patch.object(self.m, "COOKIES_JSON_PATH", missing_cookies), \
                patch.object(self.m, "init_jar", side_effect=AssertionError("不能加载账户会话")), \
                patch.object(self.m, "captcha_solve", return_value="validate_TEST_IMG") as solve, \
                patch("builtins.print"):
            with self.assertRaises(SystemExit) as exit_info:
                self.m.main()
            self.assertEqual(exit_info.exception.code, 0)
            solve.assert_called_once()
            # 默认监控路径仍要求认证来源，不能因放开自检而放开所有命令。
            with self.assertRaises(SystemExit) as auth_exit:
                self.m.load_config()
            self.assertEqual(auth_exit.exception.code, 1)

    def test_public_config_does_not_inject_account_password(self):
        with patch.object(self.m, "ENV", {"CHAO_XING_ACCOUNT": "PRIVATE_ACCOUNT",
                                          "CHAO_XING_PASSWORD": "PRIVATE_PASSWORD"}):
            cfg = self.m.load_config(require_auth=False)
        self.assertNotIn("PRIVATE_ACCOUNT", cfg.values())
        self.assertNotIn("PRIVATE_PASSWORD", cfg.values())

    def test_authenticated_exam_transport_rejects_foreign_or_insecure_targets(self):
        bad_urls = ["https://example.com/exam", "http://mooc1-api.chaoxing.com/exam",
                    "https://mooc1-api.chaoxing.com.evil.example/exam",
                    "https://user@mooc1-api.chaoxing.com/exam",
                    "https://mooc1-api.chaoxing.com:8443/exam"]
        for url in bad_urls:
            with self.subTest(url=url):
                self.assertFalse(self.m._is_exam_url(url))
                with self.assertRaises(ValueError):
                    self.real_http_get(url)
        self.m.urllib.request.build_opener.assert_not_called()
        self.m.urllib.request.urlopen.assert_not_called()

    def test_exam_redirect_guard_blocks_cookie_forwarding_outside_exam_hosts(self):
        req = self.m.urllib.request.Request("https://mooc1-api.chaoxing.com/exam",
                                          headers={"Cookie": "session=PRIVATE_COOKIE"})
        handler = self.m._ExamRedirectHandler()
        for url in ("https://example.com/exam", "http://mooc1-api.chaoxing.com/exam"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                handler.redirect_request(req, None, 302, "Found", {}, url)
        target = "https://mooc1-api.chaoxing.com/exam-ans/exam/test/look"
        redirected = handler.redirect_request(req, None, 302, "Found", {}, target)
        self.assertEqual(redirected.full_url, target)
        self.assertEqual(redirected.get_header("Cookie"), "session=PRIVATE_COOKIE")

    def test_authenticated_transport_uses_guarded_opener(self):
        from types import SimpleNamespace
        target = "https://mooc1-api.chaoxing.com/exam-ans/exam/test/examcheck"
        response = SimpleNamespace(read=lambda: b'{}', geturl=lambda: target)
        with patch.object(self.m.urllib.request, "build_opener") as build, \
                patch.object(self.m, "_JAR", {"session": "PRIVATE_COOKIE"}), \
                patch.object(self.m, "update_jar_from_response") as update:
            build.return_value.open.return_value = response
            self.assertEqual(self.real_http_get(target), ("{}", target))
            self.assertIsInstance(build.call_args.args[0], self.m._ExamRedirectHandler)
            req = build.return_value.open.call_args.args[0]
            self.assertEqual(req.get_header("Cookie"), "session=PRIVATE_COOKIE")
            update.assert_called_once_with(self.m._JAR, response)

    def test_image_size_rejects_zero_dimensions(self):
        self.assertIsNone(self.m._image_size(fake_jpeg(0, 160)))
        self.assertIsNone(self.m._image_size(make_png(0, 160, [])))

    def test_captcha_check_cli_fails_if_any_group_fails(self):
        with patch.object(self.m.sys, "argv", ["monitor.py", "--captcha-check", "--captcha-count", "2"]), \
                patch.object(self.m, "load_config", return_value={}), \
                patch.object(self.m, "captcha_solve", side_effect=["validate_TEST_IMG", ""]), \
                patch("builtins.print"):
            with self.assertRaises(SystemExit) as exit_info:
                self.m.do_captcha_check_cmd()
        self.assertEqual(exit_info.exception.code, 1)

    def test_captcha_check_cli_rejects_invalid_counts_and_exam_command_mix(self):
        for args in (["--captcha-count"], ["--captcha-count", "0"], ["--captcha-count", "21"],
                     ["--captcha-count", "two"], ["--exam-submit", "https://example.com/exam"]):
            with self.subTest(args=args), patch.object(self.m.sys, "argv", ["monitor.py", "--captcha-check", *args]), \
                    patch.object(self.m, "load_config") as load_config, patch("builtins.print"):
                with self.assertRaises(SystemExit) as exit_info:
                    self.m.main()
                self.assertEqual(exit_info.exception.code, 2)
                load_config.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
