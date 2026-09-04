(function () {
  var STYLE_URL = "https://tiles.openfreemap.org/styles/liberty";

  function preferPolishLabels(map) {
    var style = map.getStyle();
    if (!style || !style.layers) return;
    style.layers.forEach(function (layer) {
      if (layer.type !== "symbol" || !layer.layout || !layer.layout["text-field"]) return;
      try {
        map.setLayoutProperty(layer.id, "text-field", [
          "coalesce",
          ["get", "name:pl"],
          ["get", "name:latin"],
          ["get", "name"],
        ]);
      } catch (err) {
        // Ignore layers that do not accept overrides.
      }
    });
  }

  function attachMapLibre(leafletMap) {
    if (!window.maplibregl || !L.maplibreGL) return;
    if (leafletMap._euroraceMapLibreAttached) return;
    leafletMap._euroraceMapLibreAttached = true;

    // Drop any default OSM raster tiles django-leaflet may have added.
    leafletMap.eachLayer(function (layer) {
      if (layer instanceof L.TileLayer) {
        leafletMap.removeLayer(layer);
      }
    });

    var glLayer = L.maplibreGL({
      style: STYLE_URL,
      attribution: '&copy; <a href="https://openfreemap.org/">OpenFreeMap</a> &copy; OpenMapTiles &copy; OpenStreetMap',
    }).addTo(leafletMap);

    var glMap = glLayer.getMaplibreMap();
    if (!glMap) return;
    glMap.on("load", function () {
      preferPolishLabels(glMap);
    });
    glMap.on("styledata", function () {
      preferPolishLabels(glMap);
    });
  }

  window.addEventListener("map:init", function (event) {
    attachMapLibre(event.detail.map);
  });
})();
