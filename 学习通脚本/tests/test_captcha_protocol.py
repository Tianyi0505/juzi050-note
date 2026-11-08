# -*- coding: utf-8 -*-
"""验证码协议与图像匹配的离线回归；不使用真实凭据、网络或考试接口。"""

import hashlib
import importlib.util
import io
import json
import random
import struct
import sys
import unittest
import uuid
import zlib
from pathlib import Path
from unittest.mock import patch


# 显式按文件加载，既支持直接执行，也支持从仓库根目录 unittest discover。
# 只复用旧测试的临时副本 loader，绝不直接 import 项目目录中的 monitor。
_HELPER_PATH = Path(__file__).with_name("test_exam_submit_captcha.py")
_SPEC = importlib.util.spec_from_file_location("_captcha_protocol_helpers", _HELPER_PATH)
_HELPERS = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _HELPERS
_SPEC.loader.exec_module(_HELPERS)

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
CAPTCHA_ID = "TEST_CAPTCHA_ID"
CHALLENGE_TOKEN = "TEST_IMAGE_TOKEN"
VALIDATE = "validate_TEST_CAPTCHA_ID_TEST_IMAGE_TOKEN"


def png_with_chunks(width, height, color_type, raw_rows, extra_chunks=()):
    """生成有效 CRC 的 8 位 PNG，额外块放在 IDAT 前。"""
    header = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    chunks = [(b"IHDR", header), *extra_chunks,
              (b"IDAT", zlib.compress(raw_rows)), (b"IEND", b"")]
    return PNG_SIGNATURE + b"".join(_HELPERS._chunk(tag, data) for tag, data in chunks)


def slider_pair(shift=41, gain=1.0, offset=0, repeat_at=None):
    """全高透明图层；可见左边距4px，外缘两圈故意使用不匹配的描边色。"""
    width, height, fg_width = 96, 32, 24
    rng = random.Random(20261108)
    bg_pixels = [(rng.randrange(256),) * 3 for _ in range(width * height)]
    fg_pixels = [(255, 0, 255)] * (fg_width * height)
    alpha = [0] * (fg_width * height)
    for y in range(4, height - 4):
        for x in range(4, fg_width - 4):
            value = rng.randrange(30, 90)
            i = y * fg_width + x
            alpha[i] = 255
            inside = 6 <= x < fg_width - 6 and 6 <= y < height - 6
            fg_pixels[i] = (value,) * 3 if inside else (255, 255, 0)
            target = (int(value * gain + offset),) * 3
            bg_pixels[y * width + shift + x] = target
            if repeat_at is not None:
                bg_pixels[y * width + repeat_at + x] = target
    return ((width, height, bg_pixels, [255] * (width * height)),
            (fg_width, height, fg_pixels, alpha))


class IsolatedMonitorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = _HELPERS.load_monitor()

    def setUp(self):
        # 即使生产函数意外增加联网/写日志路径，也让离线回归立即失败。
        for obj, name in ((self.m, "_http_get"), (self.m, "_http_bytes"),
                          (self.m, "_post_json"),
                          (self.m.urllib.request, "urlopen")):
            blocker = patch.object(obj, name, side_effect=AssertionError("离线测试禁止联网"))
            blocker.start()
            self.addCleanup(blocker.stop)
        quiet = patch.object(self.m, "log")
        quiet.start()
        self.addCleanup(quiet.stop)


class CaptchaParameterTests(IsolatedMonitorTests):
    def test_parameters_follow_frontend_formula(self):
        server_time = 1700000000000
        local_time = 1700000123.125
        first = uuid.UUID("00000000-0000-4000-8000-000000000001")
        second = uuid.UUID("00000000-0000-4000-8000-000000000002")
        digest = lambda text: hashlib.md5(text.encode("utf-8")).hexdigest()
        expected_key = digest(str(server_time) + str(first))
        expected_token = (digest(str(server_time) + CAPTCHA_ID + "slide" + expected_key)
                          + ":1700000300000")
        expected_iv = digest(CAPTCHA_ID + "slide1700000123125" + str(second))
        with patch.object(self.m.time, "time", return_value=local_time), \
                patch.object(self.m.uuid, "uuid4", side_effect=[first, second]) as random_id:
            actual = self.m._captcha_parameters(CAPTCHA_ID, server_time)
        self.assertEqual(actual, {"captchaId": CAPTCHA_ID, "type": "slide",
                                  "captchaKey": expected_key, "token": expected_token,
                                  "iv": expected_iv})
        self.assertEqual(random_id.call_count, 2)

    def test_expiry_uses_server_clock_not_local_clock(self):
        with patch.object(self.m.time, "time", return_value=1.0), \
                patch.object(self.m.uuid, "uuid4", side_effect=["KEY_UUID", "IV_UUID"]):
            params = self.m._captcha_parameters(CAPTCHA_ID, "1700000000123")
        self.assertEqual(params["token"].split(":")[1], "1700000300123")

    def test_new_attempt_gets_independent_key_token_and_iv(self):
        with patch.object(self.m.time, "time", return_value=1700000000.0), \
                patch.object(self.m.uuid, "uuid4", side_effect=["K1", "I1", "K2", "I2"]):
            first = self.m._captcha_parameters(CAPTCHA_ID, 1700000000000)
            second = self.m._captcha_parameters(CAPTCHA_ID, 1700000000000)
        for field in ("captchaKey", "token", "iv"):
            with self.subTest(field=field):
                self.assertNotEqual(first[field], second[field])

    def test_explicit_type_is_signed(self):
        with patch.object(self.m.time, "time", return_value=1700000000.0), \
                patch.object(self.m.uuid, "uuid4", side_effect=["K", "I", "K", "I"]):
            slide = self.m._captcha_parameters(CAPTCHA_ID, 1700000000000, "slide")
            other = self.m._captcha_parameters(CAPTCHA_ID, 1700000000000, "test-type")
        self.assertEqual(other["type"], "test-type")
        self.assertEqual(slide["captchaKey"], other["captchaKey"])
        self.assertNotEqual(slide["token"], other["token"])
        self.assertNotEqual(slide["iv"], other["iv"])


