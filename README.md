# Agentic AI Workzone Inspection

三个施工区案例共用同一套组织方式：**场景输入 → 最终人工确认检测 → 三维重建与 BEV → Agentic Stage 0–6 → 规范评判报告**。目标检测误差不是本研究的评估对象。

完整私有备份：https://github.com/Keke-Long/agentic-workzone-inspection

## 重要阶段性成果：已维护完成的交互式网页工具

**这套 BEV + 图像证据 + 规范报告的交互式网页，是项目的重要研究工具，也是项目作者已经完成并维护好的阶段性成果。接收项目后，请优先恢复网页展示，将其作为理解案例、核对检查依据和继续研究的主要入口。不要仅查看 JSON、PDF 或静态截图而忽略这一工具。**

网页已经整合三个案例，接收者无需重新制作界面，可以在自己的电脑上恢复现有展示并自行使用：

- **查看完整空间场景**：点云、车辆行驶轨迹与检测对象叠加显示，支持缩放和平移。
- **从对象追溯图像证据**：点击对象，查看关联观察、对象图片与跨帧定位信息。
- **逐项查看规范评判**：同一页面底部显示规范条目、通过／未通过／证据不足等状态，以及已有的未通过项图片证据。
- **统一查看三个案例**：通过顶部导航切换 Workzone 1、2、3，保持一致的使用方式。

这是已保存结果的只读查看与证据检查工具，不是旧版人工改框界面。恢复网页不需要重新检测、重新重建点云或重新调用模型。后续扩展时应保留这一展示能力，使新案例也能通过统一网页查看。

## 1. 在自己的电脑上快速恢复网页

先确保有仓库访问权限，并安装 **Git、Git LFS 和 Python 3**。完整克隆后执行 `git lfs pull`，才能取得实际图像、点云和网页文件；不建议只下载 GitHub 的源码 ZIP。

在终端执行：

```bash
git lfs install
git clone https://github.com/Keke-Long/agentic-workzone-inspection.git
cd agentic-workzone-inspection
git lfs pull
python3 start_viewer.py
```

浏览器访问 `http://127.0.0.1:8768/workzone1/bev`，顶部导航切换案例。每页包含点云、车辆轨迹、对象图片与底部逐条报告。仅查看网页需要 Python 3 标准库，不需要 GPU、原始数据或检测权重。

启动后保持终端运行，再打开以下任意入口；无需使用项目作者原先的端口或浏览器会话：

| 网页 | 本机访问地址 |
|---|---|
| Workzone 1 | http://127.0.0.1:8768/workzone1/bev |
| Workzone 2 | http://127.0.0.1:8768/workzone2/bev |
| Workzone 3 | http://127.0.0.1:8768/workzone3/bev |

**恢复成功的检查标准**：三个案例都能切换，网格中显示点云和轨迹，点击对象能看到图片，向下滚动能看到逐条规范结果。完成这些检查，就已恢复本项目的重要网页成果，可直接用于个人查看与后续研究。

如页面打不开，先查看启动终端是否报错、服务是否仍在运行；如提示文件缺失，先确认 `git lfs pull` 成功，并运行 `python3 tools/validate_project.py` 检查数据。项目使用相对符号链接；Windows 用户建议使用 WSL，或在克隆前启用系统及 Git 的符号链接支持。在 WSL/Linux/macOS 下使用 `python3`；其他环境可按安装情况使用 `python`。

远程工作站使用 SSH 转发：`ssh -L 8768:127.0.0.1:8768 用户名@工作站`，然后在本机浏览器访问上述地址。当前服务只读，不再提供人工复检接口。

## 2. 三个案例的统一入口

| 案例 | 原始数据 | 布局 | 输入范围 | 当前评判 |
|---|---|---|---|---|
| Workzone 1 | Case_00 | TA-30 | camera0，已准备场景范围 | 16 通过、2 未通过、1 证据不足 |
| Workzone 2 | Case_18 | TA-22 | camera0，已准备场景范围 | 11 通过、2 不适用 |
| Workzone 3 | Case_14 | TA-19 | camera0，原始时间 61–85 秒 | 9 通过、2 证据不足 |

每个案例都使用以下结构；`NN` 分别为 `01`、`02`、`03`：

```text
workzones/workzone_NN/
├── README.md
├── case.json                      # 案例事实、相对路径、结果来源
├── config/                        # Stage 配置入口
├── inputs/
│   ├── scene.json                 # 场景及证据绑定
│   ├── processed/                 # 图像与元数据
│   └── detections.json            # 唯一最终检测输入入口
├── outputs/
│   ├── bev/
│   │   ├── viewer.html            # 当前 BEV 网页
│   │   └── data/                  # 点云、轨迹、对象与观察
│   └── report/
│       ├── result.json            # 统一逐条评判结构
│       └── module.html            # 网页底部报告
└── stages/
    ├── stage_0.json
    ├── ...
    └── stage_6.json
```

当前项目根目录为 `/home/klong23/workzone/`。因此三个入口完整路径为：

```text
/home/klong23/workzone/workzones/workzone_01/
/home/klong23/workzone/workzones/workzone_02/
/home/klong23/workzone/workzones/workzone_03/
```

