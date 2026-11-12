# Segunda lectura independiente: personas y medidas en decretos secretos

Vas a leer un lote de decretos argentinos de 1976–1983 (estado de sitio,
arrestos a disposición del Poder Ejecutivo Nacional, derecho de opción para
salir del país). Tu lectura se compara automáticamente con la de otro lector
que trabajó con otras instrucciones: cualquier nombre que uno tenga y el otro
no va a revisión manual. Por eso lo que importa es ser **exhaustivo y literal**:
cada persona de cada artículo, con su documento, sin interpretar de más.

Trabajá sólo con el texto que recibís. No uses herramientas ni archivos.
Respondé con un único objeto JSON y nada más (sin ``` ni comentarios).

## Procedimiento

Para cada decreto del lote (empiezan con `=== DECRETO numero/año | fecha … | paginas PDF … ===`):

1. Decidí si trata sobre personas arrestadas, detenidas, expulsadas o con
   solicitud de opción para salir del país. Si no (designaciones, comisiones al
   exterior, armas, ceses, convalidaciones…), pasá al siguiente sin anotar nada.
2. Leé la parte dispositiva ("Artículo 1°", "Art. 2°", …). Por cada artículo que
   nombre personas, anotá qué medida toma y copiá uno por uno los nombres y
   documentos. Contá los nombres: si el artículo dice "las siguientes 32
   personas" y copiaste 30, buscá los dos que faltan.
3. Si la parte dispositiva remite a personas de los considerandos ("las
   personas mencionadas en el considerando primero"), tomá los nombres de ahí.
4. Si el texto asocia a una persona con un decreto anterior ("detenido por
   Decreto 1205/76", "arrestado por Decreto Nº 2189 del 12 de agosto de 1975"),
   anotalo en `decreto_referido` con formato número/año de cuatro cifras.

## Clasificación de la medida (`tipo`)

- `arresto`: se ordena el arresto a disposición del PEN.
- `opcion_denegada`: se deniega o no se hace lugar a la solicitud de opción /
  de abandonar el país.
- `opcion_diferida`: se difiere la resolución de la solicitud de opción.
- `libertad_vigilada`: se dispone o modifica el cumplimiento del arresto bajo
  libertad vigilada (anotá el lugar en `nota`).
- `liberacion`: se deja sin efecto el arresto a disposición del PEN.
- `salida_autorizada`: se autoriza la salida del país / se concede la opción
  (anotá el destino en `destino` si figura).
- `expulsion`: se dispone la expulsión del país de un extranjero (destino en
  `destino` si figura).
- `otro`: cualquier otra medida sobre una persona en esta situación; explicá en
  `nota`. Incluye las "FE DE ERRATAS": `nota` = "fe de erratas: donde dice X debe
  decir Y" y `decreto` = el decreto corregido.

## Esquema

```
{"eventos": [
  {"persona": "Manuel Leónidas CORDOBA",
   "documento": "MI 6.999.516",
   "filiacion": "",
   "tipo": "liberacion",
   "decreto": "1282/1976",
   "fecha": "8/7/1976",
   "destino": "",
   "decreto_referido": "",
   "pagina": "6",
   "nota": ""}
]}
```

- `persona`: literal, uniendo sólo las palabras cortadas por guión de fin de
  línea. Mantené el apellido en mayúsculas como en el original.
- `documento`: literal ("MI 6.999.516", "DNI 11.773.399", "LE …", "CI …",
  "Ppte. …"), vacío si no figura.
- `filiacion`: "hijo de … y …" cuando aparece en lugar del documento.
- `decreto` y `fecha`: de la línea `=== DECRETO … ===` del decreto que contiene
  el artículo (fecha d/m/aaaa).
- `pagina`: primera página PDF de esa misma línea.
- Campos sin dato: cadena vacía, nunca null.

## Lote
