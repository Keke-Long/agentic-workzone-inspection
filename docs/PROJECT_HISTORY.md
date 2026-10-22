# Agentic AI Workzone Inspection

本项目研究 Agentic AI 如何根据施工场景检索规范、确定适用要求、获取证据、执行测量并形成逐项评判。目标检测误差不属于本研究的评估范围；三个案例均使用已确认的最终检测结果作为固定感知输入。

本 README 是当前文件位置与处理流程的入口，更新于 2026-10-21。原始数据可以保留在项目外；当前使用的处理图像、元数据、标定、检测结果、重建结果、代码和报告统一从以下路径访问：

```text
/home/klong23/workzone/
```

该路径现在是主目录磁盘上的实体目录，不再是符号链接。项目约 5.23 GB（4.9 GiB），GitHub 备份见下方说明。旧路径 `/home/data/workzone/klong23_agentic_ai_workzone/` 的兼容符号链接已删除，后续统一使用 `/home/klong23/workzone/`。原始传感器数据仍留在 `/home/data/workzone/work_zone_dataset/work_zone_data_raw/`。


## 当前有效入口与清理状态（2026-10-21 更新）

以下说明优先于后文历史处理记录。当前共三个案例，项目实体在 `/home/klong23/workzone/`；原始数据外置，处理数据与最终结果保存在项目内。

| 案例 | 外部原始目录 | 最终检测输入 |
|---|---|---|
| Workzone 1 | `/home/data/workzone/work_zone_dataset/work_zone_data_raw/Case_00/` | `/home/klong23/workzone/data/workzone_01/detections/final_detections.json` |
| Workzone 2 | `/home/data/workzone/work_zone_dataset/work_zone_data_raw/Case_18/` | `/home/klong23/workzone/data/workzone_02/detections/final_detections.json` |
| Workzone 3 | `/home/data/workzone/work_zone_dataset/work_zone_data_raw/Case_14/`，仅 61–85 秒 | `/home/klong23/workzone/data/workzone_03/detections/final_detections.json` |

每个 `data/workzone_0N/detections/` 现在只保留一个最终检测 JSON。已删除 Workzone 3 候选输出、人工复检数据库、修框队列、局部候选图片和旧复检界面；不再提供复检写入 API。最终检测文件未改动。历史 Agentic 请求、模型响应、工具轨迹、失败修复记录仍保留；其中的输入快照和旧路径是执行记录，不是另一份当前检测输入。

当前流程：原始 camera0 / LiDAR / INS → 项目内 processed 图像与元数据、标定 → 最终确认检测 → 三维关联与 BEV → Agentic Stage 0–6 → 规范报告。

BEV 数据目录：

- `/home/klong23/workzone/experiments/agentic_inspection/artifacts/workzone_01/bev_reconstruction/scene_bev/`
- `/home/klong23/workzone/experiments/agentic_inspection/artifacts/workzone_02/ta22_user_selected/post_review_20261021/scene_bev/`
- `/home/klong23/workzone/experiments/agentic_inspection/artifacts/workzone_03/bev_reconstruction/scene_bev/`

各目录保留点云显示数据、轨迹、对象位置及关联观察。原始 LiDAR 仍是重建源，不能删除；显示用降采样点云不能代替原始点云测量。

网页由 `/home/klong23/workzone/experiments/agentic_inspection/scripts/case18_bev_readonly_server.py` 提供，监听 `127.0.0.1:8768`。`/workzone1/bev`、`/workzone2/bev`、`/workzone3/bev` 均包含底部规范结果。旧复检 URL 已停用，旧 `/report` 跳转到同页底部。localhost 链接仅供本机访问，尚未公开部署。

每案底部报告的派生文件存于 `/home/klong23/workzone/experiments/agentic_inspection/reports/workzone_0N/inspection_summary/`。Workzone 1 恢复最终 PDF 的 16 条通过、2 条未通过、1 条未评判，含原有证据；这不是重跑评判。Workzone 2 按用户项目 10% 容差显示 11 条通过、2 条不适用。Workzone 3 为 9 条通过、2 条证据不足。原规范阈值和原始模型记录未改动。

清理清单、删除字节数和最终检测 SHA-256：`/home/klong23/workzone/experiments/agentic_inspection/docs/project_cleanup_20261021.json`。

## 1 原始数据在哪里

| 论文案例 | 原始数据编号 | 内部场景标识 | 当前相机范围 |
|---|---|---|---|
| Workzone 1 | Case_00 | scene-CATS-01 | camera0 / CAM_FRONT |
| Workzone 2 | Case_18 | scene-CATS-19 | camera0 / CAM_FRONT |