class CaptchaValidateTests(IsolatedMonitorTests):
    def validate(self, data):
        return self.m._captcha_validate(data, CAPTCHA_ID, CHALLENGE_TOKEN)

    def test_accepts_exact_server_validate_in_object_or_json_string(self):
        for extra in ({"validate": VALIDATE}, json.dumps({"validate": VALIDATE})):
            for error in (None, 0, "0"):
                with self.subTest(extra=extra, error=error):
                    self.assertEqual(self.validate(
                        {"result": True, "error": error, "extraData": extra}), VALIDATE)

    def test_status_or_success_cannot_override_failed_result(self):
        for result in (False, "true", "false", 1, 0, None):
            with self.subTest(result=result):
                self.assertEqual(self.validate({"status": True, "success": True,
                                               "result": result, "token": CHALLENGE_TOKEN,
                                               "extraData": {"validate": VALIDATE}}), "")

    def test_error_cannot_be_overridden_by_result_true(self):
        for error in (1, "10022", 10023, "error"):
            with self.subTest(error=error):
                self.assertEqual(self.validate({"result": True, "error": error,
                                               "extraData": {"validate": VALIDATE}}), "")

    def test_token_without_server_validate_never_counts_as_success(self):
        cases = [{"result": True, "token": CHALLENGE_TOKEN},
                 {"status": True, "token": CHALLENGE_TOKEN},
                 {"result": True, "validate": VALIDATE},
                 {"success": True, "extraData": {"validate": VALIDATE}}]
        for body in cases:
            with self.subTest(body=body):
                self.assertEqual(self.validate(body), "")

    def test_rejects_other_challenge_or_captcha_id(self):
        for value in ("validate_OTHER_ID_TEST_IMAGE_TOKEN",
                      "validate_TEST_CAPTCHA_ID_OLD_IMAGE_TOKEN",
                      CHALLENGE_TOKEN, VALIDATE + "_suffix", " " + VALIDATE, ""):
            with self.subTest(value=value):
                self.assertEqual(self.validate({"result": True,
                                               "extraData": {"validate": value}}), "")

    def test_rejects_malformed_extra_data_and_non_objects(self):
        for extra in (None, "not json", "null", "[]", [], 1,
                      {"validate": None}, {"validate": 1}, {"data": {"validate": VALIDATE}}):
            with self.subTest(extra=extra):
                self.assertEqual(self.validate({"result": True, "extraData": extra}), "")
        for body in (None, [], "true", 1):
            with self.subTest(body=body):
                self.assertEqual(self.validate(body), "")


