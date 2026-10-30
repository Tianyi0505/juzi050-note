#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
注册 Windows 计划任务，让学习通监控在后台“常驻 + 自愈”，不依赖 WorkBuddy 会话/沙箱。
- 每 20 分钟触发一次，调用 `python monitor.py --daemon`；
- --daemon 会拉起一个“脱离父进程”的独立监控实例并立即退出；
- 若监控已在运行（占用 127.0.0.1:45123 单实例锁），新实例会自动退出，不会多开；
- 因此：监控进程一旦死亡，下一个触发点（≤20 分钟）会自动重启；重开机后登录即恢复。

运行（需管理员或当前用户权限，计划任务以“仅当用户登录时运行”注册，无需密码）：
    python setup_watchdog.py
卸载：
    schtasks /delete /tn ChaoxingMonitor /f
"""
import subprocess
import sys
import os

BASE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable                                   # 当前 python 解释器
SCRIPT = os.path.join(BASE, "monitor.py")
TR = f'"{PY}" "{SCRIPT}" --daemon'                     # 无空格路径，但加引号更稳妥

TASK_NAME = "ChaoxingMonitor"


def main():
    # 删除旧任务（若存在），再创建，保证幂等
    subprocess.run(["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
                   capture_output=True, text=True)
    cmd = [
        "schtasks", "/create",
        "/tn", TASK_NAME,
        "/tr", TR,
        "/sc", "minute",
        "/mo", "20",
        "/st", "00:00",
        "/f",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    print("RC =", r.returncode)
    print("OUT =", r.stdout.strip())
    print("ERR =", r.stderr.strip())
    if r.returncode == 0:
        q = subprocess.run(["schtasks", "/query", "/tn", TASK_NAME, "/fo", "LIST", "/v"],
                           capture_output=True, text=True)
        print("---- 任务信息 ----")
        print(q.stdout.strip() or q.stderr.strip())


if __name__ == "__main__":
    main()