Workzone 1：

```text
/home/data/workzone/work_zone_dataset/work_zone_data_raw/Case_00/
/home/data/workzone/work_zone_dataset/work_zone_data_raw/Case_00/camera0/
/home/data/workzone/work_zone_dataset/work_zone_data_raw/Case_00/lidar/
/home/data/workzone/work_zone_dataset/work_zone_data_raw/Case_00/ins/
```

Workzone 2：

```text
/home/data/workzone/work_zone_dataset/work_zone_data_raw/Case_18/
/home/data/workzone/work_zone_dataset/work_zone_data_raw/Case_18/camera0/
/home/data/workzone/work_zone_dataset/work_zone_data_raw/Case_18/lidar/
/home/data/workzone/work_zone_dataset/work_zone_data_raw/Case_18/ins/gnss.csv
```

原始目录未被修改。目录中即使存在其他相机，也不属于当前 camera0-only 实验范围。原始数据路径另有机器可读记录：

```text
/home/klong23/workzone/data/raw_sources.json
```

项目内实际使用的标定副本位于：

```text
/home/klong23/workzone/data/shared/calibration/
```

Workzone 2 沿用用户确认的黑车标定。历史记录中出现的其他 `/home/data/workzone/` 处理目录是当时的来源，不是当前工作入口。

## 2 项目现在保留什么

```text
/home/klong23/workzone/
├── README.md
├── data/
│   ├── raw_sources.json
│   ├── workzone_01/
│   │   ├── detections/final_detections.json
│   │   └── processed/
│   │       ├── scene-CATS-01/CAM_FRONT/
│   │       ├── CATS_v1.0/
│   │       └── storage_manifest.json
│   ├── workzone_02/
│   │   ├── detections/final_detections.json
│   │   └── processed/
│   │       ├── scene-CATS-19/CAM_FRONT/
│   │       ├── CATS_v1.0/
│   │       └── storage_manifest.json
│   └── shared/calibration/
├── dependencies/
│   ├── preprocess/                     # 预处理参考代码
│   └── python/                         # 保留的轻量验证依赖
├── bev_full_scene/scene_evidence_current/ # Workzone 1 既有设施与几何结果
├── experiments/agentic_inspection/
│   ├── cases/                          # 场景、阶段索引和当前状态
│   ├── config/                         # 方法及阶段配置
│   ├── inputs/                         # 规范、索引和场景辅助资料
│   ├── artifacts/                      # 模型、工具及测量记录
│   ├── reports/                        # 最终报告与 BEV 可视化
│   ├── ground_truth/                   # 独立评分参考
│   ├── scripts/                        # Agentic 流程与重建工具
│   ├── schemas/
│   └── docs/
└── .docs-methodology/                   # 方法章节与排版资料
```

`workzone_18` 旧路径仅作为指向 `workzone_02` 的兼容链接；`case18_*.py` 和 `C18_...` 观察 ID 保留原命名以保证追溯，不表示还有第三个论文案例。

### 当前固定检测输入

```text
/home/klong23/workzone/data/workzone_01/detections/final_detections.json
/home/klong23/workzone/data/workzone_02/detections/final_detections.json
```

| 案例 | 已接受检测框 | 仅确认类别的记录 | 当前处理图像 |
|---|---:|---:|---:|
| Workzone 1 | 930 | 0 | 1,027 帧 camera0 |
| Workzone 2 | 238 | 32 | 632 帧 camera0 |

框数是跨帧观察数，不是物理设施数。Workzone 2 的 32 条仅类别记录不当作已接受的框参与相同等级的定位证据。检测输入是规范检查的前置条件，不用于评价原始检测器准确率。

人工复查网页、候选队列、修框界面、审核数据库和旧预处理点云已清除。历史 Agentic 阶段记录可能包含当时的感知输入快照；这些是实验记录，不是另一个当前检测结果。

### 已删除的预处理点云

两个案例的项目内 `LIDAR_TOP/` 二进制点云目录均已删除。`CATS_v1.0/sample_data.json` 等仍保留 LiDAR 的时间戳、标定索引及位姿关系，用于构建轨迹。这些 JSON 中的旧点云文件名不代表文件仍然存在。

当前可用文件以各案例的 `processed/storage_manifest.json` 为准。历史 `processing_manifest.json` 只说明当时如何生成数据，不应当作当前文件存在性检查。

## 3 整个处理流程

