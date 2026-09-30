#!/usr/bin/env python3
"""figures -- get a paper's figures onto the platform intact (A15).

The platform shows, and hands to reviewers, PNG and JPEG (SVG too, less
reliably). Papers arrive with PDF, EPS and SVG figures, or as a single PDF
with the figures inside it; the old conversion copied PNG/JPEG only, and
everything else was silently lost. This does the rest, with whatever this
machine has, and says what it could not do instead of dropping it.

    figures.py convert <source dir> <figures dir>
        Every figure file under <source dir> becomes a PNG (or stays a JPEG)
        in <figures dir>, flat, names made unique. Writes MANIFEST.json there:
        source path -> file, plus anything that failed and why.
    figures.py pages <paper.pdf> <out dir>
        Renders each page at 100 dpi (page-N.png) so a model can see where the
        figures are, and extracts the raster images embedded in it.
    figures.py crop <paper.pdf> <page> <x0> <y0> <x1> <y1> <out.png>
        Cuts one figure out of a page. Coordinates are pixels on the 100 dpi
        page image from `pages`; the crop is rendered at 200 dpi.
    figures.py check <body.md> <figures dir>
        Before submitting: every figure the text references exists, every
        figure file is referenced, and every "Figure N" the text mentions is
        there. Exit 1 with the list when not.

Tools, in the order tried: poppler (pdftocairo, pdfimages), Pillow,
ghostscript (EPS), rsvg-convert / cairosvg (SVG), macOS sips / qlmanage,
ImageMagick. None is required; a figure no tool on this machine can convert is
reported, with what to install.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

KEEP = {".png", ".jpg", ".jpeg"}
CONVERT = {".pdf", ".eps", ".ps", ".svg", ".gif", ".tif", ".tiff", ".bmp", ".webp"}
DPI = 200


def have(tool: str) -> bool:
    return shutil.which(tool) is not None


def run(cmd: list[str]) -> bool:
    try:
        return subprocess.run(cmd, capture_output=True, timeout=120).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _pil_to_png(src: str, out: str) -> bool:
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        return False
    try:
        with Image.open(src) as im:
            im.seek(0)
            (im.convert("RGBA") if im.mode in ("P", "LA", "RGBA") else im.convert("RGB")).save(out, "PNG")
        return True
    except Exception:
        return False


def _pdf_pages(src: str) -> int:
    if have("pdfinfo"):
        try:
            out = subprocess.run(["pdfinfo", src], capture_output=True, text=True, timeout=30).stdout
            m = re.search(r"^Pages:\s+(\d+)", out, re.M)
            if m:
                return int(m.group(1))
        except (OSError, subprocess.TimeoutExpired):
            pass
    # No pdfinfo: count page objects, which is right for the PDFs figure tools write.
    try:
        data = open(src, "rb").read()
        return max(1, len(re.findall(rb"/Type\s*/Page[^s]", data)))
    except OSError:
        return 0


def _pdf_to_png(src: str, out: str) -> bool:
    base = out[:-4]
    if have("pdftocairo") and run(["pdftocairo", "-png", "-singlefile", "-r", str(DPI), "-cropbox", src, base]):
        return os.path.exists(out)
    if have("sips") and run(["sips", "-s", "format", "png", src, "--out", out]):
        return os.path.exists(out)
    for magick in ("magick", "convert"):
        if have(magick) and run([magick, "-density", str(DPI), f"{src}[0]", out]):
            return os.path.exists(out)
    return False


def _eps_to_png(src: str, out: str) -> bool:
    if have("gs") and run(["gs", "-q", "-dSAFER", "-dBATCH", "-dNOPAUSE", "-dEPSCrop", "-sDEVICE=png16m",
                           f"-r{DPI}", f"-sOutputFile={out}", src]):
        return os.path.exists(out)
    if have("pstopdf"):
        with tempfile.TemporaryDirectory() as d:
            pdf = os.path.join(d, "fig.pdf")
            if run(["pstopdf", src, "-o", pdf]) and os.path.exists(pdf):
                return _pdf_to_png(pdf, out)
    return False


def _trim(path: str, margin: int = 12) -> None:
    """Cut the empty canvas around a render (Quick Look draws onto a square)."""
    try:
        from PIL import Image, ImageChops  # type: ignore
    except ImportError:
        return
    try:
        with Image.open(path) as im:
            rgb = im.convert("RGB")
            box = ImageChops.difference(rgb, Image.new("RGB", rgb.size, (255, 255, 255))).getbbox()
            if box:
                l, t, r, b = box
                rgb.crop((max(0, l - margin), max(0, t - margin), min(rgb.width, r + margin), min(rgb.height, b + margin))).save(path)
    except Exception:
        pass


def _svg_to_png(src: str, out: str) -> bool:
    if have("rsvg-convert") and run(["rsvg-convert", "-d", str(DPI), "-p", str(DPI), "-o", out, src]):
        return os.path.exists(out)
    try:
        import cairosvg  # type: ignore
        cairosvg.svg2png(url=src, write_to=out, dpi=DPI)
        return os.path.exists(out)
    except Exception:
        pass
    for magick in ("magick", "convert"):
        if have(magick) and run([magick, "-density", str(DPI), src, out]):
            return os.path.exists(out)
    if have("qlmanage"):  # macOS Quick Look renders SVG without any install
        with tempfile.TemporaryDirectory() as d:
            if run(["qlmanage", "-t", "-s", "1600", "-o", d, src]):
                made = os.path.join(d, os.path.basename(src) + ".png")
                if os.path.exists(made):
                    shutil.move(made, out)
                    _trim(out)
                    return True
    return False


def _raster_to_png(src: str, out: str) -> bool:
    if _pil_to_png(src, out):
        return True
    if have("sips") and run(["sips", "-s", "format", "png", src, "--out", out]):
        return os.path.exists(out)
    for magick in ("magick", "convert"):
        if have(magick) and run([magick, f"{src}[0]", out]):
            return os.path.exists(out)
    return False


HINT = {
    ".pdf": "install poppler (brew install poppler / apt-get install poppler-utils)",
    ".eps": "install ghostscript (brew install ghostscript / apt-get install ghostscript)",
    ".ps": "install ghostscript (brew install ghostscript / apt-get install ghostscript)",
    ".svg": "install librsvg (brew install librsvg / apt-get install librsvg2-bin), or pip install cairosvg",
}


def convert(src_dir: str, out_dir: str, skip: str | None = None) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    manifest = {"figures": {}, "failed": {}}
    used: set[str] = set(os.listdir(out_dir))
    for root, dirs, files in os.walk(src_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in sorted(files):
            src = os.path.join(root, name)
            rel = os.path.relpath(src, src_dir)
            stem, ext = os.path.splitext(name)
            ext = ext.lower()
            if ext not in KEEP | CONVERT or (skip and os.path.abspath(src) == os.path.abspath(skip)):
                continue
            # A PDF is a figure only when it has one page; the paper itself,
            # or any other document, is for `pages`, not here.
            if ext == ".pdf" and _pdf_pages(src) != 1:
                continue
            target_ext = ext if ext in KEEP else ".png"
            safe = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-") or "figure"
            cand = safe + target_ext
            if cand in used:  # the same name in two folders: prefix the folder
                parent = re.sub(r"[^A-Za-z0-9._-]+", "-", os.path.basename(root)) or "fig"
                cand = f"{parent}-{safe}{target_ext}"
                i = 2
                while cand in used:
                    cand = f"{parent}-{safe}-{i}{target_ext}"
                    i += 1
            out = os.path.join(out_dir, cand)
            if ext in KEEP:
                shutil.copyfile(src, out)
                ok = True
            elif ext == ".pdf":
                ok = _pdf_to_png(src, out)
            elif ext in (".eps", ".ps"):
                ok = _eps_to_png(src, out)
            elif ext == ".svg":
                ok = _svg_to_png(src, out)
                if not ok:  # the platform takes SVG itself; reviewers may not see it
                    cand = safe + ".svg"
                    out = os.path.join(out_dir, cand)
                    shutil.copyfile(src, out)
                    manifest["failed"][rel] = f"kept as SVG: no converter here ({HINT['.svg']}); some reviewers cannot view SVG"
                    manifest["figures"][rel] = cand
                    used.add(cand)
                    continue
            else:
                ok = _raster_to_png(src, out)
            if ok and os.path.exists(out) and os.path.getsize(out) > 0:
                manifest["figures"][rel] = cand
                used.add(cand)
            else:
                if os.path.exists(out):
                    os.remove(out)
                manifest["failed"][rel] = f"could not convert {ext}: {HINT.get(ext, 'install Pillow (pip install pillow)')}"
    with open(os.path.join(out_dir, "MANIFEST.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1, ensure_ascii=False)
    return manifest


def pages(pdf: str, out_dir: str) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    if not have("pdftocairo"):
        return {"error": "pdftocairo not found: " + HINT[".pdf"]}
    run(["pdftocairo", "-png", "-r", "100", pdf, os.path.join(out_dir, "page")])
    made = sorted(f for f in os.listdir(out_dir) if f.startswith("page") and f.endswith(".png"))
    embedded = []
    if have("pdfimages"):
        emb = os.path.join(out_dir, "embedded")
        os.makedirs(emb, exist_ok=True)
        run(["pdfimages", "-png", "-p", pdf, os.path.join(emb, "img")])
        embedded = sorted(os.listdir(emb))
    return {"pages": made, "embedded": embedded, "dpi": 100}


def crop(pdf: str, page: int, x0: float, y0: float, x1: float, y1: float, out: str) -> bool:
    if not have("pdftocairo"):
        print("pdftocairo not found: " + HINT[".pdf"], file=sys.stderr)
        return False
    s = DPI / 100.0
    x, y = int(min(x0, x1) * s), int(min(y0, y1) * s)
    w, h = int(abs(x1 - x0) * s), int(abs(y1 - y0) * s)
    base = out[:-4] if out.endswith(".png") else out
    ok = run(["pdftocairo", "-png", "-singlefile", "-r", str(DPI), "-f", str(page), "-l", str(page),
              "-x", str(x), "-y", str(y), "-W", str(w), "-H", str(h), pdf, base])
    return ok and os.path.exists(base + ".png")


IMG = re.compile(r"!\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
HTML_IMG = re.compile(r"<img\b[^>]*\bsrc\s*=\s*[\"']([^\"']+)[\"']", re.I)
FIG_MENTION = re.compile(r"\b(?:Figure|Fig\.)\s*(\d+)", re.I)


def check(body_md: str, fig_dir: str) -> list[str]:
    text = open(body_md, encoding="utf-8").read()
    refs = IMG.findall(text) + HTML_IMG.findall(text)
    files = {f for f in os.listdir(fig_dir) if os.path.splitext(f)[1].lower() in KEEP | {".svg"}} if os.path.isdir(fig_dir) else set()
    problems = []
    local = []
    for r in refs:
        if r.startswith(("http://", "https://", "data:", "/api/v1/attachments/")):
            continue
        name = os.path.basename(r)
        local.append(name)
        if name not in files:
            problems.append(f"the text shows {r}, but there is no {name} in {fig_dir}")
        elif os.path.splitext(name)[1].lower() not in KEEP | {".svg"}:
            problems.append(f"{r} is not PNG/JPEG/SVG: convert it (figures.py convert)")
    for f in sorted(files - set(local)):
        problems.append(f"{f} is in {fig_dir} but the text never shows it: reference it where the paper places it, or delete it")
    mentioned = {int(n) for n in FIG_MENTION.findall(text)}
    if mentioned and max(mentioned) > len(refs):
        problems.append(f"the text mentions Figure {max(mentioned)} but shows {len(refs)} image(s): a figure is missing")
    if text.count("$$") % 2:
        problems.append("an odd number of $$: a display equation is not closed")
    return problems


def main() -> None:
    a = sys.argv[1:]
    if not a or a[0] not in ("convert", "pages", "crop", "check"):
        print(__doc__)
        sys.exit(2)
    if a[0] == "convert" and len(a) >= 3:
        m = convert(a[1], a[2], skip=a[3] if len(a) > 3 else None)
        print(json.dumps({"converted": len(m["figures"]), "failed": m["failed"]}, indent=1, ensure_ascii=False))
        sys.exit(0)
    if a[0] == "pages" and len(a) == 3:
        print(json.dumps(pages(a[1], a[2]), indent=1))
        sys.exit(0)
    if a[0] == "crop" and len(a) == 8:
        ok = crop(a[1], int(a[2]), *map(float, a[3:7]), a[7])
        print("wrote " + a[7] if ok else "crop failed")
        sys.exit(0 if ok else 1)
    if a[0] == "check" and len(a) == 3:
        problems = check(a[1], a[2])
        for p in problems:
            print("- " + p)
        print("figures: ok" if not problems else f"figures: {len(problems)} problem(s)")
        sys.exit(1 if problems else 0)
    print(__doc__)
    sys.exit(2)


if __name__ == "__main__":
    main()
