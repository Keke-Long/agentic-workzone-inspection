"""Derived display decisions; preserve frozen agent records and normative thresholds."""
from pathlib import Path
import json, hashlib, html, re
from collections import Counter
ROOT = Path(__file__).resolve().parents[1]
SOURCES = {1:'artifacts/workzone_01/pipeline/stage6/scene-CATS-01/result.json',2:'reports/workzone_02/ta22_user_selected/post_review_20261021/result.json',3:'reports/workzone_03/final/result.json'}
LABELS = {'pass':('✓','通过'),'fail':('!','未通过'),'unknown':('?','证据不足'),'pending':('—','待复评'),'na':('—','不适用')}
def esc(v): return html.escape(str(v))
def minimum_pass(value, minimum): return value >= minimum * .9

def build(case):
    source=ROOT/SOURCES[case]; raw=source.read_bytes(); data=json.loads(raw)
    reqs=data['requirements'] if case==2 else data['record']['requirements']
    pdf_rows = {}
    if case == 1:
        final_dir = ROOT / 'reports/workzone_01/final'
        for line in (final_dir / 'stage6_final_report.md').read_text().splitlines():
            if re.match(r'\| \d+ \|', line):
                cells = [c.strip() for c in line.strip('|').split('|')]
                pdf_rows[int(cells[0])] = cells[2].strip('`')
        assert len(pdf_rows) == 19
    rows=[]
    for i,r in enumerate(reqs,1):
        original=r.get('status',r.get('inspection_status'))
        status={'supported':'pass','no_visible_defect':'pass','satisfied':'pass','deficient':'fail','not_applicable':'na'}.get(original,'unknown')
        reason=r.get('reason',r.get('inspection_reason',''))
        title=r.get('title',r.get('candidate_label',''))
        tol=None
        if case==1:
            original = pdf_rows[i]
            status = {'satisfied':'pass','deficient':'fail','not_assessed':'unknown'}[original]
            if i == 4:
                reason = '最终 PDF 补充测量：A/B/C 约为 270.8 / 249.8 / 219.4 ft，均超过已登记的 100 ft 建议最小间距。'
            elif i == 8:
                reason = '最终 PDF 补充测量：并道渐变段约 158.7 ft；W=9.39 ft、S=30 mph 时，公式要求为 140.9 ft，满足要求。'
            elif i in (6,7):
                reason = 'I4844 反光带大面积脱落、缺失；I5502 多条反光带明显破损、剥离。两条规范对应同一类设施状况问题，图片证据见下方。'
            elif i == 17:
                reason = '最终 PDF 保留为未评判：所需数值距离或几何关系未得到验证。'

        if case==2 and i in (8,11):
            t=data['geometry_validation']['full_reassessment']['taper']
            value=t['length_m'];target=t['required_length_m_at_25mph'];delta=(value/target-1)*100
            status='pass' if minimum_pass(value,target) else 'fail'
            tol={'measured_m':value,'required_m':target,'relative_deviation_percent':delta,'minimum_with_tolerance_m':target*.9,'basis':'nominal estimate; original sensitivity and lane-width limitations retained'}
            reason=f'渐变段实测 {value:.2f} m，计算要求 {target:.2f} m，偏差 {delta:+.2f}%；按本项目 10% 容差通过。原始测量敏感性及车道宽度估计限制仍保留。'+ (' 预告位置证据沿用原评判。' if i==11 else '')
        rows.append({'number':i,'title':title,'status':status,'original_status':original,'reason':reason,'source_locator':r.get('source_locator',''),'evidence_ids':r.get('evidence_ids',[]),'original_reason':r.get('reason',r.get('inspection_reason','')),'tolerance':tol})
    counts=dict(Counter(r['status'] for r in rows))
    result={'case':f'Workzone {case}','source':str(source),'source_sha256':hashlib.sha256(raw).hexdigest(),'policy':'User-requested project tolerance: 10% of numeric requirement; does not change source standards or resolve missing measurements. No visible defect is displayed as pass within inspected scope.','counts':counts,'requirements':rows}
    out=ROOT/f'reports/workzone_{case:02d}/inspection_summary';out.mkdir(parents=True,exist_ok=True)
    if case == 1:
        pdf = final_dir / 'stage6_final_report.pdf'
        result['source'] = str(pdf)
        result['source_sha256'] = hashlib.sha256(pdf.read_bytes()).hexdigest()
        result['supporting_sources'] = [str(final_dir / 'stage6_final_report.md'), str(final_dir / 'stage6_final_report.html'), str(source)]
        result['provenance'] = 'Existing final PDF conclusions, including later completed geometry assessments; presentation restoration, not a new inspection run.'
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    style='''<style>
.inspection-report{margin:24px 12px;padding:24px;background:#fff;border:1px solid #d5dfe7;border-radius:10px;color:#203244;font:14px/1.65 system-ui;scroll-margin-top:12px}.inspection-report h2{margin:0 0 8px}.inspection-report h3{margin:24px 0 8px}.inspection-report table{width:100%;border-collapse:collapse;table-layout:auto}.inspection-report th,.inspection-report td{padding:12px 10px;text-align:left;border-bottom:1px solid #e4eaf0;vertical-align:top}.inspection-report th{background:#f1f5f8}.inspection-report .decision{white-space:nowrap;font-weight:700}.inspection-report .pass{color:#13783d}.inspection-report .fail{color:#bc2525}.inspection-report .unknown{color:#9a6500}.inspection-report .pending,.inspection-report .na{color:#627080}.inspection-report .symbol{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border:1px solid currentColor;border-radius:50%;margin-right:6px}.inspection-report .counts{display:flex;gap:18px;flex-wrap:wrap;margin:14px 0}.inspection-report .note{color:#586b7d;font-size:13px}.inspection-report details{margin-top:6px}.inspection-report summary{cursor:pointer}.inspection-report .finding{padding:14px;background:#fff5f4;border-left:4px solid #bc2525;margin:12px 0}.inspection-report .table-wrap{overflow-x:auto}.inspection-report img{max-width:100%}
</style>'''
    parts=[style,f'<section class="inspection-report" id="case-report"><h2>Workzone {case} · 规范检查结果</h2>', '<p class="note">数值判定采用项目约定的 10% 容差：最低要求允许低至原值的 90%，最高限值允许高至原值的 110%。不修改规范原值；证据不足不算通过。“未发现明显不符”按已检查范围记为通过。</p>']
    if case==1:parts.append('<p>依据既有 Stage 6 最终 PDF 报告恢复结果（TA-30），包含报告中补充完成的几何测量。以下为该报告结论与原有证据，并非本次重新运行评判。</p>')
    parts.append('<div class="counts">'+''.join(f'<span class="{s}">{LABELS[s][0]} {LABELS[s][1]} {n}</span>' for s,n in counts.items())+'</div>')
    parts.append('<div class="table-wrap"><table><thead><tr><th>#</th><th>规范要求</th><th>结果</th><th>判定说明与依据</th></tr></thead><tbody>')
    for r in rows:
        s=r['status'];symbol,label=LABELS[s]
        if r['tolerance']:label+='（10% 容差）'
        evidence='、'.join(map(str,r['evidence_ids'])) or '无已登记证据编号'
        parts.append(f'<tr data-status="{s}"><td>{r["number"]}</td><td>{esc(r["title"])}</td><td class="decision {s}"><span class="symbol">{symbol}</span>{label}</td><td>{esc(r["reason"])}<details><summary>规范来源与证据</summary><div>{esc(r["source_locator"])}</div><div>案例：Workzone {case}</div><div>证据：{esc(evidence)}</div>'+ (f'<p>原评判说明：{esc(r["original_reason"])}</p>' if r['tolerance'] else '')+'</details></td></tr>')
    parts.append('</tbody></table></div><h3>未通过条目与图片证据</h3>')
    failures=[r for r in rows if r['status']=='fail']
    if not failures:parts.append('<p>当前评判没有已确认的未通过条目。</p>')
    for r in failures:
        parts.append(f'<article class="finding"><strong>! Workzone {case} · 第 {r["number"]} 条：{esc(r["title"])}</strong><p>{esc(r["reason"])}</p><p>证据编号：{esc(r["evidence_ids"])}</p></article>')
    if case == 1:
        evidence_html = (final_dir / 'stage6_final_report.html').read_text()
        figures = re.findall(r'<figure class="evidence-card">.*?</figure>', evidence_html, re.S)
        assert len(figures) == 2
        parts.append('<h3>Workzone 1 · 设施状况证据（第 6、7 条）</h3><p>以下两张图片沿用最终 PDF 的对象编号、帧编号及检测框。</p><div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px">')
        parts.extend(figures)
        parts.append('</div>')
    unknown=[r for r in rows if r['status']=='unknown']
    if unknown:
        parts.append('<h3>仍需补充证据</h3>')
        parts.extend(f'<p><strong>第 {r["number"]} 条 · {esc(r["title"])}</strong>：{esc(r["reason"])}</p>' for r in unknown)
    parts.append('</section>')
    (out/'module.html').write_text(''.join(parts))
    print(case,counts)
if __name__=='__main__':
    for case in SOURCES:build(case)
