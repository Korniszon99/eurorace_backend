(function () {
  var STYLE_URL = "https://tiles.openfreemap.org/styles/liberty";
  var FALLBACK_TILES =
    "https://basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png";

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

  function dropRasterTiles(leafletMap) {
    leafletMap.eachLayer(function (layer) {
      if (layer instanceof L.TileLayer && !(layer instanceof L.TileLayer.WMS)) {
        leafletMap.removeLayer(layer);
      }
    });
  }

  function attachFallbackRaster(leafletMap) {
    if (leafletMap._euroraceFallbackTiles) return;
    leafletMap._euroraceFallbackTiles = L.tileLayer(FALLBACK_TILES, {
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
      maxZoom: 20,
    }).addTo(leafletMap);
  }

  function attachMapLibre(leafletMap, attempt) {
    attempt = attempt || 0;
    if (leafletMap._euroraceMapLibreAttached) return true;

    if (!window.maplibregl || !L.maplibreGL) {
      if (attempt < 40) {
        setTimeout(function () {
          attachMapLibre(leafletMap, attempt + 1);
        }, 100);
        return false;
      }
      attachFallbackRaster(leafletMap);
      return false;
    }

    leafletMap._euroraceMapLibreAttached = true;
    dropRasterTiles(leafletMap);

    try {
      var glLayer = L.maplibreGL({
        style: STYLE_URL,
        attribution:
          '&copy; <a href="https://openfreemap.org/">OpenFreeMap</a> &copy; OpenMapTiles &copy; OpenStreetMap',
        interactive: false,
      }).addTo(leafletMap);

      var glMap = glLayer.getMaplibreMap && glLayer.getMaplibreMap();
      if (glMap) {
        glMap.on("load", function () {
          preferPolishLabels(glMap);
          setTimeout(function () {
            leafletMap.invalidateSize();
            if (typeof glMap.resize === "function") glMap.resize();
          }, 50);
        });
        glMap.on("styledata", function () {
          preferPolishLabels(glMap);
        });
        glMap.on("error", function () {
          if (!leafletMap._euroraceFallbackTiles) {
            attachFallbackRaster(leafletMap);
          }
        });
      }

      setTimeout(function () {
        leafletMap.invalidateSize();
      }, 100);
      return true;
    } catch (err) {
      leafletMap._euroraceMapLibreAttached = false;
      attachFallbackRaster(leafletMap);
      return false;
    }
  }

  function rememberGeometryField(map, event) {
    var field = event && event.field;
    if (!field) return;
    map._euroraceGeometryFields = map._euroraceGeometryFields || [];
    if (map._euroraceGeometryFields.indexOf(field) === -1) {
      map._euroraceGeometryFields.push(field);
    }
  }

  function plainLabel(value) {
    if (!value) return "";
    var tmp = document.createElement("div");
    tmp.innerHTML = String(value);
    return (tmp.textContent || tmp.innerText || "").trim();
  }

  function setPointOnFields(map, latlng, label) {
    var fields = map._euroraceGeometryFields || [];
    fields.forEach(function (field) {
      if (!field.options || !field.options.is_point) return;
      if (!field.drawnItems) return;

      field.drawnItems.eachLayer(function (layer) {
        map.removeLayer(layer);
      });
      field.drawnItems.clearLayers();

      var marker = L.marker(latlng);
      field.drawnItems.addLayer(marker);
      map.addLayer(marker);
      field.store.save(field.drawnItems);
    });

    var clean = plainLabel(label);
    if (clean) {
      var nameInput =
        document.getElementById("id_destination_name") ||
        document.querySelector('input[name="destination_name"]');
      if (nameInput && !String(nameInput.value || "").trim()) {
        nameInput.value = clean;
      }
    }
  }

  function attachGeocoder(leafletMap) {
    if (leafletMap._euroraceGeocoderAttached) return;
    if (!L.Control || !L.Control.geocoder || !L.Control.Geocoder) return;

    leafletMap._euroraceGeocoderAttached = true;

    var geocoder = L.Control.Geocoder.photon({
      geocodingQueryParams: { lang: "pl" },
    });

    L.Control.geocoder({
      position: "topright",
      placeholder: "Szukaj miejsca…",
      errorMessage: "Nie znaleziono miejsca",
      defaultMarkGeocode: false,
      showUniqueResult: true,
      geocoder: geocoder,
    })
      .on("markgeocode", function (e) {
        var result = e.geocode;
        var center = result.center;
        if (result.bbox) {
          leafletMap.fitBounds(result.bbox, { maxZoom: 14, padding: [24, 24] });
        } else {
          leafletMap.setView(center, Math.max(leafletMap.getZoom(), 12));
        }
        setPointOnFields(leafletMap, center, result.name || result.html || "");
      })
      .addTo(leafletMap);
  }

  function enhanceMap(leafletMap) {
    attachMapLibre(leafletMap);
    attachGeocoder(leafletMap);
  }

  window.addEventListener("map:init", function (event) {
    if (!event.detail || !event.detail.map) return;
    var map = event.detail.map;
    map.on("map:loadfield", function (e) {
      rememberGeometryField(map, e);
    });
    enhanceMap(map);
  });
})();
