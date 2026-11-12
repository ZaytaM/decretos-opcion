#!/usr/bin/env python3
"""Merge the two agents' outputs into opcion.xlsx and revisar.xlsx.

Reads events/a/*.json and events/b/*.json (one {"eventos": [...]} per batch).

opcion.xlsx
  Personas       one row per person with at least one event beyond a bare
                 arrest (opción denegada/diferida, libertad vigilada,
                 liberación, salida autorizada, expulsión, otro). Each of the
                 six categories gets "decretos" / "fechas" columns; several
                 events are joined with " ; ".
  Solo arresto   persons that only appear in arrest decrees.
  Eventos        every confirmed event, long format (one per row).
  Resumen        counts.
revisar.xlsx
  Eventos found by only one agent, or with conflicting fields, for manual review.

opcion.xlsx and eventos.csv are the public result: no batch / agent columns.
The bookkeeping (which agent, which batch, agreement counts) is in revisar.xlsx.

Countries: if paises.json exists (scripts/paises.py), `destino` is rewritten
to one spelling per country ("Reino de España" -> "España").

Adjudication: scripts/adjudicate.py asks a stronger model to settle each of
those items against the decree text and writes review/resolved/*.json. When
those files exist, merge applies them: "confirmar" moves the (corrected) event
to the confirmed set, "descartar" drops it, "dudoso" (or no resolution) leaves
it in revisar.xlsx. Discarded items are listed in a third sheet for audit.

Matching rule between agents: same decreto + same tipo + same person, where
"same person" is the same document number (digits only) if both have one,
otherwise the same normalized name (accents and case removed, tokens sorted).
"""
import csv
import glob
import hashlib
import json
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TIPOS = [
    "arresto",
    "opcion_denegada",
    "opcion_diferida",
    "libertad_vigilada",
    "liberacion",
    "salida_autorizada",
    "expulsion",
    "otro",
]
TIPO_LABEL = {
    "arresto": "Arresto a disposición del PEN",
    "opcion_denegada": "Opción denegada",
    "opcion_diferida": "Opción diferida",
    "libertad_vigilada": "Libertad vigilada",
    "liberacion": "Liberación (sin efecto el arresto)",
    "salida_autorizada": "Salida del país autorizada",
    "expulsion": "Expulsión",
    "otro": "Otro",
}
FIELDS = ["persona", "documento", "filiacion", "tipo", "decreto", "fecha",
          "destino", "decreto_referido", "pagina", "nota"]


def norm_name(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
    s = re.sub(r"[^a-z\s]", " ", s)
    toks = [t for t in s.split() if t not in ("de", "del", "la", "y", "los", "las")]
    return " ".join(sorted(toks))


def norm_doc(s: str) -> str:
    return re.sub(r"\D", "", s or "")


_PAISES = None


def canon_destino(s: str) -> str:
    """One spelling per country, from paises.json; unknown values are kept."""
    global _PAISES
    if _PAISES is None:
        try:
            raw = json.load(open(os.path.join(ROOT, "paises.json"), encoding="utf-8"))
        except Exception:  # noqa: BLE001
            raw = {}
        _PAISES = {}
        for k, v in raw.items():
            if isinstance(v, dict) and v.get("pais"):
                out = v["pais"] + (f" ({v['ciudad']})" if v.get("ciudad") else "")
                _PAISES[k] = out
                _PAISES.setdefault(k.casefold(), out)
        for out in set(_PAISES.values()):  # already-canonical values map to themselves
            _PAISES.setdefault(out, out)
    s = (s or "").strip()
    return _PAISES.get(s) or _PAISES.get(s.casefold()) or s


def norm_decreto(s: str) -> str:
    m = re.search(r"(\d+)\s*/\s*(\d{2,4})", s or "")
    if not m:
        return (s or "").strip()
    y = m.group(2)
    if len(y) == 2:
        y = "19" + y
    return f"{int(m.group(1))}/{y}"


def load(agent: str):
    evs = []
    for f in sorted(glob.glob(os.path.join(ROOT, "events", agent, "batch_*.json"))):
        batch = os.path.basename(f)[:-5]
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"WARN {agent}/{batch}: {e}", file=sys.stderr)
            continue
        for e in d.get("eventos", []):
            if not isinstance(e, dict):
                continue
            ev = {k: str(e.get(k, "") or "").strip() for k in FIELDS}
            ev["tipo"] = ev["tipo"] if ev["tipo"] in TIPOS else "otro"
            ev["decreto"] = norm_decreto(ev["decreto"])
            ev["decreto_referido"] = norm_decreto(ev["decreto_referido"])
            ev["destino"] = canon_destino(ev["destino"])
            ev["batch"] = batch
            ev["agente"] = agent
            ev["_name"] = norm_name(ev["persona"])
            ev["_doc"] = norm_doc(ev["documento"])
            evs.append(ev)
    return evs


