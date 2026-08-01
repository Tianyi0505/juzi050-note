## 一、信号量是什么

信号量 `Semaphore` 是一种**并发控制工具**，用于限制同一时刻使用某项资源的任务数量。

例如，一个 AI 模型最多稳定处理 20 个并发请求：

```text
AI 模型最大并发量：20

正在执行 12 个请求
└── 还可以执行 8 个请求

正在执行 20 个请求
└── 新请求需要等待或返回繁忙
```

信号量适合保护并发能力有限的技术资源，例如：

- AI 模型和 GPU 资源
    
- 第三方接口连接
    
- 文件导出和视频转码
    
- 报表生成
    
- 数据库复杂查询
    
- 爬虫和数据采集
    

通常采用以下模型：

```text
一种受保护资源
└── 一个独立信号量

一个正在执行的任务
└── 占用一个并发名额
```

不同资源使用不同信号量，彼此之间不会相互占用并发容量。

---

## 二、为什么需要信号量

如果大量任务同时使用同一项有限资源，可能导致：

```text
大量任务同时执行
        │
        ▼
CPU、内存、连接或 GPU 占用升高
        │
        ▼
任务执行时间增加
        │
        ▼
超时请求增多
        │
        ▼
下游服务过载
```

加入信号量后：

```text
大量任务到达
        │
        ▼
信号量控制执行并发
        │
        ├── 存在并发名额 → 执行任务
        └── 达到并发上限 → 等待或返回繁忙
```

信号量不会提高资源本身的性能，它的作用是：

> 将并发数量控制在资源能够稳定承受的范围内。

信号量控制的是**同时执行数量**，速率限流器控制的是**单位时间请求数量**：

```text
最多同时执行 10 个任务
└── Semaphore

每秒最多接收 100 个请求
└── RateLimiter
```

---

## 三、为什么需要分布式信号量

JDK 的 `Semaphore` 只能控制当前 JVM 中的线程。

如果服务部署了三个实例，每个实例都设置：

```java
new Semaphore(10);
```

实际效果是：

```text
实例 A：最多 10 个
实例 B：最多 10 个
实例 C：最多 10 个

整个系统最多：30 个
```

如果要求整个系统最多只能同时执行 10 个任务，就需要让所有服务实例共享同一组并发名额：

```text
服务实例 A ──┐
             │
服务实例 B ──┼──► Redis
             │      └── 全局并发名额：10
服务实例 C ──┘
```

Redisson 提供了两种分布式信号量：

```text
RSemaphore
└── 维护全局可用许可证数量

RPermitExpirableSemaphore
├── 维护全局可用许可证数量
├── 为每个许可证生成 permitId
└── 维护许可证到期时间
```

---

## 四、Redis 底层在做什么

### 4.1 RSemaphore

`RSemaphore` 使用 Redis String 保存当前可用许可证数量：

```text
Key：limit:ai:model
Type：String
Value：20
```

获取许可证时，可用数量减一；释放许可证时，可用数量加一。

```text
初始许可证：20

任务 A 获取
└── 20 → 19

任务 B 获取
└── 19 → 18

任务 A 释放
└── 18 → 19
```

获取许可证的核心 Lua 逻辑可以简化为：

```lua
local value = redis.call('get', KEYS[1])

if value ~= false and tonumber(value) >= 1 then
    redis.call('decrby', KEYS[1], 1)
    return 1
end

return 0
```

Lua 将下面两个操作合并成一个原子操作：

```text
检查许可证数量
        +
扣减许可证数量
```

这样，多个服务实例同时竞争最后一个许可证时，只会有一个实例成功。

释放许可证时，Redisson 主要执行：

```text
INCRBY 增加可用许可证
        │
        ▼
PUBLISH 通知等待客户端
        │
        ▼
等待客户端重新竞争
```

### 4.2 RPermitExpirableSemaphore

`RPermitExpirableSemaphore` 除了保存可用许可证数量，还会保存每个许可证的身份和到期时间：

```text
Redis String
└── 当前可用许可证数量

Redis Sorted Set
└── member：permitId
    score：许可证到期时间
```

例如：

