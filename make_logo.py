"""Generate the ApolloAgents logo."""

import math
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1200, 480
BG       = (6, 6, 18)
GOLD     = (255, 200, 60)
GOLD_DIM = (180, 120, 20)
CYAN     = (0, 220, 255)
WHITE    = (255, 255, 255)
GREY     = (120, 120, 160)

FONT_DIR = "fonts"
FONT_BIG  = ImageFont.truetype(f"{FONT_DIR}/PressStart2P-Regular.ttf", 64)
FONT_MED  = ImageFont.truetype(f"{FONT_DIR}/PressStart2P-Regular.ttf", 20)
FONT_MONO = ImageFont.truetype(f"{FONT_DIR}/ShareTechMono-Regular.ttf", 22)


def make_glow(img: Image.Image, color, radius=18) -> Image.Image:
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(glow)
    # paint filled circles at every pixel of the source that is bright
    src = img.load()
    gd = glow.load()
    for y in range(img.height):
        for x in range(img.width):
            if src[x, y][3] > 128:
                gd[x, y] = (*color, 200)
    return glow.filter(ImageFilter.GaussianBlur(radius))


def draw_sun(draw: ImageDraw.ImageDraw, cx: int, cy: int, r_inner: int, r_outer: int,
             n_rays: int = 16) -> None:
    """Draw a stylised sun with alternating long/short rays."""
    for i in range(n_rays):
        angle = math.radians(i * 360 / n_rays - 90)
        r = r_outer if i % 2 == 0 else r_outer * 0.72
        width = 4 if i % 2 == 0 else 2
        x0 = cx + r_inner * math.cos(angle)
        y0 = cy + r_inner * math.sin(angle)
        x1 = cx + r * math.cos(angle)
        y1 = cy + r * math.sin(angle)
        alpha = 255 if i % 2 == 0 else 160
        draw.line([(x0, y0), (x1, y1)], fill=(*GOLD, alpha), width=width)


def draw_circle(draw: ImageDraw.ImageDraw, cx, cy, r, fill=None, outline=None, width=3):
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill, outline=outline, width=width)


