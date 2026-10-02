1. LLM Gateway / Proxy 2. Token Metering & Billing System 3. Streaming Response Infrastructure 4. RAG Serving Pipeline 5. Semantic Cache Layer 6. Async Agent Job Queue 7. Tool Execution Sandbox 8. Multi-Tenant Knowledge Base 9. Prompt & Config Versioning Service 10. Eval Pipeline Backend 11. LLM Observability 12. Webhook & Event Fan-out 13. Context Assembly Service 14. Guardrails Middleware 15. Model Fallback & Routing Engine
参考视频：[agent 15个小知识点（比较基础）](【agent 15个小知识点（比较基础）】https://www.bilibili.com/video/BV11yhN6iE37?vd_source=1258e036eb41f172b62821a57f402efa)
本文在参考视频上添加了真实项目的代码演示。如有侵权行为，会立刻删除文章。
代码来源：[ragent](https://github.com/nageoffer/ragent)
很多地方只讲了代码里大概的思路，具体取舍可以参考 ragent 项目的知识星球付费文档。
# LLM Gateway / Proxy

## 核心思想

- 从底层屏蔽不同厂商的API差异
- 内置重试、熔断与故障自动转移
- 按 apikey 做限流管控

## 重要性

- 在框架搭建完后，接入成本降低
- 避免单个模型故障从而击垮整条链路
- 避免单个 apikey 在大模型服务端触发拒绝策略，使得该模型被误判为模型挂掉

## 代码

### 前置幂等和限流

```java
@IdempotentSubmit(  
        key = "T(com.nageoffer.ai.ragent.framework.context.UserContext).getUserId()",  
        message = "当前会话处理中，请稍后再发起新的对话"  
)  
@GetMapping(value = "/rag/v3/chat", produces = "text/event-stream;charset=UTF-8")  
public SseEmitter chat(@RequestParam @ChatQuestion String question,  
                       @RequestParam(required = false) String conversationId,  
                       @RequestParam(required = false, defaultValue = "false") Boolean deepThinking) {  
    SseEmitter emitter = new SseEmitter(ragDefaultProperties.getSseTimeoutMs());  
    ragChatService.streamChat(question, conversationId, deepThinking, emitter);  
    return emitter;  
}
```

**核心思路**：利用 @IdempotentSubmit 实现用户级别幂等
**代码缺陷**：目前粒度以用户为级别，一个用户只能拥有一个任务，粒度过粗。


```java
public void acquire(AcquireRequest req) {  
    Ticket ticket = new Ticket(req);  
    if (req.cancelBinder() != null) {  
        req.cancelBinder().accept(ticket::cancel);  
    }  
    // entry 存活标记必须先于入队写入，否则 race 窗口内的并发 claim 会把刚入队的条目当僵尸 ZREM    setEntryMarker(ticket.requestId, req.maxWaitMillis());  
    RScoredSortedSet<String> queue = redissonClient.getScoredSortedSet(queueKey, StringCodec.INSTANCE);  
    queue.add(nextQueueSeq(), ticket.requestId);  
    if (tryAcquireIfReady(ticket)) {  
        return;  
    }  
    scheduleQueuePoll(ticket);  
}
```

**核心思路**：采用 Redisson 的信号量实现限流。
### 模型路由

```java
@RagTraceNode(name = "llm-chat-routing", type = "LLM_ROUTING")  
public String chat(ChatRequest request) {  
    return executor.executeWithFallback(  
            ModelCapability.CHAT, 
            selector.selectChatCandidates(Boolean.TRUE.equals(request.getThinking())),  
            target -> clientsByProvider.get(target.candidate().getProvider()),  
            (client, target) -> client.chat(request, target)  
    );  
}
```

```java
public <C, T> T executeWithFallback(  
        ModelCapability capability,  
        List<ModelTarget> targets,  
        Function<ModelTarget, C> clientResolver,  
        ModelCaller<C, T> caller) {  
    String label = capability.getDisplayName();  
    if (targets == null || targets.isEmpty()) {  
        throw new RemoteException("No " + label + " model candidates available");  
    }  
  
    Throwable last = null;  
    for (ModelTarget target : targets) {  
        C client = clientResolver.apply(target);  
        if (client == null) {  
            log.warn("{} provider client missing: provider={}, modelId={}", label, target.candidate().getProvider(), target.id());  
            continue;  
        }  
        if (healthStore.allowCall(target.id()) == null) {  
            continue;  
        }  
  
        try {  
            T response = caller.call(client, target);  
            healthStore.markSuccess(target.id());  
            return response;  
        } catch (Exception e) {  
            last = e;  
            healthStore.markFailure(target.id());  
            log.warn("{} model failed, fallback to next. modelId={}, provider={}", label, target.id(), target.candidate().getProvider(), e);  
        }  
    }  
  
    throw new RemoteException(  
            "All " + label + " model candidates failed: " + (last == null ? "unknown" : last.getMessage()),  
            last,  
            BaseErrorCode.REMOTE_ERROR  
    );
```

| 参数               | 当前调用中的实际类型                          | 作用             |
| ---------------- | ----------------------------------- | -------------- |
| `capability`     | `ModelCapability`                   | 说明当前调用的是聊天模型   |
| `targets`        | `List<ModelTarget>`                 | 按顺序排列的候选模型     |
| `clientResolver` | `Function<ModelTarget, ChatClient>` | 根据候选模型找到对应客户端  |
| `caller`         | `ModelCaller<ChatClient, String>`   | 真正调用客户端，并返回字符串 |

**核心思路**：按照自定义优先级排序去尝试每个模型是否可用。
可用->使用该模型，将模型标记为健康，不可用->使用下一个模型，并且增加该模型的失败次数，达到一定次数进行熔断。
具体的熔断机制和熔断恢复机制可以看具体代码，在此处不做具体展开。

# Token Metering & Billing System

## 核心思想

- 精确统计每个用户的输入输出 Token
- 处理异常边界条件，如流式输出中断、部分生成等场景

## 重要性

AI 产品的成本不止有固定的服务器成本，还有 token 的成本。必须去精确计量实现管控，如果没有精确计量，这个产品很容易出现“用户越活跃，公司亏得越多”。

## 代码

该项目目前还处在快速迭代中，统计价格的优先级较低。

# Streaming Response Infrastructure

## 核心思想

- 基于 SSE/WebSocket 实现逐字返回
- 需要处理背压、断线重连与部分失败续传
- 需要压缩首字延迟

## 重要性

- 用户对 AI 产品的感知主要取决于首字延迟，而不是总生成时间
- 允许用户离开前端页面后再返回查看进度

## 代码

**代码缺陷**：目前代码中将网页关闭视作关闭连接，切换/关闭会话会直接停止任务。（计划提交issue中）

### 发起请求后返回给前端SseEmitter
```java
public SseEmitter chat(@RequestParam @ChatQuestion String question,  
                       @RequestParam(required = false) String conversationId,  
                       @RequestParam(required = false, defaultValue = "false") Boolean deepThinking) {  
    SseEmitter emitter = new SseEmitter(ragDefaultProperties.getSseTimeoutMs());  
    ragChatService.streamChat(question, conversationId, deepThinking, emitter);  
    return emitter;  
}
```

### SseEmitter 绑定取消事件

```java
public void enqueue(String question, String conversationId, SseEmitter emitter, Runnable onAcquire) {  
    if (!Boolean.TRUE.equals(rateLimitProperties.getGlobalEnabled())) {  
        try {  
            chatEntryExecutor.execute(onAcquire);  
        } catch (RejectedExecutionException ex) {  
            log.warn("直通分支线程池拒绝任务，转 reject 流程", ex);  
            handleReject(question, conversationId, emitter);  
        }  
        return;  
    }  
  
    chatRateLimiter.acquire(AcquireRequest.builder()  
            .maxWaitMillis(TimeUnit.SECONDS.toMillis(rateLimitProperties.getGlobalMaxWaitSeconds()))  
            .onAcquired(TtlRunnable.get(onAcquire))  
            .onTimeout(TtlRunnable.get(() -> handleReject(question, conversationId, emitter)))  
            .onAcquiredExecutor(chatEntryExecutor)  
            .cancelBinder(cancel -> {  
                emitter.onCompletion(cancel);  
                emitter.onTimeout(cancel);  
                emitter.onError(e -> cancel.run());  
            })  
            .build());  
}
```

# RAG Serving Pipeline

## 核心思想

- 离线入库：摄取->数据清洗（可选）->分块->向量化->建索引
- 在线检索：加载记忆->问题改写->意图路由->并行粗检索->RRF重排序->精排序->生成答案

## 重要性

RAG 的质量不止由向量数据库决定，而是由整条流水线决定。chunk 差、metadata不准、记忆过期、意图识别错，都会让模型产生错误的回答。

## 代码

### 离线入库

### 在线检索

# 5. Semantic Cache Layer

## 核心思想

- 用 Embedding 相似度判断问题是否问过
- 最省钱的 Token，是从未生成过的那个

## 重要性

LLM 调用成本高、延迟高，但很多用户问题语义高度重复。使用语义缓存能同时降低 token 成本、提高吞吐和响应速度。