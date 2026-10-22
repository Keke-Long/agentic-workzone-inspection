# Agentic workzone inspection

## 当前入口与目录职责

| 目录 | 内容 |
|---|---|
| `cases/` | 每个案例的场景清单、处理流程入口和当前状态 |
| `config/` | 检索方法与阶段执行配置 |
| `inputs/` | 规范文档及索引、Workzone 2 规范与场景辅助输入（最终检测统一在项目 data/） |
| `artifacts/` | 按案例和运行分支保存的阶段输出、工具轨迹、模型响应与测量证据 |
| `reports/` | 面向阅读的 HTML、PDF、CSV；文件夹名 final 不保证是最新版本 |
| `ground_truth/` | 独立评分参考；不得混入运行时检索与评判证据 |
| `scripts/` | 共用运行器、工具、验证与案例专用修复脚本 |
| `schemas/` | 数据结构定义 |
| `runtime/` | 本地运行依赖 |
| `docs/` | 方法、交接与历史文档 |
| `figures/` | 方法流程示意图 |

- [Workzone 1](cases/workzone_01/README.md)：19 条历史结果；camera0 范围冲突待核查，当前文件不能视为已验证的 camera0 实验。
- [Workzone 2](cases/workzone_02/README.md)：13 条人工审核后再评判；最终入口为 `reports/workzone_02/ta22_user_selected/post_review_20261021/`。

每个案例的 `processing_record.json` 是 2026-10-21 从现存文件补建的索引，列出可追溯阶段及核心文件。它不替代原始 `tool_trace.json`、`request_manifest.json`、`raw_responses.json` 或人工审核事件。

## 运行与复现

读取 `docs/HANDOFF.md` 和 `docs/METHODS_STAGE1_STAGE2.md`，再检查目标案例 README。一般执行顺序为 Stage 0–2 → Stage 3 → Stage 4 → Stage 5 → Stage 6；阶段配置绑定前一阶段的封存结果。

现有专用修复尚未全部回收到通用流程：旧坐标转换、默认旧设施清单回退、场景事实更新后规范覆盖复查仍需处理。不要把“有脚本和结果”视作“一键复现已验证”。不要覆盖封存运行，应使用新的运行目录。

人工复查网页、历史候选和旧交接说明已按研究范围清理。最终检测输入及存储位置见项目根目录 README；清理记录见 docs/storage_cleanup.json。
