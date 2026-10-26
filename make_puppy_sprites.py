#!/usr/bin/env python3
"""
Regenerates puppy_sprites.py - a realistic golden retriever puppy (side view, facing right).

    python make_puppy_sprites.py            # writes puppy_sprites.py next to this file
    python make_puppy_sprites.py --sheet    # also writes puppy_preview.png (contact sheet)

Needs Pillow + numpy (only for generating the sprites - the puppy itself needs neither).
Everything is drawn procedurally at 4x resolution (anatomical limbs with IK, shaded + textured
fur, feathering, a real head with eye / nose / jaw) and then down-sampled for smooth edges.
"""

import base64
import io
import math
import os
import random
import sys

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

K = 0.72                              # puppy size (same SCALE desktop_puppy.py expects)
SS = 4                                # supersampling
U = K * SS                            # design unit -> working pixel
FW, FH, GROUND = 137, 108, 101        # frame size and feet line, in final pixels
W, H = FW * SS, FH * SS
GY = GROUND / K                       # ground line in design units (~140)

# ---------------------------------------------------------------- palette
GOLD = dict(base=(222, 164, 78), light=(247, 210, 134), dark=(168, 108, 44))
CREAM = dict(base=(244, 216, 160), light=(253, 237, 194), dark=(206, 166, 106))
EARC = dict(base=(202, 142, 62), light=(228, 172, 92), dark=(150, 96, 36))
PAW = dict(base=(234, 192, 124), light=(249, 222, 162), dark=(188, 142, 82))
FAR = 0.80                            # darkening for the far-side limbs


def mul(pal, f):
    return {k: tuple(max(0, min(255, int(c * f))) for c in v) for k, v in pal.items()}


