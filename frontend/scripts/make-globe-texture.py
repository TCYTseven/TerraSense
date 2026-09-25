"""Make the light Earth texture for the globe: public/globe/earth-light.jpg.

Reads the two textures already in public/globe/:

- earth-day.jpg       4096x2048 satellite color (NASA Blue Marble)
- earth-topology.png  2048x1024 grayscale relief, ocean = 0

and writes a light "atlas" of the same size: pale blue-gray oceans that keep a hint
of the continental shelves, land lightened and slightly desaturated so its terrain
colors survive, white ice, and a gentle northwest hillshade from the relief map.
`--style satellite` writes the other variant we compared: the same photo, lifted
and softened, without the atlas treatment.

Run it from frontend/ with Pillow and numpy, for example:

    python3 -m venv /tmp/globe-venv && /tmp/globe-venv/bin/pip install pillow numpy
    /tmp/globe-venv/bin/python scripts/make-globe-texture.py
    /tmp/globe-venv/bin/python scripts/make-globe-texture.py --style satellite --out /tmp/earth-sat.jpg

It prints the output size. Keep the JPEG around 1 to 1.5 MB.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image

GLOBE_DIR = Path(__file__).resolve().parent.parent / "public" / "globe"

# sRGB (D65) to CIE XYZ, and the D65 white point.
RGB_TO_XYZ = np.array(
    [
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ],
    dtype=np.float32,
)
XYZ_TO_RGB = np.linalg.inv(RGB_TO_XYZ).astype(np.float32)
D65 = np.array([0.95047, 1.0, 1.08883], dtype=np.float32)
LAB_EPSILON = (6 / 29) ** 3

# Atlas palette, in CIE Lab (L 0-100). Deep and shallow ocean, then ice.
OCEAN_DEEP = (88.5, -3.0, -6.5)
OCEAN_SHALLOW = (93.0, -3.5, -4.5)
ICE = (97.5, -0.5, -1.5)
# A faint darker water line along every coast, so coastlines stay crisp at globe scale.
COAST_LINE_DARKEN = 12.0
COAST_LINE_PX = 2

# Land: lightness is squeezed into [LAND_L_MIN, LAND_L_MAX], chroma is scaled down.
LAND_L_MIN = 70.0
LAND_L_MAX = 93.0
LAND_CHROMA = 0.62

# Hillshade: light from the northwest, 45 degrees up. EXAGGERATION turns the 8-bit
# relief into slopes, STRENGTH sets how much the shade darkens or lifts the land, and
# SHADE_RANGE caps it so steep scarps (the Himalayan front) stay gentle.
SUN_AZIMUTH_DEG = 315.0
SUN_ALTITUDE_DEG = 45.0
RELIEF_EXAGGERATION = 9.0
RELIEF_STRENGTH = 0.45
RELIEF_ON_ICE = 0.6
SHADE_RANGE = (0.4, 1.45)


def srgb_to_linear(c: np.ndarray) -> np.ndarray:
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4).astype(np.float32)


def linear_to_srgb(c: np.ndarray) -> np.ndarray:
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055).astype(np.float32)


def rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    xyz = (srgb_to_linear(rgb) @ RGB_TO_XYZ.T) / D65
    f = np.where(xyz > LAB_EPSILON, np.cbrt(xyz), xyz / (3 * (6 / 29) ** 2) + 4 / 29)
    lab = np.empty_like(f)
    lab[..., 0] = 116 * f[..., 1] - 16
    lab[..., 1] = 500 * (f[..., 0] - f[..., 1])
    lab[..., 2] = 200 * (f[..., 1] - f[..., 2])
    return lab


def lab_to_rgb(lab: np.ndarray) -> np.ndarray:
    fy = (lab[..., 0] + 16) / 116
    f = np.stack([fy + lab[..., 1] / 500, fy, fy - lab[..., 2] / 200], axis=-1)
    xyz = np.where(f > 6 / 29, f**3, 3 * (6 / 29) ** 2 * (f - 4 / 29)) * D65
    return linear_to_srgb(xyz.astype(np.float32) @ XYZ_TO_RGB.T)


def smoothstep(edge0: float, edge1: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def box_blur(image: np.ndarray, radius: int, passes: int = 3) -> np.ndarray:
    """Approximate Gaussian blur. Wraps east-west, clamps at the poles."""
    out = image.astype(np.float32)
    size = 2 * radius + 1
    for _ in range(passes):
        for axis in (0, 1):
            mode = "wrap" if axis == 1 else "edge"
            pad = [(0, 0)] * out.ndim
            pad[axis] = (radius + 1, radius)
            summed = np.cumsum(np.pad(out, pad, mode=mode), axis=axis)
            upper = np.take(summed, np.arange(size, summed.shape[axis]), axis=axis)
            lower = np.take(summed, np.arange(0, summed.shape[axis] - size), axis=axis)
            out = (upper - lower) / size
    return out


def resize(channel: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    return np.asarray(Image.fromarray(channel.astype(np.float32), mode="F").resize(size, Image.BICUBIC))


def hillshade(height: np.ndarray) -> np.ndarray:
    """Relief shade for an equirectangular height map: 1 on flat ground, above 1 facing the sun."""
    rows = height.shape[0]
    latitude = (0.5 - (np.arange(rows) + 0.5) / rows) * np.pi
    # A pixel spans less ground toward the poles, so east-west slopes steepen there.
    east_scale = 1 / np.clip(np.cos(latitude), 0.08, 1.0)[:, None]
    d_east = (np.roll(height, -1, axis=1) - np.roll(height, 1, axis=1)) / 2 * east_scale
    d_south = np.gradient(height, axis=0)
    normal = np.stack(
        [-d_east * RELIEF_EXAGGERATION, d_south * RELIEF_EXAGGERATION, np.ones_like(height)], axis=-1
    )
    normal /= np.linalg.norm(normal, axis=-1, keepdims=True)
    azimuth = np.radians(SUN_AZIMUTH_DEG)
    altitude = np.radians(SUN_ALTITUDE_DEG)
    sun = np.array(
        [np.sin(azimuth) * np.cos(altitude), np.cos(azimuth) * np.cos(altitude), np.sin(altitude)],
        dtype=np.float32,
    )
    return (normal @ sun) / np.sin(altitude)


def water_mask(lab: np.ndarray, relief: np.ndarray) -> np.ndarray:
    """0 on land and ice, 1 on open water, soft along the coast."""
    lightness, b = lab[..., 0], lab[..., 2]
    # Oceans are dark and strongly blue. Bright pixels are ice or snow.
    blue = smoothstep(-4.0, -12.0, b) * smoothstep(72.0, 55.0, lightness)
    # Blue on high ground is shadow or glacier, not sea.
    blue *= smoothstep(0.06, 0.03, relief)
    # Inland lakes (the Great Lakes, Victoria, Baikal) are nearly black rather than blue.
    lake = smoothstep(14.0, 8.0, lightness) * smoothstep(10.0, 4.0, b)
    return np.maximum(blue, lake)


def atlas(day: np.ndarray, relief: np.ndarray, shade: np.ndarray) -> np.ndarray:
    lab = rgb_to_lab(day)
    water = box_blur(water_mask(lab, relief), radius=1, passes=1)[..., None]

    # Ocean: pale blue-gray, slightly lighter over the shelves the satellite shows.
    shelf = smoothstep(8.0, 32.0, lab[..., 0])[..., None]
    ocean = np.array(OCEAN_DEEP, np.float32) + shelf * (
        np.array(OCEAN_SHALLOW, np.float32) - np.array(OCEAN_DEEP, np.float32)
    )
    near_land = box_blur(1 - water[..., 0], radius=COAST_LINE_PX, passes=1)
    ocean[..., 0] -= COAST_LINE_DARKEN * np.clip(near_land * 2, 0, 1) * water[..., 0]

    # Land: keep the satellite's hue and relative lightness, but lift and soften it.
    land = lab.copy()
    lightness = np.clip(lab[..., 0] / 100, 0, 1)
    land[..., 0] = LAND_L_MIN + (LAND_L_MAX - LAND_L_MIN) * np.sqrt(lightness)
    land[..., 1:] *= LAND_CHROMA

    # Ice and snow: bright, nearly neutral pixels go to white.
    ice = (smoothstep(78.0, 92.0, lab[..., 0]) * smoothstep(14.0, 6.0, np.hypot(lab[..., 1], lab[..., 2])))[
        ..., None
    ]
    land = land + ice * (np.array(ICE, np.float32) - land)

    color = lab_to_rgb(land + water * (ocean - land))

    relief_amount = RELIEF_STRENGTH * (1 - water[..., 0]) * (1 - (1 - RELIEF_ON_ICE) * ice[..., 0])
    color *= (1 + relief_amount * (shade - 1))[..., None]
    return color


def satellite(day: np.ndarray, shade: np.ndarray) -> np.ndarray:
    """The satellite photo lifted and softened, for comparison with the atlas."""
    lab = rgb_to_lab(day)
    lab[..., 0] = 56 + 0.44 * lab[..., 0]
    # The photo's oceans lean violet. Pull red-green toward neutral so they lift to a clean blue.
    lab[..., 1] *= 0.45
    lab[..., 2] *= 0.75
    color = lab_to_rgb(lab)
    return color * (1 + 0.25 * (shade - 1))[..., None]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--style", choices=["atlas", "satellite"], default="atlas")
    parser.add_argument("--out", type=Path, default=GLOBE_DIR / "earth-light.jpg")
    parser.add_argument("--quality", type=int, default=90)
    args = parser.parse_args()

    day_image = Image.open(GLOBE_DIR / "earth-day.jpg").convert("RGB")
    size = day_image.size
    day = np.asarray(day_image, dtype=np.float32) / 255

    # Smooth the 8-bit relief so its steps do not print as contour lines.
    relief_small = box_blur(np.asarray(Image.open(GLOBE_DIR / "earth-topology.png").convert("L"), np.float32) / 255, 1)
    relief = np.clip(resize(relief_small, size), 0, 1)
    shade = np.clip(resize(hillshade(relief_small), size), *SHADE_RANGE)

    color = atlas(day, relief, shade) if args.style == "atlas" else satellite(day, shade)
    out = Image.fromarray((np.clip(color, 0, 1) * 255 + 0.5).astype(np.uint8), mode="RGB")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.save(args.out, quality=args.quality, optimize=True, progressive=True, subsampling="4:4:4")
    print(f"Wrote {args.out} ({out.size[0]}x{out.size[1]}, {args.out.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