def key(ev, use_doc: bool):
    pid = ev["_doc"] if (use_doc and ev["_doc"]) else ev["_name"]
    return (ev["decreto"], ev["tipo"], pid)


def match(a, b):
    """Pair events of a and b. Returns (confirmed, only_a, only_b, conflicts)."""
    confirmed, conflicts = [], []
    used_b = set()
    # index b by doc-key and by name-key
    idx_doc, idx_name = defaultdict(list), defaultdict(list)
    for j, ev in enumerate(b):
        if ev["_doc"]:
            idx_doc[key(ev, True)].append(j)
        idx_name[key(ev, False)].append(j)
    only_a = []
    for ev in a:
        cands = []
        if ev["_doc"]:
            cands = [j for j in idx_doc.get(key(ev, True), []) if j not in used_b]
        if not cands:
            cands = [j for j in idx_name.get(key(ev, False), []) if j not in used_b]
        if not cands:
            only_a.append(ev)
            continue
        j = cands[0]
        used_b.add(j)
        other = b[j]
        merged = dict(ev)
        merged["agente"] = "a+b"
        merged["_a"], merged["_b"] = ev, other
        diffs = []
        for k in ("persona", "documento", "destino", "decreto_referido", "fecha"):
            if k == "documento":
                nd = lambda x: re.sub(r"[^A-Z0-9]", "", re.sub(r"\bn[ºª°o]?\.?\s", "", x.lower()).upper())  # noqa: E731
                same = nd(ev[k]) == nd(other[k])
            else:
                same = norm_name(ev[k]) == norm_name(other[k]) if k == "persona" else ev[k] == other[k]
            if not same:
                diffs.append(f"{k}: a='{ev[k]}' b='{other[k]}'")
                if not ev[k]:
                    merged[k] = other[k]
        if diffs:
            merged["_diff"] = "; ".join(diffs)
            conflicts.append(merged)
        confirmed.append(merged)
    only_b = [ev for j, ev in enumerate(b) if j not in used_b]
    return confirmed, only_a, only_b, conflicts


def renorm(ev):
    """Recompute the derived fields of an event after its raw fields changed."""
    ev["tipo"] = ev["tipo"] if ev["tipo"] in TIPOS else "otro"
    ev["decreto"] = norm_decreto(ev["decreto"])
    ev["decreto_referido"] = norm_decreto(ev["decreto_referido"])
    ev["destino"] = canon_destino(ev["destino"])
    ev["_name"] = norm_name(ev["persona"])
    ev["_doc"] = norm_doc(ev["documento"])


def assign_ids(only_a, only_b, conflicts):
    """Give every review item a stable id (same inputs -> same id)."""
    seen = Counter()
    for kind, lst in (("a", only_a), ("b", only_b), ("c", conflicts)):
        for ev in lst:
            src = ev.get("_a", ev)
            raw = "|".join([kind, src["batch"], src["decreto"], src["tipo"],
                            src["persona"], src["documento"], src["filiacion"]])
            h = kind + "_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
            seen[h] += 1
            ev["_id"] = h if seen[h] == 1 else f"{h}-{seen[h]}"


