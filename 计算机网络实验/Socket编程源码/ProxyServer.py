from socket import *
import sys
import os
import threading

# 缓存目录：代理服务器把从远端取回的网页 / 图片存放在这里
CACHE_DIR = 'cache'
os.makedirs(CACHE_DIR, exist_ok=True)


def cache_path(host, path):
    """把 host + path 映射为缓存文件路径，'/' 结尾视为 index.html"""
    if path == '' or path == '/':
        path = '/index.html'
    name = host + path
    name = name.replace('?', '_')
    return os.path.join(CACHE_DIR, name.lstrip('/'))


def guess_type(filename):
    low = filename.lower()
    if low.endswith('.png'):
        return 'image/png'
    if low.endswith(('.jpg', '.jpeg')):
        return 'image/jpeg'
    if low.endswith('.gif'):
        return 'image/gif'
    if low.endswith('.css'):
        return 'text/css'
    if low.endswith('.js'):
        return 'application/javascript'
    return 'text/html; charset=utf-8'


def recv_request(sock):
    """读取一个完整的 HTTP 请求首部"""
    data = b''
    sock.settimeout(5)
    try:
        while b'\r\n\r\n' not in data:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
            if len(data) > 65536:
                break
    except timeout:
        pass
    return data


def recv_all(sock):
    """读到连接关闭为止，返回全部字节"""
    buf = b''
    sock.settimeout(8)
    while True:
        try:
            chunk = sock.recv(8192)
            if not chunk:
                break
            buf += chunk
        except timeout:
            break
    return buf


def fetch_remote(host, path):
    """向远端 Web 服务器请求对象，返回完整的 HTTP 响应字节"""
    c = socket(AF_INET, SOCK_STREAM)
    c.settimeout(8)
    c.connect((host, 80))
    req = ('GET %s HTTP/1.0\r\nHost: %s\r\nUser-Agent: PyProxyServer/1.0\r\n'
           'Accept: */*\r\nConnection: close\r\n\r\n' % (path or '/', host))
    c.sendall(req.encode())
    resp = recv_all(c)
    c.close()
    return resp


def split_response(resp):
    """拆出响应首部与正文"""
    idx = resp.find(b'\r\n\r\n')
    if idx == -1:
        return b'', resp
    return resp[:idx + 4], resp[idx + 4:]


def send_error(sock, code, phrase):
    body = ('<html><head><title>%d %s</title></head><body>'
            '<h1>HTTP ERROR %d</h1><p>%s</p></body></html>'
            % (code, phrase, code, phrase)).encode()
    sock.sendall(('HTTP/1.0 %d %s\r\n' % (code, phrase)).encode())
    sock.sendall(b'Content-Type: text/html; charset=utf-8\r\n')
    sock.sendall(('Content-Length: %d\r\n' % len(body)).encode())
    sock.sendall(b'\r\n')
    sock.sendall(body)


def handle(tcpCliSock, addr):
    """处理一个客户端连接，由独立线程调用"""
    try:
        # 获取客户机发送过来的消息
        message = recv_request(tcpCliSock)
        if not message:
            return
        text = message.decode('iso-8859-1')
        print('客户机发送过来的消息：\n' + text.strip())

        # 从消息中提取出文件名
        if text.find("HTTP") == -1:
            return
        request_line = text.split('\r\n')[0]
        parts = request_line.split()
        if len(parts) < 2 or parts[0].upper() != 'GET':
            send_error(tcpCliSock, 501, 'Not Implemented')
            return

        url = parts[1]
        # 取出 host 与 path：请求行形如 GET /www.baidu.com/index.html HTTP/1.1
        if url.startswith('http://'):
            url = url[len('http://'):]
        seg = url.lstrip('/').partition('/')
        webName, path = seg[0], '/' + seg[2]
        if not webName:
            for line in text.split('\r\n'):
                if line.lower().startswith('host:'):
                    webName = line.split(':', 1)[1].strip().split(':')[0]
                    break
        filename = cache_path(webName, path)
        print('文件名：', filename)

        # 检查要访问的文件是否在此Web代理服务器中（缓存命中）
        if os.path.exists(filename):
            print('文件存在在代理服务器中')
            with open(filename, 'rb') as f:
                content = f.read()
            tcpCliSock.sendall(b'HTTP/1.0 200 OK\r\n')
            tcpCliSock.sendall(('Content-Type: %s\r\n' % guess_type(filename)).encode())
            tcpCliSock.sendall(('Content-Length: %d\r\n' % len(content)).encode())
            tcpCliSock.sendall(b'X-Cache: HIT\r\n\r\n')
            tcpCliSock.sendall(content)
            print('Read from cache')
            return

        # 缓存未命中：向远端服务器请求，保存后再返回给客户机
        print('文件不存在在代理服务器中，向远端服务器 %s 请求 %s' % (webName, path))
        try:
            resp = fetch_remote(webName, path)
        except gaierror as e:
            print('gaierror:', e)
            send_error(tcpCliSock, 404, 'Not Found')
            return

        header, body = split_response(resp)
        if not header:
            send_error(tcpCliSock, 502, 'Bad Gateway')
            return

        # 写入缓存（网页与图片统一按二进制保存）
        dirname = os.path.dirname(filename)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        with open(filename, 'wb') as f:
            f.write(body)
        print('已缓存 %d 字节到 %s' % (len(body), filename))

        # 把响应转发给客户机
        tcpCliSock.sendall(b'HTTP/1.0 200 OK\r\n')
        tcpCliSock.sendall(('Content-Type: %s\r\n' % guess_type(filename)).encode())
        tcpCliSock.sendall(('Content-Length: %d\r\n' % len(body)).encode())
        tcpCliSock.sendall(b'X-Cache: MISS\r\n\r\n')
        tcpCliSock.sendall(body)
        print('Read from remote server')

    except Exception as e:
        print(e)
        print("Illegal request")
        try:
            send_error(tcpCliSock, 500, 'Internal Server Error')
        except Exception:
            pass
    finally:
        print('关闭套接字：tcpCliSock')
        tcpCliSock.close()


if __name__ == '__main__':
    if len(sys.argv) <= 1:
        print('Usage : "python ProxyServer.py server_port"\n'
              '[server_port : It is the Port Of Proxy Server, e.g. 8888')
        sys.exit(2)

    # 为代理服务器创建一个TCP套接字、绑定端口号、设置服务器最大连接客户机数量为100
    tcpSerSock = socket(AF_INET, SOCK_STREAM)
    tcpSerSock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
    tcpSerSock.bind(('', int(sys.argv[1])))
    tcpSerSock.listen(100)

    # 主线程只负责 accept，每个连接交给一个独立线程（多线程代理服务器）
    while 1:
        print('准备从客户机接收响应消息...')
        tcpCliSock, addr = tcpSerSock.accept()
        print('接收到一个连接，来自：', addr)
        t = threading.Thread(target=handle, args=(tcpCliSock, addr))
        t.daemon = True
        t.start()

    print('关闭套接字：tcpSerSock')
    tcpSerSock.close()
