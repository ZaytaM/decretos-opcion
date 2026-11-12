# Tarea: adjudicar discrepancias entre dos extractores (decretos secretos 1976–1983)

Sos el revisor final de una extracción de datos históricos. Dos agentes
independientes (A y B) leyeron los mismos decretos del Poder Ejecutivo Nacional
argentino ("Decretos secretos y reservados", Boletín Oficial 2013) y produjeron
un evento por cada persona nombrada en la parte dispositiva. En la mayoría de
los eventos coincidieron; acá recibís sólo los que **no** coincidieron, junto con
el texto completo del decreto. Tu trabajo es decidir, leyendo el texto, cuál es
el dato correcto.

No uses herramientas. No leas ni escribas archivos. Respondé únicamente con JSON.

## Qué recibís

Por cada decreto:

1. El texto del decreto (empieza con `=== DECRETO numero/año | fecha | paginas PDF | id ===`).
2. La lista de eventos de ese decreto en los que A y B ya coincidieron (sólo
   como contexto: `tipo | persona | documento`). No los devuelvas.
3. Los **ítems a resolver**, cada uno con un `id` y una `clase`:
   - `conflicto`: A y B encontraron el mismo evento pero difieren en algún
     campo. Vienen las dos versiones (`a` y `b`).
   - `solo_a` / `solo_b`: sólo un agente produjo el evento. Puede ser (i) un
     evento real que el otro omitió, (ii) un evento inexistente o mal
     clasificado, o (iii) el mismo evento que otro ítem `solo_*` del mismo
     decreto, escrito distinto (nombre con otra grafía, otro `tipo`, etc.).

## Qué devolver

Un único objeto JSON, sin texto antes ni después, sin bloque de código, con una
resolución por **cada** `id` recibido:

```
{"resoluciones": [
  {"id": "c_1a2b3c4d5e6f", "veredicto": "confirmar",
   "evento": {"persona": "...", "documento": "...", "filiacion": "...", "tipo": "...",
              "decreto": "...", "fecha": "...", "destino": "...",
              "decreto_referido": "...", "pagina": "...", "nota": "..."},
   "motivo": "el texto dice 'CI 7.490.739'; B leyó mal un dígito"},
  {"id": "b_0f9e8d7c6b5a", "veredicto": "descartar",
   "motivo": "duplicado de a_112233445566 (misma persona, grafía de A es la del texto)"},
  {"id": "a_aabbccddeeff", "veredicto": "dudoso",
   "motivo": "el texto está truncado y no permite saber si el artículo 2 la incluye"}
]}
```

- `confirmar`: el evento existe. `evento` lleva los diez campos con el valor
  correcto según el texto (podés tomar la versión de A, la de B, o corregir
  ambas). Obligatorio incluir `evento` completo.
- `descartar`: el evento no debe figurar: no surge del texto, la persona sólo
  aparece en los considerandos, es un duplicado de otro evento (de la lista de
  ya confirmados o de otro ítem que confirmás), o el decreto no es pertinente.
  Si dos ítems `solo_a` y `solo_b` son la misma persona y el mismo hecho,
  confirmá uno (con los campos correctos) y descartá el otro.
- `dudoso`: usalo **sólo** cuando el texto recibido no alcanza para decidir si
  el evento existe, a quién se refiere, o qué valor tiene un campo esencial
  (persona, documento, tipo). No lo uses por diferencias de formato ni por
  dudas menores sobre campos accesorios: en esos casos decidí.
- `motivo`: una frase corta que cite lo que dice el texto. Obligatorio siempre.

## Reglas de cada campo (las mismas que siguieron A y B)

- `persona`: el nombre tal como aparece en el texto, con el apellido en
  mayúsculas como en el original. Se corrigen sólo los cortes de palabra por
  guión al final de línea ("WAG-\nNER" → "WAGNER"). No se normaliza ni se
  reordena. Si el texto trae una errata evidente (por ejemplo una letra
  reemplazada por un guión), transcribí lo que dice el texto y aclaralo en
  `nota` ("el texto dice 'Ermin-do'"); eso es `confirmar`, no `dudoso`.
- `documento`: tipo y número tal como aparece ("MI 6.999.516", "DNI 11.773.399",
  "LE 7.936.542", "CI 4.947.075", "CI chilena 168.907", "Ppte. 06234"). Vacío si
  no hay. Entre dos lecturas, vale la que coincide dígito por dígito con el texto.
  Si el texto dice "Cl" o "Cl." donde corresponde "CI" (cédula de identidad),
  escribí "CI".
- `filiacion`: "hijo de … y …" si aparece en lugar del documento; si no, vacío.
- `tipo`: uno de `arresto`, `opcion_denegada`, `opcion_diferida`,
  `libertad_vigilada`, `liberacion`, `salida_autorizada`, `expulsion`, `otro`.

  | `tipo`              | Frases típicas                                                                                     |
  |---------------------|----------------------------------------------------------------------------------------------------|
  | `arresto`           | "Arréstese / Arréstase a disposición del Poder Ejecutivo Nacional a: …"                            |
  | `opcion_denegada`   | "Deniégase / No se hace lugar a la solicitud de opción para salir (abandonar) el país…"            |
  | `opcion_diferida`   | "Difiérese la resolución / consideración de la solicitud de opción…"                               |
  | `libertad_vigilada` | "…cumplirá el arresto bajo régimen de libertad vigilada…", "Modifícase la forma de aplicación…"     |
  | `liberacion`        | "Déjase sin efecto el arresto a disposición del Poder Ejecutivo Nacional…"                         |
  | `salida_autorizada` | "Autorízase la salida del país…", "Hácese lugar a la solicitud de opción…", "Concédese la opción…" |
  | `expulsion`         | "Dispónese la expulsión de la República Argentina…" (extranjeros)                                  |
  | `otro`              | Cualquier otra medida sobre una persona arrestada o detenida a disposición del PEN (explicar en `nota`) |

- `decreto`: número/año del decreto que contiene el evento (de la línea
  `=== DECRETO … ===`). En las fe de erratas, el decreto que se corrige.
- `fecha`: la fecha del decreto, de la misma línea, formato d/m/aaaa.
- `destino`: sólo para `salida_autorizada` o `expulsion`: país o ciudad de
  destino si el decreto lo menciona; si no, vacío.
- `decreto_referido`: el decreto anterior que el texto asocia con esa persona
  ("detenido por Decreto Nº 1205/76" → "1205/1976"; o el decreto de arresto del
  VISTO cuando es uno solo), en formato numero/aaaa. Vacío si no hay o si es
  ambiguo (varios decretos sin que el texto diga cuál corresponde a la persona).
- `pagina`: la página PDF del encabezado del decreto (si hay rango, la primera).
- `nota`: vacío salvo para `otro` (qué medida es), `libertad_vigilada` (lugar de
  cumplimiento), fe de erratas ("fe de erratas: donde dice X debe decir Y") o
  cuando el texto sea ilegible o traiga una errata.

Sólo cuentan las personas nombradas en la parte dispositiva (los artículos), o
en los considerandos cuando los artículos remiten a ellas.

## Caso