def compute():
    """Load both agents and pair their events. Shared with adjudicate.py."""
    a, b = load("a"), load("b")
    batches_a = {e["batch"] for e in a}
    batches_b = {e["batch"] for e in b}
    both = batches_a & batches_b
    confirmed, only_a, only_b, conflicts = match(
        [e for e in a if e["batch"] in both], [e for e in b if e["batch"] in both]
    )
    assign_ids(only_a, only_b, conflicts)
    single = [e for e in a if e["batch"] not in both] + [e for e in b if e["batch"] not in both]
    return a, b, batches_a, batches_b, confirmed, only_a, only_b, conflicts, single


def load_resolutions():
    """id -> resolution, from review/resolved/*.json (written by adjudicate.py)."""
    res = {}
    for f in sorted(glob.glob(os.path.join(ROOT, "review", "resolved", "*.json"))):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"WARN {f}: {e}", file=sys.stderr)
            continue
        for r in d.get("resoluciones", []):
            if isinstance(r, dict) and r.get("id") and r.get("veredicto") in ("confirmar", "descartar", "dudoso"):
                res[r["id"]] = r
    return res


def apply_resolutions(confirmed, only_a, only_b, conflicts, res):
    """Apply the adjudicator's verdicts.

    Returns (confirmed, resolved_single, only_a, only_b, conflicts, discarded, stats)
    where only_a / only_b / conflicts are what is still left for manual review.
    """
    stats = Counter()
    discarded = []

    def fix(ev, r, agente):
        new = r.get("evento") or {}
        for k in FIELDS:
            if k in new:
                ev[k] = str(new[k] or "").strip()
        renorm(ev)
        ev["agente"] = agente
        ev["motivo"] = r.get("motivo", "")

    left_conf, dropped = [], set()
    for ev in conflicts:
        r = res.get(ev["_id"])
        v = r["veredicto"] if r else ""
        if v == "confirmar" and isinstance(r.get("evento"), dict):
            fix(ev, r, "a+b")
            stats["conf_ok"] += 1
        elif v == "descartar":
            ev["motivo"] = "descartado: " + r.get("motivo", "")
            dropped.add(id(ev))
            discarded.append(ev)
            stats["conf_drop"] += 1
        else:
            if r:
                ev["motivo_f"] = r.get("motivo", "")
            left_conf.append(ev)
    confirmed = [e for e in confirmed if id(e) not in dropped]

    seen = set()
    for e in confirmed:
        seen.add(key(e, False))
        if e["_doc"]:
            seen.add(key(e, True))
    resolved, left = [], {"a": [], "b": []}
    for tag, lst in (("a", only_a), ("b", only_b)):
        for ev in lst:
            r = res.get(ev["_id"])
            v = r["veredicto"] if r else ""
            if v == "confirmar" and isinstance(r.get("evento"), dict):
                fix(ev, r, tag + "+f")
                k = key(ev, bool(ev["_doc"]))
                if k in seen:
                    ev["motivo"] = "descartado: duplicado de un evento ya confirmado"
                    discarded.append(ev)
                    stats["solo_dup"] += 1
                    continue
                seen.add(key(ev, False))
                if ev["_doc"]:
                    seen.add(key(ev, True))
                resolved.append(ev)
                stats["solo_ok"] += 1
            elif v == "descartar":
                ev["motivo"] = "descartado: " + r.get("motivo", "")
                discarded.append(ev)
                stats["solo_drop"] += 1
            else:
                if r:
                    ev["motivo_f"] = r.get("motivo", "")
                left[tag].append(ev)
    return confirmed, resolved, left["a"], left["b"], left_conf, discarded, stats


def person_id(ev):
    return ("doc:" + ev["_doc"]) if ev["_doc"] else ("nom:" + ev["_name"])


def build_people(events):
    people = defaultdict(lambda: {"eventos": [], "nombres": set(), "docs": set(), "fil": set()})
    # first pass: by document; then merge name-only events into a doc person with the same name
    name_to_doc = {}
    for ev in events:
        if ev["_doc"]:
            name_to_doc.setdefault(ev["_name"], ev["_doc"])
    for ev in events:
        pid = person_id(ev)
        if not ev["_doc"] and ev["_name"] in name_to_doc:
            pid = "doc:" + name_to_doc[ev["_name"]]
        p = people[pid]
        p["eventos"].append(ev)
        p["nombres"].add(ev["persona"])
        if ev["documento"]:
            p["docs"].add(ev["documento"])
        if ev["filiacion"]:
            p["fil"].add(ev["filiacion"])
    return people


