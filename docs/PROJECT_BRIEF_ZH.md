# HarnessForge：国内 Agent / Harness 岗位项目证据卡

> 使用方式：简历保留“一句话定位 + 3 条经历”；面试按 60 秒版本展开。所有数字均可从
> 仓库内的机器可读 scorecard 复核，不把开发集、预测值或不同协议实验拼成因果提升。

## 简历可直接使用

**HarnessForge｜Self-Harness Coding Agent 运行与评测框架**  
Python · asyncio · Anthropic API · Docker · Pydantic · pytest

- 针对 Coding Agent 长任务中断、上下文膨胀与 Harness 改动难以验证的问题，设计可恢复、
  可分叉的 Agent Runtime，在 turn boundary 原子提交对话、预算账本和版本化工作区快照；
  受控崩溃实验复用 **2 次模型调用 / 2,845 tokens**，恢复过程重放 **0 次**历史调用并通过
  独立 grader。
- 构建 `轨迹挖掘 → 多候选生成 → 隔离配对评测 → 回归门禁 → 晋升/拒绝` 的
  Self-Harness 闭环；真实完成 **3 轮无人干预 Campaign、6 个 live-model candidate
  gates、2 次自动轮次切换**，晋升 1 个、拒绝 5 个，并在外部配对实验中确认
  **steps/run 降低 6.94%**（95% CI 不跨 0）。
- 在冻结且不参与开发的 Terminal-Bench 2.0 子集上完成 **8 题 × 2 次 = 16 runs**，获得
  **11/16 = 68.75% Pass Rate**（Wilson 95% CI **44.4%–85.8%**，infra error
  **0/16**）；另实现同前缀 counterfactual 评测，5 个任务节省 **30,307 tokens
  （28.9%）**，并因 outcome agreement 仅 3/5 将其限定为候选筛选而非完整评测替代。

如果版面只能放两条，保留前两条，并把 `68.75%` 放在项目标题下一行的结果摘要中。

## 60 秒项目介绍

HarnessForge 解决的不是“再写一个会调用工具的 Agent”，而是 Coding Agent 的两个工程
问题：第一，长任务可能因为进程故障、上下文和预算耗尽而丢失已付费进度；第二，修改
prompt、policy 或工具策略后，很难判断成功率变化究竟来自真实改进还是随机波动。

因此我把系统拆成 Runtime 和 Self-Harness 两层。Runtime 负责强制验证、token/cost
ledger、原子 checkpoint、workspace rollback、resume 和 exact-prefix fork；Self-Harness
从失败 trace 中挖掘模式，生成多个声明式候选，在同一父 revision 上隔离评测，通过目标
任务、回归任务和统计门禁后才晋升，并把失败候选写入跨轮 memory。最终我完成了三轮
无人干预 Campaign，同时用 Terminal-Bench holdout、配对实验和受控崩溃分别验证能力、
效率与可靠性，而不是把不同分母压成一个“综合分数”。

## 系统主链路

```text
任务 / 冻结协议
      ↓
Agent Runtime ── trace + token/cost ledger ── atomic checkpoint / resume
      ↓
失败轨迹聚类 → LLM failure mining → 多候选 Harness diff
      ↓
同一父 revision 隔离验证 → target gate + regression gate + paired statistics
      ↓
promote 最优候选 / reject 并写入 dead-end memory
      ↓
下一轮 Campaign（隔离 revision、自动切换、预算熔断、可续跑）
```

工程上最重要的约束是：候选不能靠提高 step/token/cost 上限获得“提升”；兄弟候选必须
来自同一 immutable parent；Campaign 的 proposal 必须读取当前轮已经进化的隔离 Harness；
已完成轮次不能因进程在总报告落盘前退出而重复付费。

## 指标口径

| 指标 | 数据 | 测量方法 | 结论边界 |
|---|---:|---|---|
| 外部 Pass Rate | **11/16 = 68.75%** | Terminal-Bench 独立 grader；8 个冻结 holdout 任务各运行 2 次；Wilson CI | 项目级外部子集成绩，不是官方 89 题榜单 |
| Self-Harness Campaign | **3 rounds / 6 gates / 1 promote / 5 reject** | Campaign 审计报告与每轮 candidate verdict | 证明多轮闭环无人干预运行，不证明成功率单调上升 |
| 外部步骤效率 | **−6.94%** | 10 个共享任务的 treatment − control 配对差；任务级 bootstrap 95% CI | CI 不跨 0，确认 steps 改善；Pass Rate 提升未确认 |
| Crash recovery | **2 calls / 2,845 tokens reused；0 replay** | checkpoint 后以 exit code 86 强制退出，resume 后核对 ledger、快照与 grader | 受控机制实验，不是生产可用性 SLO |
| Counterfactual 成本 | **−30,307 tokens（−28.9%）** | 5 个任务 exact-prefix continuation 对 full rerun | 低成本候选筛选；agreement 3/5，不等价于 full eval |
| 历史 Campaign agent 成本 | **$6.1404**（报告值） | 244 个 agent task-runs 的结果账本；trace 可重建为 $6.140638 | 历史 miner/proposer 成本未记录，不能称为 Campaign 总成本 |

