资料来源：[agentic-ai-guide-zh](https://github.com/Chasing1020/agentic-ai-guide-zh)
# Prompt 链
![[Pasted image 20260826203919.png]]
## 核心思想
本质上是一个固定的workflow，应用场景为固定的工作流。
# Routing模式

![[Pasted image 20260826200826.png]]
## 核心思想

根据问题路由到不同的agent，使用不同的prompt来提效，即 review 采用一套prompt，Code 采用一套 prompt。

# 并行化

## 模式区分
- 分段：把大的问题分解为互不影响的子问题，并行做，例如：风格审查 | 性能审查 | 安全审查，三个可以并行去做。或者用git worktree隔离并行开发多个功能。
- 投票：把同一个问题，使用不同的随机数种子或者温度，对同一 prompt 进行多次输入，最终由奖励函数或者 LLM-as-judge 去选择最终的答案。
# Orchestrator-Workers
![[Pasted image 20260826204106.png]]
## 核心思想
将大任务拆解为小任务并行开发，最终需要处理冲突。
# Evaluator-Optimizer
![[Pasted image 20260826204754.png]]
## 核心思想
一个双模型反馈循环 ：生成器产出候选输出，由独立的评估器依据显式标准对其打分。若得分 低于阈值，则将评估器的评论追加到生成器的上下文中，循环往复，直到达到质量标准或耗尽重试 预算。
适用于具有明确质量标准的任务。