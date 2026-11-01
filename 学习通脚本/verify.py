#!/usr/bin/env python3
"""离线验证学习通脚本的语法、配置和关键行为。"""

import argparse
import json
import sys
import unittest
from pathlib import Path
from typing import Callable, Dict, NamedTuple, Tuple


SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.json"
TESTS_DIR = SCRIPT_DIR / "tests"


class Check(NamedTuple):
    label: str
    run: Callable[[], str]


def check_python_syntax() -> str:
    sources = sorted(SCRIPT_DIR.rglob("*.py"))
    if not sources:
        raise RuntimeError("没有找到 Python 源文件")
    for path in sources:
        compile(path.read_text(encoding="utf-8"), str(path), "exec")
    return "{} 个文件".format(len(sources))


def check_config_json() -> str:
    with CONFIG_PATH.open(encoding="utf-8") as stream:
        config = json.load(stream)
    if not isinstance(config, dict):
        raise ValueError("config.json 顶层必须是 JSON 对象")
    return "JSON 对象有效"


def check_behavior_tests() -> str:
    sys.dont_write_bytecode = True
    suite = unittest.defaultTestLoader.discover(
        start_dir=str(TESTS_DIR), pattern="test_*.py"
    )
    test_count = suite.countTestCases()
    if test_count == 0:
        raise RuntimeError("没有发现行为测试")

    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise RuntimeError(
            "{} 个失败，{} 个错误".format(len(result.failures), len(result.errors))
        )
    return "{} 个测试通过".format(test_count)


CHECKS: Dict[str, Check] = {
    "syntax": Check("Python 语法", check_python_syntax),
    "config": Check("config.json", check_config_json),
    "tests": Check("离线行为测试", check_behavior_tests),
}
MODES: Dict[str, Tuple[str, ...]] = {
    "all": tuple(CHECKS),
    "tests": ("tests",),
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="离线检查学习通脚本，不登录、不联网、不启动浏览器。"
    )
    parser.add_argument(
        "mode",
        nargs="?",
        choices=tuple(MODES),
        default="all",
        help="all：语法、配置和行为测试（默认）；tests：只跑行为测试",
    )
    args = parser.parse_args(argv)

    failed = False
    for name in MODES[args.mode]:
        check = CHECKS[name]
        try:
            detail = check.run()
        except Exception as exc:
            print("[FAIL] {}: {}".format(check.label, exc), file=sys.stderr)
            failed = True
        else:
            print("[PASS] {}: {}".format(check.label, detail))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
