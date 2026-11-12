# Tarea: extracción de eventos sobre personas en decretos secretos (1976–1983)

Sos un asistente de investigación histórica. Recibís a continuación un lote de
decretos del Poder Ejecutivo Nacional argentino (publicados en el Boletín Oficial
en 2013 como "Decretos secretos y reservados"). Cada decreto empieza con una
línea `=== DECRETO numero/año | fecha d/m/aaaa | paginas PDF n | id ... ===`.

No uses herramientas. No leas ni escribas archivos. Respondé únicamente con JSON.

## Qué extraer

Un **evento** por cada persona nombrada en la parte dispositiva (los artículos)
de cada decreto, para estos tipos:

| `tipo`              | Cuándo aplica (frases típicas)                                                                      |
|---------------------|-----------------------------------------------------------------------------------------------------|
| `arresto`           | "Arréstese / Arréstase a disposición del Poder Ejecutivo Nacional a: …"                             |
| `opcion_denegada`   | "Deniégase / No se hace lugar a la solicitud de opción para salir (abandonar) el país…"             |
| `opcion_diferida`   | "Difiérese la resolución / consideración de la solicitud de opción…"                                |
| `libertad_vigilada` | "…cumplirá el arresto bajo régimen de libertad vigilada…", "Modifícase la forma de aplicación…"      |
| `liberacion`        | "Déjase sin efecto el arresto a disposición del Poder Ejecutivo Nacional…"                          |
| `salida_autorizada` | "Autorízase la salida del país…", "Hácese lugar a la solicitud de opción…", "Concédese la opción…"  |
| `expulsion`         | "Dispónese la expulsión de la República Argentina…" (extranjeros)                                   |
| `otro`              | Cualquier otra medida sobre una persona arrestada o detenida a disposición del PEN (explicar en `nota`) |

Ignorá los decretos que no se refieren a personas arrestadas, detenidas o con
solicitud de opción (nombramientos, comisiones militares, armas, etc.): no
producen eventos. Ignorá a las personas mencionadas sólo en los considerandos,
salvo que la parte dispositiva remita a ellas ("las personas mencionadas en el
considerando primero"): en ese caso sí incluilas.

Un decreto puede contener varios tipos de evento (por ejemplo, un artículo
deniega la opción a unas personas y otro la difiere a otras). Un decreto con 40
personas produce 40 eventos. No omitas a nadie ni resumas: la lista completa de
nombres es el resultado principal.

## Formato de salida

Un único objeto JSON, sin texto antes ni después, sin bloque de código:

```
{"eventos": [
  {"persona": "Héctor Oscar FERNANDEZ",
   "documento": "",
   "filiacion": "hijo de Santiago y Damina Videla",
   "tipo": "liberacion",
   "decreto": "1282/1976",
   "fecha": "8/7/1976",
   "destino": "",
   "decreto_referido": "1477/1974",
   "pagina": "6",
   "nota": ""}
]}
```

Reglas de cada campo:

- `persona`: el nombre tal como aparece, con el apellido en mayúsculas como en
  el original. Corregí sólo los cortes de palabra por guión al final de línea
  ("WAG-\nNER" → "WAGNER"). No "normalices" ni reordenes.
- `documento`: tipo y número tal como aparece, por ejemplo "MI 6.999.516",
  "DNI 11.773.399", "LE 7.936.542", "CI 4.947.075", "CI chilena 168.907",
  "Ppte. 06234". Vacío si no hay.
- `filiacion`: "hijo de … y …" si aparece en lugar del documento; si no, vacío.
- `tipo`: uno de los ocho valores de la tabla.
- `decreto`: número/año del decreto que contiene el evento, tomado de la línea
  `=== DECRETO … ===`. Si la línea dice "?" tomalo del texto.
- `fecha`: la fecha del decreto, tomada de la misma línea, formato d/m/aaaa.
- `destino`: sólo para `salida_autorizada` o `expulsion`: el país o ciudad de
  destino si el decreto lo menciona; si no, vacío.
- `decreto_referido`: el decreto anterior que el texto asocia con esa persona
  (por ejemplo "detenido por Decreto Nº 1205/76" → "1205/1976"; o la lista de
  decretos de arresto en el VISTO cuando es uno solo). Vacío si no hay o si es
  ambiguo.
- `pagina`: la página PDF del encabezado del decreto (si hay rango, la primera).
- `nota`: vacío salvo para `tipo` = `otro`, para `libertad_vigilada` (lugar de
  cumplimiento) o cuando el texto sea ilegible o dudoso.

## Decretos "FE DE ERRATAS"

Algunos decretos son correcciones ("DONDE DICE … DEBE DECIR …"). Para ellos
producí un evento `otro` por cada persona afectada, con `nota` = "fe de erratas:
donde dice X debe decir Y", y `decreto` = el decreto que se corrige.

## Lote