def date_key(s):
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s or "")
    return (int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else (9999, 0, 0)


def style_header(ws):
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="DDDDDD")
        c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"
    for i, col in enumerate(ws.columns, 1):
        width = max(len(str(c.value or "")) for c in list(col)[:200])
        ws.column_dimensions[get_column_letter(i)].width = min(max(10, width + 2), 60)


def people_sheet(ws, people, pids):
    head = ["Persona", "Documento", "Filiación"]
    for t in TIPOS[:7]:
        head += [f"{TIPO_LABEL[t]} - decretos", f"{TIPO_LABEL[t]} - fechas"]
        if t in ("salida_autorizada", "expulsion"):
            head += [f"{TIPO_LABEL[t]} - destino"]
        if t == "libertad_vigilada":
            head += ["Libertad vigilada - lugar"]
    head += ["Otros eventos / notas", "Decretos referidos", "Páginas PDF"]
    ws.append(head)
    for pid in pids:
        p = people[pid]
        evs = sorted(p["eventos"], key=lambda e: (date_key(e["fecha"]), e["decreto"]))
        row = [" / ".join(sorted(p["nombres"], key=len, reverse=True)[:3]),
               " / ".join(sorted(p["docs"])), " / ".join(sorted(p["fil"]))]
        for t in TIPOS[:7]:
            sub = [e for e in evs if e["tipo"] == t]
            row += [" ; ".join(e["decreto"] for e in sub), " ; ".join(e["fecha"] for e in sub)]
            if t in ("salida_autorizada", "expulsion"):
                row += [" ; ".join(e["destino"] for e in sub if e["destino"])]
            if t == "libertad_vigilada":
                row += [" ; ".join(e["nota"] for e in sub if e["nota"])]
        otros = [f"{e['decreto']} ({e['fecha']}): {e['nota']}" for e in evs if e["tipo"] == "otro" or (e["nota"] and e["tipo"] != "libertad_vigilada")]
        row += [" ; ".join(otros),
                " ; ".join(sorted({e["decreto_referido"] for e in evs if e["decreto_referido"]})),
                " ; ".join(sorted({e["pagina"] for e in evs if e["pagina"]}, key=lambda s: int(re.sub(r"\D", "", s) or 0)))]
        ws.append(row)
    style_header(ws)


def events_sheet(ws, events, internal=False):
    """internal=True adds the bookkeeping columns (revisar.xlsx only)."""
    head = ["Persona", "Documento", "Filiación", "Tipo", "Decreto", "Fecha", "Destino",
            "Decreto referido", "Página PDF", "Nota"]
    if internal:
        head += ["Lote", "Agente", "Motivo"]
        events = sorted(events, key=lambda e: (e["batch"], e["decreto"], e["tipo"], e["persona"]))
    else:
        dk = lambda e: (date_key(e["fecha"]), [int(x) for x in re.findall(r"\d+", e["decreto"])], e["tipo"], e["persona"])  # noqa: E731
        events = sorted(events, key=dk)
    ws.append(head)
    for e in events:
        row = [e["persona"], e["documento"], e["filiacion"], TIPO_LABEL[e["tipo"]], e["decreto"],
               e["fecha"], e["destino"], e["decreto_referido"], e["pagina"], e["nota"]]
        if internal:
            row += [e["batch"], e["agente"], e.get("motivo", "")]
        ws.append(row)
    style_header(ws)