流程包含感知与几何准备，以及 Agentic 规范检查两部分。实际执行中，Stage 3–4 会发现证据缺口，Workzone 2 因此进行了补充取证和几何修复；这些补充没有被伪装为原始自主运行的输出。

### A 场景输入准备

1. 指定原始案例、camera0、标定和场景事实，例如速度、关闭车道、施工持续时间。
2. 对 camera0 图像去畸变，整理传感器时间戳、标定与位姿为 nuScenes 风格元数据。
3. 以 `final_detections.json` 中最终确认的类别和框作为固定感知输入。
4. 在场景清单中绑定图像、元数据和可用几何证据，未知场景事实保留为未知。

Workzone 2 保留了已有的全部 632 帧、10 Hz camera0 图像，没有在这一准备步骤再次时间抽帧。去畸变、相机筛选、时间采样和 BEV 显示降采样是不同操作。Workzone 1 当前保留 1,027 帧；本说明不据此推断它更早的采样策略。

`prepare_raw_case.py`、`select_prepared_cameras.py` 与 `dependencies/preprocess/` 保留了准备代码。通用预处理中的旧姿态处理尚未全面整合 Workzone 2 的专项修复，不能将其输出直接视为已验证的最终三维结果。

### B 三维关联与 BEV

**以下几何流程用于 Workzone 2 的修复重建，也已复用于 Workzone 1 新建的 camera0 BEV；Workzone 1 的规范结论仍未重新评判。**

1. 读取原始 `.pcd` 中的 XYZ 和逐点时间戳，以及原始 INS 的 ENU 位置、航向、俯仰和横滚。
2. 对位置做时间插值，对姿态做旋转插值，使用修正的 Y 朝前约定 `Rz(-azimuth) Rx(pitch) Ry(roll)`。
3. 结合 LiDAR 外参，将每个点按其采集时刻转换到统一世界坐标，完成运动补偿。
4. 根据图像时间戳选择最近的原始点云帧，再按相机拍摄时刻的位姿与内参将点投影到图像。
5. 在检测框中心区域及目标深度范围内提取位置候选，检查点数、距离、点簇离散程度和边缘截断。
6. 结合类别、空间邻近及同帧冲突进行跨帧关联，将对象分为多帧支持、暂定位置及未可靠定位。
7. 输出车辆轨迹、对象位置和 BEV。对象定位使用完整的相关原始点云；用于 BEV 背景显示的点云另做降采样，不能把显示稀疏度等同于测量点数。
8. 对标志距离、设施间距和渐变段进行测量，保留敏感性范围及适用边界。距离中的道路里程以车辆轨迹为参照，不是独立测绘的道路中心线。

主要脚本位于 `/home/klong23/workzone/experiments/agentic_inspection/scripts/`：

| 脚本 | 作用 |
|---|---|
| `case18_sign_geometry.py` | 从原始 LiDAR / INS 重建标志位置 |
| `case18_validate_sign_geometry.py` | 标志跨帧稳定性与间距验证 |
| `case18_build_bev.py` | 全场景原始点云累计、轨迹及逐观察位置候选 |
| `case18_bev_objects.py` | 跨帧对象关联与对象级状态汇总 |
| `case18_render_bev.py` | 生成交互 BEV 和静态图 |
| `case18_complete_assessment.py` | 读取重建结果，测设施间距并估计渐变段 |
| `case18_qwen_serviceability.py`、`case18_qwen_serviceability_finalize.py` | 图像可用性检查及复核 |
| `case18_post_review_report.py` | 基于现有证据生成逐项评判报告 |

最终重建读取原始点云，而不是已删除的预处理 `.pcd.bin`。它仍需要项目内的图像、标定、时间戳和轨迹元数据。对象状态综合同一对象的清晰视图；模糊视图不自动否定清晰证据，明确缺陷冲突也不能被忽略。

Workzone 1 已新增从原始 Case_00 LiDAR / INS 进行的 camera0 三维重建，复用上述修正算法，入口为 `workzone1_build_bev.py` 和 `workzone1_render_bev.py`。原始来源经全部 1,027 个 LiDAR 位姿位置与 INS 插值匹配确认；先前文档将其写成 Case_01 是编号对应错误。旧历史规范结论没有随此次几何重建重新评判。

### C Agentic AI Stage 0–6

当前报告采用 MUTCD 11th Edition（2023）。主要检索方法是 Knowledge Graph + BM25；Workzone 1 还保留其他检索方法的对照记录。独立评分参考在 `ground_truth/`，不能作为运行时检索或判断的答案输入。

