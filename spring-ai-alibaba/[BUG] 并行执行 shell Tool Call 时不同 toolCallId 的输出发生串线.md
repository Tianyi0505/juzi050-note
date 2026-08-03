## Is there an existing issue for this?

- [x] I have searched the existing issues

## Current Behavior

开启 `parallelToolExecution(true)` 后，同一次 `ReactAgent` 执行中共享同一持久 `ShellSession` 的两个 `shell` Tool Call 被并发执行，命令执行和 Tool Response 相互干扰，出现输出混入、缺失或错配，无法稳定关联到对应的 `toolCallId`。

## Expected Behavior

同一持久 Shell 会话中的命令应保持调用级隔离，每个 Tool Response 只包含对应 `toolCallId` 的命令输出。

## Steps To Reproduce

核心复现测试如下。测试通过 `StubChatModel` 固定返回两个 `shell` Tool Call，并使用同一个持久 `cmd.exe` 会话执行。

```java
private static final AssistantMessage MODEL_RESPONSE = AssistantMessage.builder()
        .content("")
        .toolCalls(List.of(
                new AssistantMessage.ToolCall("call-one", "function", "shell",
                        "{\"command\":\"powershell.exe -NoProfile -Command \\\"Start-Sleep -Milliseconds 100; 1..5 | ForEach-Object { Write-Output 'shell-call-one'; Start-Sleep -Milliseconds 50 }\\\"\"}"),
                new AssistantMessage.ToolCall("call-two", "function", "shell",
                        "{\"command\":\"powershell.exe -NoProfile -Command \\\"Start-Sleep -Milliseconds 100; 1..5 | ForEach-Object { Write-Output 'shell-call-two'; Start-Sleep -Milliseconds 50 }\\\"\"}")))
        .build();

@Test
void parallelShellCallsShouldKeepResponsesIsolated() throws Exception {
    StubChatModel model = new StubChatModel();
    ShellTool2 shell = ShellTool2.builder(Path.of("..").toAbsolutePath().normalize().toString())
            .withShellCommand(List.of("cmd.exe", "/Q", "/D", "/K"))
            .withCommandTimeout(10000)
            .build();
    ReactAgent agent = ReactAgent.builder()
            .name("parallel-shell-repro")
            .model(model)
            .hooks(List.of(ShellToolAgentHook.builder().shellTool2(shell).build()))
            .parallelToolExecution(true)
            .build();

    assertEquals("done", agent.call("Run both shell commands and return their results", RunnableConfig.builder()
            .threadId("parallel-shell-repro")
            .build()).getText());
    assertEquals(2, model.toolResponse.getResponses().size());

    assertAll(() -> assertResponse(model, 0, "shell-call-one", "shell-call-two"),
            () -> assertResponse(model, 1, "shell-call-two", "shell-call-one"));
}

private static void assertResponse(StubChatModel model, int index, String expectedOutput, String unexpectedOutput) {
    AssistantMessage.ToolCall call = MODEL_RESPONSE.getToolCalls().get(index);
    ToolResponseMessage.ToolResponse response = model.toolResponse.getResponses()
            .stream()
            .filter(item -> item.id().equals(call.id()))
            .findFirst()
            .orElseThrow();
    String actual = response.responseData();
    assertAll(() -> assertTrue(actual.contains(expectedOutput),
            () -> call.id() + " expected response containing [" + expectedOutput
                    + "], but actual response was: " + actual),
            () -> assertFalse(actual.contains(unexpectedOutput),
                    () -> call.id() + " expected isolated output without [" + unexpectedOutput
                            + "], but actual response was: " + actual));
}

private static ChatResponse response(AssistantMessage message) {
    return new ChatResponse(List.of(new Generation(message)));
}

private static final class StubChatModel implements ChatModel {
    private ToolResponseMessage toolResponse;

    @Override
    public ChatResponse call(Prompt prompt) {
        toolResponse = prompt.getInstructions().stream()
                .filter(ToolResponseMessage.class::isInstance)
                .map(ToolResponseMessage.class::cast)
                .findFirst()
                .orElse(null);
        return response(toolResponse == null ? MODEL_RESPONSE : new AssistantMessage("done"));
    }

    @Override
    public Flux<ChatResponse> stream(Prompt prompt) {
        return Flux.just(call(prompt));
    }
}
```

## Environment

```text
Spring AI Alibaba：1.1.2.2
分支：main
Commit：dc6fcadca81ed48e0c7a8ed35920ecb06c26f0e3
JDK：Microsoft OpenJDK 21.0.12
操作系统：Windows 11 64 位
Shell：cmd.exe 持久会话
```

## Debug logs

```text
21:22:56.302 [parallel-node-action-thread-2] INFO  c.a.c.a.graph.agent.tools.ShellTool2 - Executing shell command: powershell.exe -NoProfile -Command "Start-Sleep -Milliseconds 100; 1..5 | ForEach-Object { Write-Output 'shell-call-two'; Start-Sleep -Milliseconds 50 }"
21:22:56.302 [parallel-node-action-thread-1] INFO  c.a.c.a.graph.agent.tools.ShellTool2 - Executing shell command: powershell.exe -NoProfile -Command "Start-Sleep -Milliseconds 100; 1..5 | ForEach-Object { Write-Output 'shell-call-one'; Start-Sleep -Milliseconds 50 }"

call-one expected isolated output without [shell-call-two], but actual response contained [shell-call-two]
call-two expected response containing [shell-call-two], but actual response did not contain it and contained [shell-call-one]
```

## Anything else?

两个 Tool Call 并发操作同一个持久 `ShellSession` 的共享 `stdin` 和 `outputQueue`，而命令写入和输出收集缺少调用级隔离，导致命令执行及 Tool Response 相互干扰。

一个可能的修复方向是在 `AgentToolNode` 调度层声明并识别工具的并发能力：同一不支持并发重入的工具按 Tool Call 顺序执行，支持并发的工具以及不同工具仍保持并行。

> 我愿意完成这个 Issue 的修复并提交 PR。
