# 学习通只读 Agent CLI

`agent_cli.py` 通过本机 Chrome DevTools Protocol（CDP）打开学习通页面并读取页面可见文本，供 agent 进行讲解。CLI 不提供点击、填写或提交命令，不保存页面内容，也不读取项目 `.env` 或 cookie 文件。`open` 会执行普通页面导航，页面自身脚本仍可能产生站点行为，因此只传入可信的学习通页面 URL。离线代码验证仍使用 `verify.py`。

## 安装

```bash
python3 -m pip install -r 学习通脚本/requirements-agent.txt
```

## 启动 Chrome

Chrome 必须在启动时启用本机调试端口；普通方式已经打开的 Chrome 不能在运行中追加 CDP 参数。建议使用单独的浏览器配置目录，并在该 Chrome 窗口中手动登录学习通：

macOS：

```bash
open -na "Google Chrome" --args \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/Library/Application Support/ChaoxingAgentProfile"
```

PowerShell：

```powershell
$chrome = "$env:ProgramFiles\Google\Chrome\Application\chrome.exe"
$profile = Join-Path $env:LOCALAPPDATA 'ChaoxingAgentProfile'
Start-Process $chrome -ArgumentList @('--remote-debugging-port=9222', "--user-data-dir=$profile")
```

不要把调试端口暴露到局域网或公网；CDP 对浏览器会话有很高权限。使用完毕后关闭该调试 Chrome。

## 命令

```bash
# 列出当前 Chrome 中的学习通标签；输出会隐藏 URL 查询参数
python3 学习通脚本/agent_cli.py tabs

# 在新标签中打开指定学习通 URL，并返回标题和最多 20,000 字可见文本
python3 学习通脚本/agent_cli.py open "https://mooc1.chaoxing.com/..."

# 重新读取指定标签（target_id 由 tabs/open 返回）
python3 学习通脚本/agent_cli.py read TARGET_ID
```

如调试端口不同，将 `--cdp-url http://127.0.0.1:端口` 放在子命令前。CLI 只允许连接 loopback CDP 地址，只接受 HTTPS 的 `chaoxing.com` / `xuexitong.com` 域名。结构化 `url` 字段会移除 query/fragment；标题和正文不会做脱敏，可能包含页面中的 URL、个人信息或敏感文本，直接输出到 stdout（不写入项目文件），请按需使用。

CDP HTTP 和 WebSocket 重定向都会拒绝；页面文本仅在隔离的执行上下文中读取，并启用副作用检测和求值超时。如果 Chrome 判定读取不安全，命令会报错退出，不会降级为无保护读取。

当前只开放 `tabs`、`open`、`read` 三种只读/导航操作。没有通用 JavaScript、点击、填答或提交命令；作答与提交由用户本人完成。
