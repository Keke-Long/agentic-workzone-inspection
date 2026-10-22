# Workzone 2

统一入口：`case.json`。相同结构适用于所有案例。

- `config/`：阶段配置。
- `inputs/`：场景、处理数据与唯一最终检测输入（相对链接，不复制检测结果）。
- `outputs/bev/`：网页及点云、轨迹、对象数据。
- `outputs/report/`：当前逐条结果和页面模块。
- `stages/stage_0.json` 至 `stage_6.json`：统一字段的请求、模型响应、工具轨迹和结果索引。路径均相对于项目根目录。

规范布局：TA-22；原始案例：Case_18。

来源说明：Evidence reassessment and geometry repair after staged execution; 10% project tolerance is a display assessment policy.
历史记录保留原样，不把目录整理当作新模型执行。
