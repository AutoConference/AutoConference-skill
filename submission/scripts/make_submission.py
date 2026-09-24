#!/usr/bin/env python3
"""make_submission -- render a paper-writing LaTeX tree into the platform's shape.

This is the join named in `interfaces/submission-interface.md`, and until now it
was the one piece of that contract nobody had written. `check_submission_shape.py`
opens by saying it runs "after `paper-writing` has produced a manuscript and
`make_submission.py` has rendered it into the platform's shape" -- so the gate has
been waiting on a file that did not exist, and the author half of the pipeline has
never produced a submission.

    make_submission.py <paper-project-dir> [--out DIR] [--reproducibility FILE]

`<paper-project-dir>` is what `gate.sh --project` takes: the directory holding
`paper.json` and `paper/`. The output directory gets `submission.json` and
`figures/`, which is exactly what `check_submission_shape.py` then reads.

WHAT THIS IS NOT. It is not a general LaTeX-to-markdown converter, and it must
not become one. It converts the tree that `paper-writing` emits, whose shape is
fixed by `template/` and checked by `check_paper_structure.py`. Anything it does
not recognise it reports, rather than guessing -- a silent drop here is a claim
deleted from a paper.

THE THING THAT SHAPES EVERY DECISION, from the interface contract: reviewers are
agents calling `GET /api/v1/submissions/:id`, and they receive `body_md` as
SOURCE, not as rendered output. They almost certainly cannot open an attachment.
So a number that reaches them only through a figure did not reach them. Tables
are therefore load-bearing and are converted; figures are the human record.

Read `interfaces/submission-interface.md` before changing any translation. Each
one is there for a reason recorded in that file, verified against the platform's
own renderer (`src/lib/markdown.ts`) rather than assumed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------- limits ----
# From the interface contract, which took them from
# src/app/api/v1/submissions/route.ts. Characters, not bytes.
LIMITS = {
    "title": (8, 250),
    "abstract": (100, 5000),
    "body_md": (500, 100_000),
    "reproducibility": (50, 5000),
}
MAX_KEYWORDS = 10


def warn(msg: str) -> None:
    print(f"  ! {msg}", file=sys.stderr)


# ---------------------------------------------------------------- macros ----
class Macros:
    r"""`\newcommand` expansion, including the argument-taking ones.

    The paper's own macros carry its nouns -- \methodname, \armbaseline,
    \metricname -- so a body that still contains them is a body with holes in
    the places a reader most needs a word. S03 alone uses \armbaseline 31 times.

    \xspace is dropped rather than implemented: it exists to fix TeX spacing
    after a control sequence, and markdown has no such problem.
    """

    DEF = re.compile(
        r"\\(?:new|renew|provide)command\*?\s*"
        r"\{\\([A-Za-z@]+)\}\s*(?:\[(\d+)\])?\s*(?:\[[^\]]*\])?\s*",
    )

    def __init__(self) -> None:
        self.table: dict[str, tuple[int, str]] = {}
        # `\newif\ifDesignTwoColumn` plus a later `\DesignTwoColumnfalse` is how
        # the design family switches layout. The switches are set in design.tex,
        # so their values are knowable and the branch is decidable -- guessing
        # would silently publish the wrong half of the paper.
        self.flags: dict[str, bool] = {}

    def load(self, path: Path) -> None:
        if not path.exists():
            return
        text = strip_comments(path.read_text(encoding="utf-8"))
        for m in self.DEF.finditer(text):
            name, argc = m.group(1), int(m.group(2) or 0)
            body = read_group(text, m.end())
            if body is not None:
                # Strip \xspace HERE rather than at use. A body ending in
                # `\xspace` that is used before a plural `s` expands to
                # `GateSpec\xspace` + `s` = `\xspaces`, which is a different
                # control sequence and survives every later pass. Four of the
                # six papers carried one.
                self.table[name] = (argc, re.sub(r"\\xspace\b", "", body))
        for m in re.finditer(r"\\newif\s*\\if([A-Za-z@]+)", text):
            self.flags.setdefault(m.group(1), False)   # TeX defaults a new if to false
        for m in re.finditer(r"\\([A-Za-z@]+)(true|false)\b", text):
            if m.group(1) in self.flags:
                self.flags[m.group(1)] = m.group(2) == "true"

    def expand(self, text: str, depth: int = 0) -> str:
        """Expand until nothing changes. Depth-capped: macros here are allowed to
        refer to each other (\\armbaseline -> \\armspecdec) and a cycle would
        otherwise hang the build rather than fail it."""
        if depth > 12:
            return text
        out = []
        i = 0
        changed = False
        while i < len(text):
            ch = text[i]
            if ch != "\\":
                out.append(ch)
                i += 1
                continue
            m = re.match(r"\\([A-Za-z@]+)", text[i:])
            if not m:
                out.append(ch)
                i += 1
                continue
            name = m.group(1)
            if name == "xspace":
                i += m.end()
                continue
            if name not in self.table:
                out.append(text[i : i + m.end()])
                i += m.end()
                continue
            argc, body = self.table[name]
            j = i + m.end()
            args = []
            ok = True
            for _ in range(argc):
                j = skip_ws(text, j)
                arg = read_group(text, j)
                if arg is None:
                    ok = False
                    break
                j = end_of_group(text, j)
                args.append(arg)
            if not ok:
                out.append(text[i : i + m.end()])
                i += m.end()
                continue
            expanded = body
            for k, arg in enumerate(args, 1):
                expanded = expanded.replace(f"#{k}", arg)
            out.append(expanded)
            # A macro followed by `\ ` or `{}` (the TeX idiom for keeping the
            # space) leaves that marker behind; eat it so we do not emit "GateSpec\ ".
            rest = text[j:]
            if rest.startswith("\\ "):
                j += 2
                out.append(" ")
            elif rest.startswith("{}"):
                j += 2
            i = j
            changed = True
        result = "".join(out)
        return self.expand(result, depth + 1) if changed else result


def skip_ws(s: str, i: int) -> int:
    while i < len(s) and s[i] in " \t\n":
        i += 1
    return i


def read_group(s: str, i: int) -> str | None:
    """The contents of the balanced `{...}` starting at or after `i`."""
    i = skip_ws(s, i)
    if i >= len(s) or s[i] != "{":
        return None
    depth, j = 0, i
    while j < len(s):
        if s[j] == "\\":
            j += 2
            continue
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0:
                return s[i + 1 : j]
        j += 1
    return None


def end_of_group(s: str, i: int) -> int:
    i = skip_ws(s, i)
    if i >= len(s) or s[i] != "{":
        return i
    depth, j = 0, i
    while j < len(s):
        if s[j] == "\\":
            j += 2
            continue
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return j


def strip_comments(text: str) -> str:
    r"""Drop `%` comments, keeping `\%`. Done line by line because a comment runs
    to end of line and TeX also eats the newline, but keeping the newline is
    right for markdown."""
    out = []
    for line in text.split("\n"):
        j, res = 0, []
        while j < len(line):
            if line[j] == "\\" and j + 1 < len(line):
                res.append(line[j : j + 2])
                j += 2
                continue
            if line[j] == "%":
                break
            res.append(line[j])
            j += 1
        out.append("".join(res))
    return "\n".join(out)


# ------------------------------------------------------------ references ----
BIB_ENTRY = re.compile(r"@(\w+)\s*\{\s*([^,]+),", re.S)


def parse_bib(path: Path) -> dict[str, str]:
    r"""key -> "Author et al., 2023".

    The shape gate counts a citation only if it matches one of three patterns,
    and `CITE_AUTHORYEAR` is `\(([A-Z][A-Za-z\-]+(?: et al\.?)?),? (?:19|20)\d{2}[a-z]?\)`.
    So `[gatespec2024]` is not a citation to it and `(Chen et al., 2024)` is.
    Emitting the key would silently cost the paper its related work.
    """
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for m in BIB_ENTRY.finditer(text):
        key = m.group(2).strip()
        body = text[m.end() : text.find("\n@", m.end()) if "\n@" in text[m.end():] else len(text)]
        year = ""
        ym = re.search(r"year\s*=\s*[{\"]?\s*((?:19|20)\d{2})", body, re.I)
        if ym:
            year = ym.group(1)
        author = ""
        am = re.search(r"author\s*=\s*", body, re.I)
        if am:
            raw = read_group(body, am.end())
            if raw is None:
                q = re.match(r'\s*"([^"]*)"', body[am.end():])
                raw = q.group(1) if q else ""
            authors = [a.strip() for a in re.split(r"\s+and\s+", raw) if a.strip()]
            if authors:
                first = authors[0]
                surname = first.split(",")[0].strip() if "," in first else first.split()[-1]
                surname = re.sub(r"[{}\\]", "", surname).strip()
                # The gate's pattern wants a leading capital and no spaces inside
                # the surname, so a van-type particle has to collapse.
                surname = surname.replace(" ", "-")
                if surname:
                    author = surname + (" et al." if len(authors) > 1 else "")
        if author and year:
            out[key] = f"{author}, {year}"
        elif author:
            out[key] = author
    return out


# ---------------------------------------------------------------- tables ----
def cell_to_md(cell: str, macros: Macros) -> str:
    r"""One table cell.

    Cells carry math -- a `$\Delta$` row label is the commonest thing in these
    tables -- and `inline_to_md` alone would strip the backslash command and
    leave a bare `\Delta` in the reviewer's source. So math is protected here
    too, exactly as it is in prose, rather than assumed absent.
    """
    stash: list[str] = []

    def keep(m: re.Match) -> str:
        stash.append("$" + macros.expand(m.group(1)).strip() + "$")
        return f"\x00C{len(stash) - 1}\x00"

    protected = re.sub(r"(?<!\\)\$([^$]+)(?<!\\)\$", keep, cell)
    out = inline_to_md(protected, macros)
    out = re.sub(r"\x00C(\d+)\x00", lambda m: stash[int(m.group(1))], out)
    # A pipe inside a cell would split the GFM row.
    return out.replace("|", "\\|")


def tabular_to_gfm(block: str, macros: Macros) -> str | None:
    r"""One `tabular` body -> a GFM pipe table.

    Family tinting is dropped, which `table-grammar.md` anticipates: grouping has
    to be carried by row order and a rule as well, so a colour-only grouping was
    already a defect on the LaTeX side.
    """
    # Every tabular the design family emits: plain tabular, the width-taking
    # ones (tabular*, tabularx, tabulary: a width, then the column spec), and
    # nicematrix's NiceTabular, whose options follow the spec. The family-tint
    # main table is a NiceTabular; accepting only `tabular` dropped it whole.
    m = re.search(r"\\begin\{(tabular\*?|tabularx|tabulary|NiceTabular\*?)\}\s*(?:\[[^\]]*\])?\s*", block)
    if not m:
        return None
    env, j = m.group(1), m.end()
    if env in ("tabular*", "tabularx", "tabulary", "NiceTabular*"):
        if read_group(block, j) is None:
            return None
        j = end_of_group(block, j)
        j += len(block[j:]) - len(block[j:].lstrip())
    spec = read_group(block, j)
    if spec is None:
        return None
    body = block[end_of_group(block, j) :]
    opt = re.match(r"\s*\[[^\]]*\]", body)          # NiceTabular's [options]
    if opt and env.startswith("NiceTabular"):
        body = body[opt.end():]
    end = "\\end{" + env + "}"
    body = body[: body.find(end)] if end in body else body

    flat = re.sub(r"\{[^{}]*\}", "", re.sub(r"\{[^{}]*\}", "", spec))   # two levels: >{\columncolor{x}}
    ncol = len(re.findall(r"[lcrpmbXS]", flat))
    aligns = [c for c in flat if c in "lcrXS"]
    aligns = ["l" if c == "X" else "c" if c == "S" else c for c in aligns]

    rows: list[list[str]] = []
    rules: set[int] = set()
    for raw in re.split(r"\\\\", body):
        if r"\midrule" in raw or r"\hline" in raw:
            rules.add(len(rows))
        cleaned = re.sub(r"\\(top|mid|bottom|c?)rule(\[[^\]]*\])?(\{[^}]*\})*", "", raw)
        cleaned = re.sub(r"\\rowcolor\s*(\[[^\]]*\])?\{[^}]*\}", "", cleaned)
        cleaned = re.sub(r"\\(Hline|hline|CodeBefore|Body)\b", "", cleaned)
        cleaned = re.sub(r"\\cmidrule(\([^)]*\))?\s*\{[^}]*\}", "", cleaned)
        if not cleaned.strip():
            continue
        # A GFM row is one line: a line break inside a cell ends the table.
        cells = [re.sub(r"\s*\n\s*", " ", cell_to_md(c.strip(), macros)).strip()
                 for c in split_cells(cleaned)]
        if any(c for c in cells):
            rows.append(cells)
    if not rows:
        return None

    width = max(ncol, max(len(r) for r in rows))
    rows = [r + [""] * (width - len(r)) for r in rows]
    aligns = (aligns + ["l"] * width)[:width]
    sep = {"l": ":---", "c": ":---:", "r": "---:"}

    head, rest = rows[0], rows[1:]
    out = ["| " + " | ".join(head) + " |",
           "| " + " | ".join(sep[a] for a in aligns) + " |"]
    for r in rest:
        out.append("| " + " | ".join(r) + " |")
    return "\n".join(out)


def split_cells(row: str) -> list[str]:
    r"""Split on `&`, honouring `\&` and brace groups."""
    cells, buf, depth, i = [], [], 0, 0
    while i < len(row):
        ch = row[i]
        if ch == "\\" and i + 1 < len(row):
            buf.append(row[i : i + 2])
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        if ch == "&" and depth == 0:
            cells.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    cells.append("".join(buf))
    return cells


# ------------------------------------------------------- inline markup ------
SIMPLE_WRAP = [
    (r"\\textbf", "**", "**"),
    (r"\\textit", "*", "*"),
    (r"\\emph", "*", "*"),
    (r"\\texttt", "`", "`"),
    # Markdown has no underline and the renderer's allowlist has no `u`. In the
    # table grammar `\second{}` IS an underline and means "second best", so
    # dropping the markup would delete a ranking a reviewer is meant to read.
    # Italic is the one surviving second level of emphasis under the bold that
    # `\best{}` already becomes.
    (r"\\underline", "*", "*"),
    (r"\\textsc", "", ""),
    (r"\\textrm", "", ""),
    (r"\\textnormal", "", ""),
    # Affiliation markers. There is no portable markdown superscript, and `^1`
    # renders as a literal caret, so the digit stands alone.
    (r"\\textsuperscript", "", ""),
    (r"\\textsubscript", "", ""),
    (r"\\mbox", "", ""),
    (r"\\text", "", ""),
]

ESCAPES = {
    r"\textdegree": "\u00b0", r"\par": "\n\n",
    r"\%": "%", r"\&": "&", r"\_": "_", r"\#": "#", r"\$": "$",
    r"\{": "{", r"\}": "}", r"\,": " ", r"\;": " ", r"\:": " ",
    r"~": " ", r"\ ": " ",
}


def drop_first_arg(text: str, cmd: str, keep: int = 2) -> str:
    r"""`\textcolor{blue}{word}` -> `word`, `\multicolumn{2}{c}{head}` -> `head`.

    Colour and column-span are typesetting, and the platform's renderer has
    neither. What must survive is the LAST argument, which is the text.
    """
    pat = re.compile(r"\\" + cmd + r"\s*\*?\s*(?=\{)")
    while True:
        m = pat.search(text)
        if not m:
            return text
        j, last = m.end(), None
        for _ in range(keep):
            g = read_group(text, j)
            if g is None:
                break
            last = g
            j = end_of_group(text, j)
        text = text[: m.start()] + (last or "") + text[j:]


DRAWING_ENVS = ("tikzpicture", "axis", "groupplot", "semilogyaxis", "semilogxaxis",
                "loglogaxis", "polaraxis", "pgfpicture", "scope", "pgfonlayer",
                "pgfplotsinterruptdatabb")


def drop_drawings(text: str) -> str:
    r"""Remove the picture code itself.

    A pgfplots `axis` block is the FIGURE, and the figure reaches the platform
    as a PNG attachment. Left in `body_md` it is neither a picture nor prose --
    just `\addplot table[x=cond,y=arm3]` sitting in the middle of a paragraph
    for an agent reviewer to read. The caption and the image line stay; only the
    drawing instructions go.
    """
    for env in DRAWING_ENVS:
        pat = re.compile(r"\\begin\{" + env + r"\}", re.S)
        while True:
            m = pat.search(text)
            if not m:
                break
            # Nesting is normal here (a scope inside a tikzpicture), so walk to
            # the matching \end rather than trusting the first one.
            depth, i = 1, m.end()
            token = re.compile(r"\\(begin|end)\{" + env + r"\}")
            while depth and i < len(text):
                t = token.search(text, i)
                if not t:
                    i = len(text)
                    break
                depth += 1 if t.group(1) == "begin" else -1
                i = t.end()
            text = text[: m.start()] + text[i:]
    return text


def resolve_ifs(text: str, flags: dict[str, bool]) -> str:
    r"""`\ifFoo A \else B \fi` -> A or B, by the flag's real value."""
    pat = re.compile(r"\\if([A-Za-z@]+)\b")
    guard, at = 0, 0
    while guard < 500:
        guard += 1
        m = pat.search(text, at)
        if not m:
            return text
        if m.group(1) not in flags:
            # An \if we cannot decide -- \ifdim, \ifnum, \ifx, \ifcsname. ADVANCE
            # past it. Restarting the search from zero instead found the same
            # undecidable \if for ever, so every decidable branch after the first
            # one was never reached and the design's switched-off radar panel
            # stayed in the paper.
            at = m.end()
            continue
        name = m.group(1)
        depth, i = 1, m.end()
        else_at = -1
        tok = re.compile(r"\\(if[A-Za-z@]*|else|fi)\b")
        while depth and i < len(text):
            t = tok.search(text, i)
            if not t:
                break
            word = t.group(1)
            if word.startswith("if"):
                depth += 1
            elif word == "fi":
                depth -= 1
                if depth == 0:
                    then = text[m.end() : (else_at if else_at > 0 else t.start())]
                    other = text[else_at + 5 : t.start()] if else_at > 0 else ""
                    text = text[: m.start()] + (then if flags[name] else other) + text[t.end():]
                    at = m.start()
                    break
            elif word == "else" and depth == 1:
                else_at = t.start()
            i = t.end()
        else:
            return text
    return text


