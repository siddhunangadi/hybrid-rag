"""Render the launch video (assets/launch.mp4), the README preview (assets/demo.gif) and a poster frame.

macOS only (uses the system SF fonts). Setup once:
    python3 -m venv /tmp/videnv && /tmp/videnv/bin/pip install pillow imageio-ffmpeg
Run from the repo root:
    /tmp/videnv/bin/python assets/make_video.py            # full render
    /tmp/videnv/bin/python assets/make_video.py 5 20.5     # preview stills at those seconds (written to the cwd)
"""
import math
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1920, 1080, 30
OUT = Path(__file__).resolve().parent
DEMO_URL = "d25j2aj2tgz1v.cloudfront.net"
REPO = "github.com/siddhunangadi/hybrid-rag"
TAGLINE = "If it can’t cite it, it won’t say it."

# Colors: the app's light theme tokens (static/style.css)
PAGE, TEXT, TEXT2, TEXT3 = "#fbfbfd", "#1d1d1f", "#6e6e73", "#8e8e93"
ACCENT, OK, WARN, BAD = "#0071e3", "#248a3d", "#b25000", "#d70015"
ELEV, SUNK, BUBBLE, WIN, INK = "#ffffff", "#f2f2f5", "#ededf0", "#fbfbfd", "#000000"


def C(hex_, a=1.0):
    h = hex_.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) + (max(0, min(255, int(255 * a))),)


@lru_cache(maxsize=None)
def F(size, weight=400, mono=False):
    if mono:
        f = ImageFont.truetype("/System/Library/Fonts/SFNSMono.ttf", size)
        f.set_variation_by_name({400: "Regular", 500: "Medium", 600: "Semibold"}.get(weight, "Regular"))
        return f
    f = ImageFont.truetype("/System/Library/Fonts/SFNS.ttf", size)
    f.set_variation_by_axes([100, max(17, min(96, size)), 400, weight])
    return f


def ease(x):
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def ease_io(x):
    x = max(0.0, min(1.0, x))
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def appear(t, start, dur=0.5):
    return ease((t - start) / dur)


