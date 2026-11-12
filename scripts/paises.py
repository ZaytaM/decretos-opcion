#!/usr/bin/env python3
"""Normalize the destination countries (`destino`) to one spelling per country.

    python3 scripts/paises.py          # ask the model about values not yet in paises.json
    python3 scripts/paises.py --list   # show the current mapping, no model call

The decrees name the same country in many ways ("Reino de España", "República
de España", "ESPAÑA"). This script collects every distinct `destino` the agents
(and the adjudicator) produced, asks a model for the country each one refers
to, and stores the answer in paises.json:

    {"Reino de España": {"pais": "España", "iso3": "ESP", "ciudad": ""}, ...}

Criterion: `pais` is the country's current short name in Spanish as used by the
UN / ISO 3166 ("España", "Estados Unidos", "Reino Unido", "Países Bajos",
"Alemania"); `iso3` is its ISO 3166-1 alpha-3 code; `ciudad` is the city if the
text names one. Values that are not a specific country ("un país no
limítrofe") get an empty `pais` and are left as written.

merge.py reads paises.json and writes `pais` (plus the city in parentheses) in
the Destino column. The file is plain JSON: edit it by hand to override.

Env knobs: MODEL (opus).
"""
import glob
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "paises.json")
MODEL = os.environ.get("MODEL", "opus")

PROMPT = """Sos un asistente de normalización de datos. Abajo hay una lista JSON de textos
tomados de decretos argentinos de 1974-1983 que indican el país (a veces la
ciudad) de destino de una persona autorizada a salir del país o expulsada.
El mismo país aparece escrito de muchas formas.

Para cada texto devolvé:
- "pais": el nombre corto actual del país en español, según la lista de la ONU /
  ISO 3166 (por ejemplo "España", "Estados Unidos", "Reino Unido", "Países
  Bajos", "Alemania", "México", "Perú", "Suecia"). Sin "República de", "Reino
  de", "Estado de", etc. "Inglaterra" y "Gran Bretaña" son "Reino Unido";
  "Holanda" es "Países Bajos"; "República Federal de Alemania" es "Alemania".
  Si el texto no identifica un país concreto, "".
- "iso3": el código ISO 3166-1 alfa-3 de ese país ("" si no hay país).
- "ciudad": la ciudad si el texto la nombra; si no, "".

No uses herramientas. Respondé únicamente con un objeto JSON, sin texto antes ni
después y sin bloque de código, cuyas claves sean exactamente los textos
recibidos:

{"Reino de España": {"pais": "España", "iso3": "ESP", "ciudad": ""}}

Textos:
"""


def distinct():
    vals = set()
    for f in glob.glob(os.path.join(ROOT, "events", "[ab]", "batch_*.json")):
        try:
            evs = json.load(open(f, encoding="utf-8")).get("eventos", [])
        except Exception:  # noqa: BLE001
            continue
        vals |= {str(e.get("destino") or "").strip() for e in evs if isinstance(e, dict)}
    for f in glob.glob(os.path.join(ROOT, "review", "resolved", "*.json")):
        try:
            rs = json.load(open(f, encoding="utf-8")).get("resoluciones", [])
        except Exception:  # noqa: BLE001
            continue
        vals |= {str((r.get("evento") or {}).get("destino") or "").strip() for r in rs if isinstance(r, dict)}
    vals.discard("")
    return sorted(vals)


def main():
    mapping = json.load(open(PATH, encoding="utf-8")) if os.path.exists(PATH) else {}
    if "--list" in sys.argv:
        for k, v in sorted(mapping.items(), key=lambda kv: (kv[1].get("pais", ""), kv[0])):
            print(f"{v.get('pais') or '(sin país)':20} {v.get('iso3', ''):4} {v.get('ciudad', ''):12} <- {k}")
        return 0
    todo = [v for v in distinct() if v not in mapping]
    print(f"distinct destinos {len(distinct())}, already mapped {len(mapping)}, to ask {len(todo)}")
    if not todo:
        return 0
    os.environ["PATH"] = os.path.expanduser("~/.local/bin") + os.pathsep + os.environ.get("PATH", "")
    p = subprocess.run(
        ["claude", "-p", "--model", MODEL, "--output-format", "json", "--tools", "",
         "--no-session-persistence", "--strict-mcp-config"],
        input=PROMPT + json.dumps(todo, ensure_ascii=False, indent=1), capture_output=True, text=True, timeout=1800)
    raw = p.stdout
    try:
        outer = json.loads(raw)
        if isinstance(outer, dict) and "result" in outer:
            raw = outer["result"] if isinstance(outer["result"], str) else json.dumps(outer["result"])
    except Exception:  # noqa: BLE001
        pass
    raw = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", raw.strip())
    try:
        d = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
    except Exception:  # noqa: BLE001
        print(f"model reply is not JSON (rc={p.returncode}): {raw[:300]} {p.stderr[:200]}", file=sys.stderr)
        return 1
    added = 0
    for k in todo:
        v = d.get(k)
        if isinstance(v, dict):
            mapping[k] = {f: str(v.get(f, "") or "").strip() for f in ("pais", "iso3", "ciudad")}
            added += 1
    json.dump(dict(sorted(mapping.items())), open(PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"mapped {added} of {len(todo)} new values; {len({v['pais'] for v in mapping.values() if v['pais']})} countries in paises.json")
    return 0 if added == len(todo) else 1


if __name__ == "__main__":
    sys.exit(main())