def wrap_manual_floats(text: str) -> str:
    r"""A `center`/`minipage` block carrying a `\caption` IS a float.

    The design family lays the opening figure out by hand --
    `\begin{center}\begin{minipage}{0.99\linewidth} ... \caption{...} ... ` --
    so there is no `figure` environment for the float pass to find, and the
    caption and its label fell through to the prose as raw LaTeX. Renaming the
    wrapper is enough: everything downstream then treats it like any other
    figure, including numbering it so `\Cref{fig:opening}` resolves.

    A wrapper with no caption is just layout and is unwrapped instead.
    """
    for env in ("center", "minipage", "adjustbox", "adjustwidth"):
        pat = re.compile(r"\\begin\{" + env + r"\}\s*(\[[^\]]*\])?\s*(\{[^{}]*\})?")
        while True:
            m = pat.search(text)
            if not m:
                break
            depth, i = 1, m.end()
            tok = re.compile(r"\\(begin|end)\{" + env + r"\}")
            end_start = end_stop = len(text)
            while depth and i < len(text):
                t = tok.search(text, i)
                if not t:
                    break
                depth += 1 if t.group(1) == "begin" else -1
                if depth == 0:
                    end_start, end_stop = t.start(), t.end()
                i = t.end()
            inner = text[m.end() : end_start]
            # Only the OUTERMOST wrapper becomes the float. The opening block is
            # a `center` holding a `minipage`, and wrapping both produced nested
            # figures -- whereupon the float pass's non-greedy match closed the
            # outer one on the inner one's \end and left a stray \end{figure} in
            # the prose, three lines above the introduction.
            before = text[: m.start()]
            inside_float = (before.count(r"\begin{figure}") - before.count(r"\end{figure}")
                            + before.count(r"\begin{table}") - before.count(r"\end{table}")) > 0
            if r"\caption" in inner and not inside_float:
                body = "\\begin{figure}" + inner + "\\end{figure}"
            else:
                body = inner
            text = text[: m.start()] + body + text[end_stop:]
    return text


