#!/usr/bin/env python3
"""Split pdf/decretos.pdf into one text file per decree and group the
relevant ones into batches for the extraction agents.

Output (all under the repo root):
  decretos/<id>.txt          one file per decree (all 7,039), with a header
  decretos/index.csv         id, numero, fecha, paginas, relevante, archivo
  batches/batch_NNN.txt      25 relevant decrees per file, concatenated

Modes
  python3 scripts/split.py            first run: writes decretos/ and all batches
  python3 scripts/split.py --repair   batches already exist and events were
                                      extracted from them: rewrite decretos/,
                                      leave batch_001..NNN untouched, and put the
                                      relevant decrees whose operative text was
                                      incomplete in the plain column reading into
                                      a NEW batch; record them in
                                      batches/repairs.json so merge.py drops
                                      their old events.

How the text is read
  Pass 1: each page is read column by column (four strips, below the running
  header) and the stream is cut at the #I<id>I# / #F<id>F# markers. On most
  pages this is the reading order. On a few pages a decree flows differently
  (a two-column-wide block, a neighbour's tail inside another column) and the
  cut closes a decree early: it ends without its own end marker, or without an
  operative article.
  Pass 2: every decree flagged that way is re-read on its pages with a
  recursive whitespace cut (XY-cut: split on column gaps, then row gaps, so a
  two-column-wide block or a tail inside another column falls into place), or
  failing that from the PDF's own block order, and replaced when that reading
  is complete and consistent (starts and ends with its own markers).

Deterministic; takes about 2 minutes.
"""
import csv
import json
import os
import re
import sys
import unicodedata

import pymupdf  # PyMuPDF

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDF = os.path.join(ROOT, "pdf", "decretos.pdf")
OUT_DEC = os.path.join(ROOT, "decretos")
OUT_BATCH = os.path.join(ROOT, "batches")
BATCH_SIZE = 25

# Four columns on an 850pt-wide page (block x0 at ~40, ~240, ~430, ~630).
COLUMN_EDGES = [0, 235, 425, 620, 10_000]

# Running header occupies y 41-60pt; body starts at ~69pt. Clip below it.
HEADER_BOTTOM = 61

# Running page headers (or column-cut fragments of them) to drop.
HEADER_RE = re.compile(
    r"^\s*((lunes|martes|mi[ée]rcoles|jueves|viernes|s[áa]bado|domingo)\s+\d+\s+de\s+\w+\s+de\s+\d{4}"
    r"|(primera\s+)?secci[óo]n?(\s*-\s*suplemento)?"
    r"|n?\s*-\s*suplemento"
    r"|(b)?oletin oficial(\s*n[º°]\s*[\d.]+(\s+\d+)?)?"
    r"|\d{1,4})\s*$",
    re.IGNORECASE,
)

START_RE = re.compile(r"#I(\d+)I#")
END_RE = re.compile(r"#F(\d+)F#")
NUM_RE = re.compile(r"Decreto\s+S?\s*(\d+)(?:\s*/\s*(\d{2,4}))?", re.IGNORECASE)
DATE_RE = re.compile(r"Bs\.?\s*As\.?,?\s*(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{2,4})")
ARTICLE_RE = re.compile(r"Art[íi]cu-?\s*lo\s*1|Art\.\s*1|ERRATAS", re.IGNORECASE)
ART_LINE_RE = re.compile(r"^(Art[íi]cu|Art\.)", re.IGNORECASE)

# Terms that mark a decree as relevant to the "derecho de opción" study.
RELEVANT_TERMS = [
    "opcion",
    "arrest",
    "detenid",
    "disposicion del poder ejecutivo",
    "libertad vigilada",
    "abandon",
    "salir del pais",
    "salida del pais",
    "expuls",
]

# Masthead lines (first page) to drop.
MASTHEAD_RE = re.compile(
    r"www\.boletinoficial|e-mail:|Registro Nacional de la Propiedad|N[º°] 4\.995\.241"
    r"|Domicilio legal|Suipacha 767|Ciudad Aut[óo]noma de Buenos Aires|Tel\. y Fax",
    re.IGNORECASE,
)


def strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    ).lower()


