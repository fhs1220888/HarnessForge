# HarnessForge Benchmark：面向招聘的证据说明

> 一句话定位：HarnessForge 是一套带统计评测门禁的 Self-Harness——从 Coding Agent
> 轨迹中自动挖掘失败模式、生成声明式 Harness 候选，通过隔离的 Before/After 配对
> 实验决定晋升或拒绝，同时提供预算控制、可恢复执行与同前缀对照评测。

投递和面试时优先使用更紧凑的
[国内岗位项目证据卡](PROJECT_BRIEF_ZH.md)，本页保留完整 benchmark 口径。

![HarnessForge benchmark evidence](figures/industrial/15-readme-hero.png)

## 30 秒版本

我实现了一套可恢复、可分叉、可评测的 Coding Agent Harness。在冻结的
Terminal-Bench 2.0 holdout 上，用 8 个未参与开发的任务、每题 2 次独立运行，共
16 次外部 grader 评测，得到 **11/16（68.75%）** 的通过率，Wilson 95% 区间为
**[44.4%, 85.8%]**，基础设施错误 **0/16**。除了最终成功率，我还量化了系统机制：
配对外部实验把步骤数降低 **6.94%**，同前缀候选评测节省 **28.9%** token/成本，
受控进程崩溃恢复时复用了 2 次调用、2,845 个已付费 token，前缀重放为 **0**。

## 招聘方应该先看到的结果

| 证据层级 | 指标 | 结果 | 能证明什么 |
|---|---|---:|---|
| 外部能力（主指标） | Terminal-Bench holdout | **11/16 = 68.75%**；95% CI **[44.4%, 85.8%]** | Harness 在冻结外部任务上的端到端完成能力 |
| 运行可靠性 | 基础设施错误 | **0/16** | 本次 holdout 没有因评测管线故障丢失样本 |
| 外部配对效率 | steps/run | **−6.94%**；95% CI **[−13.3%, −1.6%]** | 验证纪律在相同任务上减少无效步骤；区间不跨 0 |
| 评测效率 | 同前缀 continuation | **−30,307 token（−28.9%）**；成本 **−28.9%** | 候选 Harness 可以复用相同历史前缀，降低筛选成本 |
| 恢复机制 | 受控崩溃 → resume | 复用 **2 calls / 2,845 token**；重发 **0 calls**；grader 通过 | checkpoint 同时恢复模型状态、工作区与预算账本 |
| 上下文机制（非得分） | 首次预算压缩 | 估算上下文 **12,271 → 3,795 token（−69.1%）** | 控制器确实在 token 压力下生效；不能据此声称成功率提高 |

这里故意没有“综合评分”。能力、成本、恢复和评测效率使用不同分母，把它们加权成
一个分数反而会掩盖工程权衡。

## 主结果是怎么测出来的

- Benchmark：Terminal-Bench 2.0；使用任务自带的独立 grader。
- 切分：从 metadata 冻结 8 个 holdout 任务；与 20 个开发任务不重合。
- 重复：每个任务独立运行 2 次，共 16 次；不挑选表现更好的那一轮。
- Agent：`claude-sonnet-5`；Harness revision `fd10f5ed8f93`。
- 预算：40 steps、每次最多 16,384 output tokens、每任务最多 $2。
- 结果：11 次通过、5 次失败、0 次 infrastructure error；总模型成本 $18.96。
- 稳定性：4 个任务 2/2 通过，3 个任务 1/2 通过，1 个任务 0/2 通过。

为什么不是只说 87.5%？第一次重复是 7/8，第二次是 4/8。只报第一次会构成
best-sample selection，所以最终报告固定为全部 16 次的 11/16。

为什么区间比较宽？8 个任务 × 2 次能给出可信的项目级 holdout 证据，但仍不足以
精确估计总体成功率。因此简历可以写 68.75%，面试时必须同时说明 16 次分母和
95% 区间，不能包装成官方全量榜单成绩。

## 这个项目实际解决什么问题

我们解决的是“Coding Agent 在长任务、预算限制和运行故障下不稳定，而且 Harness
改动难以被可靠评估”的问题，拆成四个可验证部分：

1. **任务结束不等于任务完成。** 第一次 `finish(done)` 只进入强制验证状态；证据
   失败或继续编辑会使验证失效，最终还要执行清理审计。
2. **长轨迹会被上下文和成本拖垮。** 预算压力控制器保留近期原文，把完整旧工具轮次
   压缩成有界 ledger；一次开发 pilot 首次压缩减少 69.1% 估算上下文。
3. **进程失败不应重新支付历史调用。** 原子 checkpoint 同时提交对话、memory、预算
   ledger 和 workspace snapshot；受控故障恢复没有重放已提交的模型调用。
4. **“看起来更好”的改动可能只是噪声。** 候选 Harness 从同一前缀配对运行，并经过
   目标指标、回归指标和置信区间门禁；一个观察到 4/5 对 3/5 的候选仍因区间不确定、
   token +6.64%、成本 +6.97% 而被拒绝。

## Self-Harness：项目的核心卖点

项目已经完整执行 3 轮无人干预候选搜索，共完成 6 个 live-model candidate gates 和
2 次自动轮次切换：1 个候选晋升、5 个拒绝，3 轮 final full-suite 均完成，仓库 Harness
没有被搜索过程修改。全程执行 244 个 agent task-runs，记录 agent 成本 $6.1404，
API/infra/timeout 结果均为 0。开发集轨迹为 55.6% → 75.0% → 63.9% → 72.2%；相同
Harness 在后两轮仍有明显波动，因此不能把逐轮点估计包装成“持续提高”。

