# Jev 自动化调研与架构影响

2026-10-15。依据公开一手资料；未调用付费 Jev API、未复现实验，以下性能不是 MetaBrowser 实测。

## 已核实的能力与证据

- [官方介绍](https://docs.typesafe.ai/introduction)：Choice、Score、Noul 提供有类型的决策输出；问题在相同状态上独立评估，相关字段不能当成联合约束已满足。
- [图像文档](https://docs.typesafe.ai/images) 已支持实验性图片输入；[Box](https://docs.typesafe.ai/primitives/box) 需要 Jev 1.14，输出归一化目标框。官方尚不认为图像与 Box 达到生产标准。Box 即使目标不存在也返回框，必须另行判断存在性；框不能直接视为可点击目标。
- [模型与价格](https://docs.typesafe.ai/models)：当前文档列 1.14/1.13，输入 $0.042/M tokens、输出免费；稳定别名与 preview 分开。总览仍写 Text，与新图像页不同步，应按能力验证，记录精确版本。中文表现需要本地任务集测试。
- [Jev-Mobile 预印本](https://arxiv.org/html/2609.30186v1)：AndroidWorld 成功率 79%，逐步 VLM 84%；成功轨迹平均时长减少 32.7%、模型成本减少 73.4%。没有浏览器实验，也没有在相同委托结构里以小 VLM 替换 Jev 的消融，不能归因全部收益于模型自身。
- [CUA-JEV](https://github.com/ZJU-REAL/CUA-JEV)：实现 observation → candidate → choice → guard → execution → verification，并比较 GUI 与结构化执行通道。公开案例范围有限，不是任意跨站可靠性证明；部分开放任务每步仍调用 planner，不能据此保证节省成本。源码 models.py、policy.py 已读，框架与模型服务是不同依赖。
- [macOS 原型](https://github.com/paulsmith/computer-use-jev)：Go 配 Swift Accessibility worker，展示原生观察与决策选择可分离；不构成我们的 Chromium 集成或生产性能验证。
- [官方 coding 说明](https://docs.typesafe.ai/introduction/coding-agents)：Jev 不替代负责写代码与对话的生成模型。

## 对 MetaBrowser 的设计结论

保留一个 AgentCore 和完整 coding/MCP 能力。在任务调度中增加可替换 DecisionPolicy，不把 Jev 设为第二个全权 agent，不重建远端 Skill 体系。策略可由 Jev、其他模型或确定性规则实现。

```text
AgentCore 高层规划 / 多模态理解 / 代码与文本生成
  ↓ LocalGoal：范围、输入、完成条件、预算、交还控制条件
局部执行循环
  observe → build candidates → choose → revalidate → execute → verify
       ↑                  每步重新观察与生成候选                 ↓
       └──────────── 未完成且仍在委托范围 ──────────────────┘
  ↓ 完成 / 阻塞 / 不确定 / 预算到期 / 状态异常
返回同一个 AgentCore，附真实执行记录和当前证据
```

新增三个内部契约：

| 契约 | 必要字段与规则 |
|---|---|
| LocalGoal | 目标、允许站点/身份/目录/工具、精确输入或产物引用、可验证完成条件、动作/费用/时间预算、handoff 条件 |
| ActionCandidate | 宿主 id、观察/文档世代、目标、执行器、固定参数或已验证参数绑定、所需授权、效果、有效期、后置验证器 |
| DecisionResult | 观察与候选集摘要、选择 id、概率及适用的 confidence、模型精确版本、usage/latency；宿主拒绝未知/过期候选 |

候选先由宿主过滤权限和有效性，再交给决策模型；执行前再检查。可执行不代表业务正确。候选缺失、业务理解错误和选择错误分别计量；所有候选都不合适时允许 blocked / reobserve / handoff，不能强制选一个。

Browser/Coding/MCP 的完整工具能力继续保留。局部模型只能从当前候选中选择，不妨碍高层 Core 编写新脚本、构造命令参数或进行跨系统调查。MCP 仍是标准 MCP：发现 schema 不等于参数和前置条件已知，不能把所有工具直接编译成可执行候选。

视觉路径同时支持外部 VLM 和经过验证的 Jev 图像/Box。任何框都需绑定截图、裁剪/缩放变换、frame、焦点和观察世代，检查目标存在、遮挡、命中位置；动作后读取结果。游戏的本地输入控制器负责时序与释放，远端 Jev 请求不是高频实时控制回路。

Confidence 是决策信号，不是授权或事实证据；Choice 的 confidence 由分布计算，随候选数变化。按任务/候选构造/模型版本校准，保留分布和次优差距，禁止直接把 0.9 当业务正确率。发送邮件等授权仍归宿主，DONE 只结束局部委托，整体成功仍需证据。

## 成本与验证

已知脚本或规则可确定时直接执行；候选有歧义时才选择决策模型；缺候选或缺语义理解时交还规划/视觉。不要每步同时调用 planner、VLM 和 Jev。同一观察的独立判断可以合批，但不能假设多个答案互相看见，组合约束由程序检查。

成本口径包括规划、候选生成、视觉、决策、知识检索、等待、验证、失败和恢复。100 次、每次 2,000 个总计费输入 token 的文本决策，按当前单价约 $0.0084，仅是算术示例，不是任务报价。图像 token、网络和其他模型另计。

同一浏览器任务集比较：逐步大模型、委托+小模型、委托+Jev、确定性脚本/规则。相同候选、观察、权限、验证器和预算；记录成功率、错误副作用、候选覆盖、选择错误、handoff、p50/p95 时长、失败在内的总费用及每成功任务成本。三类用户场景分别测，不以 AndroidWorld 比例代替浏览器证据。

本地 H200 可用于其他可获取权重的视觉/生成模型和评测；此次查到的是 Jev 托管 API 接口，不能据此声称有可在 H200 部署的官方权重。