def clean_lines(text: str):
    out = []
    for ln in text.splitlines():
        ln = re.sub(r"[ \t]+", " ", ln).strip()
        if ln and not HEADER_RE.match(ln) and not MASTHEAD_RE.search(ln):
            out.append(ln)
    return out


def page_lines_columns(page):
    """Lines of one page in column order: four strips, top to bottom each."""
    r = page.rect
    out = []
    for x0, x1 in zip(COLUMN_EDGES, COLUMN_EDGES[1:]):
        clip = pymupdf.Rect(x0, HEADER_BOTTOM, min(x1, r.x1), r.y1)
        out += clean_lines(page.get_text("text", clip=clip, sort=True))
    return out


def body_blocks(page):
    """Text blocks of a page without the running header. A narrow block that
    straddles the header line (a decree marker) is kept; the wide header
    block itself, and blocks that clean to nothing, are dropped."""
    out = []
    for b in page.get_text("blocks"):
        if b[6] != 0 or b[3] <= HEADER_BOTTOM + 4:
            continue
        lines = clean_lines(b[4])
        if not lines:
            continue
        if b[1] < HEADER_BOTTOM and (b[2] - b[0]) > 300:
            # the header block, with a decree marker glued to it: keep the
            # marker as a narrow block so it does not hide the column gaps
            out.append((b[0], b[1], b[0] + 60, b[3], "\n".join(lines)))
            continue
        out.append((b[0], b[1], b[2], b[3], "\n".join(lines)))
    return out


def page_lines_native(page):
    """Lines of one page in the PDF's own block order (used for repairs)."""
    out = []
    for b in body_blocks(page):
        out += b[4].splitlines()
    return out


MIN_GAP_X = 8   # pt of clear whitespace to count as a column gap
MIN_GAP_Y = 4   # pt of clear whitespace to count as a row gap


def _gaps(blocks, lo_i, hi_i, min_gap):
    """Positions where the union of block intervals [lo, hi] has a gap."""
    ivs = sorted((b[lo_i], b[hi_i]) for b in blocks)
    cuts, cur_hi = [], ivs[0][1]
    for lo, hi in ivs[1:]:
        if lo - cur_hi >= min_gap:
            cuts.append((cur_hi + lo) / 2)
        cur_hi = max(cur_hi, hi)
    return cuts


def xy_order(blocks):
    """Recursive XY-cut: split on full-height column gaps first, then on
    row gaps, until single blocks remain. Returns blocks in reading order."""
    if len(blocks) <= 1:
        return list(blocks)
    cuts = _gaps(blocks, 0, 2, MIN_GAP_X)
    if cuts:
        # Two multi-column flows stacked in the same columns (a decree that
        # ends in the rightmost column, whitespace across the region, the next
        # decree starting in the leftmost column) must be cut apart first, or
        # the column cut merges them.
        for c in _gaps(blocks, 1, 3, 8):
            end_right = any(END_RE.search(b[4]) and b[0] > cuts[-1] and c - 40 <= b[3] <= c for b in blocks)
            start_left = any(START_RE.search(b[4]) and b[2] < cuts[0] and c <= b[1] <= c + 40 for b in blocks)
            if end_right and start_left:
                top = [b for b in blocks if b[1] <= c]
                bot = [b for b in blocks if b[1] > c]
                if top and bot:
                    return xy_order(top) + xy_order(bot)
        out, groups = [], [[] for _ in range(len(cuts) + 1)]
        for b in blocks:
            k = sum(1 for c in cuts if b[0] > c)
            groups[k].append(b)
        for g in groups:
            out += xy_order(g) if len(g) < len(blocks) else sorted(g, key=lambda b: (b[1], b[0]))
        return out
    ycuts = _gaps(blocks, 1, 3, MIN_GAP_Y)
    if not ycuts:
        return sorted(blocks, key=lambda b: (b[1], b[0]))
    # No full-height column gap: some block spans two columns. Cut
    # horizontally right next to it, so that the remaining part becomes a
    # clean multi-column region instead of interleaving the columns row by row.
    def split_at(c):
        top = [b for b in blocks if b[1] <= c]
        bot = [b for b in blocks if b[1] > c]
        return top, bot
    for c in ycuts:  # first cut from the top whose lower part has columns
        top, bot = split_at(c)
        if top and bot and _gaps(bot, 0, 2, MIN_GAP_X):
            return xy_order(top) + xy_order(bot)
    for c in reversed(ycuts):  # last cut from the bottom whose upper part has columns
        top, bot = split_at(c)
        if top and bot and _gaps(top, 0, 2, MIN_GAP_X):
            return xy_order(top) + xy_order(bot)
    out, groups = [], [[] for _ in range(len(ycuts) + 1)]
    for b in blocks:
        k = sum(1 for c in ycuts if b[1] > c)
        groups[k].append(b)
    for g in groups:
        out += xy_order(g) if len(g) < len(blocks) else sorted(g, key=lambda b: (b[1], b[0]))
    return out


