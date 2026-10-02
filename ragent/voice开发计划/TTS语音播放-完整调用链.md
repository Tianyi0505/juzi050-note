# TTS 语音播放完整调用链

本文依据本地分支 `feat/tts` 的当前代码整理，作为时序图的语义依据。文档只记录真实生产入口可达的调用关系，不把线程、普通返回或幂等边界扩展成独立业务参与者。

## 1. 参与对象与职责

| 层次 | 类 / 对象 | 主要职责 |
| --- | --- | --- |
| 浏览器 | `useVoicePlayback.ts` | 建立播放 SSE，接收音频事件，使用 MSE 缓冲并播放；主动停止时发起停止请求并立即清理本地 Audio/MSE。 |
| HTTP 入口 | `VoicePlaybackController` | 创建 `SseEmitter`，转交播放服务；接收停止请求并返回 HTTP 结果。 |
| 播放服务 | `VoicePlaybackServiceImpl` | 生成业务 `taskId`，查询当前用户的 assistant 消息，创建事件处理器，提交异步播放任务。 |
| SSE 回调 | `VoicePlaybackEventHandler` | 注册任务、发送 `audio-meta` / `audio` / `done`，绑定取消句柄，结束 SSE。 |
| 异步执行 | `VoicePlaybackTaskRunner` | 将 TTS 合成提交到 `voicePlaybackExecutor`；它是执行边界，不是时序图中的业务生命线。 |
| 模型路由 | `RoutingTtsService` | 获取候选模型，逐个申请健康许可，等待首帧并决定 `commit` 或切换下一候选。 |
| 首帧桥接 | `BinaryProbeStreamBridge` | 首帧结果未确认前缓冲回调；成功时提交缓冲，失败时丢弃。 |
| TTS 客户端 | `AbstractWebSocketTtsClient` / `BaiLianTtsClient` | 创建 WebSocket 任务会话，分块发送文本，完成或取消供应商任务。 |
| 任务会话 | `WebSocketTaskSession` | 串行控制一个 WebSocket 任务，并在完成或取消后释放连接租约。 |
| 物理连接 | `VoiceConnection` | 管理 WebSocket 与供应商任务状态，转发音频帧及终态。 |
| 连接租约 | `WebSocketConnectionLease` | 正常关闭时归还连接；失效后关闭时销毁连接。 |
| 任务管理 | `StreamTaskManager` | 注册 SSE 任务，保存取消句柄，通过 Redis 标记和 Topic 跨节点通知取消。 |

## 2. 正常播放调用链

### 2.1 浏览器建立播放 SSE

1. `useVoicePlayback.playInternal(messageId)` 创建 `MediaSource` 和 `Audio`。
2. 前端调用 `createStreamResponse`，请求：

   `GET /rag/v3/voice/play?messageId={messageId}`

3. `VoicePlaybackController.play(messageId)` 创建 `SseEmitter`。
4. Controller 调用 `VoicePlaybackServiceImpl.play(messageId, emitter)`。

### 2.2 服务端创建播放任务

1. `VoicePlaybackServiceImpl.play` 生成业务 `taskId`。
2. `loadAssistantMessage` 按以下条件查询消息：

   - 消息 ID 等于 `messageId`；
   - 用户 ID 等于当前用户；
   - 角色为 `assistant`；
   - 未删除。

3. 服务通过 `StreamCallbackFactory` 创建 `VoicePlaybackEventHandler`。
4. `VoicePlaybackEventHandler.initialize` 执行：

   - `StreamTaskManager.register(taskId, sender, ...)`；
   - 绑定 SSE completion、timeout、error 回调；
   - 发送 `audio-meta`，其中携带 `taskId`。

5. `VoicePlaybackServiceImpl` 调用 `VoicePlaybackTaskRunner.run(text, callback)`。
6. `VoicePlaybackTaskRunner` 把 `ttsService.synthesize(text, callback, callback)` 提交到 `voicePlaybackExecutor`。

