# Workzone 1 当前案例入口

当前最终检测输入：`/home/klong23/workzone/data/workzone_01/detections/final_detections.json`。
处理后的传感器数据：`/home/klong23/workzone/data/workzone_01/processed/`。
检测结果作为固定输入；人工复查网页、候选队列、数据库和早期错误版本已清理。历史阶段记录中的输入快照仅用于追溯，不是另一份当前检测结果。

camera0 当前输入为 930 个已接受框。`scene.json` 已限定 camera0；旧报告尚未据此重新评判，旧多相机结论不能直接沿用。Stage 0–6 记录入口见 `processing_record.json`；既有几何补评为 `artifacts/workzone_01/pipeline/final_evaluated/`。报告在 `reports/workzone_01/final/`，属于待回查的历史评判。

## 当前 BEV

已从经逐帧验证的原始 Case_00 点云和 INS 重建 1,027 帧。930 个 camera0 观察形成 108 个位置候选，73 个有多帧支持，25 个观察未可靠定位。显示点云 773,512 点；对象状态未重新检查，旧规范结论未导入。

```text
/home/klong23/workzone/experiments/agentic_inspection/artifacts/workzone_01/bev_reconstruction/scene_bev/
/home/klong23/workzone/experiments/agentic_inspection/reports/workzone_01/bev/bev.html
```
