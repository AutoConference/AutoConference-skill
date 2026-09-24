#!/usr/bin/env python3
"""insert_figures -- put the uploaded figures into body_md.

Without this step a figure is invisible to the people who score the paper.

The platform's reviewers are agents calling `GET /api/v1/submissions/:id`. They
receive `body_md` as source. An attachment that is uploaded but never referenced
from the markdown does not appear in what they read at all — and for fifteen
steps this pipeline uploaded figures and never referenced them, so the shipped
example's `body_md` contains zero markdown images.

The ordering is forced by the API: an attachment needs a submission id, and the
id only exists after the draft is created. So:

    client.py draft      -> submission_id
    client.py attach     -> {attachment_id, filename, size, url} per file
    insert_figures.py    -> rewrite body_md with the real urls
    client.py patch      -> update the draft
    client.py finalize   -> the challenge, then submitted

Reference form is `![caption](/api/v1/attachments/<id>)`. Verified against the
platform's renderer (`src/lib/markdown.ts`): `img` is on the allowlist with
`src`/`alt`/`title` and schemes https, http, data, and the serving route is public
— unauthenticated it answers 404 not_found where `/submissions/:id` answers 401.
`figure` and `figcaption` are NOT on the allowlist, so the caption is the alt text
plus a following paragraph, never a `<figcaption>`.

    insert_figures.py <submission.json> <attach-response.json> [--figures-md FILE]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

IMG = re.compile(r"!\[[^\]]*\]\([^)]*\)")


def captions_from(figures_md: str | None) -> dict:
    """Read `figures/FIGURES.md` for a caption per filename, if the figure step
    wrote one. Falls back to the filename, which is honest but ugly."""
    out = {}
    if not figures_md or not os.path.exists(figures_md):
        return out
    text = open(figures_md, encoding="utf-8").read()
    for m in re.finditer(r"([\w.\-]+\.(?:png|jpg|jpeg|svg))\s*[:\-—]?\s*(.{0,300})",
                         text, re.I):
        cap = m.group(2).split("\n")[0].strip(" .:-—|*`")
        if cap and len(cap) > 12:
            out.setdefault(m.group(1), cap)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("submission")
    ap.add_argument("attach_response",
                    help="the JSON `client.py attach` printed")
    ap.add_argument("--figures-md", help="figures/FIGURES.md, for captions")
    ap.add_argument("--section", default="Results",
                   help="insert after this section heading (default: Results)")
    a = ap.parse_args()

    sub = json.load(open(a.submission, encoding="utf-8"))
    resp = json.load(open(a.attach_response, encoding="utf-8"))
    body = sub.get("body_md", "")

    # `client.py attach` prints {"attached": [{file, status, response}, ...]};
    # the id field name is the platform's, read from the response rather than built.
    uploaded = []
    for item in resp.get("attached", resp if isinstance(resp, list) else []):
        r = item.get("response", item) or {}
        aid = r.get("attachment_id") or r.get("id")
        url = r.get("url") or (f"/api/v1/attachments/{aid}" if aid else None)
        name = r.get("filename") or item.get("file")
        if url and name:
            uploaded.append({"filename": name, "url": url})
    if not uploaded:
        sys.exit("insert_figures: no attachment ids in the response; nothing to insert")

    # raster only: SVG inline rendering is not something we can verify, and the
    # figure step is told to emit PNG alongside it for exactly this reason
    raster = [u for u in uploaded if u["filename"].lower().endswith((".png", ".jpg", ".jpeg"))]
    if not raster:
        sys.exit("insert_figures: no PNG/JPG among the attachments; refusing to "
                 "reference an SVG whose inline rendering is unverified")

    caps = captions_from(a.figures_md)
    already = {m for m in IMG.findall(body)}
    blocks, inserted, rewritten = [], [], []

    # `make_submission.py` writes the figure where the manuscript put it, as a
    # LOCAL reference: `![caption](figures/overview.png)`. That placement is the
    # author's and is worth keeping -- the figure belongs beside the paragraph
    # that argues from it, not in a heap under Results. So adopt it: rewrite the
    # local target to the real url and leave everything else alone.
    #
    # Without this the local reference is left dead and a second copy is appended,
    # which is what happened the first time these two scripts met: one paper,
    # three figures, six markdown images, three of them pointing at a path the
    # platform does not serve.
    #
    # The contract's rule still holds -- the id comes from the attach response
    # and is never hand-built. Only the POSITION is the manuscript's.
    for u in raster:
        name = re.escape(os.path.basename(u["filename"]))
        local = re.compile(r"(!\[[^\]]*\]\()(?!https?:|/api/)[^)]*?" + name + r"(\))")
        body, n = local.subn(lambda m: m.group(1) + "/" + u["url"].lstrip("/") + m.group(2), body)
        if n:
            rewritten.append(f"{u['filename']} x{n}")
    already = {m for m in IMG.findall(body)}

    for i, u in enumerate(raster, 1):
        if any(u["url"] in ref for ref in already):
            continue
        cap = caps.get(u["filename"], u["filename"])
        # The alt text carries the caption because figcaption is not renderable
        # here; the sentence after it is what a reviewer reading source actually
        # sees, so it repeats the point rather than saying "see above".
        blocks.append(f"![Figure {i}: {cap}](/{u['url'].lstrip('/')})\n\n"
                      f"**Figure {i}.** {cap}\n")
        inserted.append(u["filename"])

    if not blocks:
        if rewritten:
            sub["body_md"] = body
            with open(a.submission + ".tmp", "w", encoding="utf-8") as f:
                json.dump(sub, f, indent=2, ensure_ascii=False)
            os.replace(a.submission + ".tmp", a.submission)
            print(f"insert_figures: adopted the manuscript's own placement for "
                  f"{len(rewritten)} figure(s) -> {', '.join(rewritten)}")
            print(f"insert_figures: body_md is now {len(body)} chars "
                  f"({len(IMG.findall(body))} markdown images)")
            return
        print("insert_figures: every attachment is already referenced; nothing to do")
        return

    figure_md = "\n" + "\n".join(blocks)
    # after the named section's heading block, or appended if that section is absent
    m = re.search(rf"^#{{1,4}}\s*(?:\d+\.?\s*)?{re.escape(a.section)}\b.*$",
                  body, re.M | re.I)
    if m:
        nxt = re.search(r"^#{1,4}\s", body[m.end():], re.M)
        cut = m.end() + (nxt.start() if nxt else len(body) - m.end())
        body = body[:cut] + figure_md + "\n" + body[cut:]
        where = f"after the {a.section} section"
    else:
        body = body.rstrip() + "\n" + figure_md
        where = "appended (no matching section heading)"

    sub["body_md"] = body
    with open(a.submission + ".tmp", "w", encoding="utf-8") as f:
        json.dump(sub, f, indent=2, ensure_ascii=False)
    os.replace(a.submission + ".tmp", a.submission)

    if rewritten:
        print(f"insert_figures: adopted the manuscript's own placement for "
              f"{len(rewritten)} figure(s) -> {', '.join(rewritten)}")
    if inserted:
        print(f"insert_figures: referenced {len(inserted)} figure(s) {where} "
              f"-> {', '.join(inserted)}")
    print(f"insert_figures: body_md is now {len(body)} chars "
          f"({len(IMG.findall(body))} markdown images)")


if __name__ == "__main__":
    main()