时序图约定：`VoicePlaybackTaskRunner` 不单列生命线，只在 `VoicePlaybackService / SSE Handler → RoutingTtsService` 的调用上标注“异步执行”。

### 2.3 TTS 路由选择候选模型

1. `RoutingTtsService.synthesize` 调用 `ModelSelector.selectTtsCandidates()` 获取有序候选列表。
2. 对每个 `ModelTarget` 顺序执行：

   1. 按 provider 查找对应 `TtsClient`；
   2. 调用 `ModelHealthStore.allowCall(modelId)` 申请调用许可；
   3. 创建 `BinaryProbeStreamBridge(callback)`；
   4. 调用 `client.synthesize(text, bridge, target)`；
   5. 取得 `StreamCancellationHandle` 后调用 `taskObserver.onTaskStarted(handle)`；
   6. 调用 `bridge.awaitFirstAudio(timeout)` 等待首个有效音频、错误、超时或无内容终态。

3. 首帧成功：

   - `healthStore.markSuccess(modelId)`；
   - `bridge.commit()`；
   - 已缓冲首帧下发给真实 `TtsCallback`；
   - 返回当前候选的取消句柄，不再尝试后续候选。

4. 首帧失败、超时或无内容：

   - `bridge.discard()`；
   - `healthStore.markFailure(modelId)`；
   - `handle.cancel()` 取消本候选任务；
   - 继续下一个候选。

5. 每次候选结束都调用 `releaseHalfOpenPermit(permit)`。
6. 所有候选均失败时，调用业务回调 `onError` 并抛出“所有 TTS 模型均调用失败”。

时序图约定：正常播放图只用注释概括“自动选择可用模型，首帧失败时切换候选”，不展开候选循环、健康检查和 Probe 的内部调用。

## 3. 单个候选的 WebSocket 任务启动

1. `AbstractWebSocketTtsClient.synthesize` 创建适配后的 `VoiceStreamCallback<byte[]>`。
2. 调用 `WebSocketTaskExecutor.openTask(target, taskParam, callback, invalidateOnFinish)`。
3. `WebSocketTaskExecutor.openTask`：

   - 调用 `WebSocketExecutor.acquire(target)`；
   - 按 `modelId` 从连接池借用连接，得到 `WebSocketConnectionLease`；
   - 生成供应商任务 `taskId`；
   - 调用 `VoiceConnection.startTask`；
   - 返回 `WebSocketTaskSession`。

4. `VoiceConnection.startTask` 将状态从 `IDLE` 迁移为 `TASK_STARTING`。
5. 百炼实现发送 `run-task`，等待 `task-started`。
6. 收到 `task-started` 后，连接进入 `TASK_RUNNING`。
7. 客户端按协议长度切分文本，对每个非空分片调用 `session.send(chunk)`，最终调用 `session.finish()`。
8. 百炼协议对应为：

   - 每个文本分片发送一次 `continue-task`；
   - 文本发送完毕后发送 `finish-task`。

9. `AbstractWebSocketTtsClient.synthesize` 返回 `session::cancel` 作为取消句柄。
10. `VoicePlaybackEventHandler.onTaskStarted` 将包装后的句柄绑定到 `StreamTaskManager`。

注意：业务 `taskId` 和供应商 WebSocket 任务 `taskId` 不是同一个值。前者用于播放停止接口和任务管理，后者由 `WebSocketTaskExecutor` 为单次供应商任务生成。

## 4. MP3 音频帧返回与浏览器播放

每个 MP3 二进制帧沿固定链路传递：

1. 百炼 CosyVoice 向 WebSocket 返回二进制帧。
2. `VoiceConnection.Listener.onMessage(ByteString)`：

   - 更新最后收包时间；
   - 唤醒任务结束等待；
   - 调用 `decodeBinaryMessage` 转为 `byte[]`；
   - 调用当前 `VoiceStreamCallback.onPacket`。

