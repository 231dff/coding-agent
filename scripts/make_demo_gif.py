"""
把静态终端截图变成打字机动画 GIF。
用法：
    python scripts/make_demo_gif.py
输入：
    docs/coding.png
输出：
    docs/demo.gif
"""

import os

from PIL import Image, ImageDraw

INPUT = "docs/coding.png"
OUTPUT = "docs/demo.gif"

# 如果自动检测不准，可以手动指定副标题区域：(left, top, right, bottom)
# 例如：SUBTITLE_BOX = (100, 400, 1100, 480)
SUBTITLE_BOX = None


def is_not_white(px, threshold=240):
    return px[0] < threshold or px[1] < threshold or px[2] < threshold


def detect_subtitle_box(img):
    """自动检测下半部分的副标题区域"""
    W, H = img.size
    start_y = int(H * 0.5)  # 只看下半部分
    pixels = []
    for y in range(start_y, H):
        for x in range(W):
            if is_not_white(img.getpixel((x, y))):
                pixels.append((x, y))
    if not pixels:
        raise SystemExit("未检测到副标题区域，请手动设置 SUBTITLE_BOX")
    xs = [p[0] for p in pixels]
    ys = [p[1] for p in pixels]
    return (min(xs), min(ys), max(xs) + 1, max(ys) + 1)


def main():
    if not os.path.exists(INPUT):
        raise SystemExit(f"找不到输入图片：{INPUT}")

    img = Image.open(INPUT).convert("RGB")
    W, H = img.size

    if SUBTITLE_BOX is None:
        subtitle_box = detect_subtitle_box(img)
    else:
        subtitle_box = SUBTITLE_BOX

    print(f"使用副标题区域: {subtitle_box}")

    left, top, right, bottom = subtitle_box

    # 基础图：把副标题区域涂白，只保留大标题
    base = img.copy()
    draw = ImageDraw.Draw(base)
    draw.rectangle(subtitle_box, fill=(255, 255, 255))

    frames = []
    durations = []

    # 第 1 帧：只有大标题，停留 0.8 秒
    frames.append(base)
    durations.append(800)

    # 逐字显示副标题：按宽度逐步揭示
    total_width = right - left
    steps = 30
    for i in range(1, steps + 1):
        w = int(total_width * i / steps)
        frame = base.copy()
        if w > 0:
            region = img.crop((left, top, left + w, bottom))
            frame.paste(region, (left, top))
        frames.append(frame)
        durations.append(50)

    # 完整显示，停留 1 秒
    frames.append(img)
    durations.append(1000)

    # 光标闪烁 3 次
    cursor_x = right + 2
    cursor_color = (150, 150, 150)
    for _ in range(3):
        # 显示光标
        frame = img.copy()
        draw = ImageDraw.Draw(frame)
        draw.line([(cursor_x, top), (cursor_x, bottom)], fill=cursor_color, width=2)
        frames.append(frame)
        durations.append(300)
        # 隐藏光标
        frames.append(img)
        durations.append(300)

    # 保存 GIF
    frames[0].save(
        OUTPUT,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )
    print(f"已生成：{OUTPUT}")


if __name__ == "__main__":
    main()
