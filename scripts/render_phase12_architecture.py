"""Generate editable Mermaid sources and report-ready SVG/PNG diagrams.

The card/edge definitions in this file are the single source for all four
outputs. Requires Pillow from the project's locked Python environment.
"""

from __future__ import annotations

import html
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/phase12"
WIDTH = 1920
INK = "#211c1a"
MUTED = "#665c57"
RED = "#851f2b"
ORANGE = "#d46b35"
PAPER = "#f5f1ed"
WHITE = "#fffdfb"
LINE = "#d8cec7"
PALE_RED = "#f3e3e3"
PALE_GOLD = "#f8ecd9"

ARCH_LAYERS = [
    {
        "title": "01  灾害与业务场景层",
        "body": "场景配置 + 固定种子，生成城市、用户位置/需求、移动轨迹和故障/流量事件。",
        "code": "configs/phase5 · src/lowalt6g/config.py · dynamic_config.py · scenario.py · dynamic_world.py",
    },
    {
        "title": "02  网络状态与链路模型层",
        "body": "维护基站健康/容量、回传可用性、用户和无人机状态；按距离与容量判断端到端候选路径。",
        "code": "src/lowalt6g/models.py · engine.py · multi_uav.py::evaluate_fleet",
    },
    {
        "title": "03  资源分配与调度策略层",
        "body": "策略读取当前可观察状态并输出候选目标/分配：A、B、B′、C、D、E、F、G、H、I、J。",
        "code": "src/lowalt6g/policies.py · optimizer.py · phase9_strategy_e.py · multi_uav.py · phase11_algorithms.py",
    },
    {
        "title": "04  仿真执行与运行时安全层",
        "body": "仿真环境应用故障和动作；在执行路径检查速度、城市边界、链路/容量、电池储备、返航预算和机间距。",
        "code": "src/lowalt6g/dynamic_simulation.py · multi_uav.py · multi_uav_simulation.py · phase11_simulation.py",
    },
    {
        "title": "05  实验、统计与数据审计层",
        "body": "配对场景/种子运行，保存逐种子结果、恢复/服务/时延/能耗/计算指标、配置与源码哈希。",
        "code": "src/lowalt6g/phase5.py · phase8_experiments.py · phase9_experiments.py · phase10_experiments.py · phase11_experiments.py",
    },
    {
        "title": "06  API 与数据服务层",
        "body": "FastAPI 只读读取已生成的 Phase 2/5 指标和 Phase 3/6 离线回放；无实时遥测和设备控制。",
        "code": "src/lowalt6g/api.py · phase6_api.py · phase6_demo.py",
    },
    {
        "title": "07  数字孪生展示与交互层",
        "body": "React 根据保存的离散帧展示网络状态，提供策略/时间轴选择、暂停、继续和回放。",
        "code": "frontend/src/App.tsx · data.tsx · pages.tsx · Phase6DemoPage.tsx",
    },
]

FLOW_CARDS = [
    {
        "title": "场景输入",
        "body": ["TOML 场景", "固定随机种子", "策略与约束"],
        "code": ["configs/phase5/", "configs/phase11/"],
        "fill": WHITE,
    },
    {
        "title": "共享世界轨迹",
        "body": ["同种子同轨迹", "动态用户位置", "记录轨迹哈希"],
        "code": ["dynamic_world.py", "build_world_trace()"],
        "fill": WHITE,
    },
    {
        "title": "策略观测与决策",
        "body": ["读取当前状态", "输出目标或分配", "不读未来事件"],
        "code": ["optimizer.py", "phase9_strategy_e.py", "multi_uav.py"],
        "fill": PALE_GOLD,
    },
    {
        "title": "仿真执行与安全门",
        "body": ["共享容量分配", "速度与距离检查", "电量储备与返航"],
        "code": ["dynamic_simulation.py", "phase11_simulation.py"],
        "fill": PALE_RED,
    },
    {
        "title": "逐次实验记录",
        "body": ["逐策略保存轨迹", "服务/恢复/能耗", "时延样本与耗时"],
        "code": ["results/phase5_validation_summary.json", "results/phase11_confirmation_raw.json"],
        "fill": WHITE,
    },
    {
        "title": "冻结与完整性边界",
        "body": ["Phase 5/8/9/10/11", "原始 JSON 与哈希", "只读核验"],
        "code": ["results/phase11_artifact_manifest.json"],
        "fill": PALE_GOLD,
    },
    {
        "title": "只读 API / 回放 UI",
        "body": ["只开放既有路由", "读取 Phase 2/5/6", "无实时策略控制"],
        "code": ["api.py · phase6_api.py", "frontend/src/data.tsx"],
        "fill": WHITE,
    },
]