```text
permit-A → 20:30 到期
permit-B → 20:31 到期
```

获取许可证时：

```text
回收已经到期的许可证
        │
        ▼
判断是否存在可用许可证
        │
        ├── 否 → 等待或返回失败
        └── 是
              │
              ▼
        可用数量减一
              │
              ▼
        生成 permitId
              │
              ▼
        记录到期时间
```

许可证到期后，对应的并发名额会重新参与分配。

---

## 五、基本使用

### 5.1 RSemaphore

```java
RSemaphore semaphore =
        redissonClient.getSemaphore("limit:ai:model");

semaphore.trySetPermits(20);
```

业务代码：

```java
boolean acquired = false;

try {
    acquired = semaphore.tryAcquire(
            2,
            TimeUnit.SECONDS
    );

    if (!acquired) {
        throw new IllegalStateException(
                "当前模型服务繁忙，请稍后重试"
        );
    }

    invokeModel();
} catch (InterruptedException e) {
    Thread.currentThread().interrupt();
    throw new IllegalStateException(
            "等待并发名额时被中断",
            e
    );
} finally {
    if (acquired) {
        semaphore.release();
    }
}
```

### 5.2 RPermitExpirableSemaphore

```java
RPermitExpirableSemaphore semaphore =
        redissonClient.getPermitExpirableSemaphore(
                "limit:ai:model"
        );

semaphore.trySetPermits(20);
```

获取一个租约为 60 秒的许可证：

```java
String permitId = null;

try {
    permitId = semaphore.tryAcquire(
            2,
            60,
            TimeUnit.SECONDS
    );

    if (permitId == null) {
        throw new IllegalStateException(
                "当前模型服务繁忙，请稍后重试"
        );
    }

    invokeModel();
} catch (InterruptedException e) {
    Thread.currentThread().interrupt();
    throw new IllegalStateException(
            "等待并发名额时被中断",
            e
    );
} finally {
    if (permitId != null) {
        semaphore.tryRelease(permitId);
    }
}
```

推荐按照下面的关系设置时间：

```text
任务正常最大耗时<业务超时时间<许可证租约时间
```

例如：

```text
任务 P99 耗时：35 秒
业务超时时间：50 秒
许可证租约时间：60 秒
```

---

## 六、区别与选型

|对比项|RSemaphore|RPermitExpirableSemaphore|
|---|---|---|
|全局并发控制|支持|支持|
|获取结果|`boolean`|`permitId`|
|许可证到期时间|无单独租约|支持固定租约|
|正常释放|`release()`|`tryRelease(permitId)`|
|实例宕机后的处理|可能造成许可证长期减少|租约到期后回收|
|推荐场景|简单、短时间任务|生产环境分布式并发控制|

普通 `RSemaphore` 的执行流程：

```text
获取许可证
    │
    ▼
可用数量减一
    │
    ▼
任务完成后 release()
    │
    ▼
可用数量恢复
```

如果实例在执行过程中宕机，`release()` 无法执行，可用许可证可能永久减少。

```text
初始许可证：10
第一次异常退出：10 → 9
第二次异常退出：9 → 8
……
```

因此，在生产环境中一般建议优先使用：

```text
RPermitExpirableSemaphore
```

它可以同时覆盖：

```text
任务正常完成
└── 主动释放许可证

服务实例异常退出
└── 固定租约到期后回收许可证
```

最终选型：

```text
单 JVM 并发控制
└── JDK Semaphore

分布式并发控制
└── 优先使用 RPermitExpirableSemaphore

任务很短且可以接受人工恢复
└── 可以使用 RSemaphore

单位时间请求速率控制
└── RRateLimiter
```

## 七、总结

信号量用于限制同一时刻使用某项有限资源的任务数量。

```text
JDK Semaphore
└── 控制单 JVM 并发

RSemaphore
└── 使用 Redis 控制分布式全局并发

RPermitExpirableSemaphore
└── 在全局并发控制基础上
    为每个许可证增加 ID 和固定租约
```

在生产环境中，一般优先使用 `RPermitExpirableSemaphore`，避免服务实例异常退出后，许可证无法归还导致可用并发容量持续减少。