def page_lines_xycut(page):
    """Lines of one page in XY-cut reading order (used for repairs)."""
    out = []
    for b in xy_order(body_blocks(page)):
        out += b[4].splitlines()
    return out


def parse(stream):
    """Cut a stream of (line, page) at the markers.

    A decree is `clean` when it was closed by its own end marker. One closed by
    another decree's start, or by an end marker with a different id, is not:
    its text is probably incomplete. Lines after an end marker and before the
    next start marker belong to nobody and are dropped.
    """
    decrees, cur = [], None

    def close(ok):
        cur["clean"] = ok
        decrees.append(cur)

    for ln, pg in stream:
        m = START_RE.search(ln)
        if m:
            if cur is not None:
                close(False)
            cur = {"id": m.group(1), "lines": [], "pages": set()}
            rest = ln[m.end():].strip()
            if rest:
                cur["lines"].append(rest)
                cur["pages"].add(pg)
            continue
        m = END_RE.search(ln)
        if m:
            if cur is None:
                continue
            head = ln[: m.start()].strip()
            if head:
                cur["lines"].append(head)
                cur["pages"].add(pg)
            close(m.group(1) == cur["id"])
            cur = None
            continue
        if cur is not None:
            cur["lines"].append(ln)
            cur["pages"].add(pg)
    if cur is not None:
        close(False)
    return decrees


def truncated(d) -> bool:
    return not ARTICLE_RE.search("\n".join(d["lines"]))


def suspicious(d) -> bool:
    return (not d["clean"]) or truncated(d)


def describe(d):
    body = "\n".join(d["lines"]).strip()
    mn = NUM_RE.search(body)
    md = DATE_RE.search(body)
    fecha = f"{md.group(1)}/{md.group(2)}/{md.group(3)}" if md else ""
    year = (mn.group(2) if mn and mn.group(2) else (md.group(3) if md else "")) if mn else ""
    if len(year) == 2:
        year = "19" + year
    numero = f"{mn.group(1)}/{year}" if mn else ""
    pages = sorted(d["pages"])
    pag = f"{pages[0]}" if len(pages) == 1 else f"{pages[0]}-{pages[-1]}" if pages else ""
    flat = re.sub(r"\s+", " ", strip_accents(body))
    rel = any(t in flat for t in RELEVANT_TERMS)
    header = (
        f"=== DECRETO {numero or '?'} | fecha {fecha or '?'} | "
        f"paginas PDF {pag or '?'} | id {d['id']} ===\n"
    )
    return body, numero, fecha, pag, rel, header


