# Socket 编程实验源码

《计算机网络实验》实验六（Socket 编程）的两个作业实现，Python 3，无第三方依赖。

## 文件

| 文件 | 说明 |
| --- | --- |
| `WebServer.py` | 作业一：单线程简易 Web 服务器，端口由命令行参数给定 |
| `ProxyServer.py` | 作业二：多线程 Web 代理服务器，带磁盘缓存 |
| `client.py` | 可选练习：用 socket 手工发 GET 请求并打印响应 |
| `HelloWorld.html` | 作业一用到的测试页面 |

## 运行

```powershell
python WebServer.py 6789
```

浏览器访问 `http://127.0.0.1:6789/HelloWorld.html` 返回 200 页面，
访问不存在的文件（如 `http://127.0.0.1:6789/abc.html`）返回 404 页面。

```powershell
python ProxyServer.py 8888
```

浏览器访问 `http://127.0.0.1:8888/example.com/`，首次回源并缓存到
`cache\example.com\index.html`，响应头带 `X-Cache: MISS`；再次访问直接从缓存返回，
响应头带 `X-Cache: HIT`。访问不存在的主机会由 `gaierror` 分支返回 404。

```powershell
python client.py 127.0.0.1 6789 HelloWorld.html
```

## 与原框架的差异

原始框架（`5 Socket编程实验.rar`）是 Python 2 写法。本实现按 Python 3 改写：

- `print` 语句改为 `print()` 函数；
- `socket.send(str)` 改为先 `encode()` 再 `sendall()`；
- `recv()` 返回的字节串先 `decode('iso-8859-1')` 再解析请求行；
- 服务器套接字设置 `SO_REUSEADDR`，避免上一轮残留连接处于 `TIME_WAIT` 时 `bind` 失败；
- 代理服务器由单线程改为 `threading` 每连接一个线程，否则浏览器并发请求页面与图片时会排队。
