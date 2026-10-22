"""Render the recorded Workzone 3 Stage 6 results without changing conclusions."""
import json
from collections import Counter
from html import escape
from pathlib import Path

E = Path(__file__).resolve().parents[1]
A = E / 'artifacts/workzone_03/agentic_final_review81'


def h(value):
    return escape(str(value if value is not None else ''))


def main():
    result = json.loads((A / 'stage6/result.json').read_text())
    record = result['record']
    if not record.get('finalized'):
        raise ValueError('Cannot publish an unfinished Stage 6 result')
    labels = {'satisfied': '未发现明显不符', 'deficient': '不符合', 'not_assessed': '证据不足 / 未评判'}
    counts = Counter(r.get('inspection_status') for r in record['requirements'])
    rows = []
    for i, r in enumerate(record['requirements'], 1):
        evidence = {k: record.get('evidence_records', {}).get(k) for k in r.get('evidence_ids', [])}
        measurements = {k: record.get('measurement_records', {}).get(k) for k in r.get('measurement_ids', [])}
        details = {'requirement': r, 'cited_evidence': evidence, 'cited_measurements': measurements}
        status = r.get('inspection_status', 'not_assessed')
        rows.append(f'<tr><td>{i}</td><td>{h(r.get("candidate_label"))}<br><small>{h(r.get("modality"))} · {h(r.get("source_locator"))}</small></td>'
                    f'<td class="{h(status)}">{h(labels.get(status, status))}<br><small>适用性：{h(r.get("normative_applicability"))}</small></td>'
                    f'<td>{h(r.get("inspection_reason"))}<br><small>未解决输入：{h(", ".join(r.get("unresolved_inputs", [])) or "无")}</small>'
                    f'<details><summary>规范原文、证据与测量记录</summary><pre>{h(json.dumps(details, ensure_ascii=False, indent=2))}</pre></details></td></tr>')
    layouts = ', '.join(x['layout_code'] for x in record['selected_layouts'] if x['layout_role'] == 'primary_applicable')
    html = f'''<!doctype html><html lang="zh"><meta charset="utf-8"><title>Workzone 3 规范评判</title>
<style>body{{font:16px/1.6 system-ui;margin:24px;color:#183047}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ccd5dd;padding:12px;text-align:left;vertical-align:top}}th{{background:#eaf1f6}}small{{color:#526575}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;max-height:500px;overflow:auto;font-size:12px}}.satisfied{{color:#157047}}.deficient{{color:#ae2929}}.not_assessed{{color:#8a6100}}summary{{cursor:pointer}}</style><body>
<h1>Workzone 3 · Agentic AI 规范评判</h1>
<p>Case_14 · 原始时间 61–85 秒 · camera0 + 原始 LiDAR + INS · 人工审核版本 81<br>
限速 20 mph；施工小于 3 天；对向车道封闭、车辆经其他道路绕行。主要布局：{h(layouts)}。</p>
<p>流程说明：Stage 0 经来源复核后选定 TA-19，并由用户确认。本轮修复了类别触发遗漏、补充候选处置遗漏及证据批次错误；失败尝试与纠错记录均保留。因此本轮属于经干预修复的执行，不代表首次无干预成功。</p>
<p>规范来源：MUTCD 11th Edition (December 2023)，KG + BM25。Stage 0–6 的配置、请求、模型响应和工具轨迹均保存在项目中。</p>
<p>共 {len(record['requirements'])} 条：未发现明显不符 {counts['satisfied']}；不符合 {counts['deficient']}；未评判 {counts['not_assessed']}。本流程的 satisfied 表示现有证据未发现明显不符，不是对全部对象和不可见区域的合规证明。未评判不代表合规或违规。</p>
<p>原始点云与 INS 已存在；条目中的“未获取”指该要求所需证据未通过当前工具链取得，不表示传感器文件缺失。空间证据采用人工确认检测框的 BEV 关联。单帧身份暂定、未定位目标及未拍摄的绕行路线仍存在证据限制；本报告不是对场景中所有潜在规范的完整性保证。</p>
<table><thead><tr><th>#</th><th>要求与出处</th><th>结果</th><th>理由与证据</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
<details><summary>完整性与流程完成记录</summary><pre>{h(json.dumps(record.get('completion'),ensure_ascii=False,indent=2))}</pre></details>
<p>结果目录：{h(A / 'stage6')}<br>本页直接呈现已提交结果，未修改模型结论。独立参考答案尚未建立，不报告准确率。</p></body></html>'''
    out = E / 'reports/workzone_03/final'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'report.html').write_text(html)
    (out / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(out / 'report.html')


if __name__ == '__main__':
    main()
