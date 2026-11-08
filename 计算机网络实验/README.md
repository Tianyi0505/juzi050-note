# 计算机网络实验

本目录包含《计算机网络实验》（课程号 (2023-2024-1)-S0507170-09）六次实验的实验材料与实验报告。

## 实验报告

| 实验 | 题目 | 页数 | 报告 |
| --- | --- | --- | --- |
| 实验一 | Wireshark 抓包工具的使用 | 9 | [[实验一 Wireshark抓包工具使用.pdf]] |
| 实验二 | HTTP 抓包及分析 | 10 | [[实验二 HTTP抓包及分析.pdf]] |
| 实验三 | DNS 抓包及分析 | 9 | [[实验三 DNS抓包及分析.pdf]] |
| 实验四 | TCP 抓包及分析 | 11 | [[实验四 TCP抓包及分析.pdf]] |
| 实验五 | UDP 抓包及分析 | 8 | [[实验五 UDP抓包及分析.pdf]] |
| 实验六 | Socket 编程 | 13 | [[实验六 Socket编程.pdf]] |

每份报告同时提供 `.docx` 源文件，可直接修改。报告中的数据均来自本机 WLAN 网卡的真实抓包，原始文件见 `抓包文件/`。

## 抓包文件

| 文件 | 对应实验 | 捕获过滤器 |
| --- | --- | --- |
| `cap_http.pcapng` | 实验二 | `tcp port 80 and host 128.119.245.12` |
| `cap_http2.pcapng` | 实验二（浏览器并行下载） | `tcp port 80` |
| `cap_dns.pcapng` | 实验三 | `udp port 53 or tcp port 53` |
| `cap_dns2.pcapng` | 实验三（NS / MX / 指定 DNS） | `udp port 53` |
| `cap_tcp_post.pcapng` | 实验四 | `tcp port 80 and host 128.119.245.12` |
| `cap_udp.pcapng` | 实验五 | `udp` |

打开方式：`E:\tools\Wireshark\Wireshark.exe -n -r <文件> -Y "<显示过滤器>"`。

## Socket 编程源码

见 `Socket编程源码/`，包含 `WebServer.py`（作业一）、`ProxyServer.py`（作业二）、`client.py`（可选练习）与 `HelloWorld.html`，均已改写为 Python 3。

## 实验材料

- 课件：`0 wireshark抓包工具使用.pptx` ~ `4 UDP抓包及分析实验.pptx`、`5 Socket编程实验.rar`
- 官方实验指导：`Wireshark_Intro_v7.0.pdf`、`Wireshark_HTTP_v7.0.pdf`、`Wireshark_DNS_v7.0.pdf`、`Wireshark_TCP_v7.0.pdf`、`Wireshark_UDP_v7.0.pdf`
- 报告模板：`实验报告模板.docx`