def _font(size: int, *, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        [r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\msyh.ttc"]
        if bold
        else [r"C:\Windows\Fonts\msyh.ttc"]
    )
    if mono:
        candidates = [r"C:\Windows\Fonts\consola.ttf", *candidates]
    candidates.extend([r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf"])
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            pass
    return ImageFont.load_default()


def _visual_code_lines(items: list[str], max_chars: int = 25) -> list[str]:
    lines: list[str] = []
    for item in items:
        while len(item) > max_chars:
            lines.append(item[:max_chars])
            item = item[max_chars:]
        lines.append(item)
    return lines


def _arrow(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], color: str, width: int = 4) -> None:
    draw.line((start, end), fill=color, width=width)
    x, y = end
    draw.polygon([(x, y), (x - 11, y - 18), (x + 11, y - 18)], fill=color)


def _write_architecture_mmd() -> None:
    lines = ["flowchart TB"]
    for index, layer in enumerate(ARCH_LAYERS, 1):
        label = f"{layer['title']}<br/>{layer['body']}<br/>{layer['code']}"
        lines.append(f'  L{index}["{label}"]')
    for index in range(1, len(ARCH_LAYERS)):
        lines.append(f"  L{index} --> L{index + 1}")
    lines.append("  L4 -. 当前仿真状态反馈 .-> L3")
    lines.append("  L3 -. 候选动作 .-> L4")
    lines.append("  classDef focus fill:#f3e3e3,stroke:#851f2b,color:#211c1a,stroke-width:2px")
    lines.append("  class L3,L4 focus")
    (OUT / "system_architecture.mmd").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_flow_mmd() -> None:
    labels = []
    for i, card in enumerate(FLOW_CARDS, 1):
        body = "<br/>".join(card["body"] + card["code"])
        labels.append(f'  F{i}["{card["title"]}<br/>{body}"]')
    lines = ["flowchart LR", *labels]
    for i in range(1, len(FLOW_CARDS)):
        lines.append(f"  F{i} --> F{i + 1}")
    lines.extend(
        [
            '  P12["Phase 12 只读审计<br/>模块路径/哈希/API/图表核验<br/>新建 results/phase12_integrity_audit.json<br/>不写回历史结果"]',
            "  F6 --> P12",
            "  F2 -. 同种子相同轨迹 .-> F4",
            "  classDef safety fill:#f3e3e3,stroke:#851f2b,color:#211c1a,stroke-width:2px",
            "  class F3,F4 safety",
        ]
    )
    (OUT / "research_dataflow.mmd").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _svg_text(x: int, y: int, text: str, *, size: int, color: str, weight: int = 400, family: str = "Segoe UI, Microsoft YaHei, sans-serif") -> str:
    return f'<text x="{x}" y="{y}" fill="{color}" font-family="{family}" font-size="{size}px" font-weight="{weight}">{html.escape(text)}</text>'


def _save_architecture() -> None:
    height = 1450
    image = Image.new("RGB", (WIDTH, height), PAPER)
    draw = ImageDraw.Draw(image)
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" viewBox="0 0 {WIDTH} {height}">',
        '<defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="5" refY="4" orient="auto"><path d="M0,0 L10,4 L0,8 z" fill="#851f2b"/></marker><marker id="arrowOrange" markerWidth="10" markerHeight="10" refX="5" refY="4" orient="auto"><path d="M0,0 L10,4 L0,8 z" fill="#d46b35"/></marker></defs>',
        f'<rect width="100%" height="100%" fill="{PAPER}"/>',
    ]
    title_font, body_font, code_font = _font(38, bold=True), _font(23), _font(17, mono=True)
    x, card_w, card_h, first_y, step = 250, 1420, 145, 125, 177
    for index, layer in enumerate(ARCH_LAYERS):
        y = first_y + index * step
        draw.rounded_rectangle((x, y, x + card_w, y + card_h), radius=24, fill=WHITE, outline=LINE, width=2)
        draw.rounded_rectangle((x, y, x + 17, y + card_h), radius=8, fill=RED)
        draw.text((x + 42, y + 14), layer["title"], font=title_font, fill=INK)
        draw.text((x + 43, y + 62), layer["body"], font=body_font, fill=MUTED)
        draw.text((x + 43, y + 106), layer["code"], font=code_font, fill=RED)
        svg.extend(
            [
                f'<rect x="{x}" y="{y}" width="{card_w}" height="{card_h}" rx="24" fill="{WHITE}" stroke="{LINE}" stroke-width="2"/>',
                f'<rect x="{x}" y="{y}" width="17" height="{card_h}" rx="8" fill="{RED}"/>',
                _svg_text(x + 42, y + 50, layer["title"], size=38, color=INK, weight=700),
                _svg_text(x + 43, y + 88, layer["body"], size=23, color=MUTED),
                _svg_text(x + 43, y + 127, layer["code"], size=17, color=RED, family="Consolas, monospace"),
            ]
        )
        if index < len(ARCH_LAYERS) - 1:
            _arrow(draw, (WIDTH // 2, y + card_h + 3), (WIDTH // 2, y + step - 9), RED)
            svg.append(f'<path d="M{WIDTH // 2} {y + card_h + 3} L{WIDTH // 2} {y + step - 9}" stroke="{RED}" stroke-width="4" marker-end="url(#arrow)"/>')

    # A separate right-side state feedback path makes the observe/act loop explicit.
    y_strategy = first_y + 2 * step + card_h // 2
    y_runtime = first_y + 3 * step + card_h // 2
    right = x + card_w + 85
    draw.line([(x + card_w, y_runtime), (right, y_runtime), (right, y_strategy), (x + card_w, y_strategy)], fill=ORANGE, width=4)
    draw.polygon([(x + card_w, y_strategy), (x + card_w + 17, y_strategy - 10), (x + card_w + 17, y_strategy + 10)], fill=ORANGE)
    draw.text((right - 120, y_strategy - 34), "当前状态反馈", font=_font(18, bold=True), fill=ORANGE)
    svg.extend(
        [
            f'<path d="M{x + card_w} {y_runtime} L{right} {y_runtime} L{right} {y_strategy} L{x + card_w} {y_strategy}" fill="none" stroke="{ORANGE}" stroke-width="4" marker-end="url(#arrowOrange)"/>',
            _svg_text(right - 130, y_strategy - 20, "当前状态反馈", size=18, color=ORANGE, weight=700),
        ]
    )
    foot = "控制器只接收当前仿真观察；环境事件表由仿真器执行。运行时安全检查位于动作执行路径，不由策略自行绕过。"
    draw.text((250, 1395), foot, font=_font(22), fill=MUTED)
    svg.extend([_svg_text(250, 1405, foot, size=22, color=MUTED), "</svg>"])
    (OUT / "system_architecture.svg").write_text("\n".join(svg), encoding="utf-8")
    image.save(OUT / "system_architecture.png", optimize=True)


def _save_dataflow() -> None:
    height = 1030
    image = Image.new("RGB", (WIDTH, height), PAPER)
    draw = ImageDraw.Draw(image)
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" viewBox="0 0 {WIDTH} {height}">',
        '<defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="5" refY="4" orient="auto"><path d="M0,0 L10,4 L0,8 z" fill="#851f2b"/></marker><marker id="arrowOrange" markerWidth="10" markerHeight="10" refX="5" refY="4" orient="auto"><path d="M0,0 L10,4 L0,8 z" fill="#d46b35"/></marker></defs>',
        f'<rect width="100%" height="100%" fill="{PAPER}"/>',
    ]
    x0, card_w, card_h, gap, y = 38, 245, 340, 22, 260
    title_font, body_font, code_font = _font(23, bold=True), _font(18), _font(12, mono=True)
    for index, card in enumerate(FLOW_CARDS):
        x = x0 + index * (card_w + gap)
        draw.rounded_rectangle((x, y, x + card_w, y + card_h), radius=20, fill=card["fill"], outline=LINE, width=2)
        draw.rounded_rectangle((x, y, x + card_w, y + 13), radius=7, fill=RED if index in (2, 3) else ORANGE)
        draw.text((x + 17, y + 32), card["title"], font=title_font, fill=INK)
        body_y = y + 88
        for item in card["body"]:
            draw.text((x + 17, body_y), f"• {item}", font=body_font, fill=MUTED)
            body_y += 35
        code_y = y + 214
        code_font = _font(12, mono=True)
        visual_codes = _visual_code_lines(card["code"])
        for item in visual_codes:
            draw.text((x + 17, code_y), item, font=code_font, fill=RED)
            code_y += 24
        svg.extend(
            [
                f'<rect x="{x}" y="{y}" width="{card_w}" height="{card_h}" rx="20" fill="{card["fill"]}" stroke="{LINE}" stroke-width="2"/>',
                f'<rect x="{x}" y="{y}" width="{card_w}" height="13" rx="7" fill="{RED if index in (2, 3) else ORANGE}"/>',
                _svg_text(x + 17, y + 62, card["title"], size=23, color=INK, weight=700),
            ]
        )
        for row, item in enumerate(card["body"]):
            svg.append(_svg_text(x + 17, y + 110 + row * 35, f"• {item}", size=18, color=MUTED))
        for row, item in enumerate(visual_codes):
            svg.append(_svg_text(x + 17, y + 238 + row * 24, item, size=12, color=RED, family="Consolas, monospace"))
        if index < len(FLOW_CARDS) - 1:
            ax = x + card_w + 3
            draw.line((ax, y + card_h // 2, ax + gap - 6, y + card_h // 2), fill=RED, width=4)
            draw.polygon([(ax + gap - 6, y + card_h // 2), (ax + gap - 18, y + card_h // 2 - 9), (ax + gap - 18, y + card_h // 2 + 9)], fill=RED)
            svg.append(f'<path d="M{ax} {y + card_h // 2} L{ax + gap - 6} {y + card_h // 2}" stroke="{RED}" stroke-width="4" marker-end="url(#arrow)"/>')

    # Separate Phase 12 audit from the frozen evidence path: it reads checksums,
    # but its sole result is a new Phase 12 namespace file.
    box = (575, 735, 1370, 965)
    draw.rounded_rectangle(box, radius=24, fill=PALE_GOLD, outline=ORANGE, width=3)
    draw.text((box[0] + 30, box[1] + 28), "Phase 12：只读证据审计与架构追踪", font=_font(31, bold=True), fill=INK)
    draw.text((box[0] + 30, box[1] + 87), "核验历史哈希、运行计数、源码路径、API 路由和追踪关系", font=_font(22), fill=MUTED)
    draw.text((box[0] + 30, box[1] + 139), "新增结果文件：", font=_font(20, bold=True), fill=RED)
    draw.text((box[0] + 190, box[1] + 139), "results/phase12_integrity_audit.json", font=_font(17, mono=True), fill=RED)
    draw.text((box[0] + 30, box[1] + 185), "新增文档与图表；历史 Phase 5–11 文件保持只读。", font=_font(20), fill=MUTED)
    svg.extend(
        [
            f'<rect x="{box[0]}" y="{box[1]}" width="{box[2]-box[0]}" height="{box[3]-box[1]}" rx="24" fill="{PALE_GOLD}" stroke="{ORANGE}" stroke-width="3"/>',
            _svg_text(box[0] + 30, box[1] + 66, "Phase 12：只读证据审计与架构追踪", size=31, color=INK, weight=700),
            _svg_text(box[0] + 30, box[1] + 124, "核验历史哈希、运行计数、源码路径、API 路由和追踪关系", size=22, color=MUTED),
            _svg_text(box[0] + 30, box[1] + 171, "新增结果文件：", size=20, color=RED, weight=700),
            _svg_text(box[0] + 190, box[1] + 171, "results/phase12_integrity_audit.json", size=17, color=RED, family="Consolas, monospace"),
            _svg_text(box[0] + 30, box[1] + 215, "新增文档与图表；历史 Phase 5–11 文件保持只读。", size=20, color=MUTED),
        ]
    )
    # Dashed read-only evidence link from the manifest card to the audit box.
    start_x = x0 + 5 * (card_w + gap) + card_w // 2
    end_x = box[0] + (box[2] - box[0]) // 2
    draw.line((start_x, y + card_h, start_x, 690), fill=ORANGE, width=3)
    draw.line((start_x, 690, end_x, 690), fill=ORANGE, width=3)
    draw.line((end_x, 690, end_x, box[1]), fill=ORANGE, width=3)
    draw.polygon([(end_x, box[1]), (end_x - 8, box[1] - 14), (end_x + 8, box[1] - 14)], fill=ORANGE)
    svg.append(f'<path d="M{start_x} {y + card_h} L{start_x} 690 L{end_x} 690 L{end_x} {box[1]}" fill="none" stroke="{ORANGE}" stroke-width="3" stroke-dasharray="9 8" marker-end="url(#arrowOrange)"/>')
    note = "当前 React 页面加载的是 API 明确开放的历史回放；Phase 8–11 确认集用于研究审计，尚未接入当前交互页面。"
    draw.text((38, 985), note, font=_font(21), fill=MUTED)
    svg.extend([_svg_text(38, 1000, note, size=21, color=MUTED), "</svg>"])
    (OUT / "research_dataflow.svg").write_text("\n".join(svg), encoding="utf-8")
    image.save(OUT / "research_dataflow.png", optimize=True)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    _write_architecture_mmd()
    _write_flow_mmd()
    _save_architecture()
    _save_dataflow()
    for name in ("system_architecture", "research_dataflow"):
        for extension in ("mmd", "svg", "png"):
            path = OUT / f"{name}.{extension}"
            print(f"{path.relative_to(ROOT)} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