def main() -> int:
    repair = "--repair" in sys.argv
    doc = pymupdf.open(PDF)
    os.makedirs(OUT_DEC, exist_ok=True)
    os.makedirs(OUT_BATCH, exist_ok=True)

    existing_batches = sorted(f for f in os.listdir(OUT_BATCH) if re.match(r"batch_\d{3}\.txt$", f))
    if existing_batches and not repair:
        print("batches/ already exists; use --repair to keep them, or delete batches/ to start over")
        return 1
    for f in os.listdir(OUT_DEC):
        os.remove(os.path.join(OUT_DEC, f))

    # Pass 1: column order over the whole document (this is what the first
    # extraction run saw; `first` keeps it for the change report).
    stream = []
    for i, page in enumerate(doc):
        stream += [(ln, i + 1) for ln in page_lines_columns(page)]
        if (i + 1) % 200 == 0:
            print(f"  read {i + 1}/{doc.page_count} pages", flush=True)
    decrees = parse(stream)
    first = {d["id"]: d for d in decrees}
    flagged = [d for d in decrees if suspicious(d)]
    print(f"pass 1: {len(decrees)} decrees; {len(flagged)} closed irregularly or without an operative article")

    # Pass 2: re-read flagged decrees from the PDF's block order on their pages.
    cache = {}

    def lines(pg, mode):
        if (pg, mode) not in cache:
            fn = page_lines_xycut if mode == "xy" else page_lines_native
            cache[(pg, mode)] = [(ln, pg) for ln in fn(doc[pg - 1])]
        return cache[(pg, mode)]

    repaired, still = 0, []
    for idx, d in enumerate(decrees):
        if not suspicious(d):
            continue
        pages = sorted(d["pages"]) or [1]
        window = range(max(1, pages[0] - 1), min(doc.page_count, pages[-1] + 1) + 1)
        best = None
        for mode in ("xy", "native"):
            alt = []
            for pg in window:
                alt += lines(pg, mode)
            for cand in parse(alt):
                if cand["id"] == d["id"] and cand["clean"] and not truncated(cand):
                    best = cand
                    break
            if best is not None:
                break
        if best is not None:
            decrees[idx] = best
            repaired += 1
        else:
            still.append(d)
    print(f"pass 2: repaired {repaired}; still irregular {len(still)}")
    for d in still:
        _, numero, fecha, pag, rel, _ = describe(d)
        print(f"   still irregular: {numero} ({fecha}) p.{pag} relevant={int(rel)} clean={int(d['clean'])} truncated={int(truncated(d))}")

    # Write decree files and index; collect what changed in operative text.
    rows, relevant, changed = [], [], []
    for d in decrees:
        body, numero, fecha, pag, rel, header = describe(d)
        text = header + body + "\n"
        fname = f"{d['id']}.txt"
        with open(os.path.join(OUT_DEC, fname), "w", encoding="utf-8") as fh:
            fh.write(text)
        rows.append([d["id"], numero, fecha, pag, int(rel), fname])
        if rel:
            relevant.append(text)
        if repair and rel:
            old_lines = set(first[d["id"]]["lines"])
            gained_art = any(ART_LINE_RE.match(ln) and ln not in old_lines for ln in d["lines"])
            if gained_art or (truncated(first[d["id"]]) and not truncated(d)):
                changed.append((d["id"], numero, fecha, text))
    with open(os.path.join(OUT_DEC, "index.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "numero", "fecha", "paginas", "relevante", "archivo"])
        w.writerows(rows)

    if not repair:
        nb = 0
        for i in range(0, len(relevant), BATCH_SIZE):
            nb += 1
            with open(os.path.join(OUT_BATCH, f"batch_{nb:03d}.txt"), "w", encoding="utf-8") as fh:
                fh.write("\n".join(relevant[i : i + BATCH_SIZE]))
        print(f"relevant: {len(relevant)} -> {nb} batches of {BATCH_SIZE}")
    else:
        rep_path = os.path.join(OUT_BATCH, "repairs.json")
        repairs = json.load(open(rep_path, encoding="utf-8")) if os.path.exists(rep_path) else {}
        already = {r["id"] for items in repairs.values() for r in items}
        changed = [c for c in changed if c[0] not in already]
        if changed:
            nb = int(existing_batches[-1][6:9]) + 1
            for i in range(0, len(changed), BATCH_SIZE):
                name = f"batch_{nb:03d}"
                chunk = changed[i : i + BATCH_SIZE]
                with open(os.path.join(OUT_BATCH, name + ".txt"), "w", encoding="utf-8") as fh:
                    fh.write("\n".join(t for _, _, _, t in chunk))
                repairs[name] = [{"id": i_, "numero": n, "fecha": f} for i_, n, f, _ in chunk]
                print(f"repair batch {name}: {len(chunk)} decrees")
                nb += 1
            json.dump(repairs, open(rep_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            for i_, n, f, _ in changed:
                print(f"   {n} ({f}) id {i_}")
        else:
            print("repair: no relevant decree gained operative text")

    print(f"decrees: {len(rows)}; relevant: {len(relevant)}")
    print(f"without number: {sum(1 for r in rows if not r[1])}, without date: {sum(1 for r in rows if not r[2])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