3. `AbstractWebSocketTtsClient` 的适配回调调用 `TtsCallback.onAudio`。
4. 在首帧 Probe 尚未提交时，`BinaryProbeStreamBridge` 先缓冲该回调；`commit()` 后执行缓冲并让后续音频直接透传。
5. `VoicePlaybackEventHandler.onAudio` 将音频编码为 Base64，发送 SSE `audio` 事件。
6. 前端收到 `audio`：

   - Base64 解码为 `Uint8Array`；
   - 放入 `appendQueue`；
   - 依次调用 `SourceBuffer.appendBuffer`；
   - 首帧入缓冲后调用 `audio.play()`。

该链路会对每个 MP3 音频帧重复，因此在正常播放时序图中使用唯一的 `loop [MP3 音频帧]`。

## 5. 正常结束与连接复用

1. 百炼返回 `task-finished`。
2. `BaiLianTtsConnection.handleTextMessage` 调用 `markTaskFinished()`。
3. `markTaskFinished()` 先调用业务 `VoiceStreamCallback.onComplete()`，再完成 `taskFinished` Future。
4. 完成回调沿以下链路传递：

   `VoiceConnection → AbstractWebSocketTtsClient → BinaryProbeStreamBridge → VoicePlaybackEventHandler`

5. `VoicePlaybackEventHandler.onComplete`：

   - 发送 SSE `done`；
   - `StreamTaskManager.unregister(taskId)`；
   - `SseEmitterSender.complete()` 关闭 SSE。

6. 前端收到 `done`：

   - 标记流已结束；
   - 等待 append 队列排空；
   - 调用 `MediaSource.endOfStream()`；
   - 音频自然播放结束。

7. 后台 `WebSocketTaskSession.finishTask` 在供应商终态后继续：

   - `VoiceConnection.completeTask` 将 `TASK_FINISHING` 迁移为 `IDLE`；
   - 清理当前任务上下文；
   - `lease.close()`。

8. 租约未失效时，`WebSocketConnectionLease.close()` 调用 `pool.returnObject(connection)`，连接回到对应 `modelId` 的池中复用。

## 6. 用户主动停止调用链

### 6.1 前端发起停止并立即清理本地播放器

`useVoicePlayback.stopInternal()` 的顺序是：

1. 保存当前停止请求函数；
2. 清空 `streamRef` 和 `requestStopRef`，使前端忽略该播放流的后续业务事件；
3. 若已经收到业务 `taskId`，立即异步发送：

   `POST /rag/v3/voice/stop?taskId={taskId}`

4. 暂停并清理 `Audio`；
5. 回收 Object URL；
6. 尝试 `MediaSource.endOfStream()`；
7. 清空 SourceBuffer 和 append 队列。

`stopInternal()` 没有调用播放流的 `stream.cancel()`，所以这里不会主动中断原 SSE。停止接口请求和本地播放器清理不等待彼此完成；原 SSE 保持到后端完成异步取消后关闭。

### 6.2 HTTP 停止请求只负责发布取消通知

1. `VoicePlaybackController.stop(taskId)` 调用 `VoicePlaybackServiceImpl.stop(taskId)`。
2. Service 调用 `StreamTaskManager.cancel(taskId)`。
3. `StreamTaskManager.cancel`：

   - 写入 Redis 取消标记并设置 TTL；
   - 向 `ragent:stream:cancel` Topic 发布 `taskId`。

4. 发布完成后方法返回，Controller 返回 HTTP 200。

HTTP 请求链与真正的本地取消链不是同一个同步调用栈，时序图必须分为两个阶段。

### 6.3 Topic 监听器执行本地取消