| 阶段 | 工作 | 应保留的证据 |
|---|---|---|
| Stage 0 | 选择适用施工布局 TA；记录人工指定或模型选择的来源 | 布局选择记录及来源 |
| Stage 1 | 检索相关规范；KG 提供结构化关联，BM25 补充检索 | 查询、候选条文与工具轨迹 |
| Stage 2 | 判断适用性、编译原子要求，记录保留／排除依据 | 要求注册表、原文、条件及指纹 |
| Stage 3 | 核查证据可用性并制定取证计划，不作合规结论 | 证据缺口、工具和测量计划 |
| Stage 4 | 获取图像证据、对象信息并执行测量 | 与要求绑定的证据、测量、失败原因及质量信息 |
| Stage 5 | 根据证据逐项评判 | 结论、依据、不确定性和适用范围 |
| Stage 6 | 汇总已有结论并生成报告 | 最终结果和报告；不在此阶段隐式新增适用要求 |

配置目录：

```text
/home/klong23/workzone/experiments/agentic_inspection/config/workzone_01/
/home/klong23/workzone/experiments/agentic_inspection/config/workzone_02/ta22_user_selected/
```

Stage 0–2 由 `stage1_kg_bm25.json` 配置的同次运行承担，共用请求与响应记录；Stage 3–6 分别对应 `stage3.json` 至 `stage6.json`。一般顺序为 Stage 0–2 → 3 → 4 → 5 → 6。

阶段目录中保留的典型文件：

- `request_manifest.json`：请求配置与运行元数据，不等同于完整 HTTP 请求体。
- `raw_responses.json`：原始模型响应。
- `tool_trace.json`：工具调用及返回结果。
- `stage_0_layout_selection.json`：布局选择及来源。
- `stage_1_to_6_registry.json`：要求与证据注册记录。
- `measurements.json`、`result.json`、`resource_usage.json`：测量、结果与资源使用。

历史阶段输出和执行配置保留原文。后期修复与再评判单独存放；不要覆盖原阶段记录，也不要将人工辅助结果回写为模型原来的自主成绩。现有索引是记录入口，不代表已验证清理后的全流程一键重跑。

## 4 每个案例的结果在哪里

### Workzone 1

```text
/home/klong23/workzone/experiments/agentic_inspection/cases/workzone_01/processing_record.json
/home/klong23/workzone/experiments/agentic_inspection/artifacts/workzone_01/benchmark/stage1_stage2/
/home/klong23/workzone/experiments/agentic_inspection/artifacts/workzone_01/pipeline/
/home/klong23/workzone/experiments/agentic_inspection/artifacts/workzone_01/pipeline/final_evaluated/scene-CATS-01/result.json
/home/klong23/workzone/experiments/agentic_inspection/reports/workzone_01/final/
/home/klong23/workzone/bev_full_scene/scene_evidence_current/
```

历史报告登记 19 条要求，记录为 16 satisfied、2 deficient、1 not_assessed。但历史评判曾引用非 camera0 证据，不能直接作为当前 camera0-only 输入的已验证结论。当前输入已限定 camera0，尚未完成对应的重新评判。新 BEV 包含重新累计的显示点云、车辆轨迹、camera0 对象及跨帧图片，布局与 Workzone 2 一致。对象状态显示“未重新检查”，不导入历史多相机结论。

```text
/home/klong23/workzone/experiments/agentic_inspection/artifacts/workzone_01/bev_reconstruction/scene_bev/
/home/klong23/workzone/experiments/agentic_inspection/reports/workzone_01/bev/bev.html
/home/klong23/workzone/experiments/agentic_inspection/reports/workzone_01/bev/bev_overview.png
```

### Workzone 2

```text
/home/klong23/workzone/experiments/agentic_inspection/cases/workzone_02/STAGES.md
/home/klong23/workzone/experiments/agentic_inspection/cases/workzone_02/stage_0_to_6_index.json
/home/klong23/workzone/experiments/agentic_inspection/cases/workzone_02/current_run.json
/home/klong23/workzone/experiments/agentic_inspection/artifacts/workzone_02/ta22_user_selected/
/home/klong23/workzone/experiments/agentic_inspection/artifacts/workzone_02/ta22_user_selected/post_review_20261021/
/home/klong23/workzone/experiments/agentic_inspection/reports/workzone_02/ta22_user_selected/post_review_20261021/
```

`post_review_20261021/` 是当前人工辅助后的评判。`reports/workzone_02/ta22_user_selected/final/` 是更早的自动流程报告，不能仅凭 final 目录名判断最新版本。