def if_file_exists(text: str, base: Path) -> str:
    r"""`\IfFileExists{f}{then}{else}` -> whichever branch TeX would have taken.

    It guards a figure here, so guessing wrong drops a figure or emits one whose
    data file is not there. The file is on disk, so this is decidable rather
    than a heuristic."""
    pat = re.compile(r"\\IfFileExists\s*(?=\{)")
    while True:
        m = pat.search(text)
        if not m:
            return text
        j = m.end()
        parts = []
        for _ in range(3):
            g = read_group(text, j)
            if g is None:
                break
            parts.append(g)
            j = end_of_group(text, j)
        if len(parts) < 2:
            return text[: m.start()] + text[j:]
        chosen = parts[1] if (base / parts[0]).exists() else (parts[2] if len(parts) > 2 else "")
        text = text[: m.start()] + chosen + text[j:]


def inline_to_md(text: str, macros: Macros) -> str:
    """Inline markup only. Math is protected by the caller before this runs."""
    text = macros.expand(text)
    text = drop_first_arg(text, "textcolor", 2)
    text = drop_first_arg(text, "multicolumn", 3)
    # \cellcolor[model]{colour} takes one argument and the cell's text follows
    # it; read as two, the colour name was left in the cell. \colorbox and
    # \fcolorbox wrap their text: the rank-colors table and the default-delta
    # ablation shade cells with them, and the renderer has no colour anyway.
    text = re.sub(r"\\(?:cellcolor|rowcolor)\s*(?:\[[^\]]*\])?\s*\{[^{}]*\}", "", text)
    text = drop_first_arg(text, "fcolorbox", 3)
    text = drop_first_arg(text, "colorbox", 2)
    # Struts and invisible spacers align a typeset table and are nothing on a
    # rendered one: \phantom{0}, \hphantom, \vphantom, \rule[raise]{w}{h}.
    text = re.sub(r"\\[hv]?phantom\s*\{[^{}]*\}", "", text)
    text = re.sub(r"\\rule\s*(?:\[[^\]]*\])?\s*\{[^{}]*\}\s*\{[^{}]*\}", "", text)
    for cmd, open_s, close_s in SIMPLE_WRAP:
        pat = re.compile(cmd + r"\s*\{")
        while True:
            m = pat.search(text)
            if not m:
                break
            inner = read_group(text, m.end() - 1)
            if inner is None:
                text = text[: m.start()] + text[m.end():]
                continue
            end = end_of_group(text, m.end() - 1)
            text = text[: m.start()] + open_s + inner + close_s + text[end:]
    text = re.sub(r"\\label\s*\{[^}]*\}", "", text)
    text = re.sub(r"\\(vspace|hspace|noindent|centering|small|footnotesize|normalsize|bf|it)\b\*?(\{[^}]*\})?", "", text)
    # Counter machinery, which arrives by expanding the paper's own list macros
    # (\contribution is `\stepcounter{accontrib}\item[\textbf{(\arabic{...})}]`).
    # Markdown numbers its own lists, so the counters have nothing to drive.
    text = re.sub(r"\\(stepcounter|refstepcounter|setcounter|addtocounter)\s*\{[^}]*\}(\{[^}]*\})?", "", text)
    text = re.sub(r"\\(arabic|roman|Roman|alph|Alph|value)\s*\{[^}]*\}", "", text)
    # Booktabs rules and float furniture that leak out of a macro body rather
    # than out of a tabular the table path already handled.
    text = re.sub(r"\\(top|mid|bottom)rule\b(\[[^\]]*\])?", "", text)
    text = re.sub(r"\\(cmidrule|addlinespace|morecmidrules)\b(\([^)]*\))?(\{[^}]*\})?", "", text)
    # \ding{51}/{55} are the zapf check and cross, and they carry meaning in a
    # results cell -- dropping them would delete the verdict rather than its
    # styling.
    text = re.sub(r"\\ding\s*\{\s*51\s*\}", "\u2713", text)
    text = re.sub(r"\\ding\s*\{\s*55\s*\}", "\u2717", text)
    text = re.sub(r"\\ding\s*\{[^}]*\}", "", text)
    text = re.sub(r"\\(checkmark|cmark)\b", "\u2713", text)
    text = re.sub(r"\\xmark\b", "\u2717", text)
    for a, b in ESCAPES.items():
        text = text.replace(a, b)
    text = text.replace("---", "\u2014").replace("--", "\u2013")
    text = re.sub(r"``|''", '"', text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


# ------------------------------------------------------- the converter ------
class Converter:
    def __init__(self, project: Path, macros: Macros, bib: dict[str, str]) -> None:
        self.project = project
        self.paper = project / "paper"
        self.macros = macros
        self.bib = bib
        self.labels: dict[str, str] = {}
        self.figures: list[tuple[str, str]] = []   # (label, caption)
        self.missing_cites: set[str] = set()
        self.unknown_cmds: set[str] = set()
        self._math: list[str] = []

    # -- pass 1: number every float and section so \Cref can be resolved -----
    def index(self, body: str) -> None:
        """The platform emits no heading ids, so a reference has to become the
        words "Table 1". That means numbering has to happen before conversion,
        in order of appearance -- which is why this is a separate pass."""
        counts = {"table": 0, "figure": 0, "section": 0, "equation": 0}
        kind_of = {"tab": "table", "fig": "figure", "sec": "section", "eq": "equation",
                   "app": "section", "alg": "algorithm"}
        for m in re.finditer(
            r"\\(section|subsection|subsubsection)\s*\*?\s*\{|"
            r"\\begin\{(table|figure|equation|acwidetable|acwidefigure)\*?\}|"
            r"\\label\s*\{([^}]*)\}",
            body,
        ):
            if m.group(1) == "section":
                counts["section"] += 1
            elif m.group(2):
                g = m.group(2).replace("acwide", "")
                if g in counts:
                    counts[g] += 1
            elif m.group(3):
                label = m.group(3)
                prefix = label.split(":")[0] if ":" in label else ""
                kind = kind_of.get(prefix)
                if kind and kind in counts:
                    self.labels[label] = f"{kind.capitalize()} {counts[kind]}"
                elif kind == "algorithm":
                    self.labels[label] = "the algorithm"

    # -- math protection ----------------------------------------------------
    def _stash(self, s: str) -> str:
        self._math.append(s)
        return f"\x00M{len(self._math) - 1}\x00"

    def protect_math(self, text: str) -> str:
        r"""Pull every math span out before any markup runs, so `\textbf` inside a
        formula is not turned into `**` and `_` in a subscript is not escaped.

        Display forms all become `$$...$$`: the contract says all four render, but
        `$$` is what the shape check counts, so emitting `\[` would pass the eye
        and fail the gate."""
        def disp(m: re.Match) -> str:
            inner = m.group(2) if m.lastindex and m.lastindex >= 2 else m.group(1)
            inner = re.sub(r"\\label\s*\{[^}]*\}", "", inner).strip()
            inner = self.macros.expand(inner)
            return self._stash("\n\n$$\n" + inner.strip() + "\n$$\n\n")

        text = re.sub(r"\\begin\{(equation|align|gather|multline)\*?\}(.*?)\\end\{\1\*?\}",
                      disp, text, flags=re.S)
        text = re.sub(r"\\\[(.*?)\\\]", disp, text, flags=re.S)
        text = re.sub(r"\\\((.*?)\\\)",
                      lambda m: self._stash("$" + self.macros.expand(m.group(1)).strip() + "$"),
                      text, flags=re.S)
        # Inline `$...$`, skipping `\$`. Must not span a blank line -- the
        # contract says the renderer breaks on that, so a run that does is left
        # alone and will be reported by the stray-dollar check rather than
        # silently mangled here.
        def inline(m: re.Match) -> str:
            inner = m.group(1)
            if "\n\n" in inner:
                return m.group(0)
            # Put the run on one line. TeX ignores line breaks inside math, so
            # this is lossless -- and the LaTeX source wraps, which left 113 of
            # this paper's inline spans straddling a newline. The shape gate
            # reads two of those as unpaired `$`, and an unpaired `$` makes the
            # renderer swallow a span or throw.
            one = re.sub(r"\s+", " ", self.macros.expand(inner)).strip()
            return self._stash("$" + one + "$")

        return re.sub(r"(?<!\\)\$(.+?)(?<!\\)\$", inline, text, flags=re.S)

    def restore_math(self, text: str) -> str:
        r"""Restore to a fixed point, because a stashed value can contain a stash
        marker of its own.

        A table is stashed whole (to keep the body-wide inline pass from turning
        its `|:---|` separator into an em dash), and the cells inside it were
        already stashed individually by the body-wide `protect_math` before the
        float pass ran. A single `re.sub` swaps the outer marker for content that
        still carries the inner one — which is how the delta row's `$\Delta$`
        label reached a submitted paper as the literal text `\x00M89\x00`.
        """
        for _ in range(8):
            out = re.sub(r"\x00M(\d+)\x00", lambda m: self._math[int(m.group(1))], text)
            if out == text:
                return out
            text = out
        return text

    # -- references and citations -------------------------------------------
    def refs(self, text: str) -> str:
        def one(m: re.Match) -> str:
            cmd, keys = m.group(1), [k.strip() for k in m.group(2).split(",")]
            names = [self.labels.get(k, "") for k in keys]
            if not any(names):
                # A dangling \ref is a hole in the paper, not a cosmetic issue.
                for k in keys:
                    self.unknown_cmds.add(f"{cmd}{{{k}}}")
                return "the " + ("table" if keys[0].startswith("tab") else
                                 "figure" if keys[0].startswith("fig") else "section")
            joined = names[0] if len(names) == 1 else ", ".join(n for n in names if n)
            return joined if cmd in ("Cref", "Autoref") else joined[0].lower() + joined[1:]

        return re.sub(r"\\(Cref|cref|autoref|Autoref|ref)\s*\{([^}]*)\}", one, text)

    def cites(self, text: str) -> str:
        r"""`\citep{a,b}` -> `(Author et al., 2023; Other, 2024)`.

        Parenthesised author-year is the form the shape gate recognises, so this
        is not a style choice -- emitting the bib key would leave the paper
        reading as though it cited nothing.

        The whole natbib family is handled, with its starred forms and its
        optional notes (`\citep[e.g.,][p.~3]{a}`), and biblatex's
        parencite/textcite/autocite: a writer reaches for `\citealp` inside
        its own parentheses as readily as for `\citep`, and one unknown command
        used to fail the whole render."""
        def split(r: str):
            return r.rsplit(", ", 1) if ", " in r else (r, "")

        def one(m: re.Match) -> str:
            cmd = m.group(1).lower()
            opts = [o[1:-1].strip() for o in (m.group(2), m.group(3)) if o]
            pre, post = (opts[0], opts[1]) if len(opts) == 2 else ("", opts[0] if opts else "")
            keys = [k.strip() for k in m.group(4).split(",")]
            resolved = []
            for k in keys:
                if k in self.bib:
                    resolved.append(self.bib[k])
                else:
                    self.missing_cites.add(k)
            if not resolved:
                return ""
            if cmd in ("citet", "textcite"):
                # Textual: "Chen et al. (2024)".
                out = []
                for r in resolved:
                    who, yr = split(r)
                    out.append(f"{who} ({yr})" if yr else who)
                return "; ".join(out)
            if cmd == "citeauthor":
                return "; ".join(split(r)[0] for r in resolved)
            if cmd == "citeyear":
                return "; ".join(split(r)[1] or split(r)[0] for r in resolved)
            if cmd == "citeyearpar":
                return "(" + "; ".join(split(r)[1] or split(r)[0] for r in resolved) + ")"
            if cmd == "citealt":
                return "; ".join(" ".join(x for x in split(r) if x) for r in resolved)
            inner = "; ".join(resolved)
            if pre:
                inner = f"{pre} {inner}"
            if post:
                inner = f"{inner}, {post}"
            if cmd == "citealp":
                return inner
            return "(" + inner + ")"

        return re.sub(
            r"\\((?:[cC]ite(?:p|t|alp|alt|author|year|yearpar|num)?)|parencite|textcite|autocite"
            r"|Parencite|Textcite|Autocite)\*?\s*(\[[^\]]*\])?\s*(\[[^\]]*\])?\s*\{([^}]*)\}",
            one, text)

    # -- environments -------------------------------------------------------
    def environments(self, text: str) -> str:
        text = self.floats(text)
        # `contributionlist` is one of paper-writing's own list environments
        # (blocks/contributions.tex). Its items arrive via \contribution, which
        # expands to an \item, so it converts like any other bullet list -- but
        # only if it is named here, and an unnamed list env leaves a raw \begin
        # sitting in the prose.
        text = re.sub(r"\\begin\{(itemize|compactitem|contributionlist|acbullets)\}(.*?)\\end\{\1\}",
                      lambda m: self.items(m.group(2), "- "), text, flags=re.S)
        text = re.sub(r"\\begin\{(enumerate|compactenum|acnumbered)\}(.*?)\\end\{\1\}",
                      lambda m: self.items(m.group(2), "1. "), text, flags=re.S)
        text = re.sub(r"\\begin\{(abstract|quote|quotation)\}(.*?)\\end\{\1\}",
                      lambda m: m.group(2), text, flags=re.S)
        return text

    def items(self, body: str, bullet: str) -> str:
        out = []
        for chunk in re.split(r"\\item\b", body):
            # \item[(1)] -- the optional marker is typographic; the bullet
            # replaces it, and leaving it produces "- [(1)] text".
            chunk = re.sub(r"^\s*\[[^\]]*\]", "", chunk).strip()
            if chunk:
                out.append(bullet + re.sub(r"\s*\n\s*", " ", chunk))
        return "\n\n" + "\n".join(out) + "\n\n"

    def floats(self, text: str) -> str:
        r"""`table` -> its GFM body; `figure` -> an image line plus the caption as
        a paragraph.

        `figure` and `figcaption` are not on the renderer's allowlist, so a
        caption is alt text plus a following paragraph and nothing else."""
        def one(m: re.Match) -> str:
            env, body = m.group(1), m.group(2)
            cap = ""
            cm = re.search(r"\\caption\s*(?:\[[^\]]*\])?\s*\{", body)
            if cm:
                raw = read_group(body, cm.end() - 1)
                if raw:
                    cap = raw
            label = ""
            lm = re.search(r"\\label\s*\{([^}]*)\}", body)
            if lm:
                label = lm.group(1)
            number = self.labels.get(label, "")

            if "table" in env:
                gfm = tabular_to_gfm(body, self.macros)
                if gfm is None:
                    self.unknown_cmds.add(f"table without tabular ({label or 'unlabelled'})")
                    return ""
                head = f"**{number}.** " if number else ""
                # Stash the built table the way math is stashed. The body-wide
                # inline pass turns `---` into an em dash, which is right in
                # prose and fatal here: it rewrote every separator row as
                # `| :— | :—: |`, and a GFM table without a separator row is not
                # a table at all. Every one of this paper's tables was silently
                # destroyed that way, while still looking plausible in the JSON.
                return "\n\n" + head + self.finish_inline(cap) + "\n\n" + self._stash(gfm) + "\n\n"

            # figure
            self.figures.append((label or f"figure{len(self.figures) + 1}", cap))
            fname = (label.split(":")[-1] if label else f"figure{len(self.figures)}") + ".png"
            alt = self.finish_inline(cap).replace("\n", " ")
            head = f"**{number}.** " if number else ""
            # The url is a placeholder on purpose: insert_figures.py replaces it
            # with the real attachment url, which only exists after the upload.
            return ("\n\n![" + alt[:180] + "](figures/" + fname + ")\n\n"
                    + head + alt + "\n\n")

        return re.sub(
            r"\\begin\{(table|figure|acwidetable|acwidefigure)\*?\}(.*?)\\end\{\1\*?\}",
            one, text, flags=re.S)

    def finish_inline(self, text: str) -> str:
        t = self.protect_math(text)
        t = self.cites(t)
        t = self.refs(t)
        t = inline_to_md(t, self.macros)
        return self.restore_math(t)

    # -- inputs -------------------------------------------------------------
    def resolve_inputs(self, text: str, depth: int = 0) -> str:
        if depth > 6:
            return text

        def one(m: re.Match) -> str:
            rel = m.group(1).strip()
            for cand in (self.paper / rel, self.paper / (rel + ".tex")):
                if cand.exists():
                    # Decide this file's OWN conditionals before descending into
                    # it. This recursion inlines a whole subtree in one call, so
                    # without it the caller's resolve_ifs never gets a look:
                    # blocks/opening_panel.tex hides \input{data/opening-radar-series}
                    # inside \ifOPradar, the design switches that off, and the
                    # file is deliberately never generated -- so the descent
                    # reported a missing file the paper had not asked for.
                    inner = resolve_ifs(strip_comments(cand.read_text(encoding="utf-8")),
                                        self.macros.flags)
                    inner = if_file_exists(inner, self.paper)
                    return "\n" + self.resolve_inputs(inner, depth + 1) + "\n"
            self.unknown_cmds.add(f"\\input{{{rel}}} (not found)")
            return ""

        return re.sub(r"\\(?:input|include)\s*\{([^}]*)\}", one, text)

    # -- the whole body -----------------------------------------------------
    def document_body(self) -> str:
        r"""`main.tex` between `\maketitle` and `\end{document}`, minus the
        abstract and the bibliography.

        Driven by main.tex rather than by a glob of `sections/*.tex`, because
        the glob was wrong twice over:

        - **Order.** A filename sort is not the paper's order. It happened to
          agree, which is worse than disagreeing.
        - **Anything main.tex does itself is invisible to a glob**, and the
          design family has main.tex do real work. The opening figure lives
          there so it can span the full width above the first column. And
          `\AfterConclusionBlocks` — the macro that emits the Limitations
          content for the `own-section` placement — is invoked there, after
          the conclusion. Globbing meant S26's entire Limitations section was
          correct in the PDF and **absent from the markdown the reviewers
          actually read**, with nothing reporting it.

        The abstract is cut because it is its own field on the platform and
        would otherwise print twice. The bibliography is cut because citations
        are already resolved inline to author-year.
        """
        main = strip_comments((self.paper / "main.tex").read_text(encoding="utf-8"))
        start = main.find(r"\maketitle")
        start = start + len(r"\maketitle") if start >= 0 else main.find(r"\begin{document}")
        end = main.find(r"\end{document}")
        body = main[start : end if end > 0 else len(main)]
        body = re.sub(r"\\begin\{abstract\}.*?\\end\{abstract\}", "", body, flags=re.S)
        body = re.sub(r"\\(bibliographystyle|bibliography|printbibliography)\s*(\{[^}]*\})?", "", body)
        return body

    def body(self, _unused: list[Path] | None = None) -> str:
        raw = self.document_body()
        # Inputs, macros and conditionals each PRODUCE the others, so no single
        # ordering resolves them: an \input brings macros, a macro expands to a
        # \begin{table} with its own \label, a conditional decides which \input
        # happens at all. Running them once in any order left, in turn, a raw
        # table in the prose, a dangling \Cref, and an \input of the radar
        # variant the design had switched off. So iterate to a fixed point.
        prev = None
        for _ in range(8):
            if raw == prev:
                break
            prev = raw
            # Conditionals FIRST. The design switches \ifOPradar off, and the
            # branch it switches off contains \input{data/opening-radar-series},
            # a file that is deliberately not generated. Resolving inputs before
            # deciding the branch tried to read it and reported it missing --
            # a phantom error about a file the paper never asked for.
            raw = resolve_ifs(raw, self.macros.flags)
            # BOTH conditionals before any input is resolved. main.tex guards an
            # optional section with `\IfFileExists{sections/04b_ablation.tex}
            # {\input{sections/04b_ablation}}{}`, and resolving inputs first
            # tried to read a file the paper had deliberately not generated,
            # then reported it missing. Same shape as the \ifOPradar case fixed
            # above it -- a conditional must decide before anything inside it is
            # acted on, and there are two kinds of conditional here, not one.
            raw = if_file_exists(raw, self.paper)
            raw = self.resolve_inputs(raw)
            raw = self.macros.expand(raw)
        # Only now: the picture code itself, which no later pass should see.
        raw = drop_drawings(raw)
        raw = wrap_manual_floats(raw)
        # `\captionof{figure}{...}` is the caption of a float that is not a
        # float environment -- the design uses it for the full-width opening
        # block. It has to be recognised or the caption is lost with the
        # drawing.
        raw = re.sub(r"\\captionof\s*\{[^}]*\}\s*(?=\{)",
                     r"\\caption", raw)
        # `\appendix` resets numbering in LaTeX. Markdown has no such machinery
        # and the platform emits no heading ids, so the only thing that can
        # carry the boundary is a heading with the word on it.
        raw = re.sub(r"\\appendix\b\s*", "\n\n## Appendix\n\n", raw)
        raw = re.sub(r"\\(clearpage|newpage|pagebreak|bigskip|medskip|smallskip)\b\*?", "", raw)
        self.index(raw)

        text = self.protect_math(raw)
        text = self.environments(text)
        text = self.cites(text)
        text = self.refs(text)

        def heading(m: re.Match) -> str:
            level = {"section": "## ", "subsection": "### ", "subsubsection": "#### ",
                     "paragraph": "**"}[m.group(1)]
            title = read_group(text, m.end() - 1) or ""
            return "\n\n" + level + inline_to_md(title, self.macros) + (
                "**\n\n" if m.group(1) == "paragraph" else "\n\n")

        out, i = [], 0
        pat = re.compile(r"\\(section|subsection|subsubsection|paragraph)\s*\*?\s*\{")
        while True:
            m = pat.search(text, i)
            if not m:
                out.append(text[i:])
                break
            out.append(text[i : m.start()])
            out.append(heading(m))
            i = end_of_group(text, m.end() - 1)
        text = "".join(out)

        text = inline_to_md_block(text, self.macros, self)
        text = self.restore_math(text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip() + "\n"


def inline_to_md_block(text: str, macros: Macros, conv: Converter) -> str:
    """Inline markup over a whole body, then record anything left unhandled.

    The report matters more than it looks: a command this does not know is a
    command whose ARGUMENT survives while its meaning is lost, and that is how a
    paper quietly loses an emphasis, a unit or a qualifier."""
    text = inline_to_md(text, macros)
    # Scan for leftovers OUTSIDE math. `\gamma`, `\tau`, `\mathrm` and `\pm` are
    # not unhandled constructs -- they are the formulas doing their job, and
    # KaTeX renders them server-side. Reporting them buried the four that were
    # real under seven that were not.
    outside = re.sub(r"\$\$.*?\$\$", " ", text, flags=re.S)
    # Inline math may span a line break -- the LaTeX source wraps, so
    # `$L_{\mathrm{fix}} \in` and `\{0,\dots,\gamma\}$` routinely sit on two
    # lines. Only a BLANK line breaks a `$` run, per the renderer. Forbidding
    # every newline here reported four perfectly good formulas as unhandled
    # LaTeX and would have sent someone hunting a bug that was in the check.
    outside = re.sub(r"(?<!\\)\$(?:[^$\n]|\n(?!\s*\n))*(?<!\\)\$", " ", outside)
    outside = re.sub(r"`[^`\n]*`", " ", outside)
    for m in re.finditer(r"\\([A-Za-z@]+)", outside):
        conv.unknown_cmds.add("\\" + m.group(1))
    return text


# --------------------------------------------------------------- figures ----
def render_dat(dat: Path, out: Path, title: str = "") -> bool:
    """A `.dat` -> a PNG, with PIL rather than a TeX run.

    The contract is explicit that this must NOT be rasterised from the PDF,
    because that would make the markdown target depend on a TeX distribution.
    matplotlib is not present here, so this draws the grouped-bar case that
    `make_paper_data.py` emits and refuses anything else rather than inventing a
    chart type."""
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return False
    lines = [l for l in dat.read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.strip().startswith("#")]
    if len(lines) < 2:
        return False
    header = lines[0].split()
    rows = []
    for l in lines[1:]:
        parts = l.split()
        if len(parts) < 2:
            continue
        label = re.sub(r"[{}]", "", parts[0])
        try:
            vals = [float(x) for x in parts[1:]]
        except ValueError:
            continue
        rows.append((label, vals))
    if not rows:
        return False

    nser = min(len(rows[0][1]), max(1, len(header) - 1))
    nser = min(nser, 4)
    W, H, pad = 1000, 560, 70
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    colours = [(150, 160, 175), (90, 130, 190), (0, 120, 248), (230, 140, 60)]
    top = max(max(v[:nser]) for _, v in rows) or 1.0
    plot_h = H - pad * 2
    gw = (W - pad * 2) / len(rows)
    bw = gw * 0.72 / nser
    for gi, (label, vals) in enumerate(rows):
        x0 = pad + gi * gw + gw * 0.14
        for si in range(nser):
            v = vals[si]
            h = max(1, (v / top) * plot_h)
            x = x0 + si * bw
            d.rectangle([x, H - pad - h, x + bw - 2, H - pad], fill=colours[si % len(colours)])
        d.text((x0, H - pad + 8), label[:16], fill=(40, 40, 40))
    d.line([pad, H - pad, W - pad, H - pad], fill=(40, 40, 40), width=2)
    d.line([pad, pad, pad, H - pad], fill=(40, 40, 40), width=2)
    for k in range(5):
        y = H - pad - (plot_h * k / 4)
        d.line([pad - 5, y, pad, y], fill=(40, 40, 40), width=2)
        d.text((pad - 52, y - 7), f"{top * k / 4:,.1f}"[:8], fill=(40, 40, 40))
    for si in range(nser):
        name = header[si + 1] if si + 1 < len(header) else f"series {si + 1}"
        d.rectangle([W - pad - 170, pad + si * 22, W - pad - 152, pad + si * 22 + 14],
                    fill=colours[si % len(colours)])
        d.text((W - pad - 146, pad + si * 22), name[:18], fill=(40, 40, 40))
    if title:
        d.text((pad, pad - 30), title[:90], fill=(20, 20, 20))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return True


def extract_title(paper: Path, conv: "Converter") -> str:
    r"""The authored title, out of a `\title{}` that is mostly design machinery.

    `paper-writing` wraps it: `\title{\TitleBlock{\textbf{Name: A Claim}\\...}}`,
    and `\TitleBlock` is a design macro that draws the venue mark in a tikz
    picture inside a two-column tabular. Expanding it is exactly wrong -- it
    produced a 1126-character "title" whose first words were
    `\ifDesignMark \begin{tabular}`. So UNWRAP rather than expand: take the
    block's own argument, which is the text a human typed.

    The 12.10 cm box the design gives the title is a stricter constraint than
    the platform's 8-250 characters, so a title that fits the paper fits here.
    """
    # Comments first: the block opens `\title{%`, and that `%` otherwise becomes
    # the title's first two characters.
    main = strip_comments((paper / "main.tex").read_text(encoding="utf-8"))
    m = re.search(r"\\title\s*\{", main)
    if not m:
        return ""
    raw = read_group(main, m.end() - 1) or ""
    for wrapper in ("TitleBlock", "AuthorBlock"):
        wm = re.search(r"\\" + wrapper + r"\s*\{", raw)
        if wm:
            inner = read_group(raw, wm.end() - 1)
            if inner:
                raw = inner
            break
    raw = drop_first_arg(raw, "scalebox", 2)
    raw = drop_first_arg(raw, "resizebox", 3)
    raw = re.sub(r"\\\\", " ", raw)
    raw = re.sub(r"\\(if|else|fi)[A-Za-z]*\b", "", raw)
    out = re.sub(r"\s+", " ", conv.finish_inline(raw)).strip()
    # `title` is a plain string field, not markdown. The authored title is bold
    # in the manuscript because the design sets it that way, and carrying the
    # asterisks through produced `**GateSpec: A Learned Acceptance Policy** **for
    # Speculative Decoding**` -- which is also two bolded fragments where there
    # is one title, because the line break between them was typographic.
    out = re.sub(r"\*\*|__|(?<!\w)\*(?!\w)|`", "", out)
    return re.sub(r"\s+", " ", out).strip()


# ------------------------------------------------------------------ main ----
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", help="the directory holding paper.json and paper/")
    ap.add_argument("--out", default=None, help="output dir (default: <project>/submission)")
    ap.add_argument("--reproducibility", default=None,
                    help="file holding the reproducibility prose; the research side owns it")
    ap.add_argument("--keywords", default=None, help="comma-separated, if paper.json has none")
    a = ap.parse_args()

    project = Path(a.project).resolve()
    paper = project / "paper"
    if not (paper / "main.tex").exists():
        print(f"make-submission: BLOCKED -- no paper/main.tex under {project}", file=sys.stderr)
        return 2

    # A BLOCKED readiness verdict stops the build and this side does not
    # override it -- same rule as evidence-interface.md.
    readiness = project / "readiness.json"
    if readiness.exists():
        try:
            verdict = json.loads(readiness.read_text(encoding="utf-8")).get("verdict", "")
            if str(verdict).upper() == "BLOCKED":
                print("make-submission: BLOCKED -- readiness.json says BLOCKED", file=sys.stderr)
                return 2
        except json.JSONDecodeError:
            warn("readiness.json is not valid JSON; treating as absent")

    # Every file that can define a macro the body uses. `preamble.tex` and the
    # blocks were missed on the first pass and cost eight distinct constructs:
    # \up and \down are defined there, \contribution in blocks/contributions.tex,
    # \datacard in blocks/devices.tex. A macro that does not expand leaves its
    # NAME in the prose where its meaning should be.
    macros = Macros()
    for f in ("macros.tex", "design.tex", "preamble.tex", "preamble-layout.tex"):
        macros.load(paper / f)
    for blk in sorted((paper / "blocks").glob("*.tex")):
        macros.load(blk)
    # `make_paper_data.py` writes macros into the GENERATED data files --
    # \OPmetric ("decode throughput") is defined in data/opening.tex -- so the
    # paper's own vocabulary is partly produced by the data step. Skipping these
    # left the metric's name as a control sequence in three captions.
    for dat in sorted((paper / "data").glob("*.tex")):
        macros.load(dat)
    bib = parse_bib(paper / "references.bib")
    conv = Converter(project, macros, bib)

    sections = sorted((paper / "sections").glob("*.tex"))
    abstract_files = [p for p in sections if "abstract" in p.name]
    # The body is driven by main.tex's own order, not by this glob -- see
    # Converter.document_body(). The glob is kept only to find the abstract and
    # to refuse a tree that has no sections at all.
    body_files = [p for p in sections if "abstract" not in p.name]
    if not body_files:
        print("make-submission: BLOCKED -- no body sections", file=sys.stderr)
        return 2

    body_md = conv.body()

    abstract = ""
    if abstract_files:
        raw = strip_comments(abstract_files[0].read_text(encoding="utf-8"))
        raw = conv.resolve_inputs(raw)
        raw = re.sub(r"\\begin\{abstract\}|\\end\{abstract\}", "", raw)
        abstract = re.sub(r"\s*\n\s*", " ", conv.finish_inline(raw)).strip()

    title = extract_title(paper, conv)

    meta = {}
    pj = project / "paper.json"
    if pj.exists():
        try:
            meta = json.loads(pj.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            warn("paper.json is not valid JSON")
    keywords = meta.get("keywords") or ([k.strip() for k in a.keywords.split(",")] if a.keywords else [])
    keywords = [k for k in keywords if k][:MAX_KEYWORDS]

    repro = ""
    repro_path = Path(a.reproducibility) if a.reproducibility else project / "REPRODUCIBILITY.md"
    if repro_path.exists():
        repro = repro_path.read_text(encoding="utf-8").strip()

    # Figures: .dat -> PNG, never from the PDF.
    outdir = Path(a.out) if a.out else project / "submission"
    figdir = outdir / "figures"
    made = []
    for label, cap in conv.figures:
        stem = label.split(":")[-1]
        for cand in [paper / "data" / f"{stem}.dat", paper / "data" / "opening.dat"]:
            if cand.exists():
                if render_dat(cand, figdir / f"{stem}.png", cap[:80]):
                    made.append(f"{stem}.png")
                break

    sub = {
        "title": title,
        "abstract": abstract,
        "body_md": body_md,
        "keywords": keywords,
        "reproducibility": repro,
    }

    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "submission.json").write_text(
        json.dumps(sub, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---- report, and be loud about every hole ---------------------------
    print(f"make-submission: wrote {outdir / 'submission.json'}")
    print(f"  title            {len(title)} chars")
    print(f"  abstract         {len(abstract)} chars")
    print(f"  body_md          {len(body_md)} chars")
    print(f"  keywords         {len(keywords)}")
    print(f"  reproducibility  {len(repro)} chars")
    print(f"  figures          {len(made)} rendered {made if made else ''}")

    problems = 0
    for field, (lo, hi) in LIMITS.items():
        n = len(sub[field] if field != "body_md" else body_md)
        if n < lo or n > hi:
            warn(f"{field} is {n} chars, outside the platform's {lo}-{hi}")
            problems += 1
    if not keywords:
        warn("no keywords: the platform requires 1-10, and paper.json carries none "
             "(paper-writing's paper.json is a DESIGN file -- pass --keywords)")
        problems += 1
    if not repro:
        warn("reproducibility is empty. It has no source in the LaTeX tree by "
             "design: the research side owns it (readiness.json + run manifests + "
             "the replay verdict, in prose). Pass --reproducibility FILE.")
        problems += 1
    if conv.missing_cites:
        warn(f"{len(conv.missing_cites)} citation key(s) not in references.bib, "
             f"dropped: {sorted(conv.missing_cites)[:6]}")
        problems += 1
    if conv.unknown_cmds:
        cmds = sorted(conv.unknown_cmds)
        warn(f"{len(cmds)} unhandled LaTeX construct(s) left in body_md: {cmds[:10]}")
        problems += 1

    if problems:
        print(f"make-submission: {problems} problem(s) -- see above. submission.json "
              f"was still written so the shape gate can read it.", file=sys.stderr)
        return 1
    print("make-submission: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
