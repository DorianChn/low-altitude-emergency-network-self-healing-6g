from __future__ import annotations

import argparse
import base64
import html
from pathlib import Path


ROOT = Path.cwd()
FINAL = ROOT / "submission" / "final"
AUDIT = FINAL / "audit"
HTML_OUT = AUDIT / "evidence_material_render_source.html"
PDF_OUT = FINAL / "佐证材料.pdf"

parser = argparse.ArgumentParser()
parser.add_argument("--overwrite", action="store_true")
args = parser.parse_args()
if PDF_OUT.exists() and not args.overwrite:
    raise SystemExit(f"Refusing to overwrite {PDF_OUT}")


def data_uri(relative: str) -> str:
    source = ROOT / relative
    if not source.is_file():
        raise FileNotFoundError(source)
    encoded = base64.b64encode(source.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


home = data_uri("submission/final/audit/screenshots/desktop-1920x1080-home.png")
demo = data_uri("submission/final/audit/screenshots/desktop-1920x1080-demo.png")
phase10 = data_uri("plots/phase10/confirmation_policy_comparison.png")
phase14 = data_uri("plots/phase14/phase14_model_service.png")
phase15 = data_uri("plots/phase15/phase15_fit_and_holdout.png")

pages = [
    f"""<section class="page cover"><div class="eyebrow">FIELD SCENARIO DESIGN / EVIDENCE</div>
      <h1>6G / RESCUE</h1><h2>面向6G的低空应急网络智能自愈平台</h2>
      <div class="rule"></div><p class="large">佐证材料</p>
      <p>实际软件界面 · 冻结实验图表 · 测试记录摘要</p>
      <div class="scope">研究仿真与离线回放原型。非真实 6G 网络测试，非目标设备校准，非实物 HIL。</div>
      <footer>学生组 · 场景设计　｜　队伍身份由参赛者补充</footer></section>""",
    f"""<section class="page"><div class="eyebrow">01 / RUNNING PRODUCT</div><h1>系统实际界面</h1>
      <p>截图来自本机 React 应用的真实浏览器页面。界面调用保存的仿真实验与离线回放 API；截图不代表真实设备遥测。</p>
      <img class="wide" src="{home}" alt="首页真实浏览器截图" />
      <div class="caption">来源：submission/final/audit/screenshots/desktop-1920x1080-home.png · 1920×1080</div>
      <p class="note">数字孪生页面展示离散仿真状态。播放控制只读取已计算帧，不插值生成未运行状态。</p></section>""",
    f"""<section class="page"><div class="eyebrow">02 / SAVED DISASTER REPLAY</div><h1>四类灾害场景回放</h1>
      <img class="wide" src="{demo}" alt="严重持续故障的真实浏览器截图" />
      <div class="caption">来源：submission/final/audit/screenshots/desktop-1920x1080-demo.png · 固定 Phase 5 验证回放</div>
      <div class="two"><div><b>场景</b><p>严重持续故障、动态故障、高移动救援、高负载/回传受限。</p></div>
      <div><b>数据口径</b><p>每个场景的演示地图是一个固定种子的逐帧记录；策略表来自同场景20个留出种子。未恢复运行留在成功率分母。</p></div></div>
      <p class="note">场景来源与复现文件见 results/phase6_demo_*.json 及 submission/final/TEST_REPORT.md。</p></section>""",
    f"""<section class="page"><div class="eyebrow">03 / MULTI-UAV CONFIRMATION</div><h1>多无人机策略对照</h1>
      <img class="chart" src="{phase10}" alt="Phase 10 多无人机确认实验图" />
      <div class="caption">来源：plots/phase10/confirmation_policy_comparison.png · Phase 10，4场景、80个确认种子、400次策略运行</div>
      <div class="metrics"><div><b>严重故障</b><span>B′ 58.66%</span><span>G2 66.58% · G3 66.89%</span></div><div><b>高负载</b><span>F3 49.99%</span><span>G3 47.40%</span></div></div>
      <p class="note">结果显示收益依场景变化；高负载下并非集中协同占优。指标是抽象仿真救援用户服务成功率，不可外推成真实网络实测。</p></section>""",
    f"""<section class="page"><div class="eyebrow">04 / LINK MODEL & PUBLIC DATA</div><h1>链路模型与测量边界</h1>
      <div class="figure"><img src="{phase14}" alt="Phase 14 链路模型对服务率影响" /><p>Phase 14：链路预算约束降低动态故障场景中 B′ 服务率，显示距离阈值模型可能高估可行链路。</p></div>
      <div class="figure"><img src="{phase15}" alt="Phase 15 公开空地数据留出结果" /><p>Phase 15：公开 3.6 GHz A2G 数据环境留出，570条样本候选 MAE 1.8195 dB；不是项目设备校准。</p></div>
      <div class="caption">来源：plots/phase14/phase14_model_service.png；plots/phase15/phase15_fit_and_holdout.png；results/phase14_*、results/phase15_*。</div>
      <p class="note">目前没有目标无人机/基站的实测链路数据，不能声称完成设备校准。</p></section>""",
    """<section class="page"><div class="eyebrow">05 / SOFTWARE VERIFICATION</div><h1>软件验证与安全范围</h1>
      <table><thead><tr><th>检查范围</th><th>本机实测结果</th><th>边界</th></tr></thead><tbody>
      <tr><td>Python 全量 pytest</td><td>193 passed</td><td>Windows 11 / Python 3.12</td></tr>
      <tr><td>前端组件测试</td><td>17 passed</td><td>5个测试文件</td></tr>
      <tr><td>Playwright E2E</td><td>30 passed</td><td>6条路由、数据/回放与窄屏断言</td></tr>
      <tr><td>桌面/笔记本/手机页面审计</td><td>18/18 HTTP 200</td><td>未代表第二台设备</td></tr>
      <tr><td>软件故障注入</td><td>21/21通过</td><td>设备输出关闭，非实物HIL</td></tr>
      <tr><td>依赖审计</td><td>npm 0漏洞</td><td>pytest 8.4.2 有 Unix 临时目录公告</td></tr>
      </tbody></table>
      <p>Windows 启动脚本完成 API/前端就绪、页面访问和正常关闭检查。物理断网、第二台设备、外场、真实无线发射和目标设备校准未测试。</p>
      <div class="sources">详细命令、原始日志、hash 审计：submission/final/TEST_REPORT.md、SECURITY_AUDIT.md、audit/history_integrity.json 与 audit/logs/。</div>
      <div class="scope">算法为规则或确定性优化，不是训练型机器学习。研究方向映射不等于 IMT-2030 标准符合性认证。</div></section>""",
]

style = """<style>
@page{size:A4;margin:18mm 19mm}*{box-sizing:border-box}body{margin:0;color:#201c19;font:11pt/1.55 'Microsoft YaHei','SimSun',serif}
.page{height:258mm;page-break-after:always;position:relative;padding:2mm 0 12mm}.page:last-child{page-break-after:auto}
.cover{height:258mm;display:flex;flex-direction:column;justify-content:center;text-align:center;background:linear-gradient(145deg,#1a1310,#281612 55%,#4a1c13);color:#f8f0e8;padding:20mm}
.eyebrow{font:700 9pt/1.3 Arial,sans-serif;letter-spacing:.18em;color:#b3472e;margin-bottom:5mm}.cover .eyebrow{color:#ff8954}
h1{font:700 24pt/1.2 'Microsoft YaHei',sans-serif;margin:0 0 5mm;color:#261d19}h2{font:700 18pt/1.3 'Microsoft YaHei',sans-serif;margin:0 0 8mm;color:#f8f0e8}.cover h1{font:900 46pt/1 Arial,sans-serif;letter-spacing:-.04em;color:#fff;margin-bottom:8mm}
.rule{width:42mm;height:2px;background:#c74e2e;margin:7mm auto}.large{font-size:20pt;font-weight:700;margin:0 0 3mm}.scope{margin-top:13mm;padding:4mm;border:1px solid rgba(255,255,255,.22);font-size:10pt}
img{display:block;object-fit:contain;max-width:100%}.wide{width:100%;height:136mm;margin:3mm auto 2mm;border:1px solid #ddd;background:#120f0e}.chart{width:100%;height:140mm;object-fit:contain;margin:1mm auto 2mm}
.caption{font-size:8.5pt;color:#675c55;margin:1mm 0 4mm}.note{font-size:9pt;color:#655b55;border-left:2px solid #c74e2e;padding-left:3mm;margin-top:5mm}
.two{display:grid;grid-template-columns:1fr 1fr;gap:8mm;margin-top:4mm}.two>div{padding:4mm;background:#f5f1ed}.two b{color:#943a27}.figure{display:grid;grid-template-columns:1.1fr .9fr;align-items:center;gap:6mm;margin:1mm 0 6mm}.figure img{height:79mm;width:100%;object-fit:contain}.figure p{font-size:10pt}
.metrics{display:grid;grid-template-columns:1fr 1fr;gap:5mm;margin-top:3mm}.metrics div{border:1px solid #ddd;padding:4mm;display:flex;flex-direction:column;gap:1mm}.metrics b{color:#9a3c27}.metrics span:first-of-type{font-size:16pt;font-weight:700}
table{border-collapse:collapse;width:100%;margin:6mm 0 8mm;font-size:9.5pt}th{background:#2a1c18;color:#fff;text-align:left}td,th{border:1px solid #d5ccc5;padding:3mm 2.5mm;vertical-align:top}tr:nth-child(even) td{background:#f7f4f1}.sources{font-size:9pt;color:#645952;border-top:1px solid #cfc2b8;padding-top:4mm;margin-top:7mm}
.cover footer{position:absolute;bottom:18mm;left:0;right:0;color:#c8bcb5;font-size:9pt}
</style>"""

HTML_OUT.write_text("<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>6G RESCUE 佐证材料</title>" + style + "<body>" + "".join(pages) + "</body></html>", encoding="utf-8")
print(f"html={HTML_OUT} pages={len(pages)}")