当前报告和可视化：

```text
/home/klong23/workzone/experiments/agentic_inspection/reports/workzone_02/ta22_user_selected/post_review_20261021/report.pdf
/home/klong23/workzone/experiments/agentic_inspection/reports/workzone_02/ta22_user_selected/post_review_20261021/report.html
/home/klong23/workzone/experiments/agentic_inspection/reports/workzone_02/ta22_user_selected/post_review_20261021/requirements.csv
/home/klong23/workzone/experiments/agentic_inspection/reports/workzone_02/ta22_user_selected/post_review_20261021/bev.html
```

在对应 `artifacts/.../post_review_20261021/` 中：

| 子目录或文件 | 内容 |
|---|---|
| `scene.json` | 最终感知输入适配成测量工具可读的场景，并非另一轮检测 |
| `sign_geometry_repair/` | 标志位置、跨帧验证和间距结果 |
| `scene_bev/objects.json` | 关联对象与位置可靠性 |
| `scene_bev/observations.json` | 观察与几何候选 |
| `scene_bev/trajectory.json` | 轨迹 |
| `scene_bev/pointcloud_display.npz` | 降采样显示点云，不是完整原始点云 |
| `full_reassessment/` | 设施间距与渐变段评估 |
| `qwen_serviceability/` | 设施状态证据 |
| `result.json` | 当前 13 条规范再评判 |
| `end_road_work_applicability.json` | END ROAD WORK 可选性的补充核查 |

Workzone 2 为用户指定 TA-22、25 mph、长期施工超过三天。当前 13 条结果：8 条观察范围内支持符合、1 条未发现明确失效、2 条不适用、2 条已测量但临界待定。这不是“全部合格”，也不是原自动检测与自主 Agentic 流程的独立准确率结果。

## 5 当前仍需注意的问题

- Workzone 1 的 camera0-only 规范评判尚需重做或回查，不能继承旧多相机结论。
- Workzone 2 的 Arrow Board 已确认，但已登记要求中的对应条款覆盖仍需审计；已处理完 13 条不等于证明规范提取完整。
- Workzone 2 的坐标和运动补偿修复目前主要在专用脚本，尚未全面回收到通用预处理流程。
- 旧通用点云投影工具依赖已删除的二进制点云，现在会明确返回不可用；不能当作当前重建入口。
- 既有配置和模型轨迹包含历史路径；读取历史记录不需要恢复被清理的审核界面，重新执行旧流程则需重新核对输入与依赖。
- 系统 Python、CUDA、Ollama 是运行环境，不是数据文件。设施状态模型使用本地 `qwen3-vl:4b-instruct`；个人 API 凭据继续由 `/home/klong23/.config/workzone/` 管理，不纳入研究数据。

清理记录和当前存储状态：

```text
/home/klong23/workzone/experiments/agentic_inspection/docs/storage_cleanup.json
/home/klong23/workzone/data/workzone_01/processed/storage_manifest.json
/home/klong23/workzone/data/workzone_02/processed/storage_manifest.json
```

进一步查看 `experiments/agentic_inspection/docs/METHODS_STAGE1_STAGE2.md` 了解方法定义。旧 `docs/HANDOFF.md` 的 Workzone 1 完成状态属于历史描述；当前范围和状态以本 README 及案例入口为准。

## Workzone 3：Case_14（61–85 秒输入）

原始数据：`/home/data/workzone/work_zone_dataset/work_zone_data_raw/Case_14/`。最新用户指令覆盖之前所有裁剪范围：图像和 LiDAR 均只用原始时间戳 **61 ≤ t ≤ 85 秒**，不重新归零、不修改原始文件。仅用 camera0，保持原有采样率，240 张图像、240 帧 LiDAR。点云重建同时过滤逐点时间戳，区间外 INS 仅可用于边界姿态插值。

范围配置：`/home/klong23/workzone/experiments/agentic_inspection/cases/workzone_03/input_window.json`。具体输入文件清单：`/home/klong23/workzone/data/workzone_03/selection_manifest.json`。去畸变图像、480 条相机/LiDAR 元数据及姿态：`/home/klong23/workzone/data/workzone_03/processed/`。BEV 点云、轨迹与重建记录：`/home/klong23/workzone/experiments/agentic_inspection/artifacts/workzone_03/bev_reconstruction/scene_bev/`。

