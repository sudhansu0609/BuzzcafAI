"""Generate high-resolution Buzzcaf Studio application icon (.ico and .png).

Creates a sleek modern icon with Buzzcaf dark purple/violet gradient,
stylized coffee cup, and AI spark glow in all standard Windows icon sizes:
256x256, 128x128, 64x64, 48x48, 32x32, 16x16.
"""

import os
from PIL import Image, ImageDraw


def create_buzzcaf_icon(output_path: str):
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    sizes = [256, 128, 64, 48, 32, 16]
    images = []

    for size in sizes:
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Scale factor
        s = size / 256.0

        # Outer rounded squircle background
        margin = int(12 * s)
        bg_radius = int(48 * s)
        bg_box = [margin, margin, size - margin, size - margin]

        # Draw rounded rectangle with dark violet/purple fill
        draw.rounded_rectangle(
            bg_box,
            radius=bg_radius,
            fill=(24, 20, 48, 255),  # Deep violet dark
            outline=(167, 139, 250, 220),  # Light purple border (#a78bfa)
            width=max(1, int(4 * s)),
        )

        # Inner subtle gradient glow ring
        inner_margin = int(22 * s)
        draw.rounded_rectangle(
            [inner_margin, inner_margin, size - inner_margin, size - inner_margin],
            radius=int(38 * s),
            outline=(124, 58, 237, 100),  # Glowing violet (#7c3aed)
            width=max(1, int(2 * s)),
        )

        # Coffee Cup Body
        cx, cy = size / 2, size / 2 + int(10 * s)
        cw, ch = int(50 * s), int(42 * s)

        cup_box = [cx - cw, cy - ch, cx + cw, cy + ch]
        draw.rounded_rectangle(
            cup_box,
            radius=int(18 * s),
            fill=(245, 158, 11, 240),  # Warm amber coffee (#f59e0b)
            outline=(254, 243, 199, 255),
            width=max(1, int(3 * s)),
        )

        # Cup handle on the right
        handle_left = cx + cw - int(8 * s)
        handle_top = cy - int(24 * s)
        handle_right = cx + cw + int(26 * s)
        handle_bottom = cy + int(14 * s)
        draw.arc(
            [handle_left, handle_top, handle_right, handle_bottom],
            start=270,
            end=90,
            fill=(254, 243, 199, 255),
            width=max(2, int(6 * s)),
        )

        # Coffee liquid rim inside cup
        rim_top = cy - ch + int(4 * s)
        draw.ellipse(
            [cx - cw + int(6 * s), rim_top, cx + cw - int(6 * s), rim_top + int(16 * s)],
            fill=(146, 64, 14, 255),  # Dark rich roast
        )

        # AI Spark / Star on the cup center
        spark_r = int(14 * s)
        spark_cx = cx - int(4 * s)
        spark_cy = cy + int(6 * s)

        star_points = [
            (spark_cx, spark_cy - spark_r),
            (spark_cx + spark_r // 3, spark_cy - spark_r // 3),
            (spark_cx + spark_r, spark_cy),
            (spark_cx + spark_r // 3, spark_cy + spark_r // 3),
            (spark_cx, spark_cy + spark_r),
            (spark_cx - spark_r // 3, spark_cy + spark_r // 3),
            (spark_cx - spark_r, spark_cy),
            (spark_cx - spark_r // 3, spark_cy - spark_r // 3),
        ]
        draw.polygon(star_points, fill=(255, 255, 255, 255))

        # Rising Steam Curves (AI neural vapor)
        steam_y = cy - ch - int(8 * s)
        for offset_x in [-int(20 * s), 0, int(20 * s)]:
            curve_top = steam_y - int(24 * s)
            draw.arc(
                [cx + offset_x - int(8 * s), curve_top, cx + offset_x + int(8 * s), steam_y],
                start=200,
                end=340,
                fill=(192, 132, 252, 200),  # Soft purple steam (#c084fc)
                width=max(1, int(3 * s)),
            )

        images.append(img)

    # Save multi-size .ico
    images[0].save(
        output_path,
        format="ICO",
        sizes=[(img.width, img.height) for img in images],
        append_images=images[1:],
    )

    # Also save 256x256 PNG for UI / web use
    png_path = os.path.splitext(output_path)[0] + ".png"
    images[0].save(png_path, format="PNG")
    print(f"Generated icon: {output_path} ({len(sizes)} resolutions) and {png_path}")


if __name__ == "__main__":
    icon_dest = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "buzzcaf_studio.ico")
    create_buzzcaf_icon(icon_dest)
