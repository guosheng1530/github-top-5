"""Pillow 程序化信息卡 —— 本项目的“画面引擎”。

为什么技术介绍视频以信息卡为主（而不是每秒生成式视频）？
* 信息准确：Star 数、功能点直接来自已核验数据，不会被生成模型画错；
* 可复现、可测试：同样的数据产出同样的画面；
* 成本为零、修复成本极低：改文案重渲染一张 PNG 即可；
* 4GB 显存的机器无需任何本地扩散模型。

所有几何尺寸/字号先按 1920x1080 设计，再乘 ``sf = min(w/1920, h/1080)``，
因此同一套代码可以渲染 720p/缩略图而不会溢出。
字幕**不**烧在静态卡片上（那样 45~60 秒的镜头只能看到口播前三行）：
卡片只出画面，RenderAgent 在 FFmpeg 阶段用 libass 按 SRT 时间轴动态烧字幕。
页脚标注数据来源与“程序化画面”，与真实生成素材明确区分。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from videoforge.schemas import StoryboardScene

# 调色板（深色科技风）
BG_TOP = (13, 27, 42)
BG_BOTTOM = (27, 38, 59)
ACCENT = (76, 201, 240)
GOLD = (255, 209, 102)
WHITE = (237, 242, 247)
GREY = (160, 174, 192)
CARD_FILL = (20, 33, 51, 235)
RANK_COLORS = [(255, 209, 102), (192, 203, 215), (205, 127, 50), ACCENT, (160, 174, 192)]

FONT_REG = "C:/Windows/Fonts/msyh.ttc"
FONT_BOLD = "C:/Windows/Fonts/msyhbd.ttc"


def _font(size: int, bold: bool = False, sf: float = 1.0) -> ImageFont.FreeTypeFont:
    path = FONT_BOLD if bold and Path(FONT_BOLD).exists() else FONT_REG
    return ImageFont.truetype(path, max(10, int(size * sf)))


def _gradient(w: int, h: int) -> Image.Image:
    img = Image.new("RGB", (w, h), BG_TOP)
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        draw.line([(0, y), (w, y)], fill=tuple(
            int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3)))
    return img


# 这些标点不允许出现在一行的开头（CJK 排版禁则），折行越界一个字也要留在行尾
_NO_LINE_START = set("）)】》」』”’\"'，。、；：！？．.,:;!?…")


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont,
          max_width: int) -> list[str]:
    """按像素宽度折行：中文逐字可断，英文按整词不断开（避免 A/gent 这种断词）。"""
    lines: list[str] = []
    for para in str(text).split("\n"):
        cur = ""
        i = 0
        while i < len(para):
            ch = para[i]
            if ch.isascii() and ch.isalnum():
                j = i
                while j < len(para) and para[j].isascii() and (
                        para[j].isalnum() or para[j] in "-_'/."):
                    j += 1
                token = para[i:j]
                candidate = cur + token
                if not cur or draw.textlength(candidate, font=font) <= max_width:
                    cur = candidate
                else:
                    lines.append(cur.rstrip())
                    cur = token
                i = j
            else:
                if draw.textlength(cur + ch, font=font) <= max_width or ch in _NO_LINE_START:
                    cur += ch
                else:
                    if cur:
                        lines.append(cur)
                    cur = ch
                i += 1
        if cur:
            lines.append(cur.rstrip())
    return lines


def _fit_text(draw, text: str, sizes: tuple[int, ...], max_width: int,
              sf: float, bold: bool = False, ellipsis: int = 0) -> tuple[ImageFont.FreeTypeFont, str]:
    """从大到小尝试字号让整行文本适配宽度；都放不下则按最大可容纳字数加省略号。

    返回最终字体与可渲染文本。用于榜单仓库名这类长度不可控的单行文。
    """
    text = str(text)
    for size in sizes:
        font = _font(size, bold=bold, sf=sf)
        if draw.textlength(text, font=font) <= max_width:
            return font, text
    font = _font(sizes[-1], bold=bold, sf=sf)
    if ellipsis and draw.textlength("…", font=font) < max_width:
        body = text[:ellipsis]
        while body and draw.textlength(body + "…", font=font) > max_width:
            body = body[:-1]
        return font, body + "…"
    return font, text


def _draw_multiline(draw, xy, text, font, fill, max_width, line_gap: int = 10):
    x, y = xy
    for line in _wrap(draw, text, font, max_width):
        draw.text((x, y), line, font=font, fill=fill)
        y += font.size + line_gap
    return y


def _footer(draw, w: int, sf: float, source: str) -> None:
    f = _font(20, sf=sf)
    draw.text((int(40 * sf), int(24 * sf)),
              "AgentVideoForge · 开源项目情报", font=f, fill=GREY)
    tw = draw.textlength(source, font=f)
    draw.text((w - 40 * sf - tw, int(24 * sf)), source, font=f, fill=GREY)


def _new_card(w: int, h: int):
    img = _gradient(w, h).convert("RGBA")
    sf = min(w / 1920, h / 1080)
    return img, ImageDraw.Draw(img), sf


# --------------------------------------------------------------------------- #
# 各类画面（坐标均为 1080p 设计值，乘 sf）
# --------------------------------------------------------------------------- #
def _title_card(d: dict, w: int, h: int) -> Image.Image:
    img, draw, sf = _new_card(w, h)
    _footer(draw, w, sf, "数据：GitHub REST API")
    y = h * 0.28
    for line in _wrap(draw, d.get("title", ""), _font(82, bold=True, sf=sf), w - int(240 * sf)):
        tw = draw.textlength(line, font=_font(82, bold=True, sf=sf))
        draw.text(((w - tw) / 2, y), line, font=_font(82, bold=True, sf=sf), fill=ACCENT)
        y += int(104 * sf)
    y += int(30 * sf)
    for line in _wrap(draw, d.get("subtitle", ""), _font(40, sf=sf), w - int(320 * sf)):
        tw = draw.textlength(line, font=_font(40, sf=sf))
        draw.text(((w - tw) / 2, y), line, font=_font(40, sf=sf), fill=WHITE)
        y += int(58 * sf)
    if d.get("meta"):
        f = _font(28, sf=sf)
        tw = draw.textlength(d["meta"], font=f)
        draw.text(((w - tw) / 2, h - int(280 * sf)), d["meta"], font=f, fill=GREY)
    return img.convert("RGB")


def _section_card(d: dict, w: int, h: int) -> Image.Image:
    img, draw, sf = _new_card(w, h)
    _footer(draw, w, sf, d.get("source", "程序化画面"))
    f = _font(64, bold=True, sf=sf)
    y = h * 0.36
    for line in _wrap(draw, d.get("title", ""), f, w - int(240 * sf)):
        tw = draw.textlength(line, font=f)
        draw.text(((w - tw) / 2, y), line, font=f, fill=GOLD)
        y += int(84 * sf)
    return img.convert("RGB")


def _ranking_card(d: dict, w: int, h: int) -> Image.Image:
    img, draw, sf = _new_card(w, h)
    _footer(draw, w, sf, "评分=Star/活跃度/契合度/许可证 加权（自定义启发式，非官方排名）")
    draw.text((int(80 * sf), int(70 * sf)), d.get("title", "Top 5 总览"),
              font=_font(54, bold=True, sf=sf), fill=ACCENT)
    items: list[dict[str, Any]] = d.get("items", [])
    max_stars = max((it.get("stars", 1) for it in items), default=1) or 1
    top = int(250 * sf)
    available = max(120, h - int(180 * sf) - top)
    row_h = min(int(110 * sf), available // max(1, len(items)))
    # 三栏：名次 / 仓库名（自适应字号，最长可占 620sf）/ 条形 + 数值
    name_x = int(200 * sf)
    name_max_w = int(620 * sf)
    bar_x = name_x + name_max_w + int(24 * sf)
    label_w = int(360 * sf)  # “★ 277,917  综合分 100.0”
    bar_w_max = max(100, w - bar_x - label_w - int(40 * sf))
    for i, it in enumerate(items):
        y = top + i * row_h
        color = RANK_COLORS[i] if i < len(RANK_COLORS) else GREY
        draw.text((int(80 * sf), y), f"#{i+1}", font=_font(44, bold=True, sf=sf), fill=color)
        nf, name_text = _fit_text(draw, it.get("name", ""), (34, 30, 27, 24),
                                  name_max_w, sf, bold=True, ellipsis=34)
        draw.text((name_x, y + int(4 * sf)), name_text, font=nf, fill=WHITE)
        bw = max(10, int(bar_w_max * (it.get("stars", 0) / max_stars)))
        draw.rounded_rectangle([bar_x, y + int(6 * sf), bar_x + bw, y + int(52 * sf)],
                               radius=max(2, int(8 * sf)), fill=color)
        draw.text((bar_x + bw + int(14 * sf), y + int(8 * sf)),
                  f"★ {it.get('stars', 0):,}  综合分 {it.get('score', 0):.1f}",
                  font=_font(28, sf=sf), fill=GREY)
    return img.convert("RGB")


def _project_card(d: dict, w: int, h: int) -> Image.Image:
    img, draw, sf = _new_card(w, h)
    _footer(draw, w, sf, "数据：GitHub REST API（实时采集）")
    rank = d.get("rank", 1)
    color = RANK_COLORS[rank - 1] if 1 <= rank <= len(RANK_COLORS) else GREY
    cx, cy, r = int(125 * sf), int(115 * sf), int(55 * sf)
    draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)], fill=color)
    txt = str(rank)
    rf = _font(56, bold=True, sf=sf)
    tb = draw.textbbox((0, 0), txt, font=rf)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    draw.text((cx - tw / 2 - tb[0], cy - th / 2 - tb[1]), txt, font=rf, fill=(20, 30, 45))

    nf, name_text = _fit_text(draw, d.get("name", ""), (50, 44, 38, 33),
                              w - int(300 * sf), sf, bold=True, ellipsis=46)
    draw.text((int(210 * sf), int(72 * sf)), name_text, font=nf, fill=WHITE)
    meta = (f"★ {d.get('stars', 0):,}   ⑂ {d.get('forks', 0):,}   "
            f"语言 {d.get('language') or '—'}   许可证 {d.get('license') or '—'}")
    draw.text((int(212 * sf), int(138 * sf)), meta, font=_font(26, sf=sf), fill=GOLD)

    # 字幕由 ffmpeg 按 SRT 时间轴烧在画面底部（两行约占 170sf），信息盒给字幕留位
    box = (int(80 * sf), int(210 * sf), w - int(80 * sf), h - int(170 * sf))
    if box[3] <= box[1] + 60:  # 极小画布兜底
        box = (int(80 * sf), int(180 * sf), w - int(80 * sf), h - int(100 * sf))
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rounded_rectangle(box, radius=max(2, int(18 * sf)), fill=CARD_FILL,
                         outline=color, width=max(1, int(2 * sf)))
    img.alpha_composite(overlay)
    draw = ImageDraw.Draw(img)
    y = box[1] + int(26 * sf)
    y = _draw_multiline(draw, (int(110 * sf), y), d.get("one_liner", ""),
                        _font(34, bold=True, sf=sf), ACCENT,
                        box[2] - box[0] - int(60 * sf))
    y += int(14 * sf)
    for bullet in d.get("bullets", [])[:5]:
        draw.text((int(110 * sf), y), "•", font=_font(30, sf=sf), fill=color)
        y = _draw_multiline(draw, (int(146 * sf), y), bullet, _font(29, sf=sf),
                            WHITE, box[2] - box[0] - int(110 * sf), line_gap=8)
        y += int(8 * sf)
    draw.text((int(110 * sf), box[3] - int(40 * sf)), d.get("url", ""),
              font=_font(22, sf=sf), fill=GREY)
    return img.convert("RGB")


def _end_card(d: dict, w: int, h: int) -> Image.Image:
    img, draw, sf = _new_card(w, h)
    _footer(draw, w, sf, "AgentVideoForge 自动生成")
    title = d.get("title", "感谢观看")
    f = _font(58, bold=True, sf=sf)
    tw = draw.textlength(title, font=f)
    draw.text(((w - tw) / 2, h * 0.26), title, font=f, fill=ACCENT)
    y = h * 0.40
    for line_text in d.get("lines", []):
        ff = _font(32, sf=sf)
        for line in _wrap(draw, line_text, ff, w - int(320 * sf)):
            tw = draw.textlength(line, font=ff)
            draw.text(((w - tw) / 2, y), line, font=ff, fill=WHITE)
            y += int(48 * sf)
        y += int(14 * sf)
    return img.convert("RGB")


_RENDERERS = {
    "title_card": _title_card,
    "section_card": _section_card,
    "ranking_card": _ranking_card,
    "project_card": _project_card,
    "end_card": _end_card,
}


def render_scene_image(scene: StoryboardScene, out_path,
                       width: int = 1920, height: int = 1080) -> Path:
    """根据分镜卡数据渲染一张 PNG（字幕由渲染管线按 SRT 另行烧录）。"""
    out_path = Path(out_path)
    data = dict(scene.card_data)
    img = _RENDERERS[scene.visual_type](data, width, height)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG")
    return out_path


def render_thumbnail(title: str, subtitle: str, out_path,
                     width: int = 1280, height: int = 720) -> Path:
    img = _title_card({"title": title, "subtitle": subtitle}, width, height)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG")
    return out_path
