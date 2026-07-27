# 修复并行检索中的 Query Embedding 重复计算

## 问题背景

当一个子问题需要并行检索多个意图或 Collection 时，`AbstractParallelRetriever` 会为每个检索目标创建异步任务。

改动前，每个任务都会调用 `VectorRetrieverService.retrieve`，并独立完成 Query Embedding、向量转换和归一化。单个子问题的并行检索耗时可以简化表示为：

$$
T_{\mathrm{before}}=\max(E_1+R_1,\ldots,E_N+R_N)
$$

改动后只生成一次 Query 向量：

$$
T_{\mathrm{after}}=E+\max(R_1,\ldots,R_N)
$$

其中，$E$ 表示 Query Embedding 及归一化耗时，$R_i$ 表示第 $i$ 个检索目标的查询耗时。

## 改动前

![[Pasted image 20260726162752.png]]


## 改动后

![[Pasted image 20260726162622.png]]


## 主要改动

- 在 `VectorRetrieverService` 中增加 `embedAndNormalize`，复用 Milvus 和 PG 原先各自的向量生成与归一化逻辑。
- 在 `AbstractParallelRetriever.executeParallelRetrieval` 创建异步任务前生成一次 Query 向量，并将同一个只读向量传给所有任务。
- `IntentParallelRetriever` 和 `CollectionParallelRetriever` 复用预计算向量，直接调用 `retrieveByVector`，不再在每个任务中重复生成 Query Embedding。

## 改动边界

- 本次仅去除单次并行检索内，一个子问题因命中多个意图或 Collection 而产生的重复 Embedding、向量转换和归一化。
## 单元测试

新增以下测试场景：

- fan-out 全库检索时，同一个子问题只生成一次 Query 向量。
- 多个意图并行检索时，所有任务复用同一个 Query 向量。

## 性能测试

### 测试环境

- 评测框架：`ragenteval`
- Embedding 模型：硅基流动 `Qwen3-Embedding-8B`
- 并发数：3
- 知识库数量：4
- 对照方式：Baseline 与 Optimized 交替运行三轮，结果取平均值

### 全部请求

| 指标       |     优化前 |       优化后 |         变化 |
| -------- | ------: | --------: | ---------: |
| TTFT P50 | 5053 ms | 4448.5 ms | **-12.0%** |
| TTFT 平均值 | 6452 ms | 6219.5 ms |  **-3.6%** |

### 实际命中多个 KB 的请求

| 指标       |       优化前 |       优化后 |         变化 |
| -------- | --------: | --------: | ---------: |
| TTFT P50 |   8781 ms |   7378 ms | **-16.0%** |
| TTFT 平均值 | 9551.4 ms | 7928.6 ms | **-17.0%** |