def make_bg():
    bg = Image.new("RGB", (W, H), PAGE)
    glow = Image.radial_gradient("L").resize((2200, 1300))
    glow = glow.point(lambda v: int(max(0, 128 - v) / 128 * 150))
    tint = Image.new("RGB", glow.size, "#dbe9fb")
    bg.paste(tint, ((W - 2200) // 2, -650), glow)
    return bg


BG = make_bg()


class Frame:
    def __init__(self):
        self.im = BG.copy()
        self.d = ImageDraw.Draw(self.im, "RGBA")

    def text(self, xy, s, font, fill, a=1.0, anchor="la"):
        self.d.text(xy, s, font=font, fill=C(fill, a), anchor=anchor)

    def rrect(self, box, r, fill=None, a=1.0, outline=None, oa=1.0, width=1):
        self.d.rounded_rectangle(box, r, fill=C(fill, a) if fill else None,
                                 outline=C(outline, oa) if outline else None, width=width)

    def card(self, box, r, a=1.0, fill=ELEV, border=0.08, lift=1.0):
        """White card with a soft drop shadow."""
        x0, y0, x1, y1 = box
        for i in range(1, 9):
            g = i * 2.2 * lift
            self.rrect((x0 - g, y0 - g + 5 * lift, x1 + g, y1 + g + 5 * lift), r + g, fill=INK, a=a * 0.009)
        self.rrect(box, r, fill=fill, a=a, outline=INK, oa=border * a)

    def tw(self, s, font):
        return self.d.textlength(s, font=font)

    def logo(self, cx, cy, size, a=1.0):
        s = size / 32
        self.rrect((cx - size / 2, cy - size / 2, cx + size / 2, cy + size / 2), 8 * s, fill="#0071e3", a=a)
        for dx, op in ((-3, 1.0), (3, 0.7)):
            r = 6 * s
            self.d.ellipse((cx + dx * s - r, cy - r, cx + dx * s + r, cy + r),
                           outline=C("#ffffff", a * op), width=max(2, round(2.4 * s)))

    def words(self, cx, y, parts, font, t, start, per=0.09, anchor_mid=True):
        """Centered line revealed word by word. parts: [(text, color), ...]."""
        items = []
        for text, color in parts:
            for w in text.split(" "):
                if w:
                    items.append((w, color))
        space = self.tw(" ", font)
        total = sum(self.tw(w, font) for w, _ in items) + space * (len(items) - 1)
        x = cx - total / 2
        for i, (w, color) in enumerate(items):
            a = appear(t, start + i * per, 0.45)
            if a > 0:
                self.text((x, y + 18 * (1 - a)), w, font, color, a, "lm")
            x += self.tw(w, font) + space


# ---------------------------------------------------------------- 1. cold open (4.5 s)
def s_open(f, t):
    f.words(W / 2, 470, [("Somewhere in your files", TEXT)], F(96, 700), t, 0.3)
    f.words(W / 2, 600, [("is the answer you need.", TEXT)], F(96, 700), t, 1.2)


# ---------------------------------------------------------------- 2. the problem (6.5 s)
def s_problem(f, t):
    dim = 1 - 0.65 * appear(t, 3.4, 0.6)
    f.words(W / 2, 300, [("Search finds", TEXT), ("words,", TEXT), ("not answers.", TEXT3)], F(64, 650), t, 0.3)
    f.words(W / 2, 400, [("Chatbots sound sure,", TEXT), ("even when they’re wrong.", TEXT3)], F(64, 650), t, 1.6)
    if dim < 1:  # fade the two lines back so the payoff stands out
        f.d.rectangle((0, 240, W, 460), fill=C(PAGE, 1 - dim))
    f.words(W / 2, 640, [("What if you got", TEXT), ("both?", TEXT)], F(100, 700), t, 3.6)
    f.words(W / 2, 770, [("The answer,", TEXT), ("and the proof.", ACCENT)], F(100, 700), t, 4.3)


# ---------------------------------------------------------------- 3. meet (4 s)
def s_meet(f, t):
    p = appear(t, 0.1, 0.8)
    f.logo(W / 2, 360, 170 * (0.75 + 0.25 * p), a=p)
    a = appear(t, 0.6)
    f.text((W / 2, 570 + 20 * (1 - a)), "Meet Hybrid RAG.", F(120, 700), TEXT, a, "mm")
    a = appear(t, 1.4)
    f.text((W / 2, 690 + 14 * (1 - a)), "Ask your documents anything. Check every answer.", F(46, 500), TEXT2, a, "mm")


# ---------------------------------------------------------------- 4. product walkthrough (20 s)
WX0, WY0, WX1, WY1 = 150, 56, 1770, 980
SIDE = 360
CX0, CX1 = WX0 + SIDE + 110, WX1 - 110
DOCS = [
    ("travel-expense-policy-2026.md", "MD", 14),
    ("employee-handbook-2026.md", "MD", 22),
    ("kestrel-hub-manual.pdf", "PDF", 9),
    ("kestrel-edge-manual.md", "MD", 11),
    ("warranty-terms-scanned.pdf", "PDF", 4),
    ("politica-reembolsos-es.md", "MD", 6),
]
Q1 = "What’s the hotel limit in London?"
A1 = ["The hotel cap is ", ("$320 per night", "b"), " in New York, London and Munich. ", ("1", "c"),
      " Everywhere else, it’s ", ("$250", "b"), ". ", ("1", "c")]
Q2 = "How many vacation days do UK staff get?"
CAPTIONS = [
    (0.0, "Drop in your documents."),
    (3.0, "Ask the way you’d ask a colleague."),
    (7.2, "Get the answer, and the exact line it came from."),
    (12.4, "Not in your files? It tells you, instead of guessing."),
]


def typed(s, t, start, cps=22):
    return s[:int(max(0, t - start) * cps)]


def layout_tokens(f, tokens, font, bold, width):
    pieces = []
    for tok in tokens:
        s, kind = (tok, "") if isinstance(tok, str) else tok
        if kind == "c":
            pieces.append((s, "c"))
        else:
            pieces += [(w, kind) for w in s.replace(" ", " \0").split("\0") if w]
    lines, cur, x = [], [], 0
    for s, kind in pieces:
        wdt = 34 if kind == "c" else f.tw(s, bold if kind == "b" else font)
        if x + wdt > width and cur:
            lines.append(cur)
            cur, x = [], 0
            s = s.lstrip()
            wdt = 34 if kind == "c" else f.tw(s, bold if kind == "b" else font)
        cur.append((x, s, kind))
        x += wdt + (6 if kind == "c" else 0)
    lines.append(cur)
    return lines


def draw_answer(f, x, y, tokens, nchars, lh=44):
    font, bold = F(28, 400), F(28, 650)
    shown = 0
    for li, line in enumerate(layout_tokens(f, tokens, font, bold, CX1 - x)):
        for px, s, kind in line:
            if shown >= nchars:
                return
            yy = y + li * lh
            if kind == "c":
                f.rrect((x + px + 2, yy - 2, x + px + 32, yy + 30), 8, fill=ACCENT, a=0.12)
                f.text((x + px + 17, yy + 14), s, F(18, 700), ACCENT, 1, "mm")
                shown += 1
            else:
                f.text((x + px, yy), s[: max(0, nchars - shown)], bold if kind == "b" else font, TEXT)
                shown += len(s)


def s_demo(f, t):
    d = f.d
    f.card((WX0, WY0, WX1, WY1), 22, fill=WIN, border=0.1, lift=1.6)
    f.logo(WX0 + 44, WY0 + 32, 30)
    f.text((WX0 + 72, WY0 + 32), "Hybrid RAG", F(22, 600), TEXT, 1, "lm")

    # library
    d.line((WX0 + SIDE, WY0 + 64, WX0 + SIDE, WY1 - 2), fill=C(INK, 0.08), width=1)
    ndocs = sum(1 for i in range(len(DOCS)) if t > 0.5 + i * 0.32)
    f.text((WX0 + 28, WY0 + 104), "LIBRARY" + (f"   {ndocs}" if ndocs else ""), F(16, 600), TEXT3, 1, "lm")
    active = 0.2 < t < 2.6
    f.rrect((WX0 + 22, WY0 + 132, WX0 + SIDE - 22, WY0 + 252), 16, fill=ACCENT if active else ELEV,
            a=0.06 if active else 1, outline=ACCENT if active else INK, oa=0.7 if active else 0.1, width=2)
    f.text((WX0 + SIDE / 2, WY0 + 178), "Add documents", F(21, 600), TEXT, 1, "mm")
    f.text((WX0 + SIDE / 2, WY0 + 212), "Drop PDF, Markdown or text", F(17), TEXT3, 1, "mm")
    for i, (name, kind, n) in enumerate(DOCS):
        st = 0.5 + i * 0.32
        a = appear(t, st, 0.4)
        if a <= 0:
            continue
        y = WY0 + 282 + i * 76 + 14 * (1 - a)
        f.rrect((WX0 + 26, y, WX0 + 70, y + 52), 9, fill=ELEV, a=a, outline=INK, oa=0.1 * a)
        f.text((WX0 + 48, y + 26), kind, F(13, 700), BAD if kind == "PDF" else ACCENT, a, "mm")
        f.text((WX0 + 86, y + 6), name if len(name) < 27 else name[:25] + "…", F(18, 500), TEXT, a)
        ready = t > st + 1.1
        d.ellipse((WX0 + 87, y + 37, WX0 + 95, y + 45), fill=C("#34c759" if ready else "#ff9f0a", a))
        f.text((WX0 + 103, y + 41), f"{n} passages" if ready else "Reading…", F(15), TEXT3, a, "lm")

    # conversation
    q1_sent = 5.3
    intro_a = 1 - appear(t, q1_sent, 0.4)
    if intro_a > 0:
        f.text((CX0, WY0 + 250), "Hybrid retrieval · cited answers", F(19, 600), ACCENT, intro_a)
        f.text((CX0, WY0 + 290), "Ask anything about", F(64, 700), TEXT, intro_a)
        f.text((CX0, WY0 + 365), "your documents.", F(64, 700), TEXT, intro_a)
    top = WY0 + 110 - 470 * ease_io((t - 12.3) / 0.9)

    def bubble(y, s, a):
        font = F(26)
        w = f.tw(s, font) + 48
        f.rrect((CX1 - w, y, CX1, y + 62), 22, fill=BUBBLE, a=a)
        f.text((CX1 - 24, y + 31), s, font, TEXT, a, "rm")

    def thinking(y, a, tt):
        for k in range(3):
            ph = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(tt * 7 - k * 0.9))
            d.ellipse((CX0 + k * 22, y, CX0 + k * 22 + 12, y + 12), fill=C(TEXT3, a * ph))
        f.text((CX0 + 80, y + 6), "Reading 6 documents…", F(20), TEXT3, a, "lm")

    if t > q1_sent:
        bubble(top, Q1, appear(t, q1_sent, 0.3))
    if q1_sent + 0.4 < t < 7.2:
        thinking(top + 110, appear(t, q1_sent + 0.4, 0.3), t)
    if t > 7.2:
        draw_answer(f, CX0, top + 100, A1, int((t - 7.2) * 55))
        a = appear(t, 9.0, 0.5)
        y = top + 210 + 16 * (1 - a)
        if a > 0:
            f.card((CX0, y, CX1, y + 156), 16, a=a, lift=0.6)
            f.rrect((CX0 + 22, y + 22, CX0 + 52, y + 52), 8, fill=ACCENT, a=0.12 * a)
            f.text((CX0 + 37, y + 37), "1", F(18, 700), ACCENT, a, "mm")
            f.text((CX0 + 68, y + 37), "travel-expense-policy-2026.md", F(21, 600), TEXT, a, "lm")
            f.text((CX1 - 24, y + 37), "5. Lodging and Accommodation", F(18), TEXT3, a, "rm")
            pre = "…exceptions apply to select metropolitan areas."
            hi = "The hotel cap is $320 per night in New York, London and Munich."
            f.text((CX0 + 24, y + 78), pre, F(20), TEXT2, a)
            hw = f.tw(hi, F(20, 500))
            hl = appear(t, 10.0, 0.6)
            f.rrect((CX0 + 20, y + 106, CX0 + 20 + (hw + 8) * hl, y + 138), 6, fill="#ffd60a", a=0.45 * a)
            f.text((CX0 + 24, y + 110), hi, F(20, 500), TEXT, a)
        a = appear(t, 10.2, 0.4)
        if a > 0:
            f.text((CX0, top + 395), "Answered in 3.4 s   ·   Helpful?   ·   Copy", F(17), TEXT3, a, "lm")
    q2_start = 13.4
    q2_sent = q2_start + len(Q2) / 22 + 0.3
    y2 = top + 470
    if t > q2_sent:
        bubble(y2, Q2, appear(t, q2_sent, 0.3))
    if q2_sent + 0.4 < t < q2_sent + 1.6:
        thinking(y2 + 110, appear(t, q2_sent + 0.4, 0.3), t)
    if t > q2_sent + 1.6:
        a = appear(t, q2_sent + 1.6, 0.4)
        f.rrect((CX0, y2 + 96, CX0 + 250, y2 + 146), 12, fill="#ff9f0a", a=0.14 * a)
        f.text((CX0 + 125, y2 + 121), "Insufficient context", F(22, 600), WARN, a, "mm")
        f.text((CX0, y2 + 170), "None of your documents mention vacation days for UK staff, so it won’t guess.",
               F(22), TEXT2, appear(t, q2_sent + 2.0, 0.4))

    # cover the thread where it scrolls under the top bar / composer, then draw them
    by0, by1 = WY1 - 112, WY1 - 46
    f.im.paste(BG.crop((WX0 + SIDE, 0, WX1, WY0)), (WX0 + SIDE, 0))
    d.rectangle((WX0 + SIDE + 1, WY0 + 2, WX1 - 2, WY0 + 64), fill=C(WIN))
    d.rectangle((WX0 + SIDE + 1, by0 - 24, WX1 - 2, WY1 - 16), fill=C(WIN))
    d.line((WX0 + 2, WY0 + 64, WX1 - 2, WY0 + 64), fill=C(INK, 0.08), width=1)
    d.ellipse((WX1 - 326, WY0 + 27, WX1 - 316, WY0 + 37), fill=C("#34c759"))
    f.text((WX1 - 306, WY0 + 32), "Connected", F(19), TEXT2, 1, "lm")
    f.text((WX1 - 30, WY0 + 32), "+  New chat", F(20, 500), TEXT, 1, "rm")

    f.rrect((CX0, by0, CX1, by1), 33, fill=ELEV, outline=INK, oa=0.12, width=2)
    if 3.0 < t < q1_sent:
        s = typed(Q1, t, 3.2)
    elif q2_start < t < q2_sent:
        s = typed(Q2, t, q2_start)
    else:
        s = ""
    if s:
        f.text((CX0 + 30, (by0 + by1) / 2), s, F(24), TEXT, 1, "lm")
        if int(t * 2.5) % 2 == 0:
            cxp = CX0 + 32 + f.tw(s, F(24))
            d.line((cxp, by0 + 18, cxp, by1 - 18), fill=C(ACCENT), width=3)
    else:
        f.text((CX0 + 30, (by0 + by1) / 2), "Ask about your documents", F(24), TEXT3, 1, "lm")
    d.ellipse((CX1 - 56, by0 + 11, CX1 - 12, by1 - 11), fill=C(ACCENT if s else "#d2d2d7"))
    ax, ay = CX1 - 34, (by0 + by1) / 2
    d.line((ax, ay + 10, ax, ay - 10), fill=C("#ffffff"), width=3)
    d.line((ax - 8, ay - 2, ax, ay - 10, ax + 8, ay - 2), fill=C("#ffffff"), width=3, joint="curve")
    f.text(((CX0 + CX1) / 2, by1 + 26), "Answers cite their sources", F(15), TEXT3, 1, "mm")

    # caption under the window
    st, cap = [c for c in CAPTIONS if t >= c[0]][-1]
    a = appear(t, st, 0.45)
    f.text((W / 2, 1030 + 8 * (1 - a)), cap, F(36, 650), TEXT, a, "mm")


# ---------------------------------------------------------------- 5. how it works (9 s)
def s_how(f, t):
    d = f.d
    f.words(W / 2, 140, [("Two searches.", TEXT), ("One honest answer.", ACCENT)], F(76, 700), t, 0.1)
    f.text((W / 2, 225), "What happens in the 3 seconds after you press Enter.", F(30), TEXT2, appear(t, 0.8), "mm")
    bw, bh = 310, 140
    boxes = {
        "q": (90, 500, "You ask", "“Hotel limit in London?”", 0.9, TEXT),
        "m": (570, 350, "Search by meaning", "“hotel limit” → “lodging cap”", 1.6, TEXT),
        "k": (570, 650, "Search by exact words", "never misses a code like E142", 1.8, TEXT),
        "r": (1050, 500, "Keep the best", "top 15 passages, re-ranked", 2.8, TEXT),
        "a": (1530, 420, "Answer with sources", "passage and page, every time", 3.8, OK),
        "n": (1530, 650, "“Insufficient context”", "no source? no answer.", 4.4, WARN),
    }
    links = [("q", "m", 1.2), ("q", "k", 1.4), ("m", "r", 2.3), ("k", "r", 2.5), ("r", "a", 3.4), ("r", "n", 4.0)]
    for src, dst, st in links:
        x0, y0 = boxes[src][0] + bw, boxes[src][1] + bh / 2
        x1, y1 = boxes[dst][0], boxes[dst][1] + bh / 2
        mx = (x0 + x1) / 2
        pts = [(x0, y0), (mx, y0), (mx, y1), (x1, y1)]
        seg = [math.dist(pts[i], pts[i + 1]) for i in range(3)]
        total = sum(seg)

        def at(dist):
            for i, L in enumerate(seg):
                if dist <= L or i == 2:
                    k = 0 if L == 0 else min(1, dist / L)
                    return pts[i][0] + (pts[i + 1][0] - pts[i][0]) * k, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * k
                dist -= L

        grow = appear(t, st, 0.6) * total
        if grow > 0:
            line_pts, drawn = [pts[0]], 0
            for i, L in enumerate(seg):
                if drawn + L <= grow:
                    line_pts.append(pts[i + 1])
                    drawn += L
                else:
                    line_pts.append(at(grow))
                    break
            d.line(line_pts, fill=C(INK, 0.18), width=3, joint="curve")
        if t > st + 0.6:
            px, py = at(((t - st - 0.6) * 0.8) % 1 * total)
            d.ellipse((px - 7, py - 7, px + 7, py + 7), fill=C(ACCENT))
    for x, y, title, sub, st, col in boxes.values():
        a = appear(t, st, 0.5)
        if a <= 0:
            continue
        yy = y + 14 * (1 - a)
        f.card((x, yy, x + bw, yy + bh), 20, a=a, lift=0.7)
        if col != TEXT:
            f.rrect((x, yy, x + bw, yy + bh), 20, outline=col, oa=0.55 * a, width=2)
        f.text((x + bw / 2, yy + 54), title, F(26, 650), col, a, "mm")
        f.text((x + bw / 2, yy + 94), sub, F(19), TEXT2, a, "mm")
    a = appear(t, 5.4, 0.7)
    f.text((W / 2, 930 + 12 * (1 - a)), TAGLINE, F(52, 700), TEXT, a, "mm")


# ---------------------------------------------------------------- 6. proof (8 s)
def s_proof(f, t):
    f.words(W / 2, 250, [("We tried to trick it.", TEXT), ("76 times.", ACCENT)], F(84, 700), t, 0.1)
    f.text((W / 2, 345), "Look-alike products · outdated policies · scanned pages · Spanish · hidden instructions",
           F(28), TEXT2, appear(t, 0.9), "mm")
    stats = [
        (98.6, "{:.1f}%", "found the right\ndocument"),
        (97.1, "{:.1f}%", "answered\ncorrectly"),
        (100, "{:.0f}%", "stayed true to\nthe sources"),
        (7, "{:.0f}/7", "said “I don’t know”\nwhen it should"),
        (0.0006, "${:.4f}", "per question:\n~1,600 for $1"),
    ]
    tw, gap = 316, 26
    x0 = (W - (5 * tw + 4 * gap)) / 2
    for i, (val, fmt, label) in enumerate(stats):
        st = 1.3 + i * 0.35
        a = appear(t, st, 0.5)
        if a <= 0:
            continue
        x = x0 + i * (tw + gap)
        y = 450 + 20 * (1 - a)
        f.card((x, y, x + tw, y + 300), 24, a=a, lift=0.8)
        size = 76
        while f.tw(fmt.format(val), F(size, 700)) > tw - 44:
            size -= 2
        f.text((x + tw / 2, y + 115), fmt.format(val * ease((t - st) / 1.4)), F(size, 700),
               OK if i < 4 else ACCENT, a, "mm")
        for j, ln in enumerate(label.split("\n")):
            f.text((x + tw / 2, y + 205 + j * 34), ln, F(25), TEXT2, a, "mm")


# ---------------------------------------------------------------- 7. features (5.5 s)
def s_features(f, t):
    f.words(W / 2, 270, [("Built for real", TEXT), ("documents.", TEXT)], F(84, 700), t, 0.1)
    feats = [
        ("Reads scanned PDFs", "Even pages that are only pictures"),
        ("Speaks your language", "Ask in Spanish, get Spanish back"),
        ("Remembers the thread", "“And in Munich?” just works"),
        ("Made for teams", "Private libraries, keys, spending caps"),
        ("Plugs into your app", "One API call: answer plus sources"),
        ("Ships in one command", "To AWS, with HTTPS and alerts"),
    ]
    cw, ch, gx, gy = 520, 170, 34, 34
    x0 = (W - (3 * cw + 2 * gx)) / 2
    for i, (title, sub) in enumerate(feats):
        a = appear(t, 0.6 + i * 0.18, 0.45)
        if a <= 0:
            continue
        x = x0 + (i % 3) * (cw + gx)
        y = 400 + (i // 3) * (ch + gy) + 16 * (1 - a)
        f.card((x, y, x + cw, y + ch), 22, a=a, lift=0.7)
        f.rrect((x + 34, y + 42, x + 40, y + 128), 3, fill=ACCENT, a=a)
        f.text((x + 64, y + 64), title, F(31, 650), TEXT, a, "lm")
        f.text((x + 64, y + 108), sub, F(24), TEXT2, a, "lm")


# ---------------------------------------------------------------- 8. call to action (7.5 s)
def s_cta(f, t):
    f.logo(W / 2, 190, 110, a=appear(t, 0.1, 0.6))
    f.words(W / 2, 330, [("Answers you can", TEXT), ("check.", ACCENT)], F(100, 700), t, 0.4)
    a = appear(t, 1.3)
    font = F(38, 600)
    label = "Try it now  →  " + DEMO_URL
    wdt = f.tw(label, font) + 90
    f.rrect((W / 2 - wdt / 2, 445, W / 2 + wdt / 2, 529), 42, fill=ACCENT, a=a)
    f.text((W / 2, 487), label, font, "#ffffff", a, "mm")
    a = appear(t, 2.1)
    f.text((W / 2, 630), "Or run your own in 5 minutes", F(32, 500), TEXT2, a, "mm")
    cmds = ["git clone https://" + REPO, "cp .env.example .env    # add your OpenAI key + Supabase URL",
            "pip install -r requirements.txt && uvicorn main:app"]
    bx0, bx1 = W / 2 - 580, W / 2 + 580
    f.card((bx0, 680, bx1, 850), 18, a=a, fill="#1d1d1f", border=0, lift=0.8)
    for i, c in enumerate(cmds):
        aa = appear(t, 2.4 + i * 0.3)
        f.text((bx0 + 40, 722 + i * 46), "$", F(24, 500, mono=True), "#30d158", aa, "lm")
        f.text((bx0 + 72, 722 + i * 46), c, F(24, 400, mono=True), "#f5f5f7", aa, "lm")
    f.text((W / 2, 940), REPO, F(30, 600), TEXT2, appear(t, 3.2), "mm")


SCENES = [(s_open, 4.5), (s_problem, 6.5), (s_meet, 4), (s_demo, 20), (s_how, 9), (s_proof, 8),
          (s_features, 5.5), (s_cta, 7.5)]
DEMO_AT = sum(d for _, d in SCENES[:3])


def render(t):
    start = 0
    for i, (fn, dur) in enumerate(SCENES):
        last = i == len(SCENES) - 1
        if t < start + dur or last:
            lt = t - start
            f = Frame()
            fn(f, lt)
            fade = min(1.0, lt / 0.35) if last else min(1.0, lt / 0.35, (dur - lt) / 0.35)
            return f.im if fade >= 1 else Image.blend(BG, f.im, max(0.0, fade))
        start += dur


def encode(path, frames, size, fps, extra_out):
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{size[0]}x{size[1]}", "-r", str(fps), "-i", "-"] + extra_out + [str(path)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for im in frames:
        p.stdin.write(im.tobytes())
    p.stdin.close()
    if p.wait():
        sys.exit(f"ffmpeg failed for {path}")


def main():
    total = sum(d for _, d in SCENES)
    n = int(total * FPS)

    def video_frames():
        for i in range(n):
            if i % FPS == 0:
                print(f"\r{i // FPS}/{total:.0f} s", end="", flush=True)
            yield render(i / FPS)

    encode(OUT / "launch.mp4", video_frames(), (W, H), FPS,
           ["-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart"])
    print("\nwrote launch.mp4")
    render(DEMO_AT + 11).save(OUT / "poster.png")

    # README preview: the walkthrough only, at 960x540 / 12 fps
    gfps, gw, gh = 12, 960, 540
    frames = (render(DEMO_AT + 0.2 + i / gfps).resize((gw, gh), Image.LANCZOS) for i in range(int(19.6 * gfps)))
    tmp = OUT / "_demo.mp4"
    encode(tmp, frames, (gw, gh), gfps, ["-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p"])
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(tmp), "-vf",
                    "split[a][b];[a]palettegen=max_colors=200:stats_mode=full[p];"
                    "[b][p]paletteuse=dither=none:diff_mode=rectangle",
                    "-loop", "0", str(OUT / "demo.gif")], check=True)
    tmp.unlink()
    print("wrote demo.gif, poster.png")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        for s in sys.argv[1:]:
            render(float(s)).save(Path.cwd() / f"still_{s}.png")
    else:
        main()
