from socket import *
import sys
import os

# 读入要监听的端口号
if len(sys.argv) <= 1:
    print('Usage : "python WebServer.py server_port"\n[server_port : It is the Port Of Web Server')
    sys.exit(2)

# 为Web服务器创建一个TCP套接字、绑定端口号、设置服务器最大连接客户机数量为3
tcpSerSock = socket(AF_INET, SOCK_STREAM)
tcpSerSock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
tcpSerSock.bind(('', int(sys.argv[1])))
tcpSerSock.listen(3)

while True:
    # 准备从客户机接收响应消息
    print('准备从客户机接收响应消息...')
    tcpCliSock, addr = tcpSerSock.accept()
    print('接收到一个连接，来自：', addr)

    # 获取客户机发送过来的消息
    message = tcpCliSock.recv(4096).decode('iso-8859-1')
    print('客户机发送过来的消息：\n' + message.strip())

    # 从消息中提取出文件名
    if message.find("HTTP") == -1:
        tcpCliSock.close()
        continue
    filename = message.split()[1].lstrip('/')
    if filename == '':
        filename = 'HelloWorld.html'
    print('文件名：', filename)

    try:
        # 检查要访问的文件是否在此Web服务器中
        print('开始检查服务器中是否存在文件：', filename)
        f = open(filename, "rb")
        outputdata = f.read()
        f.close()
        print('文件存在在服务器中')

        # 文件存在于服务器中，返回响应消息（首部行 + 内容）给客户机
        header = "HTTP/1.1 200 OK\r\n"
        header += "Server: PyWebServer/1.0\r\n"
        header += "Content-Type: text/html; charset=utf-8\r\n"
        header += "Content-Length: %d\r\n" % len(outputdata)
        header += "Connection: close\r\n\r\n"
        tcpCliSock.send(header.encode())
        for i in range(0, len(outputdata), 1024):
            tcpCliSock.send(outputdata[i:i + 1024])
        print('OK!')

    # 文件不在服务器当中，返回 404
    except IOError:
        body = ("<html><head><title>404 Not Found</title></head>"
                "<body><h1>HTTP ERROR 404</h1>"
                "<p>File not found: %s</p></body></html>" % filename).encode()
        header = "HTTP/1.1 404 Not Found\r\n"
        header += "Content-Type: text/html; charset=utf-8\r\n"
        header += "Content-Length: %d\r\n" % len(body)
        header += "Connection: close\r\n\r\n"
        tcpCliSock.send(header.encode())
        tcpCliSock.send(body)
        print('文件不在服务器当中，已返回 404')

    # 关闭客户机套接字
    print('关闭套接字：tcpCliSock')
    tcpCliSock.close()

print('关闭套接字：tcpSerSock')
tcpSerSock.close()
