# [Bug] Triple REST does not clean up HttpPostRequestDecoder after a form request completes

## Pre-check

- [x] I am sure that all the content I provide is in English.

## Search before asking

- [x] I searched the existing Issues and Pull Requests and found no identical issue.

PR #14741 changed the request-body buffer allocation path, while PR #14760 avoided creating a decoder for an empty request body. Neither change cleans up the decoder after a non-empty form request completes.

## Apache Dubbo Component

Java SDK (apache/dubbo)

## Dubbo Version

- Dubbo: `3.3.7-SNAPSHOT`
- Branch: `3.3`
- Commit: `3a3043227f5571d25eb2889de5bca22f2914843b`
- JDK: Eclipse Temurin 17.0.17
- Operating system: Windows 11 x86_64
- Netty: 4.2.15.Final

## Steps to reproduce this issue

Add the following test to the existing `RestProtocolTest.groovy`:

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

Run `RestProtocolTest`. The request succeeds and returns:

```text
Sam is 8 years old
```

However, the assertion fails:

```text
expected: 0
actual:   1
```

After running the same request 20 times, the number of tracked requests in the factory grows to 20 and remains unchanged after GC.

## What you expected to happen

After the form request completes, its `HttpPostRequestDecoder` should be destroyed so that `DefaultHttpDataFactory` removes the associated request and `HttpData`. With no other concurrent form requests, the number of tracked requests should be 0.

The request currently completes successfully, but the factory still retains it and continues to grow as more form requests are processed.

## Anything else

The relevant call chain is:

```text
RestHttpMessageCodec.decode()
  → CompositeArgumentResolver
  → FallbackArgumentResolver
  → DefaultHttpRequest.parameter()
  → DefaultHttpRequest.getPostDecoder()
  → HttpUtils.createPostRequestDecoder()
```

`HttpUtils` creates the decoder with the static `DATA_FACTORY` and a newly created synthetic `DefaultFullHttpRequest`. Netty's factory stores the parsed form `HttpData` using that synthetic request as the key.

[`DefaultHttpDataFactory`](https://netty.io/4.2/xref/io/netty/handler/codec/http/multipart/DefaultHttpDataFactory.html) uses an identity-based map to strongly reference the synthetic request and its associated `HttpData`. The resource contract of [`HttpPostRequestDecoder`](https://netty.io/4.2/xref/io/netty/handler/codec/http/multipart/HttpPostRequestDecoder.html) explicitly requires calling the following method after the decoder is no longer needed:

```java
postDecoder.destroy();
```

This removes the synthetic request entry from the factory and releases the associated data. The current production code does not destroy the decoder when request processing terminates, so these entries remain reachable through the static factory.

The default implementation of `AbstractServerTransportListener.onDataFinally()` only closes the current inbound message, while `GenericHttp2ServerTransportListener` overrides it with a no-op. Neither path releases the adapted `DefaultHttpRequest` or destroys its cached decoder. Completion of inbound message processing is not the same as completion of the overall request or response lifecycle.

Requests that do not trigger form or parameter parsing, and empty-body requests for which `createPostRequestDecoder()` returns `null`, do not create such entries.

Because `DefaultHttpRequest` lazily creates and caches the decoder, it needs an explicit cleanup mechanism that can be invoked from the terminal server request lifecycle. Cleanup should cover successful completion, failure, cancellation, and transport closure, and should run only after application code can no longer access request parameters or multipart parts.

Destroying the decoder immediately after argument resolution would be unsafe because multipart `FileUpload` objects returned by `part()` or `parts()` still depend on its underlying `HttpData` and may be consumed later by application code.

## Do you have a (mini) reproduction demo?

- [x] Yes, I have a minimal reproduction demo to help resolve this issue more effectively!

## Are you willing to submit a pull request to fix on your own?

- [x] Yes I am willing to submit a pull request on my own!

## Code of Conduct

- [x] I agree to follow this project's [Code of Conduct](https://www.apache.org/foundation/policies/conduct).
