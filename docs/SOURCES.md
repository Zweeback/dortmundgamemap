# DortmundGameMap — Geodatenquellen

Stand: 2026-08-15

## Priorität A — amtliche Kerngeometrie

### 1. Stadt Dortmund 3D-Stadtmodell (LoD2)
- Anbieter: Stadt Dortmund / Vermessungs- und Katasteramt
- Datensatz: `3d-stadtmodell-gml-format`
- Format: CityGML/GML
- Kachelung: 1 km²
- Umfang: 323 Datensätze/Kacheln
- Datenstand: November 2025
- Lizenz: Datenlizenz Deutschland Zero 2.0 (kommunales Portal)
- Einsatz: Gebäudegeometrie für chunkbasiertes Streaming, Dachformen, Höhen.
- Empfehlung: Primärquelle für Dortmund-spezifische LoD2-Gebäude.

API-Basis:
`https://open-data.dortmund.de/api/explore/v2.1/catalog/datasets/3d-stadtmodell-gml-format/records`

### 2. Stadt Dortmund ALKIS Gebäude/Bauwerke
- Datensatz: `liegenschaftskataster-gebaude-bauwerke`
- Umfang: >225.000 Datensätze
- API + WMS/WFS
- Lizenz: Datenlizenz Deutschland Zero 2.0
- Einsatz: Gebäudegrundrisse, Objektabgleich, Collision-Footprints, Plausibilisierung gegen LoD2.

WMS/WFS:
`https://geoweb1.digistadtdo.de/doris_gdi/geoserver/ALKIS_ADV/ows`

### 3. Geobasis NRW DGM1
- Produkt: Digitales Geländemodell, Rasterweite 1 m
- Format: GeoTIFF / WCS / Download
- Lizenz: Datenlizenz Deutschland Zero 2.0
- Einsatz: Terrain-Höhen, Ground Collision, Navmesh-Untergrund.

### 4. Geobasis NRW 3D-Messdaten / LiDAR
- Produkt: 3D-Messdaten NW
- Punktdichte: ca. 4–10 Punkte/m²
- Einsatz: Terrain-/Oberflächenvalidierung, Brücken, Böschungen, Vegetationshöhen, spätere LoD3-Experimente.

### 5. Geobasis NRW LoD2
- Produkt: 3D-Gebäudemodell NW LoD2
- Formate/Dienste: CityGML, OGC API Features, I3S/REST, WMS
- Einsatz: Fallback/Erweiterung außerhalb kommunaler Dortmund-Kacheln und automatischer Regionenimport.

## Priorität B — Texturen und Oberflächen

### 6. Digitale Orthophotos NRW
- Anbieter: Geobasis NRW
- Formate: JPEG2000, WMTS, WMS, Download
- Einsatz: Terrain-Albedo, Straßen-/Dachreferenz, automatische Materialklassifikation.
- Hinweis: Nicht als monolithische 16K-Textur verwenden. In 256–1024 m Zellen schneiden, Mipmaps/KTX2 erzeugen.

## Priorität B — Straßen und semantische Stadtstruktur

### 7. OpenStreetMap
- Lizenz: ODbL 1.0
- Einsatz: Straßenachsen, highway-Typen, Fußwege, Radwege, Ampeln, POIs, Flächen, Routinggraph.
- Pflicht: Attribution `© OpenStreetMap contributors`; bei abgeleiteten Daten ODbL-Regeln beachten.
- Architektur: OSM-Daten in eigener Datenebene halten, nicht unkontrolliert mit DL-DE-Zero-Quelldaten zu einer einzigen weiterverteilten Datenbank verschmelzen.

### 8. ATKIS Basis-DLM NRW
- Anbieter: Geobasis NRW
- WFS / NAS / Atom-Feed
- Einsatz: amtliche Straßen-/Gewässer-/Landnutzungsgeometrie als OSM-Kontrollquelle.

## Priorität C — lebendige Simulation

### 9. Baumkataster Dortmund
- Datensatz: `baumkataster`
- ca. 154.000 Bäume
- Attribute u.a.: Position, Art, Baumhöhe, Kronendurchmesser, Stammdurchmesser, Pflanzjahr
- Lizenz: Datenlizenz Deutschland Zero 2.0
- Einsatz: prozedurale Vegetation / MultiMesh-Instancing statt Mesh-Handarbeit.

### 10. Parkhäuser und P+R
- Datensatz: `parkhauser`
- enthält aktuelle Verfügbarkeit, Kapazität, Öffnungszeiten
- Aktualitätslogik: Daten älter als 10 Minuten gelten im Parkleitsystem als gestört
- Einsatz: dynamische Parkhausbelegung, Missionen, UI, Verkehrsfluss.

### 11. Baustellen
- Datensätze: `fb66-baustellen-tagesaktuell`, `fb66-baustellen-geplant`
- Lizenz: Datenlizenz Deutschland Zero 2.0
- Einsatz: dynamische Straßensperren, Baustellenobjekte, Routing-Änderungen.

### 12. Haltestellen / P+R / Taxi / POIs
- Datensätze u.a. `haltestellen`, `park-and-ride`, `taxistand`, `spielplatze`, `fb63-spielgeraete`
- überwiegend Datenlizenz Deutschland Zero 2.0
- Einsatz: Missionsanker, Fast Travel, Transit-Simulation, Stadtleben.

## Koordinatensystem

Für die amtlichen NRW-Geodaten ist ETRS89 / UTM Zone 32N, EPSG:25832, die zentrale Referenz. Das passt zur Größenordnung der vorhandenen Modellkoordinaten (~392k / ~5.708M).

Regel im Projekt:
- Niemals amtliche Weltkoordinaten zerstören.
- Pro Chunk: `global_easting`, `global_northing`, `base_height` als Metadaten halten.
- Godot lokal: Chunk-Position relativ zu einem Floating Origin.
- Welt → Godot: `(E - origin_E, H - origin_H, -(N - origin_N))` bzw. konsistent definierte Achsenkonvention.

## Nicht als Primärquelle verwenden

- Google Maps/Google Earth/Street View nicht scrapen oder als Geometriedatenquelle kopieren.
- Karten-Screenshots nicht als frei wiederverwendbare Textur behandeln.
- Proprietäre 3D-Kartenmodelle nicht extrahieren.
