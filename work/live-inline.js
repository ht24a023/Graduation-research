
    const chatLog = document.getElementById('chat-log');
    const messageInput = document.getElementById('message');
    const sessionInput = document.getElementById('session-id');
    const locationInput = document.getElementById('current-location');
    const turboModeInput = document.getElementById('turbo-mode');
    const sendBtn = document.getElementById('send-btn');
    const resetBtn = document.getElementById('reset-btn');
    const healthText = document.getElementById('health-text');
    const healthCard = document.getElementById('health-card');
    const storageCard = document.getElementById('storage-card');
    const metaCard = document.getElementById('meta-card');
    const serverUrlChip = document.getElementById('server-url-chip');
    const serverIpChip = document.getElementById('server-ip-chip');
    const sessionText = document.getElementById('session-text');
    const capabilityGuide = document.getElementById('capability-guide');
    const capabilityTemplateList = document.getElementById('capability-template-list');
    const capabilityRefreshBtn = document.getElementById('capability-refresh-btn');
    const documentList = document.getElementById('document-list');
    const documentNewBtn = document.getElementById('document-new-btn');
    const documentTitleInput = document.getElementById('document-title');
    const documentContentInput = document.getElementById('document-content');
    const documentMeta = document.getElementById('document-meta');
    const documentCurrentCard = document.getElementById('document-current-card');
    const documentMode = document.getElementById('document-mode');
    const documentRefreshBtn = document.getElementById('document-refresh-btn');
    const documentSaveBtn = document.getElementById('document-save-btn');
    const documentDeleteBtn = document.getElementById('document-delete-btn');
    const documentClearBtn = document.getElementById('document-clear-btn');
    const geoPanelCard = document.getElementById('geo-panel-card');
    const geoFetchBtn = document.getElementById('geo-fetch-btn');
    const geoManualApplyBtn = document.getElementById('geo-manual-apply-btn');
    const geoSourceSelect = document.getElementById('geo-source-select');
    const geoManualInput = document.getElementById('geo-manual-input');
    const worldMapSvg = document.getElementById('world-map-svg');
    const japanMapSvg = document.getElementById('japan-map-svg');
    const worldMapMarker = document.getElementById('world-map-marker');
    const worldMapWave = document.getElementById('world-map-wave');
    const japanMapMarker = document.getElementById('japan-map-marker');
    const japanMapWave = document.getElementById('japan-map-wave');
    const worldMapLabel = document.getElementById('world-map-label');
    const japanMapLabel = document.getElementById('japan-map-label');
    const japanMapOutside = document.getElementById('japan-map-outside');
    const geoDetailTitle = document.getElementById('geo-detail-title');
    const geoBreadcrumb = document.getElementById('geo-breadcrumb');
    const geoNavBackBtn = document.getElementById('geo-nav-back-btn');
    const geoNavHomeBtn = document.getElementById('geo-nav-home-btn');
    const geoManualCandidates = document.getElementById('geo-manual-candidates');
    const geoLocationLabel = document.getElementById('geo-location-label');
    const geoLocationMeta = document.getElementById('geo-location-meta');
    const geoLatLon = document.getElementById('geo-latlon');
    const geoProvider = document.getElementById('geo-provider');
    const geoAccuracy = document.getElementById('geo-accuracy');
    const geoTimezone = document.getElementById('geo-timezone');
    const geoLocalTime = document.getElementById('geo-local-time');
    const geoHumidity = document.getElementById('geo-humidity');
    const geoWind = document.getElementById('geo-wind');
    const geoObservedAt = document.getElementById('geo-observed-at');
    const geoWeather = document.getElementById('geo-weather');
    const geoTemp = document.getElementById('geo-temp');
    const geoHiLo = document.getElementById('geo-hi-lo');
    const geoRain = document.getElementById('geo-rain');
    const geoStatus = document.getElementById('geo-status');
    const clockTime = document.getElementById('clock-time');
    const clockDate = document.getElementById('clock-date');
    const runtimeConnection = document.getElementById('runtime-connection');
    const runtimeModel = document.getElementById('runtime-model');
    const runtimeProcessing = document.getElementById('runtime-processing');
    const runtimeLatency = document.getElementById('runtime-latency');
    const runtimeRoute = document.getElementById('runtime-route');
    const runtimeCloud = document.getElementById('runtime-cloud');
    const runtimeLogList = document.getElementById('runtime-log-list');

    const storageKey = 'local-ai-session-id';
    const locationStorageKey = 'local-ai-current-location';
    const turboModeStorageKey = 'local-ai-turbo-mode-v1';
    const geoPanelCacheKey = 'local-ai-geo-panel-cache-v1';
    const geoPanelModeKey = 'local-ai-geo-mode-v1';
    const geoManualRegionKey = 'local-ai-geo-manual-region-v1';

    const geoState = {
      mode: 'ip',
      device: null,
      manual: '',
      manualResolvedAddress: '',
      manualCandidates: [],
      manualLock: false,
      targetCoord: null,
      panelVisible: true,
      isInitialized: false,
      requestSeq: 0,
      appliedSeq: 0,
      worldReady: false,
      japanReady: false,
      worldFeatures: [],
      japanFeatures: [],
      detailHistory: ['world'],
      detailPath: ['世界'],
      detailLevel: 'world',
      selectedCountry: '',
      selectedRegionBand: '',
      selectedPrefecture: '',
      selectedPrefCode: '',
    };

    const runtimeLogItems = [];

    function appendRuntimeLog(message) {
      const line = String(message || '').trim();
      if (!line) {
        return;
      }
      runtimeLogItems.unshift(line);
      while (runtimeLogItems.length > 5) {
        runtimeLogItems.pop();
      }
      runtimeLogList.innerHTML = '';
      runtimeLogItems.forEach((item) => {
        const li = document.createElement('li');
        li.textContent = item;
        runtimeLogList.appendChild(li);
      });
    }

    function refreshTokyoClock() {
      window.desktopIntegration?.renderClock();
    }

    function makeSessionId() {
      try {
        if (window.crypto && typeof window.crypto.randomUUID === 'function') {
          return window.crypto.randomUUID();
        }
      } catch (e) {
      }
      return String(Date.now());
    }

    function safeStorageGet(key) {
      try {
        return window.localStorage.getItem(key);
      } catch (e) {
        return null;
      }
    }

    function safeStorageSet(key, value) {
      try {
        window.localStorage.setItem(key, value);
      } catch (e) {
      }
    }

    function safeStorageRemove(key) {
      try {
        window.localStorage.removeItem(key);
      } catch (e) {
      }
    }

    function getPathValue(obj, path, fallbackValue) {
      let cursor = obj;
      for (let i = 0; i < path.length; i += 1) {
        if (!cursor || typeof cursor !== 'object' || !(path[i] in cursor)) {
          return fallbackValue;
        }
        cursor = cursor[path[i]];
      }
      return cursor == null ? fallbackValue : cursor;
    }

    const savedSessionId = safeStorageGet(storageKey) || makeSessionId();
    safeStorageSet(storageKey, savedSessionId);
    sessionInput.value = savedSessionId;
    const savedCurrentLocation = safeStorageGet(locationStorageKey) || '';
    locationInput.value = savedCurrentLocation;
    const savedTurboMode = safeStorageGet(turboModeStorageKey) === 'true';
    if (turboModeInput) {
      turboModeInput.checked = savedTurboMode;
    }
    const savedGeoMode = safeStorageGet(geoPanelModeKey) || 'ip';
    const savedManualRegion = safeStorageGet(geoManualRegionKey) || '';
    geoState.mode = ['device', 'ip', 'manual'].includes(savedGeoMode) ? savedGeoMode : 'ip';
    geoState.manual = savedManualRegion;
    if (geoSourceSelect) {
      geoSourceSelect.value = geoState.mode;
    }
    if (geoManualInput) {
      geoManualInput.value = geoState.manual;
    }

    function persistCurrentLocation(value) {
      safeStorageSet(locationStorageKey, value || '');
    }

    function persistTurboMode(enabled) {
      safeStorageSet(turboModeStorageKey, enabled ? 'true' : 'false');
    }

    function persistGeoMode(mode) {
      safeStorageSet(geoPanelModeKey, mode || 'ip');
    }

    function persistManualRegion(value) {
      safeStorageSet(geoManualRegionKey, value || '');
    }

    function normalizeMode(value) {
      const mode = String(value || '').trim().toLowerCase();
      if (mode === 'device' || mode === 'manual' || mode === 'ip') {
        return mode;
      }
      return 'ip';
    }

    function clearGeoPanelCache() {
      safeStorageRemove(geoPanelCacheKey);
    }

    function setGeoPanelState(state) {
      if (!geoPanelCard) {
        return;
      }
      geoPanelCard.classList.remove('state-loading', 'state-error', 'state-ready');
      geoPanelCard.classList.add(`state-${state}`);
    }

    function formatLatLon(value) {
      if (typeof value !== 'number' || Number.isNaN(value)) {
        return '—';
      }
      return value.toFixed(4);
    }

    function formatAccuracy(value) {
      const numeric = Number(value);
      if (!Number.isFinite(numeric) || numeric <= 0) {
        return '—';
      }
      return `±${Math.round(numeric)}m`;
    }

    const PREF_CODE_TO_NAME = {
      1: '北海道', 2: '青森県', 3: '岩手県', 4: '宮城県', 5: '秋田県', 6: '山形県', 7: '福島県',
      8: '茨城県', 9: '栃木県', 10: '群馬県', 11: '埼玉県', 12: '千葉県', 13: '東京都', 14: '神奈川県',
      15: '新潟県', 16: '富山県', 17: '石川県', 18: '福井県', 19: '山梨県', 20: '長野県',
      21: '岐阜県', 22: '静岡県', 23: '愛知県', 24: '三重県', 25: '滋賀県', 26: '京都府', 27: '大阪府',
      28: '兵庫県', 29: '奈良県', 30: '和歌山県', 31: '鳥取県', 32: '島根県', 33: '岡山県', 34: '広島県',
      35: '山口県', 36: '徳島県', 37: '香川県', 38: '愛媛県', 39: '高知県', 40: '福岡県', 41: '佐賀県',
      42: '長崎県', 43: '熊本県', 44: '大分県', 45: '宮崎県', 46: '鹿児島県', 47: '沖縄県'
    };

    const EAST_PREF_SET = new Set([
      '北海道', '青森県', '岩手県', '宮城県', '秋田県', '山形県', '福島県',
      '茨城県', '栃木県', '群馬県', '埼玉県', '千葉県', '東京都', '神奈川県',
      '新潟県', '富山県', '石川県', '福井県', '山梨県', '長野県',
      '岐阜県', '静岡県', '愛知県'
    ]);

    const WEST_PREF_SET = new Set(Object.values(PREF_CODE_TO_NAME).filter((name) => !EAST_PREF_SET.has(name)));

    const PREF_EN_ALIAS = {
      hokkaido: '北海道', aomori: '青森県', iwate: '岩手県', miyagi: '宮城県', akita: '秋田県', yamagata: '山形県', fukushima: '福島県',
      ibaraki: '茨城県', tochigi: '栃木県', gunma: '群馬県', saitama: '埼玉県', chiba: '千葉県', tokyo: '東京都', kanagawa: '神奈川県',
      niigata: '新潟県', toyama: '富山県', ishikawa: '石川県', fukui: '福井県', yamanashi: '山梨県', nagano: '長野県',
      gifu: '岐阜県', shizuoka: '静岡県', aichi: '愛知県', mie: '三重県', shiga: '滋賀県', kyoto: '京都府', osaka: '大阪府',
      hyogo: '兵庫県', nara: '奈良県', wakayama: '和歌山県', tottori: '鳥取県', shimane: '島根県', okayama: '岡山県', hiroshima: '広島県',
      yamaguchi: '山口県', tokushima: '徳島県', kagawa: '香川県', ehime: '愛媛県', kochi: '高知県', fukuoka: '福岡県', saga: '佐賀県',
      nagasaki: '長崎県', kumamoto: '熊本県', oita: '大分県', miyazaki: '宮崎県', kagoshima: '鹿児島県', okinawa: '沖縄県'
    };

    function normalizePrefName(value) {
      const raw = String(value || '').trim();
      if (!raw) {
        return '';
      }
      const base = raw
        .replace(/都道府県|都|道|府|県/g, '')
        .replace(/\s+/g, '')
        .toLowerCase();
      if (PREF_EN_ALIAS[base]) {
        return PREF_EN_ALIAS[base];
      }
      const entries = Object.values(PREF_CODE_TO_NAME);
      for (let i = 0; i < entries.length; i += 1) {
        const pref = entries[i];
        const key = pref.replace(/都道府県|都|道|府|県/g, '').toLowerCase();
        if (key === base || pref === raw) {
          return pref;
        }
      }
      return raw;
    }

    function updateDetailBreadcrumb() {
      if (!geoBreadcrumb) {
        return;
      }
      geoBreadcrumb.textContent = geoState.detailPath.join(' > ');
      if (geoDetailTitle) {
        if (geoState.detailLevel === 'world') {
          geoDetailTitle.textContent = 'JAPAN';
        } else if (geoState.detailLevel === 'country') {
          geoDetailTitle.textContent = isJapanCountryName(geoState.selectedCountry || '') ? 'JAPAN' : (geoState.selectedCountry || 'COUNTRY');
        } else if (geoState.detailLevel === 'east-west') {
          geoDetailTitle.textContent = geoState.selectedRegionBand || 'JAPAN';
        } else if (geoState.detailLevel === 'prefecture') {
          geoDetailTitle.textContent = geoState.selectedPrefecture || 'JAPAN';
        }
      }
    }

    function pushDetailState(level, label) {
      geoState.detailLevel = level;
      const current = geoState.detailHistory[geoState.detailHistory.length - 1];
      if (current !== level) {
        geoState.detailHistory.push(level);
      }
      if (label) {
        const lastLabel = geoState.detailPath[geoState.detailPath.length - 1];
        if (lastLabel !== label) {
          geoState.detailPath.push(label);
        }
      }
      updateDetailBreadcrumb();
    }

    function resetDetailState() {
      geoState.detailHistory = ['world'];
      geoState.detailPath = ['世界'];
      geoState.detailLevel = 'world';
      geoState.selectedCountry = '';
      geoState.selectedRegionBand = '';
      geoState.selectedPrefecture = '';
      geoState.selectedPrefCode = '';
      updateDetailBreadcrumb();
    }

    function setupGeoVisibilityWatcher() {
      if (!geoPanelCard || typeof IntersectionObserver !== 'function') {
        return;
      }
      const observer = new IntersectionObserver((entries) => {
        const entry = entries && entries[0];
        geoState.panelVisible = !!(entry && entry.isIntersecting);
        geoPanelCard.classList.toggle('paused', !geoState.panelVisible);
      }, { threshold: 0.1 });
      observer.observe(geoPanelCard);
      document.addEventListener('visibilitychange', () => {
        geoPanelCard.classList.toggle('paused', document.hidden || !geoState.panelVisible);
      });
    }

    function projectWorldPoint(latitude, longitude) {
      const width = 960;
      const height = 460;
      const x = ((longitude + 180) / 360) * width;
      const y = ((90 - latitude) / 180) * height;
      return { x, y };
    }

    function projectJapanPoint(latitude, longitude) {
      const minLon = 122;
      const maxLon = 154;
      const minLat = 24;
      const maxLat = 46;
      if (longitude < minLon || longitude > maxLon || latitude < minLat || latitude > maxLat) {
        return null;
      }
      const width = 960;
      const height = 460;
      const x = ((longitude - minLon) / (maxLon - minLon)) * width;
      const y = ((maxLat - latitude) / (maxLat - minLat)) * height;
      return { x, y };
    }

    function drawMapSvg(svgElement, features, projectionMode, options = {}) {
      if (!svgElement || !Array.isArray(features)) {
        return;
      }
      const pathParts = [];
      const lineParts = [];

      const project = projectionMode === 'japan' ? projectJapanPoint : projectWorldPoint;
      const highlightPref = normalizePrefName(options.highlightPrefecture || '');
      const regionBand = options.regionBand || '';

      function ringToPath(ring) {
        const points = [];
        ring.forEach((coord) => {
          const lon = Number(coord[0]);
          const lat = Number(coord[1]);
          if (!Number.isFinite(lon) || !Number.isFinite(lat)) {
            return;
          }
          const p = project(lat, lon);
          if (!p) {
            return;
          }
          points.push(p);
        });
        if (points.length < 2) {
          return '';
        }
        return `M${points[0].x.toFixed(2)},${points[0].y.toFixed(2)} ` + points.slice(1).map((p) => `L${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(' ') + ' Z';
      }

      function geometryPath(geometry) {
        if (!geometry) {
          return '';
        }
        const segments = [];
        if (geometry.type === 'Polygon') {
          (geometry.coordinates || []).forEach((ring) => {
            const d = ringToPath(ring);
            if (d) {
              segments.push(d);
            }
          });
        } else if (geometry.type === 'MultiPolygon') {
          (geometry.coordinates || []).forEach((poly) => {
            (poly || []).forEach((ring) => {
              const d = ringToPath(ring);
              if (d) {
                segments.push(d);
              }
            });
          });
        }
        return segments.join(' ');
      }

      features.forEach((feature) => {
        const geometry = feature && feature.geometry;
        const d = geometryPath(geometry);
        if (!d) {
          return;
        }

        if (projectionMode === 'japan') {
          const code = Number(feature.id);
          const prefName = PREF_CODE_TO_NAME[code] || '';
          const isEast = EAST_PREF_SET.has(prefName);
          const inBand = regionBand ? ((regionBand === '東日本' && isEast) || (regionBand === '西日本' && WEST_PREF_SET.has(prefName))) : true;
          const isHighlight = highlightPref && prefName === highlightPref;
          const fillClass = isHighlight ? 'geo-map-land focus' : (inBand ? 'geo-map-land' : 'geo-map-land muted');
          pathParts.push(`<path class="${fillClass}" data-pref-code="${code}" data-pref-name="${prefName}" d="${d}"></path>`);
          lineParts.push(`<path class="geo-map-border" d="${d}"></path>`);
        } else {
          pathParts.push(`<path class="geo-map-land" d="${d}"></path>`);
          lineParts.push(`<path class="geo-map-border" d="${d}"></path>`);
        }
      });

      const width = 960;
      const height = 460;
      const graticules = [
        `<path class="geo-map-grid" d="M0 ${height / 2} L${width} ${height / 2}"></path>`,
        `<path class="geo-map-grid" d="M${width / 4} 0 L${width / 4} ${height}"></path>`,
        `<path class="geo-map-grid" d="M${width / 2} 0 L${width / 2} ${height}"></path>`,
        `<path class="geo-map-grid" d="M${(width * 3) / 4} 0 L${(width * 3) / 4} ${height}"></path>`,
      ];

      const labels = projectionMode === 'world'
        ? [
            { name: 'Tokyo', lat: 35.68, lon: 139.76 },
            { name: 'London', lat: 51.51, lon: -0.13 },
            { name: 'New York', lat: 40.71, lon: -74.0 },
            { name: 'Sydney', lat: -33.86, lon: 151.21 },
          ]
        : [
            { name: '札幌', lat: 43.06, lon: 141.35 },
            { name: '東京', lat: 35.68, lon: 139.76 },
            { name: '名古屋', lat: 35.18, lon: 136.91 },
            { name: '大阪', lat: 34.69, lon: 135.50 },
            { name: '福岡', lat: 33.59, lon: 130.40 },
          ];
      const labelMarkup = labels
        .map((item) => {
          const p = project(item.lat, item.lon);
          if (!p) {
            return '';
          }
          return `<text class="geo-map-city" x="${p.x.toFixed(1)}" y="${(p.y - 4).toFixed(1)}">${item.name}</text>`;
        })
        .join('');

      svgElement.innerHTML = [
        '<rect class="geo-map-sea" x="0" y="0" width="960" height="460"></rect>',
        ...graticules,
        ...pathParts,
        ...lineParts,
        labelMarkup,
      ].join('');
    }

    function applyJapanViewBox(level, prefCode = '') {
      if (!japanMapSvg) {
        return;
      }
      japanMapSvg.style.transition = 'all 220ms ease';
      if (level === 'world' || level === 'country') {
        japanMapSvg.setAttribute('viewBox', '0 0 960 460');
        return;
      }
      if (level === 'east-west') {
        if (geoState.selectedRegionBand === '東日本') {
          japanMapSvg.setAttribute('viewBox', '380 20 560 380');
        } else if (geoState.selectedRegionBand === '西日本') {
          japanMapSvg.setAttribute('viewBox', '120 80 620 340');
        } else {
          japanMapSvg.setAttribute('viewBox', '0 0 960 460');
        }
        return;
      }
      if (level === 'prefecture') {
        const node = japanMapSvg.querySelector(`[data-pref-code="${prefCode}"]`);
        if (node && typeof node.getBBox === 'function') {
          const box = node.getBBox();
          const padX = Math.max(40, box.width * 0.8);
          const padY = Math.max(30, box.height * 0.8);
          const x = Math.max(0, box.x - padX);
          const y = Math.max(0, box.y - padY);
          const w = Math.min(960 - x, box.width + (padX * 2));
          const h = Math.min(460 - y, box.height + (padY * 2));
          japanMapSvg.setAttribute('viewBox', `${x.toFixed(1)} ${y.toFixed(1)} ${Math.max(120, w).toFixed(1)} ${Math.max(90, h).toFixed(1)}`);
          return;
        }
      }
      japanMapSvg.setAttribute('viewBox', '0 0 960 460');
    }

    function renderDetailMap() {
      if (!geoState.japanReady) {
        return;
      }

      if (geoState.selectedCountry && geoState.selectedCountry !== 'Japan') {
        drawMapSvg(japanMapSvg, geoState.worldFeatures, 'world');
        applyJapanViewBox('country');
        japanMapOutside.classList.add('show');
        return;
      }

      drawMapSvg(japanMapSvg, geoState.japanFeatures, 'japan', {
        regionBand: geoState.detailLevel === 'east-west' ? geoState.selectedRegionBand : '',
        highlightPrefecture: geoState.selectedPrefecture,
      });
      applyJapanViewBox(geoState.detailLevel, geoState.selectedPrefCode);
      japanMapOutside.classList.remove('show');
    }

    function isJapanCountryName(country) {
      const value = String(country || '').trim().toLowerCase();
      return value === 'japan' || value === '日本';
    }

    function resolveRegionBandFromPref(prefName) {
      const normalized = normalizePrefName(prefName);
      if (!normalized) {
        return '';
      }
      if (EAST_PREF_SET.has(normalized)) {
        return '東日本';
      }
      if (WEST_PREF_SET.has(normalized)) {
        return '西日本';
      }
      return '';
    }

    async function initializeGeoMaps() {
      if (geoState.worldReady && geoState.japanReady) {
        return;
      }
      try {
        const [worldRes, japanRes] = await Promise.all([
          fetch('/site/maps/world-110m.topojson'),
          fetch('/site/maps/japan.topojson'),
        ]);
        const worldTopo = await worldRes.json();
        const japanTopo = await japanRes.json();
        const worldFeatures = window.topojson.feature(worldTopo, worldTopo.objects.countries).features;
        const japanFeatures = window.topojson.feature(japanTopo, japanTopo.objects.japan).features;
        geoState.worldFeatures = worldFeatures;
        geoState.japanFeatures = japanFeatures;
        drawMapSvg(worldMapSvg, worldFeatures, 'world');
        drawMapSvg(japanMapSvg, japanFeatures, 'japan');
        geoState.worldReady = true;
        geoState.japanReady = true;
        resetDetailState();
        updateDetailBreadcrumb();
      } catch (e) {
        geoStatus.textContent = '地図データを読み込めませんでした。';
      }
    }

    function attachGeoMapInteractions() {
      if (worldMapMarker) {
        worldMapMarker.addEventListener('click', () => {
          if (!geoState.targetCoord) {
            return;
          }
          const selectedCountry = geoState.selectedCountry || '';
          if (!selectedCountry) {
            return;
          }
          if (isJapanCountryName(selectedCountry)) {
            geoState.detailLevel = 'country';
            pushDetailState('country', '日本');
            const band = geoState.selectedRegionBand || resolveRegionBandFromPref(geoState.selectedPrefecture);
            if (band) {
              geoState.selectedRegionBand = band;
              pushDetailState('east-west', band);
            }
          } else {
            geoState.detailLevel = 'country';
            pushDetailState('country', selectedCountry);
          }
          renderDetailMap();
          if (geoState.targetCoord) {
            setGeoMapMarkers(geoState.targetCoord.latitude, geoState.targetCoord.longitude, japanMapLabel.textContent);
          }
        });
      }

      if (japanMapSvg) {
        japanMapSvg.addEventListener('click', (event) => {
          const target = event.target;
          if (!target || typeof target.getAttribute !== 'function') {
            return;
          }
          const prefCode = target.getAttribute('data-pref-code');
          const prefName = target.getAttribute('data-pref-name');
          if (!prefCode || !prefName || !isJapanCountryName(geoState.selectedCountry || '')) {
            return;
          }
          const band = resolveRegionBandFromPref(prefName);
          if (band) {
            geoState.selectedRegionBand = band;
            if (geoState.detailLevel !== 'east-west') {
              pushDetailState('east-west', band);
            }
          }
          geoState.selectedPrefecture = prefName;
          geoState.selectedPrefCode = prefCode;
          pushDetailState('prefecture', prefName);
          renderDetailMap();
          if (geoState.targetCoord) {
            setGeoMapMarkers(geoState.targetCoord.latitude, geoState.targetCoord.longitude, japanMapLabel.textContent);
          }
        });
      }
    }

    function setMapMarker(marker, wave, label, projectedPoint, labelText, hide = false) {
      if (!marker || !wave || !label) {
        return;
      }
      if (hide || !projectedPoint) {
        marker.classList.add('hidden');
        wave.classList.add('hidden');
        label.textContent = labelText || '—';
        return;
      }
      marker.classList.remove('hidden');
      wave.classList.remove('hidden');
      const frame = marker.parentElement;
      const frameWidth = frame ? (frame.clientWidth || 960) : 960;
      const frameHeight = frame ? (frame.clientHeight || 460) : 460;
      const left = (projectedPoint.x / 960) * frameWidth;
      const top = (projectedPoint.y / 460) * frameHeight;
      marker.style.left = `${left}px`;
      marker.style.top = `${top}px`;
      wave.style.left = `${left}px`;
      wave.style.top = `${top}px`;
      label.textContent = labelText || '—';
    }

    function setGeoMapMarkers(latitude, longitude, labelText) {
      if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) {
        setMapMarker(worldMapMarker, worldMapWave, worldMapLabel, null, '座標なし', true);
        setMapMarker(japanMapMarker, japanMapWave, japanMapLabel, null, '座標なし', true);
        japanMapOutside.classList.remove('show');
        return;
      }

      const worldPoint = projectWorldPoint(latitude, longitude);
      const japanPoint = projectJapanPoint(latitude, longitude);
      setMapMarker(worldMapMarker, worldMapWave, worldMapLabel, worldPoint, labelText || `${formatLatLon(latitude)}, ${formatLatLon(longitude)}`);

      if (!japanPoint) {
        setMapMarker(japanMapMarker, japanMapWave, japanMapLabel, null, '日本国外', true);
        japanMapOutside.classList.add('show');
      } else {
        japanMapOutside.classList.remove('show');
        setMapMarker(japanMapMarker, japanMapWave, japanMapLabel, japanPoint, labelText || `${formatLatLon(latitude)}, ${formatLatLon(longitude)}`);
      }
    }

    function buildGeoRequestKey(params) {
      const keys = Object.keys(params || {}).sort();
      return keys.map((key) => `${key}:${params[key]}`).join('|');
    }

    function renderGeoPanel(payload, requestMode = geoState.mode) {
      const location = getPathValue(payload, ['location'], {});
      const weather = getPathValue(payload, ['weather'], {});
      const status = getPathValue(payload, ['status'], 'error');
      const mode = normalizeMode(location.mode || requestMode);

      const latitude = Number(location.latitude);
      const longitude = Number(location.longitude);
      const hasCoord = Number.isFinite(latitude) && Number.isFinite(longitude);
      geoState.targetCoord = hasCoord ? { latitude, longitude } : null;
      geoState.selectedCountry = String(location.country || '').trim();

      const prefCandidate = normalizePrefName(location.region || location.city || '');
      geoState.selectedPrefecture = prefCandidate;
      geoState.selectedPrefCode = String(
        Object.keys(PREF_CODE_TO_NAME).find((code) => PREF_CODE_TO_NAME[Number(code)] === prefCandidate) || ''
      );
      geoState.selectedRegionBand = resolveRegionBandFromPref(prefCandidate);

      setGeoMapMarkers(
        hasCoord ? latitude : NaN,
        hasCoord ? longitude : NaN,
        `${location.region || location.city || location.country || '地点不明'}`
      );
      renderDetailMap();

      geoLocationLabel.textContent = location.label || '地点: —';
      const formalAddress = [location.city, location.region, location.country].filter((item) => item && item !== '—').join(', ') || '—';
      geoLocationMeta.textContent = `地域: ${location.region || location.city || '—'} / 国: ${location.country || '—'} / 住所: ${formalAddress}`;
      geoLatLon.textContent = `緯度: ${formatLatLon(location.latitude)} / 経度: ${formatLatLon(location.longitude)}`;
      geoProvider.textContent = `取得元: ${mode === 'device' ? '端末位置' : mode === 'manual' ? '手動' : 'IP推定'} / ${location.provider || '—'}`;
      geoAccuracy.textContent = mode === 'ip' ? '精度: IPによる概算（誤差は不明）' : mode === 'manual' ? '精度: 指定地域の代表地点' : `精度: ${formatAccuracy(location.accuracy_m)}`;
      geoTimezone.textContent = weather.timezone || '—';
      geoLocalTime.textContent = weather.local_time || '—';
      geoWeather.textContent = weather.weather || '—';
      geoTemp.textContent = weather.current_temp || '—';
      geoHumidity.textContent = weather.humidity || '—';
      geoWind.textContent = `${weather.wind_speed || '—'} / ${weather.wind_direction || '—'}`;
      geoObservedAt.textContent = weather.observed_at || '—';
      geoHiLo.textContent = `${weather.high_temp || '—'} / ${weather.low_temp || '—'}`;
      geoRain.textContent = weather.precipitation || '—';
      geoStatus.textContent = payload.message || (status === 'ready' ? '表示中' : '取得に失敗しました。チャットは利用可能です。');

      if (mode === 'manual') {
        const manualLabel = location.region || location.city || location.country || '未設定';
        const representative = geoState.manualResolvedAddress && geoState.manualResolvedAddress.includes('代表地点') ? '（代表地点）' : '';
        locationInput.value = `手動: ${manualLabel}${representative}`;
      } else if (mode === 'device') {
        locationInput.value = `端末位置: ${location.region || location.city || location.country || '現在地'}`;
      } else {
        locationInput.value = `IP推定: ${location.region || location.city || location.country || '不明'}`;
      }
      persistCurrentLocation(locationInput.value.trim());

      if (status === 'ready') {
        setGeoPanelState('ready');
      } else if (status === 'location_failed') {
        setGeoPanelState('error');
      } else {
        setGeoPanelState('loading');
      }
    }

    function readGeoPanelCache() {
      const raw = safeStorageGet(geoPanelCacheKey);
      if (!raw) {
        return null;
      }
      try {
        const parsed = JSON.parse(raw);
        if (!parsed || typeof parsed !== 'object') {
          return null;
        }
        const expiresAt = Number(parsed.expires_at || 0);
        if (expiresAt <= Date.now()) {
          return null;
        }
        if ((parsed.request_key || '') !== (geoState.requestKey || '')) {
          return null;
        }
        return parsed.payload || null;
      } catch (e) {
        return null;
      }
    }

    function writeGeoPanelCache(payload, ttlSec) {
      const ttl = Math.max(60, Number(ttlSec || 1800));
      safeStorageSet(
        geoPanelCacheKey,
        JSON.stringify({
          request_key: geoState.requestKey || '',
          payload,
          expires_at: Date.now() + (ttl * 1000),
        })
      );
    }

    function geolocationErrorMessage(error) {
      if (!error || typeof error !== 'object') {
        return '位置情報を取得できませんでした。';
      }
      if (error.code === 1) {
        return '位置情報の利用が拒否されました。';
      }
      if (error.code === 2) {
        return '位置情報を取得できませんでした。電波やネットワークを確認してください。';
      }
      if (error.code === 3) {
        return '位置情報の取得がタイムアウトしました。';
      }
      return error.message || '位置情報を取得できませんでした。';
    }

    async function reverseGeocodeByCoords(latitude, longitude) {
      const url = new URL('https://geocoding-api.open-meteo.com/v1/reverse');
      url.searchParams.set('latitude', String(latitude));
      url.searchParams.set('longitude', String(longitude));
      url.searchParams.set('language', 'ja');
      url.searchParams.set('count', '1');
      url.searchParams.set('format', 'json');

      const response = await fetch(url.toString());
      const data = await response.json();
      const result = (data.results && data.results[0]) || {};
      return {
        city: result.name || '',
        region: result.admin1 || result.admin2 || '',
        country: result.country || '',
      };
    }

    async function geocodeManualRegion(regionName) {
      const text = String(regionName || '').trim();
      if (!text) {
        return [];
      }
      const url = new URL('https://geocoding-api.open-meteo.com/v1/search');
      url.searchParams.set('name', text);
      url.searchParams.set('count', '6');
      url.searchParams.set('language', 'ja');
      url.searchParams.set('format', 'json');

      const response = await fetch(url.toString());
      const data = await response.json();
      const results = Array.isArray(data.results) ? data.results : [];
      return results.map((result) => {
        const city = result.name || text;
        const region = result.admin1 || result.admin2 || '';
        const country = result.country || '';
        const addressParts = [city, region, country].filter(Boolean);
        const featureCode = String(result.feature_code || '').toUpperCase();
        const isRepresentative = featureCode === 'ADM3' || featureCode === 'ADM2' || featureCode === 'ADM1';
        return {
          city,
          region,
          country,
          latitude: Number(result.latitude),
          longitude: Number(result.longitude),
          address: addressParts.join(', '),
          representative: isRepresentative,
        };
      });
    }

    function renderManualCandidates(candidates) {
      if (!geoManualCandidates) {
        return;
      }
      geoManualCandidates.innerHTML = '';
      if (!Array.isArray(candidates) || candidates.length === 0) {
        return;
      }
      const title = document.createElement('div');
      title.className = 'geo-meta';
      title.textContent = '候補を選択してください（自動確定しません）';
      geoManualCandidates.appendChild(title);

      candidates.forEach((candidate, index) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'geo-manual-candidate';
        const name = candidate.city || '名称不明';
        const address = candidate.address || [candidate.region, candidate.country].filter(Boolean).join(', ') || '住所不明';
        const representative = candidate.representative ? '（代表地点）' : '';
        button.innerHTML = `${escapeHtml(name)}${representative}<small>${escapeHtml(address)}</small>`;
        button.addEventListener('click', async () => {
          await confirmManualCandidate(index);
        });
        geoManualCandidates.appendChild(button);
      });
    }

    async function confirmManualCandidate(index) {
      const candidate = Array.isArray(geoState.manualCandidates) ? geoState.manualCandidates[index] : null;
      if (!candidate) {
        return;
      }
      geoState.manualDetails = {
        city: candidate.city || '',
        region: candidate.region || '',
        country: candidate.country || '',
        latitude: Number(candidate.latitude),
        longitude: Number(candidate.longitude),
      };
      geoState.manualResolvedAddress = `${candidate.address || ''}${candidate.representative ? '（代表地点）' : ''}`;
      geoState.manualLock = true;
      geoState.mode = 'manual';
      persistGeoMode('manual');
      if (geoSourceSelect) {
        geoSourceSelect.value = 'manual';
      }
      geoManualCandidates.innerHTML = '';
      clearGeoPanelCache();
      await refreshGeoPanel(true, 'manual');
    }

    function buildGeoQuery(mode, reasonText = '') {
      const selectedMode = normalizeMode(mode || geoState.mode);
      const query = { source: selectedMode };

      if (selectedMode === 'device' && geoState.device) {
        query.lat = String(geoState.device.latitude);
        query.lon = String(geoState.device.longitude);
        query.accuracy = String(geoState.device.accuracy || '');
        query.city = geoState.device.city || '';
        query.region = geoState.device.region || '';
        query.country = geoState.device.country || '';
        query.provider = 'browser_geolocation';
      }

      if (selectedMode === 'manual') {
        query.manual = geoState.manual || '';
        if (geoState.manualDetails) {
          query.lat = String(geoState.manualDetails.latitude);
          query.lon = String(geoState.manualDetails.longitude);
          query.city = geoState.manualDetails.city || '';
          query.region = geoState.manualDetails.region || '';
          query.country = geoState.manualDetails.country || '';
          query.provider = 'manual_geocode';
        }
      }

      if (selectedMode === 'ip' && reasonText) {
        query.reason = reasonText;
      }

      return query;
    }

    async function refreshGeoPanel(force = false, mode = geoState.mode, reasonText = '') {
      const normalizedMode = normalizeMode(mode || geoState.mode);
      if (geoState.manualLock && normalizedMode !== 'manual') {
        return;
      }
      await initializeGeoMaps();
      const requestSeq = (geoState.requestSeq || 0) + 1;
      geoState.requestSeq = requestSeq;
      const query = buildGeoQuery(normalizedMode, reasonText);
      geoState.requestKey = buildGeoRequestKey(query);
      if (!force) {
        const cached = readGeoPanelCache();
        if (cached) {
          if (requestSeq < geoState.requestSeq) {
            return;
          }
          geoState.appliedSeq = requestSeq;
          renderGeoPanel(cached, normalizedMode);
          return;
        }
      }

      setGeoPanelState('loading');
      geoStatus.textContent = '取得中...';
      try {
        const url = new URL('/panel/location-weather', window.location.origin);
        Object.entries(query).forEach(([key, value]) => {
          if (value != null && String(value).trim() !== '') {
            url.searchParams.set(key, String(value));
          }
        });

        const res = await fetch(url.toString());
        const data = await res.json();
        if (requestSeq < geoState.requestSeq) {
          return;
        }
        geoState.appliedSeq = requestSeq;
        renderGeoPanel(data || {}, normalizedMode);
        writeGeoPanelCache(data || {}, Number(getPathValue(data, ['next_refresh_sec'], 1800)));
        appendRuntimeLog(`location ${normalizeMode(normalizedMode)}: ${getPathValue(data, ['location', 'region'], '—') || '—'}`);
      } catch (e) {
        if (requestSeq < geoState.requestSeq) {
          return;
        }
        geoState.appliedSeq = requestSeq;
        renderGeoPanel({
          status: 'location_failed',
          message: '取得に失敗しました。チャットは利用可能です。',
          location: { label: '現在地: 取得失敗', city: '—', region: '—', country: '—', latitude: null, longitude: null, provider: '—', mode: normalizedMode },
          weather: { weather: '—', current_temp: '—', high_temp: '—', low_temp: '—', precipitation: '—' },
        }, normalizedMode);
        appendRuntimeLog(`location ${normalizeMode(normalizedMode)}: failed`);
      }
    }

    async function applyManualLocation() {
      const manual = (geoManualInput.value || '').trim();
      geoState.manual = manual;
      persistManualRegion(manual);
      geoState.mode = 'manual';
      geoState.manualLock = true;
      persistGeoMode('manual');
      if (geoSourceSelect) {
        geoSourceSelect.value = 'manual';
      }
      geoState.manualDetails = null;
      geoState.manualResolvedAddress = '';
      geoState.manualCandidates = [];
      if (geoManualCandidates) {
        geoManualCandidates.innerHTML = '';
      }

      if (!manual) {
        geoStatus.textContent = '手動地点を入力してください。';
        setGeoMapMarkers(NaN, NaN, '座標未確定');
        return;
      }

      try {
        const candidates = await geocodeManualRegion(manual);
        geoState.manualCandidates = candidates;
        if (!candidates.length) {
          geoStatus.textContent = '候補が見つかりません。入力を修正してください。';
          setGeoMapMarkers(NaN, NaN, '座標未確定');
          renderManualCandidates([]);
          return;
        }
        if (candidates.length === 1) {
          await confirmManualCandidate(0);
          geoStatus.textContent = '手動地点を確定しました。';
          return;
        }
        renderManualCandidates(candidates);
        geoStatus.textContent = '候補から地点を選択してください。';
        setGeoMapMarkers(NaN, NaN, '座標未確定');
        return;
      } catch (e) {
        geoState.manualDetails = null;
        geoState.manualCandidates = [];
        geoStatus.textContent = '手動地点の検索に失敗しました。';
        setGeoMapMarkers(NaN, NaN, '座標未確定');
        return;
      }
    }

    async function requestDeviceLocation() {
      geoState.manualLock = false;
      if (!navigator.geolocation) {
        const reason = 'このブラウザは位置情報APIに対応していません。IP推定に切り替えます。';
        geoState.mode = 'ip';
        persistGeoMode('ip');
        if (geoSourceSelect) {
          geoSourceSelect.value = 'ip';
        }
        clearGeoPanelCache();
        await refreshGeoPanel(true, 'ip', reason);
        appendRuntimeLog('device location unsupported -> ip');
        return;
      }

      if (!window.isSecureContext && window.location.hostname !== 'localhost') {
        const reason = 'この接続（LAN内HTTP）は位置情報取得が制限される場合があります。IP推定に切り替えます。';
        geoState.mode = 'ip';
        persistGeoMode('ip');
        if (geoSourceSelect) {
          geoSourceSelect.value = 'ip';
        }
        clearGeoPanelCache();
        await refreshGeoPanel(true, 'ip', reason);
        appendRuntimeLog('device location blocked on insecure context -> ip');
        return;
      }

      setGeoPanelState('loading');
      geoStatus.textContent = '端末位置を取得中...';
      navigator.geolocation.getCurrentPosition(
        async (position) => {
          const latitude = Number(position.coords.latitude);
          const longitude = Number(position.coords.longitude);
          const accuracy = Number(position.coords.accuracy);
          const place = { city: '', region: '', country: '' };
          try {
            const resolved = await reverseGeocodeByCoords(latitude, longitude);
            place.city = resolved.city || '';
            place.region = resolved.region || '';
            place.country = resolved.country || '';
          } catch (e) {
          }

          geoState.device = {
            latitude,
            longitude,
            accuracy,
            city: place.city,
            region: place.region,
            country: place.country,
          };
          geoState.mode = 'device';
          persistGeoMode('device');
          if (geoSourceSelect) {
            geoSourceSelect.value = 'device';
          }

          clearGeoPanelCache();
          await refreshGeoPanel(true, 'device');
          appendRuntimeLog('device location: success');
        },
        async (error) => {
          if (geoState.manualLock) {
            geoStatus.textContent = geolocationErrorMessage(error);
            return;
          }
          const reason = `${geolocationErrorMessage(error)} LAN内HTTPではブラウザ制限で失敗することがあります。`;
          geoState.mode = 'ip';
          persistGeoMode('ip');
          if (geoSourceSelect) {
            geoSourceSelect.value = 'ip';
          }
          clearGeoPanelCache();
          await refreshGeoPanel(true, 'ip', reason);
          appendRuntimeLog('device location denied/failed -> ip');
        },
        { enableHighAccuracy: true, timeout: 7000, maximumAge: 30000 }
      );
    }

    function escapeHtml(text) {
      return String(text || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }

    function linkifyText(text) {
      const escaped = escapeHtml(text);
      const urlPattern = new RegExp('(https?://[^\\\\s<]+)', 'g');
      return escaped.replace(urlPattern, (url) => `<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a>`);
    }

    function addBubble(role, text) {
      const el = document.createElement('div');
      el.className = `bubble ${role}`;
      const rawText = String(text || '');

      const copyIconSvg = [
        '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">',
        '<rect x="9" y="9" width="11" height="11" rx="2"></rect>',
        '<rect x="4" y="4" width="11" height="11" rx="2"></rect>',
        '</svg>',
      ].join('');
      const copiedIconSvg = [
        '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">',
        '<path d="M5 12.5l4.2 4.2L19 7.5"></path>',
        '</svg>',
      ].join('');

      if (role === 'user' || role === 'assistant') {
        const head = document.createElement('div');
        head.className = 'bubble-head';
        const copyBtn = document.createElement('button');
        copyBtn.type = 'button';
        copyBtn.className = 'bubble-copy-btn';
        copyBtn.innerHTML = copyIconSvg;
        copyBtn.setAttribute('aria-label', '全文をコピー');
        copyBtn.setAttribute('title', '全文をコピー');
        copyBtn.addEventListener('click', async () => {
          try {
            if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
              await navigator.clipboard.writeText(rawText);
            } else {
              const area = document.createElement('textarea');
              area.value = rawText;
              document.body.appendChild(area);
              area.select();
              document.execCommand('copy');
              document.body.removeChild(area);
            }
            copyBtn.classList.add('is-copied');
            copyBtn.innerHTML = copiedIconSvg;
            setTimeout(() => {
              copyBtn.classList.remove('is-copied');
              copyBtn.innerHTML = copyIconSvg;
            }, 1500);
          } catch (e) {
          }
        });
        head.appendChild(copyBtn);
        el.appendChild(head);
      }

      const body = document.createElement('div');
      body.className = 'bubble-content';
      body.innerHTML = linkifyText(rawText).split(String.fromCharCode(10)).join('<br>');
      el.appendChild(body);
      chatLog.appendChild(el);
      chatLog.scrollTop = chatLog.scrollHeight;
      return el;
    }

    function showEvaluation(evaluation) {
      if (!evaluation || typeof evaluation !== 'object') {
        return;
      }

      const requestId = evaluation.request_id || '';
      const route = evaluation.route || '不明';
      const responseTime = Number(evaluation.response_time_sec || 0).toFixed(2);
      const apiLabel = evaluation.api_called ? 'あり' : 'なし';
      const savedCost = Number(evaluation.saved_cost_yen || 0).toFixed(4);
      const reductionRate = Number(evaluation.cloud_api_call_reduction_rate || evaluation.api_reduction_rate || 0).toFixed(1);
      runtimeRoute.textContent = route || '—';
      runtimeLatency.textContent = `${responseTime}秒`;
      runtimeCloud.textContent = evaluation.api_called ? '使用あり' : '未使用';
      appendRuntimeLog(`route=${route} / ${responseTime}秒 / cloud=${evaluation.api_called ? 'on' : 'off'}`);
      const lines = [
        `処理経路：${route}`,
        `応答時間：${responseTime}秒`,
        `API使用：${apiLabel}`,
        `今回の推定削減額：${savedCost}円`,
        `累計クラウドAPI呼出削減率：${reductionRate}％`,
      ];

      const wrap = document.createElement('details');
      wrap.className = 'evaluation-wrap';
      const summary = document.createElement('summary');
      summary.textContent = '回答の評価・API使用の詳細';
      wrap.appendChild(summary);

      const body = document.createElement('div');
      body.className = 'meta-line';
      body.textContent = lines.join(String.fromCharCode(10));
      wrap.appendChild(body);

      if (requestId) {
        const actionTitle = document.createElement('div');
        actionTitle.className = 'choice-title';
        actionTitle.textContent = '回答品質評価';
        wrap.appendChild(actionTitle);

        const actions = document.createElement('div');
        actions.className = 'evaluation-actions';

        const options = [
          { label: '良い', value: 'good' },
          { label: '一部修正', value: 'partial' },
          { label: '悪い', value: 'bad' },
        ];

        const status = document.createElement('div');
        status.className = 'meta-line';
        status.textContent = `request_id: ${requestId}`;
        wrap.appendChild(status);

        options.forEach((option) => {
          const button = document.createElement('button');
          button.type = 'button';
          button.className = 'secondary';
          button.textContent = option.label;
          button.addEventListener('click', async () => {
            button.disabled = true;
            status.textContent = `request_id: ${requestId} | 評価を送信中...`;
            try {
              const res = await fetch('/evaluation/feedback', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ request_id: requestId, rating: option.value }),
              });
              const data = await res.json();
              if (!data.ok) {
                throw new Error(data.error || 'feedback failed');
              }
              status.textContent = `request_id: ${requestId} | 評価: ${option.label} を保存しました`;
              actions.querySelectorAll('button').forEach((btn) => {
                btn.disabled = true;
              });
            } catch (error) {
              status.textContent = `request_id: ${requestId} | 評価保存に失敗しました`;
              actions.querySelectorAll('button').forEach((btn) => {
                btn.disabled = false;
              });
            }
          });
          actions.appendChild(button);
        });

        wrap.appendChild(actions);
      }

      chatLog.appendChild(wrap);
      chatLog.scrollTop = chatLog.scrollHeight;
    }

    function addChoicePanel(ui) {
      if (!ui || !Array.isArray(ui.options) || ui.options.length === 0) {
        return;
      }
      const wrap = document.createElement('div');
      wrap.className = 'choice-wrap';

      const title = document.createElement('div');
      title.className = 'choice-title';
      title.textContent = ui.title || '候補を選択';
      wrap.appendChild(title);

      if (ui.description) {
        const description = document.createElement('div');
        description.className = 'choice-title';
        description.textContent = ui.description;
        wrap.appendChild(description);
      }

      const grid = document.createElement('div');
      grid.className = 'choice-grid';
      wrap.appendChild(grid);

      ui.options.forEach((option) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'choice-btn';
        const label = document.createElement('div');
        label.textContent = option.label || option.message || '選択';
        btn.appendChild(label);
        if (option.description) {
          const meta = document.createElement('div');
          meta.className = 'template-item-meta';
          meta.textContent = option.description;
          btn.appendChild(meta);
        }
        btn.addEventListener('click', () => {
          messageInput.value = option.message || option.label || '';
          messageInput.focus();
          if ((ui.interaction || option.interaction || '').toLowerCase() === 'send') {
            sendMessage();
          }
        });
        grid.appendChild(btn);
      });

      chatLog.appendChild(wrap);
      chatLog.scrollTop = chatLog.scrollHeight;
    }

    function addPromptInputPanel(ui) {
      if (!ui || !ui.type || ui.type !== 'prompt_input') {
        return;
      }

      const wrap = document.createElement('div');
      wrap.className = 'choice-wrap';

      const title = document.createElement('div');
      title.className = 'choice-title';
      title.textContent = ui.title || '入力してください';
      wrap.appendChild(title);

      if (ui.description) {
        const desc = document.createElement('div');
        desc.className = 'template-item-meta';
        desc.textContent = ui.description;
        wrap.appendChild(desc);
      }

      const row = document.createElement('div');
      row.className = 'row';
      row.style.marginTop = '8px';

      const input = document.createElement('input');
      input.type = 'text';
      input.placeholder = ui.placeholder || '入力してください';
      input.style.flex = '1';
      input.value = '';
      row.appendChild(input);

      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'secondary';
      btn.textContent = ui.button_label || '再演算';
      btn.addEventListener('click', () => {
        const value = input.value.trim();
        if (!value) {
          input.focus();
          return;
        }
        const finalText = (ui.template || '{value}').replace('{value}', value);
        messageInput.value = finalText;
        messageInput.focus();
        sendMessage();
      });
      row.appendChild(btn);
      wrap.appendChild(row);

      chatLog.appendChild(wrap);
      chatLog.scrollTop = chatLog.scrollHeight;
    }

    function addFollowupPanel(followups) {
      if (!Array.isArray(followups) || followups.length === 0) {
        return;
      }

      const wrap = document.createElement('div');
      wrap.className = 'followup-wrap';

      const title = document.createElement('div');
      title.className = 'choice-title';
      title.textContent = '次にできること';
      wrap.appendChild(title);

      const chips = document.createElement('div');
      chips.className = 'followup-chips';
      wrap.appendChild(chips);

      followups.slice(0, 4).forEach((item) => {
        const text = String(getPathValue(item, ['message'], '') || '').trim();
        if (!text) {
          return;
        }
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'followup-chip';
        chip.textContent = String(getPathValue(item, ['label'], '') || text);
        const description = String(getPathValue(item, ['description'], '') || '').trim();
        if (description) {
          chip.title = description;
        }
        chip.addEventListener('click', () => {
          messageInput.value = text;
          messageInput.focus();
          sendMessage();
        });
        chips.appendChild(chip);
      });

      if (!chips.children.length) {
        return;
      }

      chatLog.appendChild(wrap);
      chatLog.scrollTop = chatLog.scrollHeight;
    }

    let documentCache = [];
    let currentDocumentId = '';
    let documentDraftMode = true;

    function applyTemplate(templateText) {
      messageInput.value = templateText || '';
      messageInput.focus();
    }

    function renderCapabilityTemplates(templates) {
      capabilityTemplateList.innerHTML = '';
      if (!Array.isArray(templates) || templates.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'doc-empty';
        empty.textContent = 'テンプレートを取得できませんでした。';
        capabilityTemplateList.appendChild(empty);
        return;
      }

      templates.forEach((item) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'template-item';

        const title = document.createElement('div');
        title.className = 'template-item-title';
        title.textContent = item.title || '無題';
        button.appendChild(title);

        const summary = document.createElement('div');
        summary.className = 'template-item-meta';
        summary.textContent = item.summary || '説明なし';
        button.appendChild(summary);

        const example = document.createElement('div');
        example.className = 'template-item-meta';
        example.textContent = `テンプレート: ${item.template || ''}`;
        button.appendChild(example);

        button.addEventListener('click', () => {
          applyTemplate(item.template || '');
        });

        capabilityTemplateList.appendChild(button);
      });
    }

    function renderDocumentList(documents) {
      documentList.innerHTML = '';
      if (!documents.length) {
        const empty = document.createElement('div');
        empty.className = 'doc-empty';
        empty.textContent = '保存文書はまだありません。';
        documentList.appendChild(empty);
        return;
      }

      documents.forEach((item) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = `doc-item ${item.is_current || item.doc_id === currentDocumentId ? 'active' : ''}`.trim();

        const title = document.createElement('div');
        title.className = 'doc-item-title';
        title.textContent = item.title || '無題';
        button.appendChild(title);

        const meta = document.createElement('div');
        meta.className = 'doc-item-meta';
        meta.textContent = `${item.doc_id || 'IDなし'} | ${item.chars || 0}文字 | ${item.saved_at || item.updated_at || '日時不明'}`;
        button.appendChild(meta);

        const preview = document.createElement('div');
        preview.className = 'doc-item-meta';
        preview.textContent = item.preview || 'プレビューなし';
        button.appendChild(preview);

        button.addEventListener('click', () => {
          loadDocument(item.doc_id);
        });
        documentList.appendChild(button);
      });
    }

    function setDocumentEditor(documentData) {
      if (!documentData) {
        currentDocumentId = '';
        documentDraftMode = true;
        documentTitleInput.value = '';
        documentContentInput.value = '';
        documentMode.textContent = '新規登録';
        documentMeta.textContent = '新規文書を入力してください。';
        documentCurrentCard.textContent = '現在表示中: なし';
        renderDocumentList(documentCache);
        return;
      }

      currentDocumentId = documentData.doc_id || '';
      documentDraftMode = false;
      documentTitleInput.value = documentData.title || '';
      documentContentInput.value = documentData.content || '';
      documentMode.textContent = '編集中';
      const newline = String.fromCharCode(10);
      documentMeta.textContent = [
        `文書ID: ${documentData.doc_id || 'なし'}`,
        `文字数: ${documentData.chars || (documentData.content || '').length || 0}`,
        `保存時刻: ${documentData.saved_at || documentData.updated_at || '不明'}`,
        `更新時刻: ${documentData.updated_at || '不明'}`,
        `ファイル: ${documentData.file_path || '不明'}`,
      ].join(newline);
      const preview = (documentData.preview || documentData.content || '').replace(new RegExp('\\\\s+', 'g'), ' ').trim();
      documentCurrentCard.textContent = `現在表示中: ${documentData.title || '無題'} (${documentData.doc_id || 'IDなし'})` + newline + `概要: ${preview ? preview.slice(0, 80) : '本文なし'}`;
      renderDocumentList(documentCache);
    }

    async function refreshDocuments(preferredDocId = currentDocumentId) {
      try {
        const res = await fetch('/documents');
        const data = await res.json();
        if (!data.ok) {
          throw new Error(data.error || 'documents unavailable');
        }

        documentCache = Array.isArray(data.documents) ? data.documents : [];
        renderDocumentList(documentCache);

        if (documentDraftMode && !preferredDocId) {
          return;
        }

        const currentSessionDocId = getPathValue(data, ['session', 'current_doc_id'], '');
        const currentDoc = currentSessionDocId
          ? documentCache.find((item) => item.doc_id === currentSessionDocId)
          : null;
        const targetDoc = preferredDocId
          ? documentCache.find((item) => item.doc_id === preferredDocId)
          : null;

        if (targetDoc) {
          await loadDocument(targetDoc.doc_id, { skipRefresh: true });
        } else if (currentDoc) {
          await loadDocument(currentDoc.doc_id, { skipRefresh: true });
        } else if (!documentCache.length) {
          setDocumentEditor(null);
        }
      } catch (e) {
        documentCache = [];
        documentList.innerHTML = '';
        const error = document.createElement('div');
        error.className = 'doc-empty';
        error.textContent = '文書一覧を取得できませんでした。';
        documentList.appendChild(error);
        setDocumentEditor(null);
      }
    }

    async function loadDocument(docId, options = {}) {
      if (!docId) {
        setDocumentEditor(null);
        return;
      }

      try {
        const res = await fetch(`/documents/${encodeURIComponent(docId)}`);
        const data = await res.json();
        if (!data.ok || !data.document) {
          throw new Error(data.error || 'document unavailable');
        }

        setDocumentEditor(data.document);
        if (!options.skipRefresh) {
          await refreshDocuments(docId);
        }
      } catch (e) {
        addBubble('system', '文書の読み込みに失敗しました。');
      }
    }

    async function saveDocument() {
      const title = documentTitleInput.value.trim();
      const content = documentContentInput.value;
      if (!title || !content.trim()) {
        addBubble('system', 'タイトルと本文を入力してください。');
        return;
      }

      try {
        const isNewDocument = !currentDocumentId;
        const res = await fetch(isNewDocument ? '/documents' : `/documents/${encodeURIComponent(currentDocumentId)}`, {
          method: isNewDocument ? 'POST' : 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title, content }),
        });
        const data = await res.json();
        if (!data.ok) {
          throw new Error(data.error || 'update failed');
        }

        addBubble('system', isNewDocument ? '文書を新規登録しました。' : '文書を保存しました。');
        setDocumentEditor(data.document || null);
        const savedDocId = getPathValue(data, ['document', 'doc_id'], '');
        await refreshDocuments(savedDocId || currentDocumentId);
      } catch (e) {
        addBubble('system', currentDocumentId ? '文書の保存に失敗しました。' : '文書の新規登録に失敗しました。');
      }
    }

    async function deleteDocument() {
      if (!currentDocumentId) {
        addBubble('system', '削除する文書を選択してください。');
        return;
      }

      const currentTitle = documentTitleInput.value.trim() || 'この文書';
      if (!window.confirm(`${currentTitle} を削除しますか？`)) {
        return;
      }

      try {
        const res = await fetch(`/documents/${encodeURIComponent(currentDocumentId)}`, {
          method: 'DELETE',
        });
        const data = await res.json();
        if (!data.ok) {
          throw new Error(data.error || 'delete failed');
        }

        addBubble('system', '文書を削除しました。');
        setDocumentEditor(null);
        await refreshDocuments();
      } catch (e) {
        addBubble('system', '文書の削除に失敗しました。');
      }
    }

    function clearDocumentSelection() {
      currentDocumentId = '';
      documentDraftMode = true;
      documentTitleInput.value = '';
      documentContentInput.value = '';
      documentMode.textContent = '新規登録';
      documentMeta.textContent = '新規文書を入力してください。';
      renderDocumentList(documentCache);
    }

    function setStatus(text) {
      healthText.textContent = text;
      healthCard.textContent = text;
    }

    function setMeta(meta) {
      const urls = getPathValue(meta, ['server', 'open_urls'], []);
      const localIp = getPathValue(meta, ['server', 'local_ip'], 'unknown');
      const modelName = getPathValue(meta, ['local_llm', 'model'], 'unknown');
      const firstUrl = urls[0] || `${window.location.origin}/`;
      const newline = String.fromCharCode(10);
      serverUrlChip.textContent = `url: ${firstUrl}`;
      serverIpChip.textContent = `ip: ${localIp}`;
      runtimeModel.textContent = modelName || '—';
      metaCard.textContent = `PCのURL: ${firstUrl}` + newline + `ローカルIP: ${localIp}` + newline + `Ollama: ${modelName}` + newline;
    }

    async function refreshHealth() {
      try {
        const res = await fetch('/health');
        const data = await res.json();
        const modelName = getPathValue(data, ['ollama', 'model_configured'], data.model || 'unknown');
        setStatus(`health: ${data.status} | model: ${modelName}`);
        runtimeConnection.textContent = data.status || '—';
        runtimeModel.textContent = modelName || '—';
      } catch (e) {
        setStatus('health: offline');
        runtimeConnection.textContent = 'offline';
      }
    }

    async function refreshMeta() {
      try {
        const res = await fetch('/meta');
        const data = await res.json();
        if (data.ok) {
          setMeta(data);
        }
      } catch (e) {
        serverUrlChip.textContent = 'url: unavailable';
        serverIpChip.textContent = 'ip: unavailable';
      }
    }

    async function refreshStorage() {
      try {
        const res = await fetch('/storage');
        const data = await res.json();
        if (!data || !data.ok) {
          throw new Error('storage unavailable');
        }

        window.dispatchEvent(new CustomEvent('jarvis:storage-status',{detail:data}));
        const dbPath = getPathValue(data, ['paths', 'documents_db'], 'unknown');
        const dbRows = getPathValue(data, ['counts', 'documents_db_rows'], 0);
        const docItems = getPathValue(data, ['counts', 'document_items'], 0);
        const repaired = getPathValue(data, ['db_repaired_rows'], 0);
        const newline = String.fromCharCode(10);
        storageCard.textContent = `DB: ${dbPath}` + newline + `DB行数: ${dbRows} | 文書件数: ${docItems}` + newline + `自己修復: ${repaired}行`;
      } catch (e) {
        storageCard.textContent = 'DB状態を取得できませんでした。';
      }
    }

    async function refreshCapabilities() {
      try {
        const res = await fetch('/capabilities');
        const data = await res.json();
        if (!data || !data.ok) {
          throw new Error('capabilities unavailable');
        }

        capabilityGuide.textContent = '選ぶと入力欄にテンプレートを入れます。必要なら少し直して送信してください。';
        renderCapabilityTemplates(data.templates || []);
      } catch (e) {
        capabilityGuide.textContent = 'テンプレート一覧を取得できませんでした。';
        renderCapabilityTemplates([]);
      }
    }

    let isSending = false;
    let queuedMessage = '';

    async function sendMessage() {
      const text = messageInput.value.trim();
      const sessionId = sessionInput.value.trim() || savedSessionId;
      const currentLocation = locationInput.value.trim() || savedCurrentLocation;
      if (!text) {
        return;
      }

      if (window.workbench?.busy() && !isSending) return;
      if (isSending) {
        queuedMessage = text;
        messageInput.value = text;
        return;
      }

      sessionInput.value = sessionId;
      safeStorageSet(storageKey, sessionId);
      persistCurrentLocation(currentLocation);
      sessionText.textContent = sessionId;

      isSending = true;
      sendBtn.disabled = true;
      const turboMode = !!(turboModeInput && turboModeInput.checked);
      runtimeProcessing.textContent = turboMode ? '処理中 (Turbo)' : '処理中';
      window.aiCore.setState('thinking');
      addBubble('user', text);
      messageInput.value = '';

      const typing = addBubble('system', 'thinking...');

      try {
        const data = await window.dashboardRequest({ message: text, session_id: sessionId, current_location: currentLocation, turbo_mode: turboMode });
        typing.remove();
        if (data.ok) {
          addBubble('assistant', data.response);
          addFollowupPanel(data.followups);
          window.workbench.complete(data);
          if (window.workbench.succeeded(data)) window.aiCore.answer(data.response, data.evaluation);
          else window.aiCore.setState('error');
          showEvaluation(data.evaluation);
          appendRuntimeLog(`message ok (${data.performance_mode || (turboMode ? 'turbo' : 'balanced')}): ${text.slice(0, 36)}`);
          if (data.ui) {
            if (data.ui.type === 'prompt_input') {
              addPromptInputPanel(data.ui);
            } else {
              addChoicePanel(data.ui);
            }
          }
          await refreshDocuments();
        } else {
          addBubble('assistant', data.error || 'error');
          window.aiCore.setState('error');
          window.workbench.complete(data);
          showEvaluation(data.evaluation);
          appendRuntimeLog(`message error (${data.performance_mode || (turboMode ? 'turbo' : 'balanced')}): ${String(data.error || 'error').slice(0, 36)}`);
        }
      } catch (e) {
        typing.remove();
        window.aiCore.setState('error');
        window.workbench.fail();
        const detail = e && e.message ? ` (${e.message})` : '';
        addBubble('assistant', `通信に失敗しました。${detail}`);
        appendRuntimeLog(`network error${detail}`);
      } finally {
        isSending = false;
        runtimeProcessing.textContent = '待機中';

        if (queuedMessage) {
          const nextText = queuedMessage;
          queuedMessage = '';
          messageInput.value = nextText;
          sendBtn.disabled = true;
          setTimeout(() => {
            if (!messageInput.value.trim()) {
              messageInput.value = nextText;
            }
            sendMessage();
          }, 0);
          return;
        }

        sendBtn.disabled = false;
        messageInput.focus();
      }
    }

    sendBtn.addEventListener('click', sendMessage);
    capabilityRefreshBtn.addEventListener('click', () => refreshCapabilities());
    documentNewBtn.addEventListener('click', clearDocumentSelection);
    documentRefreshBtn.addEventListener('click', () => refreshDocuments());
    documentSaveBtn.addEventListener('click', saveDocument);
    documentDeleteBtn.addEventListener('click', deleteDocument);
    documentClearBtn.addEventListener('click', clearDocumentSelection);
    geoFetchBtn.addEventListener('click', () => {
      requestDeviceLocation();
    });
    geoManualApplyBtn.addEventListener('click', () => {
      applyManualLocation();
    });
    geoManualInput.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        applyManualLocation();
      }
    });
    geoSourceSelect.addEventListener('change', async () => {
      const mode = normalizeMode(geoSourceSelect.value);
      geoState.mode = mode;
      if (mode !== 'manual') {
        geoState.manualLock = false;
      }
      persistGeoMode(mode);

      if (mode === 'device') {
        await requestDeviceLocation();
        return;
      }

      if (mode === 'manual') {
        await applyManualLocation();
        return;
      }

      clearGeoPanelCache();
      await refreshGeoPanel(true, 'ip');
    });
    geoNavBackBtn.addEventListener('click', () => {
      if (geoState.detailHistory.length <= 1 || geoState.detailPath.length <= 1) {
        return;
      }
      geoState.detailHistory.pop();
      geoState.detailPath.pop();
      geoState.detailLevel = geoState.detailHistory[geoState.detailHistory.length - 1] || 'world';
      if (geoState.detailLevel !== 'prefecture') {
        geoState.selectedPrefecture = '';
        geoState.selectedPrefCode = '';
      }
      if (geoState.detailLevel === 'country') {
        geoState.selectedRegionBand = '';
      }
      updateDetailBreadcrumb();
      renderDetailMap();
      if (geoState.targetCoord) {
        setGeoMapMarkers(geoState.targetCoord.latitude, geoState.targetCoord.longitude, japanMapLabel.textContent);
      }
    });
    geoNavHomeBtn.addEventListener('click', () => {
      resetDetailState();
      renderDetailMap();
      if (geoState.targetCoord) {
        setGeoMapMarkers(geoState.targetCoord.latitude, geoState.targetCoord.longitude, japanMapLabel.textContent);
      }
    });
    document.querySelectorAll('.quick-prompt').forEach((button) => {
      button.addEventListener('click', () => {
        messageInput.value = button.dataset.text || '';
        messageInput.focus();
      });
    });
    resetBtn.addEventListener('click', () => {
      safeStorageRemove(storageKey);
      const freshId = makeSessionId();
      safeStorageSet(storageKey, freshId);
      sessionInput.value = freshId;
      sessionText.textContent = freshId;
      chatLog.innerHTML = '';
      addBubble('system', 'session reset');
    });
    messageInput.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
        event.preventDefault();
        sendMessage();
      }
    });
    sessionInput.addEventListener('change', () => {
      const value = sessionInput.value.trim();
      if (value) {
        safeStorageSet(storageKey, value);
        sessionText.textContent = value;
      }
    });
    locationInput.addEventListener('change', () => {
      persistCurrentLocation(locationInput.value.trim());
    });
    if (turboModeInput) {
      turboModeInput.addEventListener('change', () => {
        persistTurboMode(!!turboModeInput.checked);
        appendRuntimeLog(`performance mode: ${turboModeInput.checked ? 'turbo' : 'balanced'}`);
      });
    }

    setupGeoVisibilityWatcher();
    initializeGeoMaps();
    attachGeoMapInteractions();

    addBubble('system', 'local-only server ready');
    runtimeProcessing.textContent = '待機中';
    runtimeConnection.textContent = '—';
    runtimeRoute.textContent = '—';
    runtimeLatency.textContent = '—';
    runtimeCloud.textContent = '—';
    refreshTokyoClock();
    setInterval(refreshTokyoClock, 1000);
    refreshMeta();
    refreshHealth();
    refreshStorage();
    refreshCapabilities();
    if (geoState.mode === 'device') {
      requestDeviceLocation();
    } else if (geoState.mode === 'manual' && geoState.manual) {
      applyManualLocation();
    } else {
      refreshGeoPanel(false, 'ip');
    }
    refreshDocuments();
    setInterval(() => {
      refreshHealth();
      refreshStorage();
    }, 20000);
    setInterval(refreshMeta, 60000);
    setInterval(() => refreshGeoPanel(true, geoState.mode), 45 * 60 * 1000);
    setInterval(() => refreshDocuments(), 60000);
    window.prepareMissionPanels();
    window.initDashboard();
    window.initWorkbench();
    window.initDesktopIntegration();
    window.initMaximalistDashboard();
    window.initTaskDeck();
    window.initJarvisOperations();
    window.initMissionControl();
    messageInput.focus({ preventScroll: true });
  