流程沿用 Workzone 1 的 KG + BM25 Agentic Stage 0–6 方法。用户确认黑车标定、20 mph、施工少于 3 天、整条对向车道封闭；用户现已确认对向车辆经其他道路绕行、不交替借用剩余车道，并确认 TA-19。旧范围场景理解已废弃，61–85 秒场景理解和最终人工 BEV 输入已更新；Stage 0–6 已完成：TA-19，共 11 条要求，9 条未发现明显不符、2 条证据不足，0 条明确不符合。流程记录：`/home/klong23/workzone/experiments/agentic_inspection/cases/workzone_03/processing_record.json`，阶段索引同目录 `stage_0_to_6_index.json`。

启动服务：`python /home/klong23/workzone/experiments/agentic_inspection/scripts/case18_bev_readonly_server.py`，本地端口 `8768`。每页顶部可切换三个案例：`/workzone1/bev`、`/workzone2/bev`、`/workzone3/bev`；各自的 `/workzoneN/report` 展示对应报告或当前处理状态。Workzone 3 当前展示点云预览和流程状态，不代表已完成对象关联或规范评判。旧 `/bev`、`/report` 链接继续指向 Workzone 2。

### Workzone 3 目标检测（待审核）

61–85 秒共 240 张 camera0 图像，Grounding DINO tiny 使用全图及两个标志局部视图，产生 5,824 个原始候选框。沿用已核验图像 SHA 的相同逐帧推理结果，重新构建 3,206 个临时二维组；并非独立设施数量。cone/drum/delineator 合并为 traffic_cone。295 个至少出现三帧的组完成代表图分类：286 张相同区间内代表图复用既有结果，9 张新代表图重新调用 gpt-5.6-luna。旧范围外的代表图不用于当前分类。

默认显示 40 组单对象目标候选，54 组框需检查；其余背景、普通标志、不确定及短暂候选可用筛选查看。当前结果：`/home/klong23/workzone/data/workzone_03/detections/current_detections.json`；逐帧候选同目录 `frames/`、`candidates.json`。当前新增模型请求/响应：`/home/klong23/workzone/experiments/agentic_inspection/artifacts/workzone_03/detection_verification/api_batches/`。复用记录同目录 `representative_reuse_cache.json`；源请求保存在 `../superseded_before_61_85/api_batches/`，仅作历史溯源。未将模型候选自动写入人工确认、三维定位或规范结论。

网页：`/workzone3/detections`，每页 100 张、置信度升序；`/workzone3/bev` 展示相同 61–85 秒范围的点云与轨迹。范围外的旧处理图像、检测帧、旧分组缩略图已移除，原始数据不变。

复现顺序：`prepare_workzone3_selection.py` → `prepare_workzone3.py` → `workzone3_build_bev.py`；检测：`workzone3_detect.py` → `workzone3_track_candidates.py` → `workzone3_render_detections.py --crops-only` → `workzone3_verify_api.py` → `workzone3_finalize_detections.py` → `workzone3_render_detections.py`。脚本位于 `/home/klong23/workzone/experiments/agentic_inspection/scripts/`，需保留已下载模型和项目授权 API 配置。

### Workzone 3 正式人工复检

访问 `/workzone3/detections?class=traffic_cone`。默认按类别显示所有未审候选组（包括短暂检测与不确定项），置信度升序，每页 100 张代表框局部放大图。只勾选错误项，默认“框错了”；可批量改为“对象对但框需修正”或更正实际类别。点击“提交并下一页”或最后一页的“提交本页”时，未操作项按最新用户规则记为“正确”。切换筛选或仅浏览上一页不提交。已审代表框自动隐藏，可撤销上一批提交；浏览器保留未提交草稿，成功提交后保存到项目数据库。

审核数据：`/home/klong23/workzone/data/workzone_03/detections/human_review.sqlite3`。`state` 保存当前判断，`events` 保存提交和撤销记录；事务及版本校验防止多标签页覆盖。数据库绑定当前检测文件 SHA256，输入变化时阻止继续写入旧审核。审核只覆盖显示的代表框，不将未见过的同组其他帧自动变为人工确认；修框标记仍需后续实际修改框。当前不自动写入规范评判或三维接受列表。

人工复检另提供“框错了（无关对象／错误框）”：保存为 `wrong_box` 拒绝记录，区别于 `fix_box`（对象正确但需修框）及历史审核中的 `no_target`，不作为有效目标输出。

