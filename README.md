# decretos-opcion

Extracción, por persona, de los eventos relacionados con el "derecho de opción"
(arresto a disposición del PEN, opción denegada / diferida, libertad vigilada,
liberación, salida del país autorizada, expulsión) a partir del suplemento del
Boletín Oficial "Decretos secretos y reservados" (1.248 páginas, 7.039 decretos,
1974–1983).

Resultado: `opcion.xlsx` (hoja **Personas**: 8.291 filas; **Solo arresto**: 746;
**Eventos**: 21.559; **Resumen**) y `revisar.xlsx` (3 ítems sin resolver,
98 descartados con su motivo). `eventos.csv` es la hoja Eventos en texto plano.
Corrida del 12 de noviembre de 2026.

| Tipo de evento | Cantidad |
|---|---|
| Arresto a disposición del PEN | 7.680 |
| Opción denegada | 3.459 |
| Opción diferida | 187 |
| Libertad vigilada | 1.660 |
| Liberación (sin efecto el arresto) | 7.395 |
| Salida del país autorizada | 665 |
| Expulsión | 268 |
| Otro (rectificaciones, fe de erratas, cambios de régimen) | 245 |

## Qué se hizo

| Paso | Qué | Script | Dónde / cuánto |
|------|-----|--------|----------------|
| 1 | Cortar el PDF en un .txt por decreto (marcadores `#I…I#` / `#F…F#`), leyendo cada página en cuatro franjas de columna debajo del encabezado. Marcar como relevantes los que hablan de arresto, detención, opción, libertad vigilada, salida o expulsión: 3.360 de 7.039. Armar 135 lotes de 25. | `scripts/split.py` | Mac, 1 min |
| 2 | Dos agentes independientes (`claude -p`, modelo Sonnet) leen cada lote con instrucciones distintas (`prompts/extract.md` → `events/a/`, `prompts/verify.md` → `events/b/`) y devuelven un evento por persona en JSON. 3 lotes a la vez; reintenta ante límites de uso; saltea lo ya hecho. | `scripts/run_agents.sh` | dell3, 4,5 h (260 de 270 trabajos; 6 lotes se agotaron por límite de uso y se corrieron de nuevo en 3 min) |
| 3 | Adjudicación: los eventos que sólo un agente encontró, o donde difieren en algún campo, se mandan con el texto completo del decreto a un modelo más fuerte (Fable) que decide `confirmar` / `descartar` / `dudoso` con motivo. 745 ítems en 15 min. | `scripts/adjudicate.py`, `prompts/adjudicate.md` | dell3 |
| 4 | Normalizar destinos: cada valor distinto de `destino` ("Reino de España", "ESPAÑA") se mapea a un nombre de país único (`paises.json`, editable a mano). | `scripts/paises.py` | dell3, 1 min |
| 5 | Fusionar: aparear los eventos de A y B (mismo decreto + tipo + persona, por número de documento si lo hay, si no por nombre normalizado), aplicar las resoluciones del adjudicador, agrupar por persona y escribir los Excel. | `scripts/merge.py` | segundos |

Piloto previo sobre 50 decretos: 752 eventos por agente, 751 coincidentes.
En la corrida completa los dos agentes coincidieron en todo salvo 752 ítems
(3,5 %), de los cuales el adjudicador confirmó 651, descartó 98 y dejó 3 dudosos.

### Qué se verificó a mano

- Los 50 decretos del piloto, nombre por nombre, contra el PDF.
- Conteo de nombres por decreto contra el texto en los decretos más largos
  (83, 81, 57 y 51 personas): coincidencia exacta.
- Los 98 descartados del adjudicador: muestreo de los que no son duplicados
  evidentes. Todos correctos. Las categorías son: (a) un agente registró la
  grafía errónea *y* la corregida de una fe de erratas como dos personas;
  (b) "continuará arrestada" leído como nuevo arresto; (c) "déjase sin efecto
  el arresto en el momento que haga abandono del país" dentro de un decreto
  de expulsión, registrado además como liberación (ver decisión de modelado
  abajo); (d) "déjase sin efecto lo resuelto por el Decreto X" sin precisar
  la medida.

### Decisiones de modelado que conviene conocer

- **Un decreto de expulsión que además deja sin efecto el arresto** cuenta
  sólo como `expulsion`, no como `liberacion`. Si para el análisis importa
  la fecha de cese del arresto, esa fecha está en la columna de expulsión.
- **Fe de erratas y rectificaciones de nombre** son eventos `otro` con la
  nota "donde dice X debe decir Y", a nombre de la grafía corregida.
- **"Decretos referidos"** es el decreto anterior que el texto cita para esa
  persona (por ejemplo el arresto que se deja sin efecto). Sirve para enlazar
  filas; no se usó todavía para fusionar personas.
- **Los números de decreto se repiten**: 98 números aparecen dos veces con
  fechas distintas (la numeración volvió a empezar tras el golpe de marzo de
  1976). Por eso cada columna de decretos tiene al lado su columna de fechas;
  nunca identificar un decreto sólo por su número.
