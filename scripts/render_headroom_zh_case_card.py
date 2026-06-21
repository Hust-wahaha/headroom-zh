from __future__ import annotations

import math
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "docs" / "assets"
BG_PATH = ASSET_DIR / "headroom-zh-case-card-bg.png"
OUT_PATH = ASSET_DIR / "headroom-zh-case-card.png"


def load_font(size: int, *, mono: bool = False, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates: list[str]
    if mono:
        candidates = [
            "C:/Windows/Fonts/consola.ttf",
            "C:/Windows/Fonts/consolab.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        ]
    elif bold:
        candidates = [
            "C:/Windows/Fonts/msyhbd.ttc",
            "C:/Windows/Fonts/msyh.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
    else:
        candidates = [
            "C:/Windows/Fonts/msyh.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.splitlines():
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for char in paragraph:
            trial = current + char
            width = draw.textbbox((0, 0), trial, font=font)[2]
            if current and width > max_width:
                lines.append(current)
                current = char
            else:
                current = trial
        if current:
            lines.append(current)
    return lines


def draw_multiline(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
    max_width: int,
    line_gap: int,
) -> int:
    x, y = xy
    lines = wrap_text(draw, text, font, max_width)
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        bbox = draw.textbbox((x, y), line or " ", font=font)
        y += (bbox[3] - bbox[1]) + line_gap
    return y


def rounded_panel(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    fill: tuple[int, int, int, int],
    outline: tuple[int, int, int, int],
    width: int = 2,
    radius: int = 28,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def add_chip(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    label: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
    text_fill: tuple[int, int, int, int],
    outline: tuple[int, int, int, int],
) -> int:
    left, top, right, bottom = draw.textbbox((0, 0), label, font=font)
    w = (right - left) + 34
    h = (bottom - top) + 18
    draw.rounded_rectangle((x, y, x + w, y + h), radius=16, fill=fill, outline=outline, width=1)
    draw.text((x + 17, y + 9), label, font=font, fill=text_fill)
    return w


def build_base(size: tuple[int, int]) -> Image.Image:
    width, height = size
    if BG_PATH.exists():
        bg = Image.open(BG_PATH).convert("RGBA").resize(size)
    else:
        bg = Image.new("RGBA", size, (12, 20, 25, 255))
        pix = bg.load()
        for y in range(height):
            t = y / max(height - 1, 1)
            r = int(10 + 18 * t)
            g = int(20 + 46 * (1 - abs(t - 0.45)))
            b = int(28 + 52 * (1 - t * 0.55))
            for x in range(width):
                xmix = 0.8 + 0.2 * math.sin(x / 160)
                pix[x, y] = (int(r * xmix), int(g * xmix), int(b * xmix), 255)

    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for idx, alpha in enumerate((55, 35, 20)):
        inset = 80 + idx * 110
        od.rounded_rectangle(
            (inset, inset - 10, width - inset, height - inset + 10),
            radius=48,
            outline=(123, 194, 177, alpha),
            width=2,
        )
    for x in range(160, width, 140):
        od.line((x, 110, x - 120, height - 110), fill=(124, 206, 188, 18), width=1)
    return Image.alpha_composite(bg, overlay)


def main() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    canvas = build_base((1600, 980))
    canvas = canvas.filter(ImageFilter.GaussianBlur(radius=0.4))
    draw = ImageDraw.Draw(canvas)

    title_font = load_font(48, bold=True)
    title_font_small = load_font(42, bold=True)
    subtitle_font = load_font(24)
    section_font = load_font(22, bold=True)
    body_font = load_font(19)
    code_font = load_font(20, mono=True)
    chip_font = load_font(18, bold=True)
    small_font = load_font(18)

    ivory = (244, 238, 222, 255)
    muted = (188, 202, 198, 255)
    teal = (111, 214, 191, 255)
    mint = (177, 235, 221, 255)
    slate = (16, 30, 36, 228)
    slate_light = (24, 42, 49, 212)
    stroke = (126, 196, 181, 110)
    amber = (238, 184, 92, 255)

    draw.text((90, 72), "Representative Case Card", font=subtitle_font, fill=teal)
    draw.text((90, 104), "Chinese Agent Handoff", font=title_font, fill=ivory)
    draw.text((92, 158), "for headroom-zh", font=title_font_small, fill=ivory)
    draw.text(
        (92, 214),
        "Compression is only useful if the agent can still decide what to do next.",
        font=subtitle_font,
        fill=muted,
    )

    metric_box = (1080, 84, 1512, 206)
    rounded_panel(draw, metric_box, (12, 28, 33, 210), (123, 194, 177, 120), width=2, radius=30)
    draw.text((1112, 112), "Recorded Payload", font=section_font, fill=teal)
    draw.text((1112, 148), "14,342 bytes  →  4,200 bytes", font=load_font(28, bold=True), fill=ivory)
    draw.text((1114, 182), "anchors preserved for the agent", font=small_font, fill=muted)

    before_box = (84, 286, 768, 758)
    after_box = (834, 286, 1518, 758)
    rounded_panel(draw, before_box, slate, stroke, radius=36)
    rounded_panel(draw, after_box, slate_light, (170, 231, 219, 155), radius=36)

    draw.text((114, 316), "Before", font=section_font, fill=amber)
    draw.text((114, 350), "raw handoff fragment", font=load_font(30, bold=True), fill=ivory)
    before_text = (
        "目前最大的展示短板不是代理或模型本身，而是缺少高质量中文 demo 工作负载。\n"
        "如果从零给 agent 扔一个很短的空任务，它几乎不需要读任何东西。\n\n"
        "推荐执行顺序：\n"
        "1. 在 AutoDL 上启动 `scripts/smoke_autodl_headroom.py --keep-running`\n"
        "2. 保持代理运行在 `8790`\n"
        "3. 把 CodeX 或 Claude Code 指向代理\n"
        "4. 让 agent 先读取大体量中文材料，再回答问题或执行探索\n"
        "5. 截图 `/dashboard`\n"
        "6. 导出或截图 `/stats-history`\n\n"
        "风险与依赖：依赖 AutoDL 网络与模型缓存；任务太短时节省数字会弱。"
    )
    draw_multiline(draw, (116, 404), before_text, body_font, muted, 610, 7)

    draw.text((864, 316), "After", font=section_font, fill=teal)
    draw.text((864, 350), "compressed but still actionable", font=load_font(30, bold=True), fill=ivory)
    after_text = (
        "问题: 若任务过短, agent 无需读长中文材料, Headroom 优势不显。\n\n"
        "执行顺序:\n"
        "1. AutoDL 起 `scripts/smoke_autodl_headroom.py --keep-running`\n"
        "2. 代理端口固定 `8790`\n"
        "3. CodeX / Claude Code 指向代理\n"
        "4. 先读长中文材料, 后回答/探索\n"
        "5. 展示 `/dashboard` 与 `/stats-history`\n\n"
        "风险: 依赖 AutoDL 网络与模型缓存; 短任务节省数字弱; 纯英文任务可能走原生 `kompress`。"
    )
    draw_multiline(draw, (866, 404), after_text, body_font, mint, 610, 7)

    draw.line((780, 522, 824, 522), fill=(215, 233, 226, 160), width=4)
    draw.polygon([(824, 522), (804, 508), (804, 536)], fill=(215, 233, 226, 160))

    footer_box = (84, 804, 1518, 932)
    rounded_panel(draw, footer_box, (11, 24, 30, 196), (129, 192, 178, 88), radius=28)
    draw.text((112, 820), "Signals that remain explicit after compression", font=section_font, fill=teal)

    chip_x = 112
    chip_y = 856
    chips = [
        "`scripts/smoke_autodl_headroom.py`",
        "`8790`",
        "`/dashboard`",
        "`/stats-history`",
        "`CodeX / Claude Code`",
        "next-step order",
        "risk awareness",
    ]
    for label in chips:
        width = add_chip(
            draw,
            chip_x,
            chip_y,
            label,
            chip_font,
            (22, 52, 59, 218),
            ivory,
            (124, 206, 188, 104),
        )
        chip_x += width + 12
        if chip_x > 1360:
            chip_x = 112
            chip_y += 48

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(OUT_PATH)
    print(f"saved={OUT_PATH}")


if __name__ == "__main__":
    main()
