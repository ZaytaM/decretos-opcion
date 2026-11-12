# decretos-opcion

Extracción, por persona, de los eventos relacionados con el "derecho de opción"
(arresto a disposición del PEN, opción denegada / diferida, libertad vigilada,
liberación, salida del país autorizada) a partir del suplemento del Boletín
Oficial "Decretos secretos y reservados" (1.248 páginas, 7.038 decretos).

## Pipeline

| Paso | Qué | Dónde | Cómo |
|------|-----|-------|------|
| 1 | `scripts/split.py` corta el PDF en un .txt por decreto y arma `batches/batch_NNN.txt` (25 decretos relevantes por lote) | Mac o dell3, ~1 min | `python3 scripts/split.py` |
| 2 | `scripts/run_agents.sh` corre dos agentes independientes (`prompts/extract.md` → `events/a/`, `prompts/verify.md` → `events/b/`) con `claude -p` sobre cada lote, 3 a la vez, reintentando ante límites de uso y salteando lo ya hecho | dell3, horas | ver abajo |
| 3 | `scripts/merge.py` compara ambos agentes y escribe `opcion.xlsx` (personas), `revisar.xlsx` (desacuerdos) y `eventos.csv` | cualquiera, segundos | `python3 scripts/merge.py` |

Dependencias: `pip install --user pymupdf openpyxl` y Claude Code (`claude`).

## En dell3

```bash
# piloto: lotes 1 y 2 (50 decretos, ~15 min)
ssh dell3 'tmux new -d -s pilot "bash ~/bin/dell3_run.sh decretos-opcion cmd \"bash scripts/run_agents.sh 1 2 && python3 scripts/merge.py\""'
# corrida completa
ssh dell3 'tmux new -d -s full "bash ~/bin/dell3_run.sh decretos-opcion cmd \"bash scripts/run_agents.sh && python3 scripts/merge.py\""'
# seguir
ssh dell3 'tail -40 ~/work/decretos-opcion/logs/agents_latest.log'
```

Los resultados vuelven por git: `git pull` en la Mac y abrir `opcion.xlsx`.

## Archivos

- `pdf/decretos.pdf` fuente (37 MB)
- `batches/` lotes de entrada a los agentes (generados, versionados)
- `decretos/` un .txt por decreto + `index.csv` (generados, no versionados salvo el índice)
- `events/a`, `events/b` salida JSON de cada agente por lote; `events/raw` respuestas crudas
- `opcion.xlsx`, `revisar.xlsx`, `eventos.csv` resultado
