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


CORE_GROUPS: Dict[str, str] = {
    "notices": "通知解析",
    "targets": "目标筛选",
    "keepalive": "保活页面解析",
}


def _iter_test_cases(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _iter_test_cases(item)
        else:
            yield item


def check_behavior_tests(group=None) -> str:
    sys.dont_write_bytecode = True
    suite = unittest.defaultTestLoader.discover(
        start_dir=str(TESTS_DIR), pattern="test_*.py"
    )
    if group is not None:
        prefix = "test_{}_".format(group)
        selected = [
            case
            for case in _iter_test_cases(suite)
            if case.id().rsplit(".", 1)[-1].startswith(prefix)
        ]
        suite = unittest.TestSuite(selected)

    test_count = suite.countTestCases()
    if test_count == 0:
        label = CORE_GROUPS.get(group, "行为")
        raise RuntimeError("没有发现{}测试".format(label))

    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise RuntimeError(
            "{} 个失败，{} 个错误".format(len(result.failures), len(result.errors))
        )
    return "{} 个测试通过".format(test_count)


CHECKS: Dict[str, Check] = {
    "syntax": Check("Python 语法", check_python_syntax),
    "config": Check("config.json", check_config_json),
    "core": Check("核心功能测试", check_behavior_tests),
}
for group, label in CORE_GROUPS.items():
    CHECKS[group] = Check(
        label, lambda group=group: check_behavior_tests(group)
    )

MODES: Dict[str, Tuple[str, ...]] = {
    "all": ("syntax", "config", "core"),
    "core": ("core",),
    "tests": ("core",),
}
MODES.update({group: (group,) for group in CORE_GROUPS})


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="离线检查学习通脚本，不登录、不联网、不启动浏览器。"
    )
    parser.add_argument(
        "mode",
        nargs="?",
        choices=tuple(MODES),
        default="all",
        help=(
            "all：语法、配置和全部核心测试（默认）；core/tests：全部核心测试；"
            "notices、targets、keepalive：分别验证对应功能"
        ),
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