class CaptchaDecodeTests(IsolatedMonitorTests):
    @staticmethod
    def palette_png():
        return png_with_chunks(3, 1, 3, bytes([0, 0, 1, 2]),
                               [(b"PLTE", bytes([10, 20, 30, 40, 50, 60, 70, 80, 90])),
                                (b"tRNS", bytes([0, 128]))])

    def test_palette_trns_keeps_transparent_partial_and_default_alpha(self):
        decoded = self.m._png_decode(self.palette_png())
        self.assertEqual(decoded[:2], (3, 1))
        self.assertEqual(decoded[2], [(10, 20, 30), (40, 50, 60), (70, 80, 90)])
        self.assertEqual(decoded[3], [0, 128, 255])

    def test_gray_trns_keeps_transparent_color(self):
        blob = png_with_chunks(2, 1, 0, bytes([0, 17, 18]),
                               [(b"tRNS", struct.pack(">H", 17))])
        self.assertEqual(self.m._png_decode(blob)[3], [0, 255])

    def test_rgb_trns_keeps_transparent_color(self):
        blob = png_with_chunks(2, 1, 2, bytes([0, 10, 20, 30, 10, 20, 31]),
                               [(b"tRNS", struct.pack(">HHH", 10, 20, 30))])
        self.assertEqual(self.m._png_decode(blob)[3], [0, 255])

    def test_truncated_and_short_ihdr_return_none_not_exception(self):
        chunks = [PNG_SIGNATURE + struct.pack(">I", 13) + b"IHDR" + bytes(4),
                  PNG_SIGNATURE + _HELPERS._chunk(b"IHDR", bytes(4)),
                  PNG_SIGNATURE + struct.pack(">I", 13) + b"IHDR"]
        for blob in chunks:
            with self.subTest(blob=blob):
                self.assertIsNone(self.m._png_decode(blob))

    def test_decode_png_falls_back_without_pillow(self):
        with patch.dict(sys.modules, {"PIL": None, "PIL.Image": None}):
            decoded = self.m._decode_image(self.palette_png())
        self.assertEqual(decoded[3], [0, 128, 255])

    def test_decode_invalid_image_fails_closed(self):
        for blob in (b"", b"not an image", PNG_SIGNATURE + bytes(20)):
            with self.subTest(blob=blob):
                self.assertIsNone(self.m._decode_image(blob))

    def test_decode_jpeg_when_optional_pillow_is_installed(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("可选 Pillow 未安装；标准库 PNG 路径另有覆盖")
        stream = io.BytesIO()
        Image.new("RGB", (8, 5), (40, 80, 120)).save(stream, format="JPEG")
        decoded = self.m._decode_image(stream.getvalue())
        self.assertEqual(decoded[:2], (8, 5))
        self.assertEqual(len(decoded[2]), 40)
        self.assertEqual(decoded[3], [255] * 40)


class CaptchaMatchingTests(IsolatedMonitorTests):
    def test_match_returns_full_layer_shift_not_visible_left_edge(self):
        bg, fg = slider_pair(shift=41)
        match = self.m._match_slider(bg, fg)
        self.assertIsNotNone(match)
        self.assertEqual(match[0], 41)       # 可见缺口左缘为45，协议图层位移为41。
        self.assertNotEqual(match[0], 45)
        self.assertGreater(match[1], 0.99)
        self.assertEqual(self.m._locate_gap(bg, fg), 41)

    def test_ncc_survives_darker_or_brighter_gap_and_outline(self):
        for gain, offset in ((0.5, 7), (2.0, 30), (1.0, 50)):
            with self.subTest(gain=gain, offset=offset):
                bg, fg = slider_pair(shift=35, gain=gain, offset=offset)
                match = self.m._match_slider(bg, fg)
                self.assertIsNotNone(match)
                self.assertEqual(match[0], 35)
                self.assertGreater(match[1], 0.99)

    def test_flat_foreground_is_not_matchable(self):
        bg, fg = slider_pair()
        flat = (fg[0], fg[1], [(100, 100, 100)] * len(fg[2]), fg[3])
        self.assertIsNone(self.m._match_slider(bg, flat))

    def test_flat_background_is_not_matchable(self):
        bg, fg = slider_pair()
        flat = (bg[0], bg[1], [(100, 100, 100)] * len(bg[2]), bg[3])
        self.assertIsNone(self.m._match_slider(flat, fg))

    def test_repeated_texture_is_ambiguous_and_rejected(self):
        bg, fg = slider_pair(shift=48, repeat_at=8)
        self.assertIsNone(self.m._match_slider(bg, fg))

    def test_unrelated_texture_is_rejected(self):
        bg, fg = slider_pair()
        rng = random.Random(107)
        unrelated = (bg[0], bg[1], [(rng.randrange(256),) * 3
                                   for _ in bg[2]], bg[3])
        self.assertIsNone(self.m._match_slider(unrelated, fg))

    def test_cropped_non_equal_height_foreground_is_rejected(self):
        bg, fg = slider_pair()
        cropped = (fg[0], fg[1] - 1, fg[2][:-fg[0]], fg[3][:-fg[0]])
        self.assertIsNone(self.m._match_slider(bg, cropped))

    def test_no_foreground_or_no_opaque_evidence_is_rejected(self):
        bg, fg = slider_pair()
        transparent = (fg[0], fg[1], fg[2], [0] * len(fg[3]))
        self.assertIsNone(self.m._match_slider(bg, transparent))
        self.assertIsNone(self.m._match_slider(bg, None))
        self.assertIsNone(self.m._match_slider(None, fg))
        self.assertIsNone(self.m._locate_gap(bg))


if __name__ == "__main__":
    unittest.main(verbosity=2)
