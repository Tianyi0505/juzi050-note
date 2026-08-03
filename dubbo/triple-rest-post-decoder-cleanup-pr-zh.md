# PR 标题

```text
fix(triple): clean up REST form request decoder
```

# PR 正文

## What is the purpose of the change?

Closes #16403.

Triple REST 在解析 `application/x-www-form-urlencoded` 或 `multipart/form-data` 请求时，会由 `DefaultHttpRequest` 延迟创建并缓存 `HttpPostRequestDecoder`。请求结束后没有调用 decoder 的 `destroy()`，导致 `DefaultHttpDataFactory` 继续保存该请求及其表单数据。

本次修改将清理动作接入 HTTP 响应的终止生命周期：

- 为 `DefaultHttpRequest` 增加专用的 decoder 销毁方法。
- 在 HTTP/1.1 和 HTTP/2 服务端响应观察器终止时清理 decoder。
- 覆盖正常完成、异常响应和连接关闭路径，并保证并发终止事件下只执行一次清理。
- 等到响应终止时再清理，避免参数解析完成后过早释放仍可能被业务方法使用的 multipart 数据。

## How was it tested?

新增 `HttpPostRequestDecoderLifecycleTest`，通过 Triple REST 的真实请求入口发送表单请求，并比较请求前后 `DefaultHttpDataFactory` 跟踪的请求数量。

- 修复前：测试稳定失败，单次请求后跟踪数量由 `0` 增加到 `1`。
- 修复后：`Tests run: 1, Failures: 0, Errors: 0, Skipped: 0`。

执行命令：

```shell
./mvnw -pl dubbo-rpc/dubbo-rpc-triple -am -Dtest=HttpPostRequestDecoderLifecycleTest -Dsurefire.failIfNoSpecifiedTests=false test
```

同时已使用仓库中的 `codestyle/dubbo_codestyle_for_idea.xml` 格式化改动文件，Maven Checkstyle 和 Spotless 检查通过。

## Checklist

- [x] Make sure there is a [GitHub_issue](https://github.com/apache/dubbo/issues) field for the change.
- [x] Write a pull request description that is detailed enough to understand what the pull request does, how it does it, and why it does it.
- [x] Write necessary unit-test to verify the code.
- [x] Make sure gitHub actions can pass.
