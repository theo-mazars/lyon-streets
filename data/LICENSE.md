# Data licence

`lyon-data.json` is derived from [OpenStreetMap](https://www.openstreetmap.org) data
exported on 19 October 2026 through the Overpass API.

© OpenStreetMap contributors. The data is available under the
[Open Database Licence (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1-0/).
See <https://www.openstreetmap.org/copyright> for details.

`scripts/process.py` produced this file by:

- keeping named streets and the nine arrondissement boundaries;
- dropping tunnel ramps (trémies), slip roads (bretelles), the tram line and other technical links;
- grouping street segments by name and assigning each street to the arrondissements
  holding at least 15% (or 150 m) of its length;
- simplifying the geometry and converting it to metres from a point near Place Bellecour.

Under the ODbL, if you publicly use or share an adapted version of this data, you must
credit OpenStreetMap and make the adapted data available under the same licence.
