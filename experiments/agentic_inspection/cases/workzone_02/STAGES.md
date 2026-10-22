# Workzone 2 Stage 0–6 追溯记录

论文案例名为 **Workzone 2**，正式目录为 `workzone_02`。`Case_18` 是原始数据编号，`scene-CATS-19` 是内部数据标识。旧 `workzone_18` 目录为兼容符号链接，不是第三个案例。

本索引整理已有执行，不代表重新调用模型。保留原配置、请求清单、响应、工具轨迹的原始内容和哈希。Stage 0–2 共用一次运行；后续人工辅助评判独立列出。

| 阶段 | 内容 | 配置 | 追溯报告 |
|---|---|---|---|
| 0 | 布局选择 | [stage1_kg_bm25.json](../../config/workzone_02/ta22_user_selected/stage1_kg_bm25.json) | [阶段记录](../../reports/workzone_02/stage_records/stage_0.html) |
| 1 | 规范检索 | [stage1_kg_bm25.json](../../config/workzone_02/ta22_user_selected/stage1_kg_bm25.json) | [阶段记录](../../reports/workzone_02/stage_records/stage_1.html) |
| 2 | 要求编译与登记 | [stage1_kg_bm25.json](../../config/workzone_02/ta22_user_selected/stage1_kg_bm25.json) | [阶段记录](../../reports/workzone_02/stage_records/stage_2.html) |
| 3 | 检查计划与证据可用性 | [stage3.json](../../config/workzone_02/ta22_user_selected/stage3.json) | [阶段记录](../../reports/workzone_02/stage_records/stage_3.html) |
| 4 | 证据获取与测量 | [stage4.json](../../config/workzone_02/ta22_user_selected/stage4.json) | [阶段记录](../../reports/workzone_02/stage_records/stage_4.html) |
| 5 | 逐项结论 | [stage5.json](../../config/workzone_02/ta22_user_selected/stage5.json) | [阶段记录](../../reports/workzone_02/stage_records/stage_5.html) |
| 6 | 汇总报告 | [stage6.json](../../config/workzone_02/ta22_user_selected/stage6.json) | [阶段记录](../../reports/workzone_02/stage_records/stage_6.html) |

各阶段报告链接到 `request_manifest.json`、`raw_responses.json`、`tool_trace.json` 和 `result.json`。请求清单是请求元数据，不宣称它包含可直接重放的完整 HTTP 请求体。

- [原自动 Stage 6 报告](../../reports/workzone_02/ta22_user_selected/final/report.html)。
- [人工审核后最终报告 PDF](../../reports/workzone_02/ta22_user_selected/post_review_20261021/report.pdf)。
- [机器可读阶段索引](stage_0_to_6_index.json)：包括原记录 SHA-256。

规范来源 MUTCD 2023，TA-22 由用户选择，camera0；最终 13 条结果为 8 支持符合、1 未见明确失效、2 不适用、2 临界待定。原自动运行曾缺少有效证据，不能把最终人工补评结果回写为原模型自主成绩。