新的 Campaign 会把 agent trace 与 miner/proposer 调用分别写入持久化账本，汇总 calls、
input/output tokens 和 USD；`--max-campaign-cost-usd` 在阶段边界熔断，状态为
`budget_exhausted` 时可提高上限续跑。正在执行的阶段可能略微超出阈值，因此它是安全
上限而不是 provider 级事务配额。

## 高频追问

### 1. 你们到底解决的是 Coding Agent 运行不稳定，还是 Self-Improvement？

两者是上下层关系。Runtime 先解决长任务的状态一致性、故障恢复、预算与验证纪律；
Self-Harness 再把运行 trace 变成可评测的 Harness 候选。没有稳定 Runtime，失败数据和
Before/After 实验都不可信；没有 Self-Harness，可靠性能力又无法形成自动迭代闭环。

### 2. Self-Harness 为什么没有每轮持续提高成功率？

真实 stochastic agent 的逐轮 Pass Rate 不应被假设为单调。开发集轨迹为
`55.6% → 75.0% → 63.9% → 72.2%`，波动本身说明单次点估计不可靠。Self-Harness 的
承诺是持续提出、隔离验证并拒绝没有证据的改动，而不是无条件修改 Harness。6 个候选只
晋升 1 个、拒绝 5 个，正是门禁在工作。总体 Pass Rate 的因果提升仍需 round-0 与最终
revision 在独立 holdout 上做同协议 A/B。

### 3. 68.75% 比原来的 47.5% 高，能说提升了 21.25 个百分点吗？

不能。47.5% 来自 Haiku、20 个开发任务 × 2；68.75% 来自 Sonnet、8 个冻结 holdout
任务 × 2，任务、模型、Harness revision 和预算都不同。68.75% 是当前外部能力结果，
不是相对 47.5% 的因果 uplift。

### 4. 为什么只测 8 题？成绩够不够强？

8 题 × 2 已经比只跑一次或自建题更可信，因为任务冻结、使用外部 grader 且报告了所有
16 个结果，但 Wilson 区间仍较宽，所以只能称为有质量的项目级证据。它的竞争力来自
“外部 holdout + 重复运行 + 统计区间 + 完整失败口径”，不能包装成官方全量榜单。

### 5. 为什么一个候选观测到 4/5 对 3/5 仍然拒绝？

配对 Pass Rate delta 虽为 +0.20，但 95% CI 为 `[-0.40, +0.80]`、McNemar p=1.0；
同时 tokens 增加 6.64%、cost 增加 6.97%。质量提升未确认且效率显著退化，因此按预先
声明的门禁拒绝。这个案例比只展示成功候选更能说明评测系统会抵抗小样本噪声。

### 6. 成本是怎么测出来的？20 美元预算会不会失控？

每次 `llm_response` 记录 input/output tokens，根据固定 pricing revision 计算 USD；
miner/proposer 结构化调用使用独立 meta ledger，Campaign 汇总两部分且保留中断归档的
真实花费。预算检查发生在 baseline、mining、proposal 和 candidate validation 等阶段
边界；达到阈值后不启动下一阶段，并能从最后完成轮次续跑。

### 7. 为什么 exact-prefix fork 结果和 full rerun 只有 3/5 一致？

fork 固定了候选决策前的历史，适合比较“同一状态下换 Harness 会发生什么”；full rerun
还包含前缀采样差异，回答的是端到端总体表现。两者估计对象不同，所以我把 fork 用作
低成本筛选和诊断，最终晋升仍要求完整评测，没有用 28.9% 节省掩盖 3/5 agreement。

## 不能说的三句话

- “Self-Harness 显著提高了总体 Pass Rate。”——当前外部配对 Pass Rate CI 跨 0。
- “系统连续三轮自动提高成功率。”——完成三轮是真的，但逐轮结果非单调。
- “Terminal-Bench 2.0 官方成绩是 68.75%。”——这是冻结的 8 题子集，不是全量榜单。

更准确的总结是：

> 我实现了证据驱动的 Self-Harness：它能在无人干预的多轮 Campaign 中挖掘失败、搜索
> 候选、隔离评测并拒绝噪声改动；当前已确认外部步骤效率提升和运行恢复能力，总体
> Pass Rate 的因果提升仍保持为未确认。

## 证据入口

- [中文 Benchmark 说明](BENCHMARK_ZH.md)
- [Self-Harness Claim Card](data/selfharness_scorecard.json)
- [三轮 Campaign Scorecard](data/selfharness_campaign_v2_scorecard.json)
- [Benchmark 总表](data/benchmark_scorecard.json)
- [Self-Harness 因果证明协议](SELF_HARNESS_EVIDENCE.md)
- [简历英文素材](RESUME_BULLETS.md)
