#!/usr/bin/env python3
"""Split pdf/decretos.pdf into one text file per decree and group the
relevant ones into batches for the extraction agents.

Output (all under the repo root):
  decretos/<id>.txt          one file per decree (all 7,038), with a header
  decretos/index.csv         id, numero, fecha, paginas, relevante, archivo
  batches/batch_NNN.txt      25 relevant decrees per file, concatenated

Deterministic; takes about 2 minutes. Re-running overwrites everything.
"""
import csv
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


def page_text(page) -> str:
    """Text of one page in reading order: column by column, top to bottom."""
    r = page.rect
    parts = []
    for x0, x1 in zip(COLUMN_EDGES, COLUMN_EDGES[1:]):
        clip = pymupdf.Rect(x0, HEADER_BOTTOM, min(x1, r.x1), r.y1)
        t = page.get_text("text", clip=clip, sort=True)
        lines = []
        for ln in t.splitlines():
            ln = re.sub(r"[ \t]+", " ", ln).strip()
            if ln and not HEADER_RE.match(ln) and not MASTHEAD_RE.search(ln):
                lines.append(ln)
        parts.append("\n".join(lines))
    return "\n".join(parts)


def main() -> int:
    doc = pymupdf.open(PDF)
    os.makedirs(OUT_DEC, exist_ok=True)
    os.makedirs(OUT_BATCH, exist_ok=True)
    for d in (OUT_DEC, OUT_BATCH):
        for f in os.listdir(d):
            os.remove(os.path.join(d, f))

    # Build one stream of (line, page_number) over the whole document.
    stream = []
    for i, page in enumerate(doc):
        for ln in page_text(page).splitlines():
            stream.append((ln, i + 1))
        if (i + 1) % 200 == 0:
            print(f"  read {i + 1}/{doc.page_count} pages", flush=True)

    # Cut at #I...I# / #F...F#.
    decrees = []
    cur = None
    for ln, pg in stream:
        m = START_RE.search(ln)
        if m:
            if cur is not None:  # unterminated previous decree
                decrees.append(cur)
            cur = {"id": m.group(1), "lines": [], "pages": set()}
            rest = ln[m.end():].strip()
            if rest:
                cur["lines"].append(rest)
                cur["pages"].add(pg)
            continue
        m = END_RE.search(ln)
        if m and cur is not None:
            head = ln[: m.start()].strip()
            if head:
                cur["lines"].append(head)
                cur["pages"].add(pg)
            decrees.append(cur)
            cur = None
            continue
        if cur is not None:
            cur["lines"].append(ln)
            cur["pages"].add(pg)
    if cur is not None:
        decrees.append(cur)

    # Write files.
    rows = []
    relevant = []
    for d in decrees:
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
        fname = f"{d['id']}.txt"
        with open(os.path.join(OUT_DEC, fname), "w", encoding="utf-8") as fh:
            fh.write(header + body + "\n")
        rows.append([d["id"], numero, fecha, pag, int(rel), fname])
        if rel:
            relevant.append(header + body + "\n")

    with open(os.path.join(OUT_DEC, "index.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "numero", "fecha", "paginas", "relevante", "archivo"])
        w.writerows(rows)

    nb = 0
    for i in range(0, len(relevant), BATCH_SIZE):
        nb += 1
        with open(os.path.join(OUT_BATCH, f"batch_{nb:03d}.txt"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(relevant[i : i + BATCH_SIZE]))

    missing_num = sum(1 for r in rows if not r[1])
    missing_date = sum(1 for r in rows if not r[2])
    print(f"decrees: {len(rows)}")
    print(f"relevant: {len(relevant)}  -> {nb} batches of {BATCH_SIZE}")
    print(f"without number: {missing_num}, without date: {missing_date}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