Workzone 3 最新人工范围：用户确认 Barricade、Road Barrier、Vertical Panel、Arrow Board、PCMS、Worker、Work Vehicle 均不存在，按案例级声明排除，并非逐框视觉确认。Cone 相关 494 组恢复为待审（显示类别为 Cone 或原始预测为 Cone），不继承先前拒绝或试算接受结果。范围与审核类别覆盖记录见 `/home/klong23/workzone/data/workzone_03/detections/review_scope.json`，模型原始检测文件保持不变。新增消防栓更正类别；它不属于施工设施。

最新审核交互采用 `errors_only_v1`：仅勾选错误，未操作代表框在提交本页时按当前审核类别确认正确；不提交不落盘。旧页面会被服务端拒绝提交，必须刷新；旧模式未提交草稿不自动套用到新模式。已保存判断不变。

最新交互已改为 `selected_only_v2`，覆盖之前的默认接受/默认拒绝模式：按原候选类别浏览，支持待审核、已审核、已拒绝、全部视图。勾选后可选择正确、框错误、修框或更正类别；仅保存勾选项，未操作记录不变。已拒绝项可重新分类为施工标志。旧模式页面须刷新，已提交结果保留。

最新显示规则：已保存为 `wrong_box` 或 `no_target` 的候选从所有当前审核视图中剔除，不再显示或重复审核；后台 SQLite 仅保留历史追溯。原始模型预测作为来源档案保留，不代表当前有效检测结果。

当前 Workzone 3 人工审核已切换至 `/workzone3/cone-review` 单张 Cone 审核（`single_cone_v1`），旧检测地址自动跳转。一次只保存一个显示的代表框，下一张清空选择，上一张/跳过不保存；后台拒绝旧批量模式及多框请求，保留此前审核结果。已拒绝或改为其他类别的候选不进入 Cone 队列；本轮保存标记 `single_cone_review_complete` 用于刷新后继续未完成内容。

当前 Cone 页面已改为只读候选框清单：`/workzone3/cone-review` 每页 50 张局部放大图，置信度升序，显示固定 W3_TRACK 编号及原观察 ID。包含当前保留的 Cone 候选，已拒绝及已改为其他类别的对象不显示；翻页不改变结果。用户在聊天中提供编号和处理方式，由助手据明确指令更新记录。网页 POST 写入已禁用，避免旧标签页继续提交。

修框页面：`/workzone3/fix-boxes`，实时读取数据库中 fix_box 状态的对象。支持局部放大或原图、拖角/边缩放、框内平移、重新画框。原图像素坐标保存至 human_review.sqlite3，保留 original_bbox 与事件历史。修正后状态为 correct、bbox_review_status=human_corrected，退出待修队列，候选图页面自动按新框显示。不重新推断同组其他帧。

## Workzone 3 最终人工检测与对象 BEV

人工审核完成，41 个框修正已全部保存。最终输入为 241 个代表观察：227 Cone、14 ROAD WORK AHEAD；未审核同组帧不自动纳入。最终文件 `/home/klong23/workzone/data/workzone_03/detections/final_detections.json`，记录 review revision 81 与来源哈希。人工框坐标和类别已经同步到当前 scene.json。

原始来源仍是 `/home/data/workzone/work_zone_dataset/work_zone_data_raw/Case_14/`，仅 61–85 秒 camera0、LiDAR，使用黑车标定和逐点时间的 INS 插值姿态。处理流水线：`workzone3_finalize_review.py` → `workzone3_build_bev.py` → `validate_workzone3_bev.py` → `workzone3_render_bev.py` → `validate_workzone3_bev_browser.py`。脚本根目录 `/home/klong23/workzone/experiments/agentic_inspection/scripts/`。

BEV 输出目录 `/home/klong23/workzone/experiments/agentic_inspection/artifacts/workzone_03/bev_reconstruction/scene_bev/`：`pointcloud_display.npz`（191,120 个展示点）、`trajectory.json`（240 姿态）、`observations.json`（241 条关联记录）、`objects.json`（31 个对象位置候选）、`reconstruction.json`、`validation.json`。31 个位置包括 22 个多帧支持和 9 个单帧/身份暂定位置；166 条观察已关联、75 条未可靠定位。聚类采用同类空间最大直径 1m，并防止同帧分离框合并。位置是算法推断，不是测绘真值；未定位观察没有被赋予可靠坐标。

网页 `/workzone3/bev`；文件 `/home/klong23/workzone/experiments/agentic_inspection/reports/workzone_03/bev.html`，同目录 `bev_overview.png`、`bev_work_area.png`。点击对象可查看最终修正框、关联帧和几何质量；未定位观察可独立查看。此次未运行设施状态 VLM 或规范符合性评判。