def main() -> int:
    a, b, batches_a, batches_b, confirmed, only_a, only_b, conflicts, single = compute()
    print(f"agent a: {len(a)} eventos in {len(batches_a)} batches; agent b: {len(b)} in {len(batches_b)}")
    both = batches_a & batches_b
    print(f"confirmed {len(confirmed)} (with field conflicts {len(conflicts)}), only a {len(only_a)}, only b {len(only_b)}, single-agent batches {len(single)}")
    n_review = len(only_a) + len(only_b) + len(conflicts)

    res = load_resolutions()
    confirmed, resolved, only_a, only_b, conflicts, discarded, st = apply_resolutions(
        confirmed, only_a, only_b, conflicts, res)
    if res:
        print(f"adjudicated: conflicts settled {st['conf_ok']}, single-agent confirmed {st['solo_ok']}, "
              f"discarded {st['solo_drop'] + st['solo_dup'] + st['conf_drop']}; "
              f"left for manual review {len(only_a) + len(only_b) + len(conflicts)} of {n_review}")

    all_events = confirmed + resolved + only_a + only_b + single
    people = build_people(all_events)
    with_option = [pid for pid, p in people.items() if any(e["tipo"] != "arresto" for e in p["eventos"])]
    arrest_only = [pid for pid in people if pid not in set(with_option)]
    sort_key = lambda pid: norm_name(sorted(people[pid]["nombres"])[0]).split()[-1:] + [pid]  # noqa: E731
    with_option.sort(key=sort_key)
    arrest_only.sort(key=sort_key)

    wb = Workbook()
    ws = wb.active
    ws.title = "Personas"
    people_sheet(ws, people, with_option)
    people_sheet(wb.create_sheet("Solo arresto"), people, arrest_only)
    events_sheet(wb.create_sheet("Eventos"), all_events)
    ws = wb.create_sheet("Resumen")
    ws.append(["Métrica", "Valor"])
    rows = [
        ("Personas con eventos de opción/otros", len(with_option)),
        ("Personas sólo con arresto", len(arrest_only)),
        ("Eventos (total)", len(all_events)),
    ] + [(f"Eventos: {TIPO_LABEL[t]}", sum(1 for e in all_events if e["tipo"] == t)) for t in TIPOS]
    for r in rows:
        ws.append(list(r))
    style_header(ws)
    wb.save(os.path.join(ROOT, "opcion.xlsx"))

    # revisar.xlsx: internal working file (what is left to check by hand + bookkeeping)
    wb = Workbook()
    ws = wb.active
    ws.title = "Sólo un agente"
    for e in only_a + only_b:
        e["motivo"] = "sólo agente " + e["agente"]
    for e in conflicts:
        e["motivo"] = "campos distintos: " + e.get("_diff", "")
    for e in only_a + only_b + conflicts:
        if e.get("motivo_f"):
            e["motivo"] += " | adjudicador (dudoso): " + e["motivo_f"]
    events_sheet(ws, only_a + only_b, internal=True)
    events_sheet(wb.create_sheet("Campos en conflicto"), conflicts, internal=True)
    if discarded:
        events_sheet(wb.create_sheet("Descartados"), discarded, internal=True)
    ws = wb.create_sheet("Resumen")
    ws.append(["Métrica", "Valor"])
    rows = [
        ("Lotes procesados por ambos agentes", len(both)),
        ("Lotes procesados por un solo agente", len(batches_a ^ batches_b)),
        ("Eventos en que ambos agentes coinciden", len(confirmed)),
        ("Ítems enviados a revisión (antes de adjudicar)", n_review),
        ("Adjudicador: conflictos de campos resueltos", st["conf_ok"]),
        ("Adjudicador: eventos de un solo agente confirmados", st["solo_ok"]),
        ("Adjudicador: eventos descartados", st["solo_drop"] + st["solo_dup"] + st["conf_drop"]),
        ("Pendientes: sólo agente A", len(only_a)),
        ("Pendientes: sólo agente B", len(only_b)),
        ("Pendientes: campos en conflicto", len(conflicts)),
        ("Pendientes de revisión manual (total)", len(only_a) + len(only_b) + len(conflicts)),
    ]
    for r in rows:
        ws.append(list(r))
    style_header(ws)
    wb.save(os.path.join(ROOT, "revisar.xlsx"))

    with open(os.path.join(ROOT, "eventos.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(FIELDS)
        for e in sorted(all_events, key=lambda e: (date_key(e["fecha"]), e["decreto"], e["tipo"], e["persona"])):
            w.writerow([e[k] for k in FIELDS])
    print("wrote opcion.xlsx, revisar.xlsx, eventos.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
