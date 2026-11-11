# Ruta Viva FW

Mapa del transporte público de Fort Worth. Muestra los autobuses de Trinity Metro y el TEXRail moviéndose según su horario publicado, los negocios cerca de cada parada, y te dice qué autobús tomar ("llévame a Walmart").

App no oficial: no es de Trinity Metro. Trinity Metro no publica la ubicación GPS de sus autobuses, así que cada autobús se dibuja donde debería ir según el horario.

## Datos

- Rutas, paradas y horarios: [Trinity Metro GTFS](https://gtfsdata.ridetm.org/gtfs/fwtatransitdata.zip)
- Calles, ríos, parques y negocios: © colaboradores de [OpenStreetMap](https://www.openstreetmap.org/copyright), licencia ODbL. Los archivos de `app/data/` y `docs/data/` derivados de OpenStreetMap se comparten bajo la misma licencia ODbL.

## Estructura

- `app/src/page.html`: la app completa (HTML, CSS y JavaScript).
- `app/data/`: datos procesados (`transit.json`, `basemap.json`, `places.json`).
- `docs/`: el sitio que publica GitHub Pages (se genera con `tools/build_page.py`).
- `tools/`: scripts para descargar y procesar los datos.

## Actualizar los horarios

Los horarios cambian unas cuantas veces al año. Para actualizarlos (requiere Python 3):

```bash
curl -L -o gtfs.zip https://gtfsdata.ridetm.org/gtfs/fwtatransitdata.zip
mkdir -p gtfs && unzip -o gtfs.zip -d gtfs
py -I tools/build_gtfs.py gtfs app/data
py -I tools/build_page.py
```

Para volver a descargar los mapas y negocios de OpenStreetMap:

```bash
py -I tools/fetch_osm.py app/data/transit.json osm_raw
py -I tools/build_osm.py app/data/transit.json osm_raw app/data
py -I tools/build_page.py
```

Luego sube los cambios de `docs/` a GitHub.