网页和报告文件已归入这些标准目录。大型输入、几何数据和原配置通过**项目内相对链接**引用唯一实体，不额外复制检测结果或传感器数据；旧报告路径保留兼容链接。Git/Linux 会保留这些链接，Windows 克隆需启用符号链接支持。

`case.json` 中所有内部路径相对于项目根目录；只有 `raw_root` 为外部数据路径。查看器通过 `workzones/workzone_*/case.json` 自动发现案例。

## 3. 原始数据与项目内文件

原始数据保留在外部，未上传 GitHub、未修改：

```text
/home/data/workzone/work_zone_dataset/work_zone_data_raw/Case_00/
/home/data/workzone/work_zone_dataset/work_zone_data_raw/Case_18/
/home/data/workzone/work_zone_dataset/work_zone_data_raw/Case_14/
```

每案原始 camera0、LiDAR、INS 由上述目录提供，来源索引为 `data/raw_sources.json`。Workzone 3 的图像与点云均限 61–85 秒。

项目内实体按用途存放：

| 目录 | 内容 |
|---|---|
| `data/workzone_NN/processed/` | 处理图像、时间戳、标定引用和位姿元数据 |
| `data/workzone_NN/detections/final_detections.json` | 每案唯一最终确认检测结果 |
| `data/shared/calibration/` | 标定副本 |
| `experiments/agentic_inspection/inputs/` | 规范 PDF、结构化规范、知识图谱、索引 |
| `experiments/agentic_inspection/artifacts/` | 实际执行请求、响应、工具轨迹和几何成果 |
| `experiments/agentic_inspection/scripts/` | 既有重建、检查和报告实现 |
| `tools/` | 统一案例读取、验证工具 |
| `docs/PROJECT_HISTORY.md` | 整理前的历史说明，仅用于追溯 |

最终已接受框：Workzone 1 为 930；Workzone 2 为 238，另有 32 条仅类别记录；Workzone 3 为 241。跨帧框数不等于独立对象数。`tools/project_layout.py::load_detections()` 将三份历史输入格式映射为相同字段，保留原有类别、坐标和观察 ID，不改写原输入。

## 4. 统一处理流程与真实来源

1. **准备输入**：指定原始案例、时间范围、camera0、标定及场景事实；生成项目内图像和元数据。
2. **固定检测**：使用最终人工确认框；不依赖旧候选、复检数据库和修框网页。
3. **重建 BEV**：读取原始 LiDAR 与 INS，逐点运动补偿、图像投影、框内关联及跨帧聚合，输出点云、轨迹、对象位置和不确定性。显示点云经过降采样，不能代替原始测量点云。
4. **Stage 0–6**：选择布局、检索规范、注册要求、计划取证、获取证据与测量、逐项评判、生成报告。
5. **发布结果**：统一 `outputs/report/result.json`、`outputs/bev/viewer.html` 和报告模块。

每个 `stages/stage_N.json` 都具有相同字段：`stage`、`config`、`request`、`model_response`、`tool_trace`、`result`、`execution_group`、`record_status`。合并执行的阶段可以指向同一记录，不虚构独立请求。

结构统一不代表改写执行历史：

- Workzone 1 展示既有最终 PDF 的结论，包括后补几何测量；未因整理目录重跑评判。
- Workzone 2 保留分阶段执行、人工复检后补充取证和几何复评的来源区分。两条临界项按用户要求的项目 10% 容差通过，不修改规范原阈值。
- Workzone 3 保留 Stage 0–6、TA-19 人工确认以及修复重试记录；不声称全部首次运行成功。

历史模型请求、响应和执行配置原样保留，其中绝对路径代表当时环境。**网页查看和统一读取接口可随项目迁移；重新运行历史重建或 Agentic 脚本仍需调整其环境、路径和 API 配置，不把结构标准化等同于计算流程全部已可移植。**

## 5. 新增案例与验证

新增 `workzones/workzone_04/`，沿用相同目录结构，在 `case.json` 填入唯一 `number`、`case_id`、原始范围、布局、来源和 `paths`。路径字段与前三案一致，指向已准备的数据和输出。为 Stage 0–6 填写同格式索引；尚未执行的字段为 `null`，状态写 `partial_record`，不得复制其他案例结果充当新案例。

```bash
python3 tools/validate_project.py
python3 start_viewer.py
```

验证工具检查路径、最终检测框和图像、Stage 记录、逐项状态计数及网页数据。新案例无需在服务器中增加硬编码分支，重启后自动出现在导航。该登记流程不自动执行模型检查；必须先完成实际案例处理。

## 6. 备份与依赖

大文件使用 Git LFS。`backup_manifest.json` 记录当前快照文件的 SHA-256（自身除外）。原始传感器数据、凭据和缓存不进入仓库。

官方 Grounding DINO 权重未做微调，已删除本地副本。固定版本、校验值与恢复命令见 `dependencies/models/grounding-dino-tiny/model_source.json`；仅重新检测时需要恢复。

旧复检文件清理记录：`experiments/agentic_inspection/docs/project_cleanup_20261021.json`。原 `workzone_inspection` 远程仓库保留不变；本仓库为完整项目备份。