def draw_waveform(draw: ImageDraw.ImageDraw, x_start, x_end, cy, height, n_bars=42, color=CYAN):
    import random
    rng = random.Random(42)
    bar_w = max(2, (x_end - x_start) // n_bars - 2)
    for i in range(n_bars):
        amp = rng.uniform(0.15, 1.0)
        # shape: bell-ish, peaking in the middle
        center_factor = 1 - abs((i / n_bars) - 0.5) * 0.6
        amp *= center_factor
        h = int(height * amp)
        x = x_start + i * ((x_end - x_start) // n_bars)
        alpha = int(200 * amp + 55)
        draw.rectangle([x, cy - h, x + bar_w, cy + h], fill=(*color, alpha))


# ── canvas ────────────────────────────────────────────────────────────────────
img = Image.new("RGBA", (W, H), (*BG, 255))
draw = ImageDraw.Draw(img)

# subtle vignette gradient via radial fade
vignette = Image.new("RGBA", (W, H), (0, 0, 0, 0))
vd = ImageDraw.Draw(vignette)
for r in range(min(W, H) // 2, 0, -4):
    alpha = int(120 * (1 - r / (min(W, H) / 2)))
    vd.ellipse([W // 2 - r, H // 2 - r, W // 2 + r, H // 2 + r],
               fill=(0, 0, 0, max(0, 120 - alpha)))
img = Image.alpha_composite(img, vignette)
draw = ImageDraw.Draw(img)

# ── sun (left panel) ──────────────────────────────────────────────────────────
SUN_CX, SUN_CY = 210, H // 2
R_INNER, R_OUTER = 62, 130

# glow behind sun
glow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
gd = ImageDraw.Draw(glow_layer)
draw_circle(gd, SUN_CX, SUN_CY, R_OUTER + 30, fill=(*GOLD_DIM, 60))
glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(30))
img = Image.alpha_composite(img, glow_layer)
draw = ImageDraw.Draw(img)

draw_sun(draw, SUN_CX, SUN_CY, R_INNER + 6, R_OUTER, n_rays=18)
draw_circle(draw, SUN_CX, SUN_CY, R_INNER, fill=(*GOLD, 255))
draw_circle(draw, SUN_CX, SUN_CY, R_INNER, outline=(*WHITE, 120), width=2)

# vinyl groove lines inside the sun disc
for gr in [20, 35, 50]:
    draw_circle(draw, SUN_CX, SUN_CY, gr, outline=(*GOLD_DIM, 100), width=1)
# centre dot
draw_circle(draw, SUN_CX, SUN_CY, 7, fill=(*BG, 255))

# ── waveform (behind text, right side) ───────────────────────────────────────
wave_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
wd = ImageDraw.Draw(wave_layer)
draw_waveform(wd, 380, W - 30, H // 2 + 60, 28, n_bars=50, color=CYAN)
wave_layer = wave_layer.filter(ImageFilter.GaussianBlur(1))
img = Image.alpha_composite(img, wave_layer)
draw = ImageDraw.Draw(img)

# ── text: APOLLO ──────────────────────────────────────────────────────────────
TEXT_X = 390

# glow pass for APOLLO
glow_txt = Image.new("RGBA", (W, H), (0, 0, 0, 0))
gtd = ImageDraw.Draw(glow_txt)
gtd.text((TEXT_X, 100), "APOLLO", font=FONT_BIG, fill=(*GOLD, 200))
glow_txt = glow_txt.filter(ImageFilter.GaussianBlur(10))
img = Image.alpha_composite(img, glow_txt)
draw = ImageDraw.Draw(img)
draw.text((TEXT_X, 100), "APOLLO", font=FONT_BIG, fill=GOLD)

# ── text: AGENTS ──────────────────────────────────────────────────────────────
glow_txt2 = Image.new("RGBA", (W, H), (0, 0, 0, 0))
gtd2 = ImageDraw.Draw(glow_txt2)
gtd2.text((TEXT_X + 4, 188), "AGENTS", font=FONT_BIG, fill=(*CYAN, 180))
glow_txt2 = glow_txt2.filter(ImageFilter.GaussianBlur(10))
img = Image.alpha_composite(img, glow_txt2)
draw = ImageDraw.Draw(img)
draw.text((TEXT_X + 4, 188), "AGENTS", font=FONT_BIG, fill=CYAN)

# ── tagline ───────────────────────────────────────────────────────────────────
draw.text((TEXT_X + 6, 290), "AI-POWERED DJ SET BUILDER", font=FONT_MONO,
          fill=(*GREY, 200))

# ── agent dots row ────────────────────────────────────────────────────────────
agents = ["JANUS", "MUSE", "MOMUS", "THEMIS", "HERMES"]
dot_colors = [
    (255, 120, 60),   # Janus — orange
    (180, 80, 255),   # Muse  — violet
    (60, 200, 120),   # Momus — green
    (255, 220, 60),   # Themis — gold
    (60, 180, 255),   # Hermes — blue
]
dot_y = 358
dot_x = TEXT_X + 6
gap = 148
dot_r = 5
tiny = ImageFont.truetype(f"{FONT_DIR}/PressStart2P-Regular.ttf", 8)

for i, (name, col) in enumerate(zip(agents, dot_colors)):
    x = dot_x + i * gap
    draw_circle(draw, x, dot_y + 4, dot_r, fill=(*col, 255))
    glow_dot = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd2 = ImageDraw.Draw(glow_dot)
    draw_circle(gd2, x, dot_y + 4, dot_r + 2, fill=(*col, 120))
    glow_dot = glow_dot.filter(ImageFilter.GaussianBlur(6))
    img = Image.alpha_composite(img, glow_dot)
    draw = ImageDraw.Draw(img)
    draw_circle(draw, x, dot_y + 4, dot_r, fill=(*col, 255))
    draw.text((x - dot_r - 2, dot_y + 14), name, font=tiny, fill=(*col, 200))

# ── thin separator line ───────────────────────────────────────────────────────
draw.line([(TEXT_X, 340), (W - 30, 340)], fill=(*GREY, 60), width=1)

# ── save ──────────────────────────────────────────────────────────────────────
out = img.convert("RGB")
out.save("apollo_agents_logo.png", "PNG", quality=95)
print("Saved: apollo_agents_logo.png")