1. `StreamTaskManager` 的 Topic 监听器收到 `taskId`。
2. 调用 `cancelLocal(taskId)`。
3. 找到本地任务后设置 canceled 状态。
4. 调用任务绑定的 `StreamCancellationHandle.cancel()`。
5. 该句柄由 `VoicePlaybackEventHandler` 包装，内部继续调用 TTS 客户端返回的取消句柄。
6. TTS 取消句柄实际为 `WebSocketTaskSession.cancel()`。

7. `handle.cancel()` 同步等待 WebSocket 任务进入取消终态并完成连接释放。
8. 随后 `StreamTaskManager` 通过原 SSE 发送 `cancel`、`done`，并调用 `sender.complete()` 关闭 SSE。由于前端已清空 `streamRef`，这些事件不会再改变本地播放器状态，但会正常结束网络流。

## 7. WebSocket 取消与连接销毁

1. `WebSocketTaskSession.cancel()` 首先调用 `lease.invalidate()`，明确禁止当前连接复用。
2. Session 将自身生命周期迁移为 `CANCELLING`。
3. 调用 `VoiceConnection.cancelTask(providerTaskId)`。
4. `VoiceConnection` 将任务状态迁移为 `TASK_CANCELLING`。
5. 百炼实现发送：

   `finish-task`，其中 `directive=cancel`。

6. Connection 等待供应商取消终态：

   - 供应商可返回 `task-finished`；
   - 也可能用 `task-failed` 或连接关闭响应取消。

7. 取消路径不再复用连接：正常完成取消等待后，`completeTask` 将状态设为 `BROKEN`；取消期间收到失败或关闭也会进入 `BROKEN`。
8. `WebSocketTaskSession.cancel()` 的 finally 块调用 `lease.close()`。
9. 因租约已失效，`WebSocketConnectionLease.close()` 调用 `pool.invalidateObject(connection)`。
10. 连接池销毁该对象，并调用 `VoiceConnection.close()` 关闭物理 WebSocket，最终状态为 `CLOSED`。

停止时序图只保留这些有业务语义的节点：

`POST stop + 清理本地播放器 → 发布取消通知 → cancelLocal → 取消 WebSocket 任务 → 供应商取消终态 → 销毁连接 → SSE cancel/done → 关闭 SSE`

不展示普通的 Java 方法退栈返回。

## 8. SSE 结束方式对照

| 场景 | SSE 的关闭时机 | 后端动作 | WebSocket 连接结果 |
| --- | --- | --- | --- |
| 正常播放完成 | 后端发送 `done` 后调用 `sender.complete()` | 注销任务 | `IDLE`，租约归还连接池 |
| 用户主动停止 | 后端异步取消完成后发送 `cancel` / `done`，再调用 `sender.complete()` | 前端立即停止本地播放；后端发布通知并取消供应商任务 | `BROKEN`，租约失效并销毁连接 |
| SSE 异常、超时或非主动断开 | `VoicePlaybackEventHandler` 绑定的 emitter 回调触发取消 | 调用 `StreamTaskManager.cancel` | 进入取消链，连接不复用 |

## 9. 时序图绘制约束

时序图遵循以下规则：

1. 只保留正常播放和主动取消两张时序图。
2. 时序图表达功能协作，不按照代码逐方法展开；候选模型、首帧 Probe、租约和状态机等细节保留在本文中。
3. 正常播放图只保留一个 `loop [流式音频帧]`，候选选择用一条注释概括。
4. 所有跨生命线消息都是同一 Y 坐标的水平线。
5. 所有自调用只使用水平—竖直—水平的直角折线。
6. 禁止斜线、曲线和自动产生的斜向回调线。
7. 消息必须连接激活期，不直接连接裸生命线。
8. 阶段标签和 `loop` 标签不得遮挡激活期或消息文字。
9. 普通 Java 方法返回不画；只保留会改变功能流程的响应或事件。
10. 正常完成只表达“完成 SSE、播放剩余缓冲、连接可复用”。
11. 主动取消表达“立即停止本地播放、异步取消远端任务、连接不再复用并销毁、后端关闭 SSE”。