用户删除 W3_OBJ_026（唯一观察 W3_T73099999_Q007），已同步人工记录、最终检测及 BEV；其他对象编号保持不变。

### Workzone 3 本次 Agentic 执行记录

当前运行目录：`/home/klong23/workzone/experiments/agentic_inspection/artifacts/workzone_03/agentic_final_review81/`。最终审核版本 81，原始时间 61–85 秒、camera0、黑车标定。Stage 0 经来源复核后选择 TA-19，用户随后明确确认。

本轮不是一次无干预成功的基线运行：初次 Stage 0 因绕行事实未确认而停止；确认后又出现遗漏方向性绕行布局和无依据假定交叉口远端的问题。失败尝试、完整 TA 目录补充、控制器发起的原文复核、原始模型响应和用户确认均保留。`stage0_source_review/` 是纠错模型复核，`user_layout_confirmation.json` 是之后的用户确认；不得在论文中将这些干预隐去。Stage 0 目录导航有所更新，Workzone 1 历史实验未因此自动重跑。

`geometry_adapter_validation.json` 验证 241 个最终观察与 BEV 绑定：166 条可关联，75 条无法可靠定位；单帧候选不允许作为稳定纵向测量。已删除的 W3_T73099999_Q007 不在输入中。后续规范测量须先登记要求，再由对应工具执行。

### Workzone 3 最终规范报告（Stage 0–6 已完成）

报告：`/home/klong23/workzone/experiments/agentic_inspection/reports/workzone_03/final/report.html`；结构化结果同目录 `result.json`。网页入口 `/workzone3/report`。最终 11 条要求：9 条 satisfied（当前证据未发现明显不符，非全场景合规证明），2 条 not_assessed（独立预告标志间距、Traffic Drum 尺寸/材料等），0 条 deficient。

每阶段配置、预检、请求、模型响应、工具轨迹、注册表与结果位于上述 `agentic_final_review81/` 下的 `stage0_1_2/`、`stage3/`、`stage4/`、`stage5/`、`stage6/`。Stage 0 的纠错复核请求/响应单独位于 `stage0_source_review/`。阶段索引 `cases/workzone_03/stage_0_to_6_index.json` 给出精确路径。Stage 4 从已保存的检查点续跑，配置明确指向相应历史检查点；不要删除其依赖目录。

本次修复详见 `pipeline_repair_notes.json`：补充候选处置、人工类别到规范类别映射、证据批次、输入名称路由、已验证 BEV 身份复用及阶段待办状态。所有失败/重试保留，不能将本轮描述为首次无干预成功，也不能将修复后的方法直接等同于未重跑的 Workzone 1/2 历史结果。完成验证见 `completion_validation.json`。

### 官方检测权重（已移除本地副本）

`dependencies/models/grounding-dino-tiny/model.safetensors` 已核对 SHA-256 与官方 `IDEA-Research/grounding-dino-tiny` 完全一致，未含本地微调修改，按用户要求删除（689,359,096 字节）。来源、固定版本、校验值及恢复命令保存在 `/home/klong23/workzone/dependencies/models/grounding-dino-tiny/model_source.json`。最终人工检测结果、BEV 和报告不依赖该权重；重新运行检测前需恢复权重。

## GitHub 完整快照与网页启动

完整根目录备份仓库：`https://github.com/Keke-Long/agentic-workzone-inspection`（私有）。此仓库从当前完整项目建立新历史；原 `workzone_inspection` 远程仓库未删除。原本嵌套 Git 元数据保存在本机 `/home/klong23/.local/state/workzone-backup/original-experiment.git`，不混入新快照。

克隆前安装 Git LFS。克隆后执行：

```bash
git lfs pull
python3 start_viewer.py
```

在运行服务器的机器上访问 `http://127.0.0.1:8768/workzone1/bev`，导航切换三个案例。服务器仅用 Python 标准库，已有网页内嵌点云和对象图片；查看结果无需原始传感器数据、GPU 或模型权重。远程工作站需通过 SSH 端口转发，例如 `ssh -L 8768:127.0.0.1:8768 用户名@工作站`，再在自己电脑打开上述地址。

备份包含处理图像、最终检测、BEV、规范资料、阶段记录和报告；原始传感器数据、凭据、可重建缓存及已删除的官方模型权重不在仓库内。源文件校验清单见 `backup_manifest.json`。已有研究流程仍有绝对路径，异地重新运行重建或模型检查前需按实际路径调整；网页查看入口可从任意项目目录启动。