- El filtro de relevancia del paso 1 es amplio a propósito. Los 3.679
  decretos excluidos son nombramientos, comisiones al exterior, armas, ceses,
  etc.; se revisó una muestra.

## Qué falta para limpiar los datos

En orden de impacto.

1. **33 decretos truncados por el corte en columnas** (8 relevantes: 567/1978,
   1321/1978, 2983/1978, 540/1979, 445/1981, 257/1982, 255/1983, 3050/1977).
   En algunas páginas el texto de un decreto no sigue el orden columna 1→4 que
   asume `split.py` (por ejemplo página 191: un decreto empieza al pie de la
   columna 3 y sigue arriba de la 4 mientras otro termina en medio), y el
   decreto queda sin su parte dispositiva. Son exactamente los 3 ítems
   "dudosos" de `revisar.xlsx` más cinco personas que faltan. Arreglo:
   detectar el orden de lectura por página a partir de los bloques del PDF
   (o cortar por marcador con el mismo id de inicio y fin) y volver a correr
   sólo esos 8 decretos. Lista completa: los archivos de `decretos/` sin
   "Artículo 1".
2. **Personas repetidas por no tener documento.** 634 filas no tienen número
   de documento; se agruparon por nombre normalizado. Cuando la misma persona
   aparece con documento en un decreto y sin documento (o con filiación) en
   otro, quedan dos filas. Hay 157 nombres normalizados que aparecen en más de
   una fila; una parte son homónimos reales. Arreglo: fusionar cuando además
   coinciden el "decreto referido" o la filiación; el resto revisar a mano.
3. **Variantes de grafía dentro de una fila.** 975 filas acumulan dos o tres
   grafías del nombre (OCR: "Amuel" por "Manuel", "Cl" por "CI") y 2.343
   acumulan variantes de formato del documento ("MI", "M.I.", "M.I. nº").
   Están unidas con " / ". Arreglo: elegir una grafía canónica por fila (la
   más frecuente o la de la rectificación si la hubo) y normalizar el
   documento a "TIPO número".
4. **Enlazar arrestos con liberaciones usando "Decretos referidos".** Hoy la
   fila junta todo lo que lleva el mismo documento o nombre. Con la columna
   de decretos referidos se puede verificar que la liberación cita el
   decreto de arresto de la misma fila, y detectar filas mal fusionadas.
5. **Cruzar los 746 "sólo arresto" con el resto**: son personas que aparecen
   en un decreto de arresto y en ningún otro. Algunas estarán en los 8
   decretos truncados; otras pueden estar en otra fila por grafía distinta.
6. **Fechas de "fe de erratas"**: tres decretos de corrección no tienen fecha
   propia; sus eventos llevan fecha vacía.
7. **Destinos**: 28 países distintos después de normalizar; quedan 2 o 3
   valores genéricos ("un país no limítrofe") sin país asignado, a propósito.
8. **Segunda lectura de los lotes con límite de uso**: los lotes 103–106 se
   leyeron en una segunda corrida, con el mismo resultado de concordancia,
   pero conviene saber que su ejecución fue distinta al resto.

## Cómo reproducir o continuar

```bash
# dependencias
pip install --user pymupdf openpyxl      # en dell3: --break-system-packages
# 1. cortar (sólo si cambia split.py)
python3 scripts/split.py
# 2. agentes (saltea lo hecho; N M = rango de lotes, opcional)
bash scripts/run_agents.sh [N M]
# 3. adjudicar desacuerdos (saltea lo resuelto)
python3 scripts/adjudicate.py
# 4. destinos nuevos
python3 scripts/paises.py
# 5. fusionar
python3 scripts/merge.py
```

En dell3, todo junto y desatendido:

```bash
ssh dell3 'tmux new -d -s run "bash ~/bin/dell3_run.sh decretos-opcion cmd \"bash scripts/run_agents.sh && python3 scripts/adjudicate.py && python3 scripts/paises.py && python3 scripts/merge.py\""'
ssh dell3 'tail -40 ~/work/decretos-opcion/logs/agents_latest.log'
```

Los resultados vuelven por git: `git pull` en la Mac. Para repetir sólo
algunos lotes, borrar sus `events/a/batch_NNN.json` y `events/b/batch_NNN.json`
y volver a correr el paso 2. El login de Claude en dell3 vence periódicamente
(`claude auth login` o `claude setup-token`).

## Archivos

- `pdf/decretos.pdf` fuente (37 MB)
- `batches/` lotes de entrada a los agentes (generados, versionados)
- `decretos/` un .txt por decreto + `index.csv` (sólo el índice versionado)
- `events/a`, `events/b` salida JSON de cada agente; `events/raw` respuestas crudas (no versionado)
- `review/` ítems de desacuerdo y resoluciones del adjudicador
- `paises.json` mapa destino → país
- `opcion.xlsx`, `revisar.xlsx`, `eventos.csv` resultado
- `docs/` guía para colegas sin experiencia en agentes (md y pdf) y diagrama
- `logs/` registros de cada corrida (en dell3; no versionados)
