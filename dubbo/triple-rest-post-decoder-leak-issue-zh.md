# [Bug] Triple REST 表单请求完成后未清理 HttpPostRequestDecoder

## Pre-check

- [ ] 正式提交前会将全部内容翻译为英文。

## Search before asking

- [x] 已搜索现有 Issues 和 Pull Requests，未发现相同问题。

PR #14741 调整了请求体 buffer 的分配路径，PR #14760 避免为空请求体创建 decoder。两项改动都没有在非空表单请求完成后清理 decoder。

## Apache Dubbo Component

Java SDK (apache/dubbo)

## Dubbo Version

- Dubbo：`3.3.7-SNAPSHOT`
- 分支：`3.3`
- Commit：`3a3043227f5571d25eb2889de5bca22f2914843b`
- JDK：Temurin 17.0.17
- 操作系统：Windows 11 x86_64
- Netty：4.2.15.Final

## Steps to reproduce this issue

在现有 `RestProtocolTest.groovy` 中增加：

```groovy
import org.apache.dubbo.remoting.http12.HttpUtils

import io.netty.handler.codec.http.multipart.DefaultHttpDataFactory

def "completed form request should release post data"() {
    given:
        HttpUtils.DATA_FACTORY.cleanAllHttpData()
        def request = new TestRequest(
            path: '/argTest',
            contentType: MediaType.APPLICATION_FROM_URLENCODED,
            body: 'name=Sam&age=8'
        )
    expect:
        runner.post(request) == 'Sam is 8 years old'
        trackedPostRequests() == 0
    cleanup:
        HttpUtils.DATA_FACTORY.cleanAllHttpData()
}

private static int trackedPostRequests() {
    def field = DefaultHttpDataFactory.getDeclaredField('requestFileDeleteMap')
    field.accessible = true
    return ((Map<?, ?>) field.get(HttpUtils.DATA_FACTORY)).size()
}
```

运行 `RestProtocolTest` 后，请求正常返回：

```text
Sam is 8 years old
```

但断言失败：

```text
expected: 0
actual:   1
```

连续执行 20 次相同请求后，Factory 中的请求条目会增长到 20，GC 后仍然保留。

## What you expected to happen

表单请求完成后，应销毁本次请求的 `HttpPostRequestDecoder`，使 `DefaultHttpDataFactory` 移除对应请求及 `HttpData`。在没有其他并发表单请求时，Factory 中的请求条目应为 0。

实际请求虽然成功完成，但 Factory 仍保留当前请求，并随请求次数持续增长。

## Anything else

真实调用链为：

```text
RestHttpMessageCodec.decode()
  → CompositeArgumentResolver
  → FallbackArgumentResolver
  → DefaultHttpRequest.parameter()
  → DefaultHttpRequest.getPostDecoder()
  → HttpUtils.createPostRequestDecoder()
```

`HttpUtils` 使用静态 `DATA_FACTORY` 和新创建的 synthetic `DefaultFullHttpRequest` 构造 decoder。Netty Factory 会以该 synthetic request 为 key 保存表单 `HttpData`。

[`DefaultHttpDataFactory`](https://netty.io/4.2/xref/io/netty/handler/codec/http/multipart/DefaultHttpDataFactory.html) 通过基于身份比较的 Map 强引用 synthetic request 及对应的 `HttpData`。[`HttpPostRequestDecoder`](https://netty.io/4.2/xref/io/netty/handler/codec/http/multipart/HttpPostRequestDecoder.html) 的资源契约明确要求在 decoder 使用完成后调用：

```java
postDecoder.destroy();
```

该操作会使 Factory 移除 synthetic request 条目并释放对应数据。当前生产代码在请求处理终止时没有销毁 decoder，因此这些条目仍可通过静态 Factory 访问。

`AbstractServerTransportListener.onDataFinally()` 的默认实现只关闭当前入站消息；HTTP/2 的 `GenericHttp2ServerTransportListener` 则将其覆盖为空实现。无论哪种情况，都不会释放适配后的 `DefaultHttpRequest`，也不会销毁其中缓存的 decoder。入站消息处理结束并不等同于完整请求或响应生命周期结束。

未触发表单或参数解析的请求，以及 `createPostRequestDecoder()` 返回 `null` 的空请求体，不会创建此类条目。

由于 `DefaultHttpRequest` 负责懒创建并缓存 decoder，因此需要提供一个可由服务端请求生命周期终止路径调用的显式清理机制。清理应覆盖正常完成、异常、取消和传输关闭，并且只能在业务代码无法再访问请求参数或 multipart part 后执行。

不能在参数解析后立即销毁 decoder，因为 `part()` 或 `parts()` 返回的 multipart `FileUpload` 仍依赖其底层 `HttpData`，业务代码可能稍后才读取它们。

## Do you have a (mini) reproduction demo?

- [x] Yes, I have a minimal reproduction demo to help resolve this issue more effectively!

## Are you willing to submit a pull request to fix on your own?

- [x] Yes I am willing to submit a pull request on my own!

## Code of Conduct

- [x] I agree to follow this project's [Code of Conduct](https://www.apache.org/foundation/policies/conduct).