当前确认的 Self-Improvement 是效率维度：Terminal-Bench 外部配对实验将执行步骤
显著降低 **6.94%**，95% 区间不跨 0；同一批实验的 Pass Rate 点估计为 +6.67 个
百分点，但区间跨 0，因此总体质量提升仍未确认。

Campaign 现在使用隔离 Harness revision，并在每轮后原子写入协议、轮次、自动转移、
Pass Rate 轨迹和晋升记录。`--resume` 会拒绝协议漂移；若单轮已经完整落盘但进程来不及
更新总报告，会校验 Harness version 后直接恢复该轮，避免重复 API 消耗；真正未完成的
轮次才会归档并从最后完成的父 revision 继续。每轮 proposal 基于当前隔离 Harness
revision 生成，避免第二、三轮仍对旧仓库版本提 diff。新 Campaign 还分别持久化 agent
与 miner/proposer 的 calls、tokens、USD，并支持 `--max-campaign-cost-usd` 阶段边界
熔断；历史 Campaign 的 `$6.1404` 仅是 agent task-run 成本，meta 成本未记录。

最终因果 A/B 由 `selfharness.proof` 审计，而不是手工相减两个百分比：模型、任务集、
任务内容 hash、容器镜像、Terminal-Bench revision、步数/Token/成本预算和重复次数任一
不一致都会拒绝出报告。只有完成至少 3 轮的 campaign、round-0/final Harness lineage
一致、20+ 冻结题 × 每臂 2+ 次，且配对 Pass Rate 95% 区间下界大于 0，机器 scorecard
才会把“多轮无人干预提升总体 Pass Rate”改为 confirmed。

机器证据：[Self-Harness scorecard](data/selfharness_scorecard.json)；完整因果证明协议：
[Self-Harness evidence](SELF_HARNESS_EVIDENCE.md)。

## 简历可直接使用

推荐选下面 2 条，不要全部堆上去：

- 设计并实现可恢复、可分叉的 Coding Agent Harness，将对话状态、工作区快照和
  token/cost ledger 在 turn boundary 原子提交；受控进程崩溃后复用 2 次调用、
  2,845 个已付费 token，历史调用重放为 0，并通过独立 grader。
- 构建带评测门禁的 Self-Harness 闭环，从失败轨迹自动生成并隔离评测候选策略；完成
  **3 轮无人干预搜索、6 个 live-model candidate gates、2 次自动轮次切换**，晋升
  1 个候选并拒绝 5 个；通过外部配对实验确认执行步骤降低 **6.94%**。
- 在冻结的 Terminal-Bench 2.0 holdout 上完成 8 题 × 2 次独立评测，取得
  **11/16（68.75%，Wilson 95% CI 44.4%–85.8%）**，0 次基础设施错误；搭建可复现
  scorecard，显式区分外部能力、效率、恢复机制与评测成本。
- 构建同前缀 counterfactual 评测，候选 Harness 复用相同 checkpoint 与历史调用；
  5 个任务上 continuation 相比完整重跑节省 **30,307 token（28.9%）** 和
  **28.9%** 成本，同时报告仅 3/5 outcome agreement，避免把低成本筛选误称为等价评测。

项目描述可写：

> HarnessForge — 面向 Coding Agent 的可靠性运行与评测 Harness，支持预算约束、
> 强制证据验证、原子 checkpoint / resume、同前缀候选分叉以及带置信区间的回归门禁。

## 面试追问怎么回答

**你们的成功率为什么只有 68.75%？**

这是冻结外部任务、强约束预算下的端到端通过率，不是自建简单题正确率。更重要的是
我没有挑选 7/8 的最好一轮，而是报告两轮全部 11/16；CI 也说明当前样本只能支持
项目级证据，不能声称模型总体能力已经精确到 68.75%。项目重点是让失败可观测、
可恢复、可对照，而不是造一个接近 100% 的封闭 demo 数字。

**这些指标分别用什么测的？**

- Pass Rate：Terminal-Bench 自带 grader 的二元 reward，按 16 个独立 run 聚合；区间
  使用 Wilson score interval。
- Steps / cost：相同任务的 treatment − control 配对差，通过任务级 bootstrap 生成
  95% 区间。
- Token saving：从 checkpoint continuation 与独立 full rerun 的 trace ledger 汇总；
  同时报告每任务 paired delta interval。
- Crash recovery：受控在 checkpoint 后以指定 exit code 终止进程；resume 后核对模型
  调用 ID、token/cost ledger、工作区版本和最终 grader。
- Context compaction：在 trace 中记录压缩前后字符估算 token、丢弃的完整工具轮次数及
  后续 input token；它是机制 telemetry，不是 capability 分数。

**为什么不用预测出的 11/16 或 75%？**

holdout-v2 没有发生 API 调用，所以状态是 `forecast_unscored`。Jeffreys-prior
Beta-Binomial 只给出中位数 11/16、95% 预测区间 5–15，用于规划下一轮预算；任何
“v2 达到 68.75% / 75% / 81.25%”的表述都被项目的 claim policy 禁止。

## 可复现入口

```bash
python -m harnessforge.demo
python -m harnessforge.eval.benchmark_scorecard
pytest -q tests/test_benchmark_scorecard.py tests/test_holdout_scorecard.py
python scripts/make_figures.py
```

- [英文完整 scorecard](../BENCHMARK.md)
- [机器可读总表](data/benchmark_scorecard.json)
- [holdout 原始汇总](data/tb_holdout_v1_verifier_scorecard.json)
- [上下文压缩 pilot](data/budget_compaction_dev_pilot.json)
- [未评分 v2 预测](data/tb_holdout_v2_forecast.json)
