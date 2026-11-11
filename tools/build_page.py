"""Arma la página a partir de app/src/page.html, incrustando el CSS de Leaflet.

Genera:
  app/index.html  -> versión para publicar como artifact de Claude (sin <head>, la plataforma lo agrega)
  app/dev.html    -> copia con <head> para probar en la computadora
  docs/           -> sitio completo para GitHub Pages (con GPS y "agregar a pantalla de inicio")

Uso: py -I tools/build_page.py
"""
import os
import re
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(os.path.join(ROOT, "app", "src", "page.html"), encoding="utf-8").read()
css = open(os.path.join(ROOT, "tools", "vendor", "leaflet.css"), encoding="utf-8").read()
css = re.sub(r"/\*# sourceMappingURL=.*?\*/", "", css)
out = src.replace("/*@LEAFLET_CSS@*/", css)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


write(os.path.join(ROOT, "app", "index.html"), out)
print("ok app/index.html", len(out.encode("utf-8")), "bytes")

RESET = ('<style>:root{color-scheme:light;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}'
         'body{margin:0;font:14px/1.4 system-ui,sans-serif}img{max-width:100%}[hidden]{display:none!important}</style>')
HEAD = '<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'

write(os.path.join(ROOT, "app", "dev.html"), HEAD + RESET + "</head><body>" + out + "</body></html>")

# ---- sitio para GitHub Pages ----
DOCS = os.path.join(ROOT, "docs")
pwa = ('<meta name="description" content="Mapa del transporte público de Fort Worth: autobuses según horario, negocios cerca de las paradas y qué autobús tomar.">'
       '<meta name="theme-color" content="#0a7468"><link rel="manifest" href="manifest.webmanifest">'
       '<link rel="icon" href="icon.svg" type="image/svg+xml"><meta name="apple-mobile-web-app-capable" content="yes">'
       '<meta name="apple-mobile-web-app-title" content="Ruta Viva FW">')
write(os.path.join(DOCS, "index.html"), HEAD + pwa + RESET + "</head><body>" + out + "</body></html>")
write(os.path.join(DOCS, ".nojekyll"), "")
write(os.path.join(DOCS, "icon.svg"),
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512"><rect width="512" height="512" rx="112" fill="#16201c"/>'
      '<rect x="128" y="104" width="256" height="248" rx="44" fill="none" stroke="#ffb320" stroke-width="30"/>'
      '<path d="M128 236h256M180 400v-48M332 400v-48" stroke="#ffb320" stroke-width="30" stroke-linecap="round"/>'
      '<circle cx="196" cy="296" r="18" fill="#ffb320"/><circle cx="316" cy="296" r="18" fill="#ffb320"/></svg>')
write(os.path.join(DOCS, "manifest.webmanifest"),
      '{"name":"Ruta Viva FW","short_name":"Ruta Viva","lang":"es","start_url":".","scope":".","display":"standalone",'
      '"background_color":"#0e1412","theme_color":"#0a7468","icons":[{"src":"icon.svg","sizes":"any","type":"image/svg+xml","purpose":"any"}]}')
os.makedirs(os.path.join(DOCS, "data"), exist_ok=True)
for name in ("transit.json", "basemap.json", "places.json"):
    shutil.copyfile(os.path.join(ROOT, "app", "data", name), os.path.join(DOCS, "data", name))
print("ok docs/ (GitHub Pages)")
