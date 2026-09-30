#!/usr/bin/env python3
"""paper_figures -- a paper's own figures, cut out of its compiled PDF.

The platform shows a paper's figures as PNGs, and they must be the figures the
paper prints. They used to be re-drawn from the data files behind them, which
showed reviewers a bar chart where the paper had a method diagram -- the
re-drawing had nothing else to draw -- in five papers of six in a live test.

So each figure is taken from the PDF itself. A copy of the paper is compiled
with two invisible marks in every figure: one at the top, spanning the
figure's width, and one just before its caption. LaTeX records where each mark
lands on the page (zref-savepos), and the region between them -- the figure,
without its caption, which the platform shows as text -- is rendered from the
PDF at 200 dpi. The marks add no space, so the copy lays out like the paper.

    paper_figures.py <project dir> <out dir> [label ...]

Needs the TeX build the paper's gates already run (build_paper.sh) and
poppler's pdftoppm. Prints a JSON object: label -> PNG file, or an error.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE.parent.parent
BUILD = KIT / "paper-writing" / "scripts" / "build_paper.sh"
DPI = 200
PAD_BP = 3.0          # a little white around the figure
SP_PER_BP = 65536 * 72.27 / 72

MARKS_TEX = r"""% Written by paper_figures.py into a throw-away copy of the paper.
\makeatletter
\RequirePackage{zref-savepos,zref-abspage}
\zref@addprop{savepos}{abspage}
% Top of a figure: a zero-height box as wide as the figure, marked at both
% ends; \prevdepth is reset so the line after it lays out as if it were not there.
\newcommand\ACfigtop[1]{\vbox to\z@{\hbox to\linewidth{\zsavepos{acfig-l-#1}\hfil\zsavepos{acfig-r-#1}}\vss}\ifvmode\prevdepth-\@m\p@\fi}
% Bottom: where the figure ends and its caption begins.
\newcommand\ACfigbot[1]{\par\zsavepos{acfig-b-#1}}
\makeatother
"""

FLOAT_ENVS = r"(?:figure\*?|acwidefigure\*?)"


def instrument(tex: str, counter: list[int]) -> str:
    """Put the two marks into every figure of one source file."""

    def float_env(m: re.Match) -> str:
        env, opt, body = m.group(1), m.group(2) or "", m.group(3)
        label = _label(body, counter)
        cap = re.search(r"\\caption\s*[\[{]", body)
        if not cap:
            return m.group(0)
        body = body[: cap.start()] + r"\ACfigbot{" + label + "}" + body[cap.start():]
        return r"\begin{" + env + "}" + opt + r"\ACfigtop{" + label + "}" + body + r"\end{" + env + "}"

    tex = re.sub(r"\\begin\{(" + FLOAT_ENVS + r")\}(\[[^\]]*\])?(.*?)\\end\{\1\}", float_env, tex, flags=re.S)

    # A figure outside a float -- the single-column opening panel is a
    # minipage with \captionof{figure}: the top mark goes inside the nearest
    # minipage that holds the caption. (Not a bare center: its first line is
    # horizontal, where a full-width mark would add a line to the layout.)
    out, pos = [], 0
    for m in re.finditer(r"\\captionof\s*\{figure\}", tex):
        if m.start() < pos:
            continue
        head = tex[pos: m.start()]
        opener = None
        for om in re.finditer(r"\\begin\{minipage\}(?:\[[^\]]*\])*\{[^{}]*\}", head):
            opener = om
        if not opener:
            continue
        label = _label(tex[m.start(): m.start() + 3000], counter)
        out.append(head[: opener.end()] + r"\ACfigtop{" + label + "}" + head[opener.end():] + r"\ACfigbot{" + label + "}")
        pos = m.start()
    out.append(tex[pos:])
    return "".join(out)


def _label(body: str, counter: list[int]) -> str:
    m = re.search(r"\\label\{(fig:[^}]*)\}", body)
    if m:
        return m.group(1)
    counter[0] += 1
    return f"auto{counter[0]}"


def positions(aux: str) -> dict[str, dict[str, int]]:
    """zref-savepos records from an .aux: mark -> posx, posy (sp), abspage."""
    found: dict[str, dict[str, int]] = {}
    for m in re.finditer(r"\\zref@newlabel\{(acfig-[lrb]-[^}]*)\}\{(.*)\}\s*$", aux, re.M):
        props = dict(re.findall(r"\\(posx|posy|abspage)\{(-?\d+)\}", m.group(2)))
        if {"posx", "posy", "abspage"} <= props.keys():
            found[m.group(1)] = {k: int(v) for k, v in props.items()}
    return found


def boxes(pos: dict[str, dict[str, int]]) -> dict[str, tuple[int, float, float, float, float]]:
    """label -> (page, x0, y_top, x1, y_bottom) in PDF points from the page's lower left."""
    out = {}
    for key, left in pos.items():
        if not key.startswith("acfig-l-"):
            continue
        label = key[len("acfig-l-"):]
        right, bottom = pos.get("acfig-r-" + label), pos.get("acfig-b-" + label)
        if not right or not bottom or bottom["abspage"] != left["abspage"]:
            continue
        x0, x1 = left["posx"] / SP_PER_BP, right["posx"] / SP_PER_BP
        top, bot = left["posy"] / SP_PER_BP, bottom["posy"] / SP_PER_BP
        if x1 - x0 > 5 and top - bot > 5:
            out[label] = (left["abspage"], x0, top, x1, bot)
    return out


def _page_height(pdf: Path, page: int) -> float:
    r = subprocess.run(["pdfinfo", "-f", str(page), "-l", str(page), str(pdf)], capture_output=True, text=True)
    m = re.search(r"Page\s+%d size:\s*([\d.]+) x ([\d.]+)" % page, r.stdout) or re.search(r"Page size:\s*([\d.]+) x ([\d.]+)", r.stdout)
    if not m:
        raise RuntimeError("pdfinfo could not read the page size")
    return float(m.group(2))


def crop(pdf: Path, box: tuple[int, float, float, float, float], out: Path) -> None:
    page, x0, top, x1, bot = box
    height = _page_height(pdf, page)
    px = lambda v: max(0, int(round(v * DPI / 72)))
    x, y = px(x0 - PAD_BP), px(height - top - PAD_BP)
    w, h = px(x1 - x0 + 2 * PAD_BP), px(top - bot + 2 * PAD_BP)
    stem = out.with_suffix("")
    r = subprocess.run(["pdftoppm", "-png", "-r", str(DPI), "-f", str(page), "-l", str(page),
                        "-x", str(x), "-y", str(y), "-W", str(w), "-H", str(h), "-singlefile",
                        str(pdf), str(stem)], capture_output=True, text=True)
    if r.returncode != 0 or not out.exists():
        raise RuntimeError(f"pdftoppm failed: {r.stderr.strip()[:200]}")


def extract(project: Path, out_dir: Path, labels: list[str]) -> dict[str, str]:
    """Compile a marked copy of project/paper and cut every figure out of it.
    label -> PNG name in out_dir, or "error: ..." when that figure could not be taken."""
    paper = project / "paper"
    result: dict[str, str] = {}
    missing = [t for t in ("pdftoppm", "pdfinfo") if not shutil.which(t)]
    if missing or not BUILD.exists() or not (paper / "main.tex").exists():
        why = f"missing {', '.join(missing)}" if missing else "no paper/main.tex or no build_paper.sh"
        return {label: f"error: {why}" for label in labels}
    work = Path(tempfile.mkdtemp(prefix="acfigs-"))
    try:
        copy = work / "paper"
        shutil.copytree(paper, copy, ignore=shutil.ignore_patterns("build", "*.pdf"))
        counter = [0]
        for tex in copy.rglob("*.tex"):
            src = tex.read_text(encoding="utf-8", errors="replace")
            marked = instrument(src, counter)
            if marked != src:
                tex.write_text(marked, encoding="utf-8")
        (copy / "acfigmarks.tex").write_text(MARKS_TEX, encoding="utf-8")
        main = copy / "main.tex"
        text = main.read_text(encoding="utf-8")
        if not re.search(r"^\\input\{preamble\}[ \t]*$", text, re.M):
            return {label: "error: main.tex has no \\input{preamble} line to hang the marks on" for label in labels}
        main.write_text(re.sub(r"^(\\input\{preamble\})[ \t]*$", r"\1\n\\input{acfigmarks}", text, count=1, flags=re.M), encoding="utf-8")
        build = subprocess.run(["bash", str(BUILD), "--final", "--paper-dir", str(copy), "--out", str(work / "out")],
                               capture_output=True, text=True, timeout=900)
        pdf = work / "out" / "paper.pdf"
        aux = copy / "build" / "main_final.aux"
        if build.returncode != 0 or not pdf.exists() or not aux.exists():
            tail = (build.stdout + build.stderr).strip().splitlines()[-3:]
            return {label: "error: the marked copy did not compile: " + " / ".join(tail)[:300] for label in labels}
        found = boxes(positions(aux.read_text(encoding="utf-8", errors="replace")))
        out_dir.mkdir(parents=True, exist_ok=True)
        for label in labels:
            if label not in found:
                result[label] = "error: no marks for this figure in the compiled copy"
                continue
            name = label.split(":")[-1] + ".png"
            try:
                crop(pdf, found[label], out_dir / name)
                result[label] = name
            except Exception as e:  # noqa: BLE001 -- reported, never silent
                result[label] = f"error: {e}"
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return result


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    project, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    labels = sys.argv[3:]
    if not labels:
        text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in (project / "paper").rglob("*.tex"))
        labels = sorted(set(re.findall(r"\\label\{(fig:[^}]*)\}", text)))
    res = extract(project, out, labels)
    print(json.dumps(res, indent=2))
    return 0 if all(not v.startswith("error") for v in res.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
