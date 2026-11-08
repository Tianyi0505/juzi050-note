from socket import *
import sys

# 用法: python client.py server_host server_port filename
if len(sys.argv) < 4:
    print('Usage : "python client.py server_host server_port filename"')
    sys.exit(2)

server_host = sys.argv[1]
server_port = int(sys.argv[2])
filename = sys.argv[3]

# 创建一个 TCP 套接字并与服务器建立连接
c = socket(AF_INET, SOCK_STREAM)
c.connect((server_host, server_port))

# 构造 HTTP 请求报文并发送
request = "GET /%s HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n\r\n" % (filename, server_host)
c.send(request.encode())

# 循环接收服务器的响应并输出
response = b""
while True:
    data = c.recv(4096)
    if not data:
        break
    response += data
c.close()

print(response.decode('utf-8', 'replace'))
