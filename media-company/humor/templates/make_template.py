#!/usr/bin/env python3
"""기본 카드뉴스 배경 템플릿(card_bg.png) 생성 스크립트.

디자인을 바꾸고 싶으면 이 스크립트를 수정해 다시 실행하거나,
직접 만든 1080x1080 PNG를 templates/에 넣고 config.yaml의 template을 바꾸면 된다.
"""
from pathlib import Path

from PIL import Image, ImageDraw

W = H = 1080
TOP = (34, 40, 66)      # 남색
BOTTOM = (18, 20, 32)   # 진한 남색

img = Image.new("RGB", (W, H))
draw = ImageDraw.Draw(img)
for y in range(H):
    t = y / H
    color = tuple(int(a + (b - a) * t) for a, b in zip(TOP, BOTTOM))
    draw.line([(0, y), (W, y)], fill=color)
# 테두리 프레임
draw.rectangle([28, 28, W - 28, H - 28], outline=(255, 214, 90), width=4)

out = Path(__file__).parent / "card_bg.png"
img.save(out)
print(f"saved: {out}")
