"""Pillow 기반 카드/썸네일 이미지 생성 공통 함수."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from common import envload

FONT_INSTALL_GUIDE = (
    "한글 폰트가 없습니다. 설치 후 .env의 FONT_PATH에 경로를 지정하세요.\n"
    "  Ubuntu:  sudo apt install fonts-nanum  → /usr/share/fonts/truetype/nanum/NanumGothicBold.ttf\n"
    "  Windows: C:/Windows/Fonts/malgunbd.ttf (맑은 고딕)"
)


def get_font(size):
    font_path = envload.get("FONT_PATH")
    if not font_path or not Path(font_path).exists():
        raise FileNotFoundError(FONT_INSTALL_GUIDE)
    return ImageFont.truetype(font_path, size)


def wrap_text(draw, text, font, max_width):
    """픽셀 폭 기준 줄바꿈 (한글은 어절 단위, 넘치면 글자 단위)."""
    lines = []
    for raw_line in text.split("\n"):
        words = raw_line.split(" ")
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if draw.textlength(candidate, font=font) <= max_width:
                current = candidate
                continue
            if current:
                lines.append(current)
            # 단어 하나가 폭을 넘으면 글자 단위로 자름
            current = ""
            for ch in word:
                if draw.textlength(current + ch, font=font) <= max_width:
                    current += ch
                else:
                    lines.append(current)
                    current = ch
        lines.append(current)
    return lines


def draw_centered_text(img, text, font, fill, y_start, max_width, line_spacing=1.35):
    """가로 중앙 정렬 멀티라인 텍스트. 마지막 y 좌표를 반환."""
    draw = ImageDraw.Draw(img)
    lines = wrap_text(draw, text, font, max_width)
    ascent, descent = font.getmetrics()
    line_height = int((ascent + descent) * line_spacing)
    y = y_start
    for line in lines:
        w = draw.textlength(line, font=font)
        draw.text(((img.width - w) / 2, y), line, font=font, fill=fill)
        y += line_height
    return y


def render_card(output_path, title=None, body=None, template_path=None,
                size=(1080, 1080), bg_color=(24, 26, 38),
                title_color=(255, 214, 90), body_color=(245, 245, 245),
                footer=None, footer_color=(150, 150, 160)):
    """템플릿 이미지(또는 단색 배경) 위에 제목/본문 텍스트를 얹어 저장한다."""
    if template_path and Path(template_path).exists():
        img = Image.open(template_path).convert("RGB")
    else:
        img = Image.new("RGB", size, bg_color)

    margin = int(img.width * 0.09)
    max_width = img.width - margin * 2
    y = int(img.height * 0.18)
    if title:
        y = draw_centered_text(img, title, get_font(int(img.width * 0.055)),
                               title_color, y, max_width)
        y += int(img.height * 0.05)
    if body:
        draw_centered_text(img, body, get_font(int(img.width * 0.042)),
                           body_color, y, max_width)
    if footer:
        draw_centered_text(img, footer, get_font(int(img.width * 0.025)),
                           footer_color, int(img.height * 0.93), max_width)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path)
    return output_path