# ---------------------------------------------------------------- geometry
def sp(pts, closed=False, per=10):
    """Catmull-Rom spline through pts (works for 1-D radii too)."""
    P = [np.array(p, dtype=float) for p in pts]
    n = len(P)
    out = []
    for i in range(n if closed else n - 1):
        p0 = P[(i - 1) % n] if (closed or i > 0) else P[0]
        p1, p2 = P[i], P[(i + 1) % n]
        p3 = P[(i + 2) % n] if (closed or i + 2 < n) else P[-1]
        for s in range(per):
            t = s / per
            out.append(0.5 * (2 * p1 + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                              + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    if not closed:
        out.append(P[-1])
    return out


def blank():
    return Image.new("L", (W, H), 0)


def m_poly(pts, smooth=True, per=8):
    q = sp(pts, True, per) if smooth else [np.array(p) for p in pts]
    m = blank()
    ImageDraw.Draw(m).polygon([(float(p[0]) * U, float(p[1]) * U) for p in q], fill=255)
    return m


def m_chain(pts, radii, per=14):
    q = sp(pts, False, per)
    r = sp([(x,) for x in radii], False, per)
    m = blank()
    d = ImageDraw.Draw(m)
    for p, rr in zip(q, r):
        x, y, R = float(p[0]) * U, float(p[1]) * U, float(rr[0]) * U
        d.ellipse([x - R, y - R, x + R, y + R], fill=255)
    return m


def m_ell(cx, cy, rx, ry, rot=0.0):
    a = math.radians(rot)
    ca, sa = math.cos(a), math.sin(a)
    pts = []
    for i in range(48):
        t = i / 48 * 2 * math.pi
        x, y = rx * math.cos(t), ry * math.sin(t)
        pts.append((cx + x * ca - y * sa, cy + x * sa + y * ca))
    return m_poly(pts, smooth=False)


def union(*ms):
    out = ms[0]
    for m in ms[1:]:
        out = ImageChops.lighter(out, m)
    return out


def ik2(a, b, l1, l2, bend):
    """Two-bone IK from a to b. Returns (joint, clamped end). bend=+1/-1 picks the knee side."""
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    d = math.hypot(dx, dy) or 1e-6
    reach = l1 + l2 - 0.4
    if d > reach:
        dx, dy, d = dx * reach / d, dy * reach / d, reach
        b = (ax + dx, ay + dy)
    d = max(d, abs(l1 - l2) + 0.5)
    aa = (l1 * l1 - l2 * l2 + d * d) / (2 * d)
    h = math.sqrt(max(l1 * l1 - aa * aa, 0))
    ux, uy = dx / d, dy / d
    return (ax + ux * aa - uy * h * bend, ay + uy * aa + ux * h * bend), b


# ---------------------------------------------------------------- painting
DOG_GRAD = (48.0, 205.0)              # one vertical light ramp shared by every golden part


def paint(cv, mask, pal, ang=200.0, fur=1.0, rim=0.5, outline=0.5, seed=0, light=0.85, mottle=0.16,
          grad=DOG_GRAD, fade=None, gain=0.85):
    """Fill `mask` on canvas `cv` with shaded, furry colour.

    grad  - (y_top, y_bottom) in design units mapped to light -> dark (None = the mask's own box)
    fade  - (y0, y1): rim shading + outline fade in between these rows (blends a limb into the body)
    gain  - how strong the light/dark ramp is
    """
    bb = mask.getbbox()
    if not bb:
        return
    x0, y0, x1, y1 = max(bb[0] - 2, 0), max(bb[1] - 2, 0), min(bb[2] + 2, W), min(bb[3] + 2, H)
    crop = mask.crop((x0, y0, x1, y1))
    m = np.asarray(crop, dtype=np.float32) / 255.0
    h, w = m.shape
    rng = np.random.RandomState(seed)

    ys = ((y0 + np.arange(h, dtype=np.float32)) / U)[:, None]            # design-unit rows
    xs = ((x0 + np.arange(w, dtype=np.float32)) / U)[None, :]
    g0, g1 = grad if grad else (y0 / U, y1 / U)
    ty = np.clip((ys - g0) / (g1 - g0), 0, 1)
    tx = np.clip((xs - 20) / 160.0, 0, 1)
    t = np.clip(light * ty + (1 - light) * (1 - tx), 0, 1)
    base, lt, dk = (np.array(pal[k], dtype=np.float32) for k in ("base", "light", "dark"))
    t3 = t[..., None]
    lo = lt + (base - lt) * np.clip(t3 / 0.45, 0, 1)
    hi = base + (dk - base) * np.clip((t3 - 0.45) / 0.55, 0, 1)
    col = base + (np.where(t3 < 0.45, lo, hi) - base) * gain

    # low-frequency mottling
    gh, gw = max(2, h // (5 * SS)), max(2, w // (5 * SS))
    noise = Image.fromarray((rng.rand(gh, gw) * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)
    col = col * (1 + (np.asarray(noise, dtype=np.float32)[..., None] / 255 - 0.5) * mottle)

    if fade:
        fy = np.clip((ys - fade[0]) / max(fade[1] - fade[0], 1e-3), 0, 1)
        fy = (fy * fy * (3 - 2 * fy))
    else:
        fy = np.ones_like(ys)
    fy = fy * np.ones((1, w), np.float32)

    # rim shading (form roundness)
    bl = np.asarray(crop.filter(ImageFilter.GaussianBlur(2.4 * SS)), dtype=np.float32) / 255.0
    d = np.clip((1 - bl) * 2.0, 0, 1)
    col = col * (1 - rim * d * fy)[..., None]

    # fur strokes
    if fur > 0:
        lay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        dr = ImageDraw.Draw(lay)
        n = int(m.sum() / (SS * SS) * 0.55 * fur)
        px = rng.randint(0, w, n)
        py = rng.randint(0, h, n)
        for i in range(n):
            if m[py[i], px[i]] < 0.5:
                continue
            a = math.radians(ang + rng.uniform(-26, 26))
            ln = rng.uniform(2.0, 5.0) * SS
            dark = rng.rand() < 0.5
            c = np.array(pal["dark"] if dark else pal["light"], dtype=np.float32)
            c = c + (np.array(pal["base"]) - c) * rng.uniform(0.25, 0.65)
            dr.line([(px[i], py[i]), (px[i] + math.cos(a) * ln, py[i] + math.sin(a) * ln)],
                    fill=(int(c[0]), int(c[1]), int(c[2]), int(rng.uniform(60, 130))), width=max(1, SS // 2))
        for i in range(int(m.sum() / (SS * SS) * 0.11 * fur)):
            x, y = rng.randint(0, w), rng.randint(0, h)
            if m[y, x] < 0.5:
                continue
            a = math.radians(ang + rng.uniform(-18, 18))
            k = rng.uniform(-0.55, 0.55)
            L = rng.uniform(6, 12) * SS
            pts = []
            for j in range(5):
                tt = j / 4.0
                aa = a + k * tt
                pts.append((x + math.cos(aa) * L * tt, y + math.sin(aa) * L * tt))
            hi = rng.rand() < 0.55
            c = np.array(pal["light"] if hi else pal["dark"], dtype=np.float32)
            dr.line(pts, fill=(int(c[0]), int(c[1]), int(c[2]), int(rng.uniform(110, 170) if hi else rng.uniform(40, 75))),
                    width=max(1, SS // 2), joint="curve")
        f = np.asarray(lay, dtype=np.float32)
        al = f[..., 3:4] / 255.0
        col = col * (1 - al) + f[..., :3] * al

    # thin dark outline on the silhouette
    er = np.asarray(crop.filter(ImageFilter.MinFilter(2 * (SS // 2 + 1) + 1)), dtype=np.float32) / 255.0
    edge = (np.clip(m - er, 0, 1) * fy)[..., None]
    oc = np.array(pal["dark"], dtype=np.float32) * np.array([0.80, 0.70, 0.58], dtype=np.float32)
    col = col * (1 - edge * outline) + oc * edge * outline

    rgba = np.dstack([np.clip(col, 0, 255), m * 255]).astype(np.uint8)
    cv.alpha_composite(Image.fromarray(rgba, "RGBA"), (x0, y0))


def crease(cv, pts, width=1.6, alpha=70, color=(120, 72, 24)):
    """Soft darker line that suggests a muscle edge (thigh, shoulder) without a hard outline."""
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(lay).line([(float(p[0]) * U, float(p[1]) * U) for p in sp(pts, False, 10)],
                             fill=color + (255,), width=max(1, int(width * U)), joint="curve")
    lay = lay.filter(ImageFilter.GaussianBlur(0.9 * SS))
    a = np.asarray(lay, dtype=np.float32).copy()
    a[..., 3] *= alpha / 255.0
    cv.alpha_composite(Image.fromarray(a.astype(np.uint8), "RGBA"))


def flat(cv, mask, color, shade=0.0):
    """Plain colour fill (nose, tongue, eye...) with optional top-to-bottom shade."""
    bb = mask.getbbox()
    if not bb:
        return
    crop = mask.crop(bb)
    w, h = crop.size
    g = np.linspace(1.0, 1.0 - shade, h, dtype=np.float32)[:, None, None]
    col = np.ones((h, w, 3), np.float32) * np.array(color, np.float32) * g
    rgba = np.dstack([col, np.asarray(crop, np.float32)]).astype(np.uint8)
    cv.alpha_composite(Image.fromarray(rgba, "RGBA"), (bb[0], bb[1]))


def stroke(cv, pts, color, width, alpha=255):
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    q = [(float(p[0]) * U, float(p[1]) * U) for p in sp(pts, False, 8)]
    ImageDraw.Draw(lay).line(q, fill=color + (alpha,), width=max(1, int(width * U)), joint="curve")
    cv.alpha_composite(lay)


def tufts(cv, path, ang, length, width, n, pals, seed=0, jitter=18, spread=1.0):
    """Tapered fur strands that start along `path` and sweep in direction `ang` (degrees)."""
    rng = random.Random(seed)
    q = sp(path, False, 12)
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dr = ImageDraw.Draw(lay)
    for _ in range(n):
        p = q[rng.randrange(len(q))]
        a = math.radians(ang + rng.uniform(-jitter, jitter))
        ln = length * rng.uniform(0.55, 1.15)
        wd = width * rng.uniform(0.7, 1.2)
        ux, uy = math.cos(a), math.sin(a)
        nx, ny = -uy, ux
        bx, by = float(p[0]) + rng.uniform(-1, 1) * spread, float(p[1]) + rng.uniform(-1, 1) * spread
        tip = (bx + ux * ln, by + uy * ln)
        pal = rng.choice(pals)
        c = np.array(pal["base"], float) + (np.array(pal["light"], float) - np.array(pal["base"], float)) * rng.uniform(0, 0.55)
        c = c * rng.uniform(0.88, 1.06)
        col = (int(min(255, c[0])), int(min(255, c[1])), int(min(255, c[2])), 255)
        lock(dr, bx, by, ux, uy, ln, wd * 0.95, col, rng)
    cv.alpha_composite(lay)


def rot(p, o, deg):
    a = math.radians(deg)
    dx, dy = p[0] - o[0], p[1] - o[1]
    return (o[0] + dx * math.cos(a) - dy * math.sin(a), o[1] + dx * math.sin(a) + dy * math.cos(a))


# ---------------------------------------------------------------- body parts
def paw_mask(px, py, pitch=0.0):
    """Paw whose ground-contact centre is (px, py)."""
    c = (px + 3.5, py - 3.6)
    return union(m_chain([rot((c[0] - 5, c[1]), c, pitch), rot((c[0] + 6, c[1] + 0.5), c, pitch)], [4.6, 4.2]),
                 m_ell(c[0] + 1, c[1] + 0.8, 8.6, 4.3, pitch))


def toes(cv, px, py, pitch, pal):
    c = (px + 3.5, py - 3.6)
    for k in (1.0, 4.2, 7.2):
        a = rot((c[0] + k, c[1] + 1.6), c, pitch)
        b = rot((c[0] + k, c[1] + 4.1), c, pitch)
        stroke(cv, [a, b], tuple(int(v * 0.5) for v in pal["dark"]), 0.45, 190)


def draw_paw(cv, px, py, pitch=0.0, pal=PAW, seed=0):
    paint(cv, paw_mask(px, py, pitch), pal, ang=0, fur=0.4, rim=0.45, outline=0.5, seed=seed, grad=None)
    toes(cv, px, py, pitch, pal)


def leg_pal(pal):
    return pal if pal is not GOLD else GOLD


def front_leg(cv, S, foot, pal, pitch=0.0, seed=0, feather=True):
    """Front leg: shoulder S -> elbow -> wrist -> paw at `foot` (one silhouette)."""
    wr = rot((foot[0] - 2.0, foot[1] - 11.5), foot, pitch)
    el, wr = ik2(S, wr, 16.5, 15.5, -1)
    pc = (foot[0] + 3.5, foot[1] - 3.6)
    m = union(m_chain([S, el, wr, (wr[0] + 1.4, wr[1] + 5.0), pc], [11.5, 8.6, 6.2, 5.8, 5.2]),
              paw_mask(foot[0], foot[1], pitch))
    paint(cv, m, pal, ang=95, fur=0.9, rim=0.12, outline=0.5, seed=seed, fade=(S[1] + 6, S[1] + 18), gain=0.5)
    if feather:                                      # feathering on the back of the leg
        tufts(cv, [(el[0] - 3, el[1] - 1), (el[0] - 2.5, el[1] + 6), (wr[0] - 3.6, wr[1] + 1)], 100, 7.0, 2.1, 12,
              [pal, CREAM if pal is GOLD else pal], seed + 3, 14, 0.6)
    toes(cv, foot[0], foot[1], pitch, PAW)
    return el, wr


def hind_leg(cv, A, foot, pal, pitch=0.0, seed=0, haunch=True):
    """Hind leg below the hip: stifle -> hock -> paw (the thigh muscle is part of the body)."""
    hock = rot((foot[0] - 3.0, foot[1] - 12.5), foot, pitch)
    st, hock = ik2(A, hock, 16.5, 16.5, +1)
    pc = (foot[0] + 3.5, foot[1] - 3.6)
    parts = [m_chain([A, st, hock, (foot[0] - 2.5, foot[1] - 7), pc], [12 if not haunch else 11, 8.8, 5.2, 4.8, 4.6]),
             paw_mask(foot[0], foot[1], pitch)]
    if not haunch:
        parts.append(m_ell(A[0] + 3, A[1] + 3, 14.5, 13.5, -20))
    paint(cv, union(*parts), pal, ang=105, fur=1.0, rim=0.12, outline=0.5, gain=0.5, seed=seed,
          fade=(A[1] + 6, A[1] + 16) if haunch else None)
    if haunch:                                       # "breeches" feathering behind the thigh
        tufts(cv, [(A[0] - 13, A[1] + 2), (A[0] - 13.5, A[1] + 12), (hock[0] - 4, hock[1] - 3)], 112, 9, 2.4, 17,
              [pal, CREAM if pal is GOLD else pal], seed + 5, 16, 0.8)
    toes(cv, foot[0], foot[1], pitch, PAW)
    return st, hock


def lock(dr, bx, by, ux, uy, ln, wd, col, rng):
    """One soft, slightly curved lock of hair (lens shape with a rounded tip)."""
    c = rng.uniform(-0.22, 0.22) * ln
    px, py = -uy, ux
    mx, my = bx + ux * ln * 0.5 + px * c * 0.6, by + uy * ln * 0.5 + py * c * 0.6
    tx, ty = bx + ux * ln + px * c, by + uy * ln + py * c
    q = [(bx - px * wd / 2, by - py * wd / 2), (mx - px * wd * 0.62, my - py * wd * 0.62),
         (tx - px * wd * 0.2, ty - py * wd * 0.2), (tx + px * wd * 0.2, ty + py * wd * 0.2),
         (mx + px * wd * 0.62, my + py * wd * 0.62), (bx + px * wd / 2, by + py * wd / 2)]
    dr.polygon([(x * U, y * U) for x, y in q], fill=col)


def fluff(cv, pts, length=5.5, width=4.6, step=1, pals=None, seed=0, back=(-0.45, 0.25), closed=True):
    """Fluffy fringe: strands that start just inside a silhouette and sweep outward + backward."""
    pals = pals or [GOLD, GOLD, CREAM]
    q = sp(pts, closed, 6)
    cx = sum(float(p[0]) for p in q) / len(q)
    cy = sum(float(p[1]) for p in q) / len(q)
    rng = random.Random(seed)
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dr = ImageDraw.Draw(lay)
    for i in range(0, len(q), step):
        p = q[i]
        nx, ny = float(p[0]) - cx, float(p[1]) - cy
        d = math.hypot(nx, ny) or 1
        nx, ny = nx / d, ny / d
        ux, uy = nx + back[0], ny + back[1]
        d = math.hypot(ux, uy) or 1
        ux, uy = ux / d, uy / d
        a = math.atan2(uy, ux) + math.radians(rng.uniform(-22, 22))
        ux, uy = math.cos(a), math.sin(a)
        ln = length * rng.uniform(0.55, 1.2)
        wd = width * rng.uniform(0.8, 1.3)
        bx, by = float(p[0]) - nx * 1.6, float(p[1]) - ny * 1.6
        tip = (bx + ux * (ln + 1.6), by + uy * (ln + 1.6))
        pal = rng.choice(pals)
        c = np.array(pal["base"], float) + (np.array(pal["light"], float) - np.array(pal["base"], float)) * rng.uniform(0, 0.45)
        c = c * rng.uniform(0.9, 1.0)
        col = (int(min(255, c[0])), int(min(255, c[1])), int(min(255, c[2])), 255)
        lock(dr, bx, by, ux, uy, ln + 1.6, wd * 1.25, col, rng)
    cv.alpha_composite(lay)


def draw_tail_chain(cv, pts, radii, seed=0, wag=0.0):
    """Feathered golden-retriever tail."""
    paint(cv, m_chain(pts, radii), GOLD, ang=180, fur=1.2, rim=0.3, outline=0.5, seed=seed, grad=None, gain=0.6)
    tufts(cv, [(q[0] + 1, q[1] + 4) for q in pts[1:]], 118 + wag * 5, 11, 2.6, 34, [GOLD, GOLD, CREAM], seed + 1, 22, 1.2)
    tufts(cv, [(q[0], q[1] - 3.2) for q in pts[1:]], 205, 7, 2.8, 12, [GOLD], seed + 2, 20, 0.8)
    tufts(cv, [pts[-1]], 185 + wag * 8, 10, 3.0, 10, [GOLD, CREAM], seed + 3, 28, 1.0)


def draw_tail(cv, base, tip_wag=0.0, curl=0.0, seed=0, hang=0.0):
    bx, by = base
    pts = [(bx, by), (bx - 9, by - 3 + tip_wag * 0.5), (bx - 19, by - 5 + tip_wag * 3 + hang * 6),
           (bx - 29, by - 4 + tip_wag * 7 + hang * 14)]
    draw_tail_chain(cv, pts, [5.0, 6.5, 6.2, 3.2], seed, tip_wag)


def draw_ear(cv, T, ear=0.0, far=False, seed=0):
    """Soft floppy drop ear."""
    piv = (-4.0, -12.0)
    ang = ear * 0.8
    off = 11.0 if far else 0.0
    loc = [(-5 + off, -14 - 1 * far), (2 + off, -13), (5 + off, -5), (5.5 + off, 6), (1.5 + off, 15), (-6 + off, 16),
           (-12 + off, 8), (-12.5 + off, -5)]
    pts = [T(*rot(p, piv, ang)) for p in loc]
    pal = mul(EARC, 0.9) if far else EARC
    paint(cv, m_poly(pts, per=5), pal, ang=95, fur=1.0, rim=0.2, outline=0.4, seed=seed, grad=None, gain=0.5)
    if not far:
        tufts(cv, [T(*rot(p, piv, ang)) for p in [(-11, 7), (-7, 15), (0, 16), (4, 10)]], 100 + ang, 8, 2.8, 22,
              [EARC, CREAM, GOLD], seed + 2, 24, 0.8)
        tufts(cv, [T(*rot(p, piv, ang)) for p in [(-10, -4), (-11, 4)]], 160 + ang, 5, 2.4, 8, [GOLD, EARC], seed + 3, 20, 0.6)


def draw_head(cv, hx, hy, ang=0.0, op=0.0, tongue=0.0, eye="open", ear=0.0, seed=7, brow=0.0):
    """Cute Pomeranian head. (hx, hy) = skull centre, ang = tilt (deg, + = nose down), op = jaw opening 0..1."""
    a = math.radians(ang)
    ca, sa = math.cos(a), math.sin(a)

    def T(x, y):
        return (hx + x * ca - y * sa, hy + x * sa + y * ca)

    jd = math.radians(30 * op)

    def Jw(x, y):                                    # lower jaw rotates about the hinge (4, 9)
        dx, dy = x - 4, y - 9
        return T(4 + dx * math.cos(jd) - dy * math.sin(jd), 9 + dx * math.sin(jd) + dy * math.cos(jd))

    tonguepal = dict(base=(240, 120, 132), light=(252, 160, 166), dark=(190, 80, 98))
    draw_ear(cv, T, ear, far=True, seed=seed + 20)

    if op > 0.04:                                    # open mouth: interior, tongue
        inner = m_poly([T(5, 8), T(14, 9.5), T(21, 9.5), Jw(22, 10.5), Jw(13, 11.5), Jw(5, 10)], smooth=False)
        flat(cv, inner, (122, 38, 50), 0.35)
        tg = m_chain([Jw(7, 10), Jw(14, 10.6), Jw(20 + tongue * 1.5, 11.5 + 3 * tongue)], [3.3, 3.3, 2.6 + tongue * 0.6])
        paint(cv, tg, tonguepal, fur=0, rim=0.3, outline=0.5, grad=None)
    elif tongue > 0:                                 # panting tongue
        tg = m_chain([T(14, 11), T(20, 13), T(21, 13 + 7 * tongue)], [2.6, 3.0, 2.8])
        paint(cv, tg, tonguepal, fur=0, rim=0.3, outline=0.5, grad=None)

    jaw = m_chain([Jw(3, 12), Jw(11, 13), Jw(19, 12.2)], [5.4, 4.6, 3.2])
    paint(cv, jaw, CREAM, ang=170, fur=0.5, rim=0.15, outline=0.6, seed=seed + 1, grad=None, gain=0.5)

    # big round fluffy skull + short foxy muzzle
    skull = m_chain([T(-3, 0), T(4, 1)], [18.0, 16.8])
    muzzle = m_chain([T(10, 5.5), T(20, 7.8)], [7.4, 6.0])
    head = union(skull, muzzle)
    fluff(cv, [T(-2 + 17.4 * math.cos(t * math.pi / 8), 17.4 * math.sin(t * math.pi / 8)) for t in range(16)],
          3.6, 6.0, 1, [GOLD, GOLD, CREAM], seed + 9, back=(-0.5, 0.2))
    paint(cv, head, GOLD, ang=170, fur=1.1, rim=0.1, outline=0.12, seed=seed, grad=None, gain=0.45)
    mz = m_chain([T(12, 7.5), T(21, 9.2)], [5.4, 4.2])
    paint(cv, mz, CREAM, ang=172, fur=0.4, rim=0.0, outline=0.0, seed=seed + 2, grad=None, gain=0.4)
    cheek = m_chain([T(3, 10), T(9, 11.5)], [5.5, 4.5])
    paint(cv, cheek, CREAM, ang=100, fur=0.5, rim=0.0, outline=0.0, seed=seed + 5, grad=None, gain=0.4)

    # nose
    flat(cv, m_ell(*T(25.4, 5.0), 3.7, 3.1, ang + 8), (26, 20, 20), 0.0)
    flat(cv, m_ell(*T(26.3, 3.8), 1.3, 0.7, ang + 8), (180, 170, 165), 0.0)

    lip_c = (96, 52, 30)
    if op > 0.04:
        stroke(cv, [T(22.5, 9.2), T(15, 10.2), T(9, 9.4)], lip_c, 0.5)
        for x in (17.5, 20.0):
            flat(cv, m_poly([T(x, 9.8), T(x + 1.4, 9.8), T(x + 0.7, 12.4)], smooth=False), (252, 248, 240))
    else:                                            # sweet little smile
        stroke(cv, [T(24.0, 8.6), T(22.0, 10.8), T(16, 11.8), T(10.5, 10.6)], lip_c, 0.55)

    # big, sparkly eye
    ex, ey = T(7.6, -2.0)
    if eye == "open":
        crease(cv, [(ex - 1.5, ey + 0.5), (ex + 1.5, ey + 0.5)], 12.5, 38, (150, 98, 46))       # soft tan eye patch
        flat(cv, m_ell(ex, ey, 5.0, 5.2, ang), (44, 26, 16), 0.0)                                   # dark rim
        flat(cv, m_ell(ex + 0.1, ey + 0.2, 4.3, 4.5, ang), (96, 56, 28), 0.5)                       # iris
        flat(cv, m_ell(ex + 0.3, ey + 0.3, 3.0, 3.2, ang), (12, 8, 8), 0.0)                         # pupil
        flat(cv, m_ell(ex + 1.6, ey - 1.9, 1.6, 1.5), (255, 255, 255))                              # big glint
        flat(cv, m_ell(ex - 1.5, ey + 1.7, 0.75, 0.75), (230, 200, 170))                            # small glint
        stroke(cv, [T(2.6, -3.0), T(7.6, -7.0), T(12.8, -3.2)], (54, 36, 26), 0.75, 210)            # upper lid line
    elif eye == "half":
        flat(cv, m_ell(ex, ey + 1.5, 4.6, 2.4, ang), (40, 24, 12), 0.0)
        stroke(cv, [T(3.0, -2.2), T(7.6, -3.6), T(12.2, -2.2)], (96, 58, 24), 0.8)
    else:                                            # closed, happy arc
        stroke(cv, [T(3.0, -2.0), T(7.6, 0.6), T(12.2, -2.0)], (70, 40, 16), 0.9)
    crease(cv, [T(1.5, 5.5), T(6.5, 6.5)], 3.2, 38, (244, 150, 140))                                       # rosy cheek

    tufts(cv, [T(12, 10.5), T(19, 10.5)], 85, 6, 2.4, 10, [CREAM, GOLD], seed + 6, 22, 0.8)          # moustache
    draw_ear(cv, T, ear, far=False, seed=seed + 30)
    return T


def draw_neck(cv, pts, radii, seed=0):
    r2 = [r + 5.0 for r in radii]
    for p, r in zip(pts, r2):                         # soft fuzzy halo around the thick neck
        fluff(cv, [(p[0] + (r - 2) * math.cos(t * math.pi / 6), p[1] + (r - 2) * math.sin(t * math.pi / 6))
                   for t in range(12)], 3.2, 5.5, 1, [GOLD, GOLD, CREAM], seed + 7, back=(-0.3, 0.3))
    paint(cv, m_chain(pts, r2), GOLD, ang=190, fur=1.1, rim=0.2, outline=0.0, seed=seed)


def chest_ruff(cv, c, seed=0):
    """Fluffy cream chest mane."""
    fluff(cv, [(c[0] + 11 * math.cos(t * math.pi / 7), c[1] + 12.5 * math.sin(t * math.pi / 7)) for t in range(14)],
          5.0, 4.8, 1, [CREAM, CREAM, GOLD], seed, back=(-0.2, 0.5))
    paint(cv, m_ell(c[0], c[1], 10.5, 12, 0), CREAM, ang=100, fur=0.7, rim=0.2, outline=0.0, seed=seed + 1,
          grad=None, gain=0.4)


def body_poly_stand():
    return [(122, 78), (110, 70), (88, 71), (64, 72), (50, 78), (45, 90), (49, 101), (62, 106), (80, 105),
            (98, 106), (116, 111), (128, 106), (132, 92)]


def stand_pose(cv, p):
    """Standing / running / barking / kicking dog. p holds the pose parameters."""
    dy, pitch = p.get("dy", 0.0) + 5.0, p.get("pitch", 0.0)
    c0 = (86.0, 90.0)

    def B(x, y):
        x, y = rot((x, y), c0, -pitch)
        return (x, y + dy)

    feet = p.get("feet", {})
    fn = feet.get("fn", (122, GY - 1.2, 0))
    ff = feet.get("ff", (106, GY - 1.2, 0))
    hn = feet.get("hn", (60, GY - 1.2, 0))
    hf = feet.get("hf", (74, GY - 1.2, 0))

    # far legs (behind the body)
    hind_leg(cv, B(60, 93), (hf[0], hf[1]), mul(GOLD, FAR), hf[2], seed=11, haunch=False)
    front_leg(cv, B(112, 95), (ff[0], ff[1]), mul(GOLD, FAR), ff[2], seed=12, feather=False)

    hip = B(58, 92)
    body = union(m_poly([B(*q) for q in body_poly_stand()]), m_ell(hip[0] + 4, hip[1] + 4, 17.5, 16.5, -20 + pitch))
    fluff(cv, [B(*q) for q in body_poly_stand()], 3.4, 5.5, 1, [GOLD, GOLD, CREAM], 38)
    paint(cv, body, GOLD, ang=188, fur=1.0, rim=0.3, outline=0.45, seed=31)
    draw_tail(cv, B(47, 84), p.get("wag", 0.0), p.get("curl", 0.0), seed=21, hang=p.get("hang", 0.0))
    crease(cv, [B(66, 80), B(76, 96), B(80, 108)], 1.5, 60)                 # front edge of the thigh
    # belly + chest feathering
    tufts(cv, [B(66, 106), B(88, 110), B(112, 110)], 98, 7.5, 2.6, 22, [GOLD, GOLD], 33, 16, 0.8)
    tufts(cv, [B(96, 74), B(76, 76), B(60, 84)], 105, 6, 2.6, 10, [GOLD, GOLD], 36, 18, 0.8)
    tufts(cv, [B(96, 70.5), B(76, 71), B(56, 74)], 188, 5, 2.0, 12, [GOLD], 35, 16, 0.6)

    hx, hy = B(p.get("hx", 141.0), p.get("hy", 59.0))
    draw_neck(cv, [B(112, 88), B(126, 80), (hx - 3, hy + 3)], [14.5, 13.8, 12.8], seed=36)
    chest_ruff(cv, B(126, 99), 39)
    
    draw_head(cv, hx, hy, p.get("tilt", 0.0) - pitch * 0.6, p.get("op", 0.0), p.get("tongue", 0.0),
              p.get("eye", "open"), p.get("ear", 0.0), brow=p.get("brow", 0.0))

    # near legs on top
    hind_leg(cv, hip, (hn[0], hn[1]), GOLD, hn[2], seed=41, haunch=True)
    front_leg(cv, B(114, 95), (fn[0], fn[1]), GOLD, fn[2], seed=42)
    crease(cv, [B(104, 80), B(110, 92), B(106, 104)], 1.4, 55)              # shoulder blade edge
    tufts(cv, [B(118, 94), B(126, 100)], 100, 5, 2.0, 7, [CREAM, GOLD], 43, 16, 0.4)
    return B


def prop_ball_arc():
    return None


# ---------------------------------------------------------------- gait
def run_feet(ph):
    """Gallop-like cycle. ph in [0, 1). Returns pose dict."""
    def leg(cx, off, amp, lift, y0=GY - 1.2):
        th = 2 * math.pi * ((ph + off) % 1.0)
        x = cx + amp * math.cos(th)
        sw = max(0.0, -math.sin(th))             # swing (foot off the ground)
        y = y0 - lift * sw
        pitch = 28 * math.sin(th) if sw > 0 else 12 * math.sin(th)
        return (x, y, pitch)

    return dict(
        fn=leg(124, 0.00, 17, 15), ff=leg(110, 0.10, 17, 15),
        hn=leg(60, 0.50, 17, 16), hf=leg(74, 0.60, 17, 16))


def run_pose(ph):
    s = math.sin(2 * math.pi * ph)
    c = math.cos(2 * math.pi * ph)
    return dict(feet=run_feet(ph), dy=-3.0 * abs(s) + 1.0, pitch=2.5 * s, wag=0.8 * s, curl=0.5,
                op=0.22 + 0.06 * c, tongue=1.0, ear=16 + 8 * c, tilt=-4 + 3 * s, hy=60.0, brow=0.5)


# ---------------------------------------------------------------- other postures
def sit_pose(cv, ph=0.0, op=0.0, eye="open", wave=True):
    """Sitting pup, near front paw raised and waving ("come on, move!")."""
    # far front leg (straight down)
    front_leg(cv, (112, 94), (123, GY - 1.2), mul(GOLD, FAR), 0, seed=12, feather=False)
    # torso (+ haunch in one silhouette)
    pts = [(122, 74), (108, 64), (92, 76), (74, 92), (54, 106), (44, 122), (50, 137), (74, 139), (94, 130),
           (110, 118), (124, 106), (131, 90)]
    body = union(m_poly(pts), m_ell(68, 118, 21, 18.5, -25))
    fluff(cv, pts, 3.4, 5.5, 1, [GOLD, GOLD, CREAM], 38)
    paint(cv, body, GOLD, ang=205, fur=1.0, rim=0.3, outline=0.45, seed=31)
    chest = m_chain([(112, 98), (122, 102), (126, 92)], [6, 6, 5])
    paint(cv, chest, CREAM, ang=100, fur=0.5, rim=0.0, outline=0.0, seed=32, grad=None)
    crease(cv, [(60, 104), (78, 106), (92, 118), (88, 132)], 1.6, 65)           # thigh edge
    tufts(cv, [(110, 112), (122, 110), (130, 98)], 98, 8.5, 2.3, 22, [CREAM, GOLD], 34, 16, 0.6)
    tufts(cv, [(52, 108), (50, 124), (56, 134)], 120, 8, 2.4, 14, [GOLD, CREAM], 44, 16, 0.7)

    tw = math.sin(ph * 2 * math.pi)
    draw_tail_chain(cv, [(49, 133), (38, 135), (27, 136 + tw * 0.3), (16, 137 + tw * 0.6)], [5, 6, 5.5, 3], 21, tw)
    hx, hy = 138, 55 + math.sin(ph * 2 * math.pi) * 0.4
    draw_neck(cv, [(108, 86), (122, 74), (hx - 3, hy + 3)], [14, 13.5, 12.6], seed=36)
    chest_ruff(cv, (122, 98), 39)
    draw_head(cv, hx, hy, -7, op, 0.0, eye, 4, brow=0.3)

    # folded hind foot, flat on the ground
    paint(cv, union(m_chain([(74, 134.5), (86, 136.5)], [5.4, 4.6]), paw_mask(88, GY - 1.2, -2)),
          GOLD, ang=0, fur=0.8, rim=0.08, outline=0.5, seed=45, grad=None, gain=0.25)
    toes(cv, 88, GY - 1.2, -2, PAW)

    # near front leg: raised & waving, or standing
    if wave:
        w = math.sin(ph * 2 * math.pi)
        S = (113, 94)
        pw = (141 + 3.0 * w, 100 - 3.0 * abs(w) - 1.5 * math.cos(ph * 2 * math.pi))     # paw centre
        el, wr = ik2(S, (pw[0] - 2.5, pw[1] + 5.5), 19, 18, -1)
        paw = paw_mask(pw[0] - 3.5, pw[1] + 3.6, -80 + 6 * w)
        paint(cv, union(m_chain([S, el, wr, pw], [10.5, 7.6, 5.0, 4.8]), paw), GOLD, ang=70, fur=0.9, rim=0.5,
              outline=0.75, seed=42, fade=(S[1] + 4, S[1] + 14))
        tufts(cv, [(el[0] - 3, el[1]), (wr[0] - 3, wr[1] + 2)], 120, 6, 2.0, 8, [GOLD, CREAM], 47, 14, 0.5)
        toes(cv, pw[0] - 3.5, pw[1] + 3.6, -80 + 6 * w, PAW)
    else:
        front_leg(cv, (114, 95), (125, GY - 1.2), GOLD, 0, seed=42)


def lie_pose(cv, ph=0.0, state="sleep", jaw=0.0, tilt_bone=0.0):
    """Lying down: sleeping with the head on the paws, drowsy, or chewing a bone."""
    breathe = math.sin(ph * 2 * math.pi) * 1.1 if state == "sleep" else 0.0
    chew = state == "chew"
    # far hind paw
    draw_paw(cv, 92, GY - 1.2, 0, mul(PAW, 0.95), 4)

    # torso: low, rounded, with the haunch merged in
    top = 103 - breathe
    pts = [(116, top + 6), (100, top - 1), (78, top - 2), (58, top + 3), (44, top + 14), (42, 126), (52, 137),
           (80, 139.5), (110, 139), (122, 132), (126, 118)]
    body = union(m_poly(pts), m_ell(66, 123, 22, 17, 0))
    fluff(cv, pts, 3.4, 5.5, 1, [GOLD, GOLD, CREAM], 38)
    paint(cv, body, GOLD, ang=190, fur=1.0, rim=0.3, outline=0.45, seed=31, grad=None, gain=0.45)
    crease(cv, [(76, 112), (84, 124), (82, 136)], 1.6, 65)                       # thigh edge
    tufts(cv, [(96, top - 1), (74, top - 1.5), (56, top + 3)], 190, 5, 2.0, 12, [GOLD], 35, 16, 0.6)
    tufts(cv, [(48, 114), (46, 128), (54, 136)], 120, 7, 2.4, 12, [GOLD, CREAM], 44, 16, 0.7)

    draw_tail_chain(cv, [(46, 128), (32, 132), (20, 133), (9, 130)], [5, 5.8, 5, 2.6], 21)

    # near hind foot
    paint(cv, union(m_chain([(80, 134), (91, 136.5)], [5.4, 4.6]), paw_mask(94, GY - 1.2, 0)), GOLD,
          ang=0, fur=0.8, rim=0.08, outline=0.5, seed=46, grad=None, gain=0.25)
    toes(cv, 94, GY - 1.2, 0, PAW)

    # front legs extended
    px = 154 if not chew else 147
    paint(cv, union(m_chain([(112, 130), (px - 8, 136)], [8.2, 4.8]), paw_mask(px - 1, GY - 1.2, 0)),
          GOLD, ang=0, fur=0.8, rim=0.08, outline=0.5, seed=50, grad=None, gain=0.25, fade=None)
    tufts(cv, [(118, 136.5), (136, 138.5)], 95, 4, 1.8, 8, [CREAM, GOLD], 51, 14, 0.5)
    toes(cv, px - 1, GY - 1.2, 0, PAW)

    if state == "sleep":
        hx, hy, tilt = 132.0, 122.0 - breathe * 0.5, 12.0
        eye, ear, op = "closed", 8, 0.0
    elif state == "drowsy":
        hx, hy, tilt = 132.0, 117.0, 8.0
        eye, ear, op = "half", 6, 0.0
    else:
        hx, hy, tilt = 128.0, 106.0 + 1.2 * math.sin(ph * 2 * math.pi), 14.0
        eye, ear, op = "open", 8, jaw
    draw_neck(cv, [(106, 118), (hx - 11, hy + 1), (hx - 2, hy + 3)], [12, 12.5, 12.5], seed=36)
    T = draw_head(cv, hx, hy, tilt, op, 0.0, eye, ear, brow=0.0)
    tufts(cv, [(hx - 12, hy + 12), (hx - 2, hy + 15)], 100, 5, 2, 8, [CREAM, GOLD], 53, 16, 0.5)
    if chew:                                          # bone held in the mouth, paws on either side
        bx, by = T(25.0, 12.0)
        draw_bone(cv, bx, by + 2, 4 + tilt_bone)
        draw_paw(cv, px + 6, GY - 1.2, 0, PAW, 54)


def draw_bone(cv, cx, cy, ang):
    a = math.radians(ang)
    ux, uy = math.cos(a), math.sin(a)
    L = 19
    shaft = m_chain([(cx - ux * L / 2, cy - uy * L / 2), (cx + ux * L / 2, cy + uy * L / 2)], [3.0, 3.0])
    ends = []
    for s in (-1, 1):
        ex, ey = cx + ux * (L / 2 + 1) * s, cy + uy * (L / 2 + 1) * s
        for q in (-1, 1):
            ends.append(m_ell(ex - uy * 3.2 * q, ey + ux * 3.2 * q, 4.0, 4.0))
    bone = union(shaft, *ends)
    paint(cv, bone, dict(base=(246, 226, 176), light=(255, 246, 214), dark=(206, 170, 112)), fur=0, rim=0.35,
          outline=0.5, light=0.9, mottle=0.03, grad=None, gain=1.0)


def draw_ball():
    S = 10
    n = 22 * S
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    cx = cy = n / 2
    r = n / 2 - S * 0.6
    dx, dy = (xx - cx) / r, (yy - cy) / r
    d = np.sqrt(dx * dx + dy * dy)
    inside = d <= 1
    z = np.sqrt(np.clip(1 - d * d, 0, 1))
    lam = np.clip(-0.45 * dx - 0.55 * dy + 0.65 * z, 0, 1)
    base = np.array([205, 226, 52], np.float32)
    col = base[None, None, :] * (0.55 + 0.6 * lam[..., None])
    # felt noise
    rng = np.random.RandomState(5)
    col *= 1 + (rng.rand(n, n, 1) - 0.5) * 0.10
    # seams (two arcs)
    for sgn in (-1, 1):
        ex = (dx + sgn * 1.05)
        seam = np.abs(np.sqrt(ex * ex + dy * dy) - 1.15) < 0.055
        col = np.where(seam[..., None] & inside[..., None], col * 0.35 + 255 * 0.65 * lam[..., None] ** 0.3, col)
    rgba = np.dstack([np.clip(col, 0, 255), inside * 255]).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA").resize((22, 22), Image.LANCZOS)


# ---------------------------------------------------------------- frame assembly
def finish(cv):
    """Downsample, crop, convert to a transparent GIF. Returns (ox, oy, w, h, b64)."""
    im = cv.resize((FW, FH), Image.LANCZOS)
    return to_gif(im)


def to_gif(im):
    a = np.asarray(im)
    alpha = a[..., 3] >= 120
    bb = Image.fromarray((alpha * 255).astype(np.uint8)).getbbox()
    if not bb:
        raise RuntimeError("empty frame")
    rgb = a[..., :3].copy()
    rgb[~alpha] = (255, 0, 255)
    crop = Image.fromarray(rgb, "RGB").crop(bb)
    q = crop.quantize(colors=255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    idx = np.asarray(q).copy()
    idx[~alpha[bb[1]:bb[3], bb[0]:bb[2]]] = 255
    out = Image.fromarray(idx, "P")
    pal = (q.getpalette() or [])[:765]
    pal += [0] * (765 - len(pal)) + [255, 0, 255]
    out.putpalette(pal)
    buf = io.BytesIO()
    out.save(buf, "GIF", transparency=255, optimize=False)
    return (bb[0], bb[1], bb[2] - bb[0], bb[3] - bb[1], base64.b64encode(buf.getvalue()).decode("ascii")), im


def new_canvas():
    return Image.new("RGBA", (W, H), (0, 0, 0, 0))


def frame_funcs():
    F = {}
    for i in range(8):
        F[f"run{i}"] = lambda cv, i=i: stand_pose(cv, run_pose(i / 8.0))
    for i in range(6):
        s = math.sin(2 * math.pi * i / 6)
        F[f"stand{i}"] = lambda cv, s=s: stand_pose(cv, dict(
            dy=0.6 * s, wag=1.0 * s, curl=0.2, hy=59.0 + 0.5 * s, tilt=1.5 * s, ear=2 + 1.5 * s, tongue=0.0))
    F["stand_blink"] = lambda cv: stand_pose(cv, dict(eye="closed", wag=0.0, curl=0.2))
    F["bark0"] = lambda cv: stand_pose(cv, dict(
        op=0.95, tilt=-14, hy=58.0, hx=140.0, pitch=2.0, curl=0.8, wag=0.5, ear=14, brow=1.0,
        feet=dict(fn=(125, GY - 1.2, 0), ff=(111, GY - 1.2, 0))))
    F["bark1"] = lambda cv: stand_pose(cv, dict(
        op=0.55, tilt=-8, hy=59.0, hx=140.5, pitch=0.8, curl=0.8, wag=-0.5, ear=8, brow=0.6))
    F["kick"] = lambda cv: stand_pose(cv, dict(
        tilt=10, hy=62.0, pitch=-1.5, wag=0.6, curl=0.4, ear=8, op=0.12,
        feet=dict(fn=(142, GY - 14, 25), ff=(106, GY - 1.2, 0))))
    for i in range(8):
        F[f"sit{i}"] = lambda cv, i=i: sit_pose(cv, i / 8.0)
    F["sit_blink"] = lambda cv: sit_pose(cv, 0.0, eye="closed")
    F["sit_bark"] = lambda cv: sit_pose(cv, 0.0, op=0.95)
    for i in range(4):
        F[f"sleep{i}"] = lambda cv, i=i: lie_pose(cv, i / 4.0, "sleep")
    F["drowsy"] = lambda cv: lie_pose(cv, 0.0, "drowsy")
    for i in range(6):
        jaw = 0.1 + 0.4 * (0.5 + 0.5 * math.sin(2 * math.pi * i / 6))
        F[f"chew{i}"] = lambda cv, i=i, jaw=jaw: lie_pose(
            cv, i / 6.0, "chew", jaw, tilt_bone=3 * math.sin(2 * math.pi * i / 6))
    return F


FRAME_FUNCS = frame_funcs()


def build_frames():
    frames, previews = {}, {}
    for name, fn in FRAME_FUNCS.items():
        cv = new_canvas()
        fn(cv)
        entry, im = finish(cv)
        frames[name] = entry
        previews[name] = im
        print("  frame", name, flush=True)
    ball = draw_ball()
    entry, _ = to_gif(ball)
    frames["ball"] = (0, 0, 22, 22, entry[4]) if entry[2:4] == (22, 22) else entry
    previews["ball"] = None
    return frames, previews


def preview_only(names, path, zoom=4, cols=3):
    """Render just some frames to a contact sheet (for tuning)."""
    prev = {}
    for n in names:
        cv = new_canvas()
        FRAME_FUNCS[n](cv)
        prev[n] = cv.resize((FW, FH), Image.LANCZOS)
    contact_sheet(prev, path, names, cols, zoom)


def write_module(frames, path):
    lines = ['"""Sprite data for Desktop Puppy - realistic golden retriever puppy (auto-generated by make_puppy_sprites.py).',
             "",
             "Each entry:  name -> (offset_x, offset_y, width, height, base64_gif)",
             "Frames are cropped; offsets place them on the FRAME_W x FRAME_H puppy canvas.",
             '"""', "",
             f"SCALE = {K}                      # puppy size relative to the original design",
             f"FRAME_W, FRAME_H, GROUND_Y = {FW}, {FH}, {GROUND}", "", "FRAMES = {"]
    for name, (ox, oy, w, h, b64) in frames.items():
        lines.append(f'    "{name}": ({ox}, {oy}, {w}, {h}, "".join((')
        for i in range(0, len(b64), 108):
            lines.append(f'        "{b64[i:i + 108]}",')
        lines.append("    ))),")
    lines.append("}")
    with open(path, "w", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def contact_sheet(previews, path, names=None, cols=6, zoom=2, bg=(196, 218, 250)):
    names = names or [n for n in previews if previews[n] is not None]
    rows = (len(names) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * FW * zoom, rows * FH * zoom), bg)
    for i, n in enumerate(names):
        im = previews[n].resize((FW * zoom, FH * zoom), Image.LANCZOS)
        sheet.paste(im, ((i % cols) * FW * zoom, (i // cols) * FH * zoom), im)
    sheet.save(path)


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    frames, previews = build_frames()
    write_module(frames, os.path.join(here, "puppy_sprites.py"))
    print("wrote puppy_sprites.py", len(frames), "frames")
    if "--sheet" in sys.argv:
        contact_sheet(previews, os.path.join(here, "puppy_preview.png"))
