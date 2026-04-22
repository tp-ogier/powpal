"""Render the leaderboard map to a self-contained HTML file.

Usage:
    python scripts/render_map.py
    python scripts/render_map.py --output docs/index.html
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import folium
import geopandas as gpd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from powpal.leaderboard import get_map_data  # noqa: E402

PISTE_GEOJSON = ROOT / "data" / "raw" / "pistes" / "vicheres_liddes.geojson"
DB_PATH = ROOT / "data" / "processed" / "powpal.db"
DEFAULT_OUTPUT = ROOT / "docs" / "index.html"

# piste:difficulty values in the GeoJSON → map colour
DIFFICULTY_COLOURS = {
    "easy": "#4287f5",          # blue
    "intermediate": "#e03030",  # red
    "advanced": "#111111",      # black
}

DIFFICULTY_WORDS = {
    "easy": "blue",
    "intermediate": "red",
    "advanced": "black",
}

MAP_ZOOM = 14

# UI colour palette
BG = "#1e1e1e"        # panel background — charcoal
BG2 = "#2a2a2a"       # slightly lighter for tab buttons, table headers
TEXT = "#f0f0f0"       # primary text
TEXT_DIM = "#999999"   # secondary / rank numbers
BORDER = "#3a3a3a"     # divider lines
ACCENT = "#4287f5"     # slider connect bar, active tab
TICKS = "white"       # ticks showing days with data on the slider


def piste_label(row) -> str:
    """Return a display name for a piste row.

    Prefers the 'name' field; falls back to '<colour> piste' based on
    difficulty (e.g. 'red piste') when name is absent.
    """
    name = row.get("name")
    if name and str(name) not in ("nan", "None", ""):
        return str(name)
    diff = str(row.get("piste:difficulty", "")).lower()
    word = DIFFICULTY_WORDS.get(diff, diff)
    return f"{word} piste" if word else "piste"


def _build_data_script(db_path: Path) -> str:
    """Embed all run/user/piste data as a JS global for client-side filtering."""
    if not db_path.exists():
        return "<script>window.POWPAL_DATA={users:{},pistes:{},runs:[]};</script>"
    data = get_map_data(db_path)
    return f"<script>window.POWPAL_DATA={json.dumps(data)};</script>"


def _build_nouislider_deps() -> str:
    """Return noUiSlider CDN tags and custom slider styles."""
    return f"""
<link rel='stylesheet'
  href='https://cdn.jsdelivr.net/npm/nouislider@15.7.1/dist/nouislider.min.css'>
<script
  src='https://cdn.jsdelivr.net/npm/nouislider@15.7.1/dist/nouislider.min.js'></script>
<style>
  #pw-slider .noUi-base {{ background: {BORDER}; }}
  #pw-slider .noUi-connect {{ background: {ACCENT}; }}
  #pw-slider .noUi-handle {{
    cursor: ew-resize; box-shadow: none;
    background: {TEXT}; border: 2px solid {ACCENT};
  }}
  #pw-slider .noUi-handle:before,
  #pw-slider .noUi-handle:after {{ background: {TEXT_DIM}; }}
  #pw-slider .noUi-pips-horizontal {{ padding: 8px 0 0; }}
  #pw-slider .noUi-value {{ font-size: 10px; color: {TEXT_DIM}; white-space: nowrap; }}
  #pw-slider .noUi-marker {{ background: {BORDER}; }}
  #pw-slider .noUi-marker-horizontal.noUi-marker {{ height: 5px; }}
  #pw-slider .noUi-marker-horizontal.noUi-marker-large {{ height: 8px; }}
  .pw-day-tick {{
    position: absolute; top: 50%; transform: translate(-50%, -50%);
    width: 2px; height: 10px; background: {TICKS}; opacity: 1;
    pointer-events: none; border-radius: 5px; z-index: 0;
  }}
  /* Zoom control dark theme */
  .leaflet-control-zoom {{
    border: 1px solid {BORDER} !important;
    box-shadow: 0 4px 16px rgba(0,0,0,0.5) !important;
    border-radius: 8px !important;
    overflow: hidden;
  }}
  .leaflet-control-zoom a {{
    background-color: {BG} !important;
    color: {TEXT} !important;
    border-bottom: 1px solid {BORDER} !important;
    font-size: 16px !important;
    line-height: 26px !important;
  }}
  .leaflet-control-zoom a:last-child {{ border-bottom: none !important; }}
  .leaflet-control-zoom a:hover {{ background-color: {BG2} !important; }}

  /* ---- Font sizes — single source of truth ---- */
  /* Desktop */
  #pw-title {{ font-size: 18px; }}
  #pw-panel {{ font-size: 12px; }}
  #pw-tab-days, #pw-tab-pistes, #pw-tab-medals {{ font-size: 12px; }}
  /* Mobile tab bar */
  #pw-mobile-tabbar {{
    display: none;
    position: fixed; bottom: 0; left: 0; right: 0; height: 70px;
    background: {BG}; border-top: 1px solid {BORDER};
    z-index: 2000; align-items: stretch;
  }}
  #pw-mobile-tabbar button {{
    flex: 1; border: none; background: transparent;
    color: {TEXT_DIM}; font-size: 12px; cursor: pointer;
    display: flex; flex-direction: column;
    align-items: center; justify-content: center; gap: 2px;
    padding: 6px 0; -webkit-tap-highlight-color: transparent;
  }}
  #pw-mobile-tabbar button.pw-mtab-active {{ color: {ACCENT}; }}
  /* Mobile sheet and its contents */
  #pw-mobile-sheet {{ font-size: 14px; }}
  #pw-mobile-lb > div:first-child,
  #pw-mobile-filter > div:first-child {{ font-size: 18px; }}
  #pw-mlb-days, #pw-mlb-pistes, #pw-mlb-medals {{ font-size: 14px; }}
  #pw-mobile-filter-label {{ font-size: 12px; }}

  /* ---- Mobile bottom sheet ---- */
  #pw-mobile-sheet {{
    display: none;
    position: fixed; left: 0; right: 0; bottom: 70px;
    max-height: 65vh; overflow-y: auto;
    background: {BG}; border-radius: 16px 16px 0 0;
    border-top: 1px solid {BORDER};
    box-shadow: 0 -4px 20px rgba(0,0,0,0.5);
    z-index: 1999; color: {TEXT}; font-family: sans-serif;
    transform: translateY(100%);
    transition: transform 0.3s cubic-bezier(0.32,0.72,0,1);
  }}
  #pw-mobile-sheet.pw-open {{ transform: translateY(0); }}

  /* Mobile slider — same theme as desktop */
  #pw-mobile-slider .noUi-base {{ background: {BORDER}; }}
  #pw-mobile-slider .noUi-connect {{ background: {ACCENT}; }}
  #pw-mobile-slider .noUi-handle {{
    cursor: ew-resize; box-shadow: none;
    background: {TEXT}; border: 2px solid {ACCENT};
  }}
  #pw-mobile-slider .noUi-handle:before,
  #pw-mobile-slider .noUi-handle:after {{ background: {TEXT_DIM}; }}
  #pw-mobile-slider .noUi-pips-horizontal {{ padding: 8px 0 0; }}
  #pw-mobile-slider .noUi-value {{ font-size: 10px; color: {TEXT_DIM}; white-space: nowrap; }}
  #pw-mobile-slider .noUi-marker {{ background: {BORDER}; }}

  /* ---- Mobile breakpoint ---- */
  @media (max-width: 640px) {{
    /* Hide desktop-only overlays */
    #pw-panel, #pw-date-panel {{ display: none !important; }}
    /* Title becomes a full-width top banner */
    #pw-title {{
      left: 0 !important; right: 0 !important; top: 0 !important;
      transform: none !important; border-radius: 0 !important;
      padding: 10px 16px !important;
      text-align: center; white-space: nowrap;
      overflow: hidden; text-overflow: ellipsis;
      font-size: 20px;
    }}
    /* Centre button sits just above the tab bar */
    #pw-centre {{ bottom: 180px !important; right: 10px !important; }}
    /* Font size overrides for mobile — no !important needed, no inline styles to fight */
    #pw-mobile-tabbar button {{ font-size: 24px; }}
    #pw-mobile-sheet {{ font-size: 24px; }}
    #pw-mobile-lb > div:first-child,
    #pw-mobile-filter > div:first-child {{ font-size: 17px; }}
    #pw-mlb-days, #pw-mlb-pistes, #pw-mlb-medals {{ font-size: 15px; padding: 12px 0; }}
    #pw-mobile-lb table {{ font-size: 15px; }}
    #pw-mobile-lb td, #pw-mobile-lb th {{ padding: 6px; }}
    #pw-mobile-filter-label {{ font-size: 14px; padding: 4px 14px; }}
    #pw-mobile-slider .noUi-value {{ font-size: 12px; }}
    #pw-mobile-slider .noUi-handle {{ width: 28px; height: 28px; top: -12px; }}
    /* Push Leaflet zoom above the tab bar */
    .leaflet-bottom.leaflet-right {{ bottom: 80px !important; }}
    /* Show mobile elements */
    #pw-mobile-tabbar {{ display: flex !important; }}
    #pw-mobile-sheet {{ display: block !important; }}
  }}
</style>
"""


def _build_slider_panel() -> str:
    """Return HTML for the date range slider bar at the bottom of the map."""
    return f"""
<div id="pw-date-panel" style="
    position:fixed; bottom:20px; left:50%; transform:translateX(-50%);
    background:{BG}; border-radius:8px;
    box-shadow:0 4px 16px rgba(0,0,0,0.5);
    padding:12px 24px 8px; z-index:1000; font-family:sans-serif;
    min-width:480px; max-width:700px; width:45vw;
    color:{TEXT};
">
  <div style="display:flex;justify-content:space-between;
              align-items:center;margin-bottom:16px">
    <span style="font-weight:bold;font-size:13px">&#128197; Date range</span>
    <span id="pw-date-label"
      style="font-size:12px;color:{TEXT};font-weight:bold;
             background:{BG2};padding:2px 10px;border-radius:4px"></span>
    <button id="pw-reset-btn" onclick="pwResetDates()"
      style="border:1px solid {BORDER};border-radius:4px;padding:2px 8px;
             font-size:11px;cursor:pointer;background:{BG2};color:{TEXT_DIM}">
      Reset
    </button>
  </div>
  <!-- extra bottom padding leaves room for pip labels below the track -->
  <div id="pw-slider" style="margin:0 8px 32px"></div>
</div>
"""


def _build_mobile_sheet() -> str:
    """Return the mobile tab bar and bottom sheet HTML."""
    lb_btn = (
        f"flex:1;padding:8px 0;border:none;border-radius:4px;"
        f"cursor:pointer;font-weight:bold;"
    )
    lb_active = lb_btn + f"background:{ACCENT};color:white;"
    lb_inactive = lb_btn + f"background:{BG2};color:{TEXT_DIM};"
    loading = f"<i style='color:{TEXT_DIM}'>Loading...</i>"

    return f"""
<div id="pw-mobile-tabbar">
  <button id="pw-mtab-lb" onclick="pwMobileShow('lb')">
    <span style="font-size:22px">&#127942;</span><span>Stats</span>
  </button>
  <button id="pw-mtab-map" onclick="pwMobileClose()" class="pw-mtab-active">
    <span style="font-size:22px">&#127956;&#65039;</span><span>Map</span>
  </button>
  <button id="pw-mtab-filter" onclick="pwMobileShow('filter')">
    <span style="font-size:22px">&#128197;</span><span>Filter</span>
  </button>
</div>

<div id="pw-mobile-sheet">
  <div onclick="pwMobileClose()"
    style="text-align:center;padding:10px 0 6px;cursor:pointer;flex-shrink:0">
    <div style="display:inline-block;width:36px;height:4px;
                background:{BORDER};border-radius:2px"></div>
  </div>

  <div id="pw-mobile-lb" style="padding:0 14px 20px;display:none">
    <div style="font-weight:bold;margin-bottom:8px;
                border-bottom:1px solid {BORDER};padding-bottom:6px">
      &#127942; Leaderboard
    </div>
    <div style="display:flex;gap:4px;margin-bottom:10px">
      <button id="pw-mlb-days" onclick="pwMobileShowTab('days')"
        style="{lb_active}">&#128197; Days</button>
      <button id="pw-mlb-pistes" onclick="pwMobileShowTab('pistes')"
        style="{lb_inactive}">&#127956;&#65039; Runs</button>
      <button id="pw-mlb-medals" onclick="pwMobileShowTab('medals')"
        style="{lb_inactive}">&#129351; Medals</button>
    </div>
    <div id="pw-body-days-m">{loading}</div>
    <div id="pw-body-pistes-m" style="display:none">{loading}</div>
    <div id="pw-body-medals-m" style="display:none">{loading}</div>
  </div>

  <div id="pw-mobile-filter" style="padding:0 14px 20px;display:none">
    <div style="font-weight:bold;margin-bottom:8px;
                border-bottom:1px solid {BORDER};padding-bottom:6px">
      &#128197; Date filter
    </div>
    <div style="display:flex;justify-content:space-between;
                align-items:center;margin-bottom:14px">
      <span id="pw-mobile-filter-label"
        style="font-weight:bold;
               background:{BG2};padding:2px 10px;border-radius:4px;color:{TEXT}"></span>
      <button onclick="pwResetDates()"
        style="border:1px solid {BORDER};border-radius:4px;padding:2px 8px;
               cursor:pointer;background:{BG2};color:{TEXT_DIM}">
        Reset
      </button>
    </div>
    <!-- extra bottom margin for pip labels -->
    <div id="pw-mobile-slider" style="margin:0 8px 36px"></div>
  </div>
</div>
"""


def _build_js_engine(map_id: str) -> str:
    """Return the JS engine that powers date filtering across popups and the panel.

    Uses DOMContentLoaded so it runs after Folium's map-init script, which
    Folium places after </body> and therefore executes before DOMContentLoaded.
    """
    lb_btn = (
        "flex:1;padding:8px 0;border:none;border-radius:4px;"
        "cursor:pointer;font-weight:bold;"
    )
    mlb_active = lb_btn + f"background:{ACCENT};color:white;"
    mlb_inactive = lb_btn + f"background:{BG2};color:{TEXT_DIM};"
    return f"""
<script>
document.addEventListener('DOMContentLoaded', function() {{
  var MAP = map_{map_id};
  L.control.zoom({{ position: 'bottomright' }}).addTo(MAP);
  var DATA = window.POWPAL_DATA;
  var pwLayers = {{}};
  var pwMinDate = '', pwMaxDate = '';

  // Build a registry of piste_db_id -> Leaflet layer from Folium's GeoJSON layers
  MAP.eachLayer(function(layer) {{
    if (layer.feature && layer.feature.properties) {{
      var pid = layer.feature.properties.piste_db_id;
      if (pid != null) {{
        pwLayers[pid] = layer;
        layer.bindPopup('', {{maxWidth: 280}});
      }}
    }}
  }});

  function fmtTime(s) {{
    var m = Math.floor(s / 60);
    var sec = Math.floor(s % 60);
    return m + ':' + (sec < 10 ? '0' : '') + sec;
  }}

  // --- Main filter entry point ---
  function pwFilter(from, to) {{
    var runs = DATA.runs.filter(function(r) {{
      return r.run_date >= from && r.run_date <= to;
    }});
    pwUpdatePopups(runs);
    pwUpdatePanel(runs);
  }}

  // --- Piste popup update ---
  function pwUpdatePopups(runs) {{
    // best[piste_id][user_id] = min duration
    var best = {{}};
    runs.forEach(function(r) {{
      if (!best[r.piste_id]) best[r.piste_id] = {{}};
      var cur = best[r.piste_id][r.user_id];
      if (cur === undefined || r.duration_seconds < cur)
        best[r.piste_id][r.user_id] = r.duration_seconds;
    }});

    Object.keys(pwLayers).forEach(function(pid) {{
      var layer = pwLayers[pid];
      var piste = DATA.pistes[pid];
      var label = (piste && piste.name) ? piste.name : 'Piste';
      var html = '<b>' + label + '</b><br>';

      if (best[pid]) {{
        var sorted = Object.keys(best[pid])
          .map(function(uid) {{ return {{uid: uid, t: best[pid][uid]}}; }})
          .sort(function(a, b) {{ return a.t - b.t; }})
          .slice(0, 5);
        html += '<table style="width:100%;font-size:12px;border-collapse:collapse">'
          + '<tr><th style="text-align:left">#</th>'
          + '<th style="text-align:left">Rider</th>'
          + '<th style="text-align:right">Best</th></tr>';
        sorted.forEach(function(e, i) {{
          var u = DATA.users[e.uid];
          html += '<tr>'
            + '<td style="color:#999;padding:2px 4px">' + (i + 1) + '</td>'
            + '<td style="color:' + u.colour + ';padding:2px 4px"><b>'
            + u.display_name + '</b></td>'
            + '<td style="text-align:right;padding:2px 4px">'
            + fmtTime(e.t) + '</td></tr>';
        }});
        html += '</table>';
      }} else {{
        html += '<i style="color:#aaa;font-size:12px">No runs in this period</i>';
      }}
      layer.setPopupContent(html);
    }});
  }}

  // Updates both the desktop panel element and its mobile counterpart
  function _setBodyHtml(key, html) {{
    var d = document.getElementById('pw-body-' + key);
    var m = document.getElementById('pw-body-' + key + '-m');
    if (d) d.innerHTML = html;
    if (m) m.innerHTML = html;
  }}

  // --- Leaderboard panel update ---
  function pwUpdatePanel(runs) {{
    pwUpdateDays(runs);
    pwUpdatePistes(runs);
    pwUpdateMedals(runs);
  }}

  function pwUpdateDays(runs) {{
    var daysets = {{}};
    runs.forEach(function(r) {{
      if (!daysets[r.user_id]) daysets[r.user_id] = {{}};
      daysets[r.user_id][r.run_date] = 1;
    }});
    var rows = Object.keys(DATA.users).map(function(uid) {{
      return {{uid: uid, value: daysets[uid] ? Object.keys(daysets[uid]).length : 0}};
    }}).sort(function(a, b) {{ return b.value - a.value; }});
    _setBodyHtml('days', _statTableHtml(rows, 'Days'));
  }}

  function pwUpdatePistes(runs) {{
    var counts = {{}};
    runs.forEach(function(r) {{
      counts[r.user_id] = (counts[r.user_id] || 0) + 1;
    }});
    var rows = Object.keys(DATA.users).map(function(uid) {{
      return {{uid: uid, value: counts[uid] || 0}};
    }}).sort(function(a, b) {{ return b.value - a.value; }});
    _setBodyHtml('pistes', _statTableHtml(rows, 'Runs'));
  }}

  function pwUpdateMedals(runs) {{
    var best = {{}};
    runs.forEach(function(r) {{
      if (!best[r.piste_id]) best[r.piste_id] = {{}};
      var cur = best[r.piste_id][r.user_id];
      if (cur === undefined || r.duration_seconds < cur)
        best[r.piste_id][r.user_id] = r.duration_seconds;
    }});

    var medals = {{}};
    Object.keys(DATA.users).forEach(function(uid) {{
      medals[uid] = {{gold: 0, silver: 0, bronze: 0}};
    }});
    Object.keys(best).forEach(function(pid) {{
      var sorted = Object.keys(best[pid])
        .map(function(uid) {{ return {{uid: uid, t: best[pid][uid]}}; }})
        .sort(function(a, b) {{ return a.t - b.t; }});
      if (sorted[0]) medals[sorted[0].uid].gold++;
      if (sorted[1]) medals[sorted[1].uid].silver++;
      if (sorted[2]) medals[sorted[2].uid].bronze++;
    }});

    var rows = Object.keys(DATA.users).map(function(uid) {{
      return {{uid: uid, gold: medals[uid].gold,
               silver: medals[uid].silver, bronze: medals[uid].bronze}};
    }}).sort(function(a, b) {{
      return b.gold - a.gold || b.silver - a.silver || b.bronze - a.bronze;
    }});
    _setBodyHtml('medals', _medalsTableHtml(rows));
  }}

  // --- HTML renderers ---
  function _statTableHtml(rows, valueLabel) {{
    if (!rows.some(function(r) {{ return r.value > 0; }}))
      return "<i style='color:{TEXT_DIM}'>No data in this period</i>";
    var h = "<table style='width:100%;border-collapse:collapse;color:{TEXT}'>"
      + "<tr style='border-bottom:1px solid {BORDER}'>"
      + "<th style='text-align:left;padding:2px 4px'>#</th>"
      + "<th style='text-align:left;padding:2px 4px'>Rider</th>"
      + "<th style='text-align:right;padding:2px 4px'>" + valueLabel + "</th></tr>";
    var rank = 1;
    rows.forEach(function(r) {{
      if (r.value === 0) return;
      var u = DATA.users[r.uid];
      h += "<tr><td style='padding:3px 4px;color:{TEXT_DIM}'>" + rank + "</td>"
        + "<td style='padding:3px 4px;color:" + u.colour + "'><b>"
        + u.display_name + "</b></td>"
        + "<td style='padding:3px 4px;text-align:right;color:{TEXT}'>" + r.value + "</td></tr>";
      rank++;
    }});
    return h + "</table>";
  }}

  function _medalsTableHtml(rows) {{
    if (!rows.some(function(r) {{ return r.gold + r.silver + r.bronze > 0; }}))
      return "<i style='color:{TEXT_DIM}'>No data in this period</i>";
    var h = "<table style='width:100%;border-collapse:collapse;color:{TEXT}'>"
      + "<tr style='border-bottom:1px solid {BORDER}'>"
      + "<th style='text-align:left;padding:2px 4px'>#</th>"
      + "<th style='text-align:left;padding:2px 4px'>Rider</th>"
      + "<th style='text-align:center;padding:2px 4px'>&#129351;</th>"
      + "<th style='text-align:center;padding:2px 4px'>&#129352;</th>"
      + "<th style='text-align:center;padding:2px 4px'>&#129353;</th></tr>";
    var rank = 1;
    rows.forEach(function(r) {{
      if (r.gold + r.silver + r.bronze === 0) return;
      var u = DATA.users[r.uid];
      h += "<tr><td style='padding:3px 4px;color:{TEXT_DIM}'>" + rank + "</td>"
        + "<td style='padding:3px 4px;color:" + u.colour + "'><b>"
        + u.display_name + "</b></td>"
        + "<td style='padding:3px 4px;text-align:center;color:{TEXT}'>" + (r.gold || '-') + "</td>"
        + "<td style='padding:3px 4px;text-align:center;color:{TEXT}'>" + (r.silver || '-') + "</td>"
        + "<td style='padding:3px 4px;text-align:center;color:{TEXT}'>" + (r.bronze || '-') + "</td>"
        + "</tr>";
      rank++;
    }});
    return h + "</table>";
  }}

  // --- noUiSlider setup (calendar-proportional) ---
  var pwDates = [];
  var pwDayOffsets = [];  // calendar day offset from first date for each ski day
  var pwTotalDays = 1;
  var pwSlider = null;

  function dateToDayOffset(iso) {{
    return Math.round((new Date(iso) - new Date(pwDates[0])) / 86400000);
  }}

  function dayOffsetToIso(offset) {{
    var ms = new Date(pwDates[0]).getTime() + Math.round(offset) * 86400000;
    return new Date(ms).toISOString().slice(0, 10);
  }}

  function fmtDateLabel(iso) {{
    var parts = iso.split('-');
    var months = ['Jan','Feb','Mar','Apr','May','Jun',
                  'Jul','Aug','Sep','Oct','Nov','Dec'];
    return parts[2] + ' ' + months[parseInt(parts[1], 10) - 1];
  }}

  function pwUpdateLabel(from, to) {{
    var label = from === to
      ? fmtDateLabel(from)
      : fmtDateLabel(from) + ' \u2013 ' + fmtDateLabel(to);
    var d = document.getElementById('pw-date-label');
    var m = document.getElementById('pw-mobile-filter-label');
    if (d) d.textContent = label;
    if (m) m.textContent = label;
  }}

  window.pwFilter = pwFilter;
  window.pwResetDates = function() {{
    if (pwSlider) pwSlider.set([0, pwTotalDays]);
    // mobile slider syncs automatically via the flag below
  }};

  if (DATA.runs.length > 0) {{
    // Collect sorted unique dates and compute calendar offsets
    var seen = {{}};
    DATA.runs.forEach(function(r) {{ seen[r.run_date] = 1; }});
    pwDates = Object.keys(seen).sort();
    pwMinDate = pwDates[0];
    pwMaxDate = pwDates[pwDates.length - 1];
    pwTotalDays = Math.max(dateToDayOffset(pwMaxDate), 1);
    pwDayOffsets = pwDates.map(dateToDayOffset);

    // Label selection: greedily pick dates with at least 13% of total span
    var minGap = Math.max(1, Math.ceil(pwTotalDays * 0.13));
    var labelOffsets = [0];
    var lastLbl = 0;
    for (var i = 1; i < pwDayOffsets.length - 1; i++) {{
      if (pwDayOffsets[i] - lastLbl >= minGap) {{
        labelOffsets.push(pwDayOffsets[i]);
        lastLbl = pwDayOffsets[i];
      }}
    }}
    if (pwTotalDays - lastLbl >= minGap) labelOffsets.push(pwTotalDays);

    function _injectTicks(sliderEl) {{
      var base = sliderEl.querySelector('.noUi-base');
      pwDayOffsets.forEach(function(offset) {{
        var tick = document.createElement('div');
        tick.className = 'pw-day-tick';
        tick.style.left = (offset / pwTotalDays * 100) + '%';
        base.appendChild(tick);
      }});
    }}

    // Init desktop slider
    pwSlider = noUiSlider.create(document.getElementById('pw-slider'), {{
      start: [0, pwTotalDays],
      step: 1,
      range: {{ min: 0, max: pwTotalDays }},
      connect: true,
      tooltips: false,
      pips: {{
        mode: 'values',
        values: labelOffsets,
        density: 100,
        format: {{
          to: function(v) {{ return fmtDateLabel(dayOffsetToIso(Math.round(v))); }},
          from: Number,
        }},
      }},
    }});
    _injectTicks(document.getElementById('pw-slider'));

    // Init mobile slider with an independently constructed config (JSON clone drops functions)
    var mobileSliderEl = document.getElementById('pw-mobile-slider');
    var pwMobileSlider = noUiSlider.create(mobileSliderEl, {{
      start: [0, pwTotalDays],
      step: 1,
      range: {{ min: 0, max: pwTotalDays }},
      connect: true,
      tooltips: false,
      pips: {{
        mode: 'values',
        values: labelOffsets,
        density: 100,
        format: {{
          to: function(v) {{ return fmtDateLabel(dayOffsetToIso(Math.round(v))); }},
          from: Number,
        }},
      }},
    }});
    _injectTicks(mobileSliderEl);

    // Sync sliders without infinite loops
    var _syncing = false;
    pwSlider.on('update', function(values) {{
      var from = dayOffsetToIso(values[0]);
      var to   = dayOffsetToIso(values[1]);
      pwUpdateLabel(from, to);
      pwFilter(from, to);
      if (!_syncing) {{ _syncing = true; pwMobileSlider.set(values); _syncing = false; }}
    }});
    pwMobileSlider.on('update', function(values) {{
      var from = dayOffsetToIso(values[0]);
      var to   = dayOffsetToIso(values[1]);
      pwUpdateLabel(from, to);
      pwFilter(from, to);
      if (!_syncing) {{ _syncing = true; pwSlider.set(values); _syncing = false; }}
    }});

    // Initial render — full season range
    pwUpdateLabel(pwMinDate, pwMaxDate);
    pwFilter(pwMinDate, pwMaxDate);
  }}

  // --- Mobile sheet ---
  var _mlbTabs = ['days', 'pistes', 'medals'];
  var _mlbActive = '{mlb_active}';
  var _mlbInactive = '{mlb_inactive}';

  window.pwMobileShow = function(section) {{
    document.getElementById('pw-mobile-sheet').classList.add('pw-open');
    ['lb', 'filter'].forEach(function(s) {{
      document.getElementById('pw-mobile-' + s).style.display =
        (s === section) ? '' : 'none';
    }});
    ['lb', 'map', 'filter'].forEach(function(t) {{
      var btn = document.getElementById('pw-mtab-' + t);
      btn.classList.toggle('pw-mtab-active', t === section);
    }});
  }};

  window.pwMobileClose = function() {{
    document.getElementById('pw-mobile-sheet').classList.remove('pw-open');
    ['lb', 'filter'].forEach(function(t) {{
      document.getElementById('pw-mtab-' + t).classList.remove('pw-mtab-active');
    }});
    document.getElementById('pw-mtab-map').classList.add('pw-mtab-active');
  }};

  window.pwMobileShowTab = function(name) {{
    _mlbTabs.forEach(function(t) {{
      document.getElementById('pw-body-' + t + '-m').style.display =
        (t === name) ? '' : 'none';
      document.getElementById('pw-mlb-' + t).style.cssText =
        (t === name) ? _mlbActive : _mlbInactive;
    }});
  }};
}});
</script>
"""


def _build_meta_panel() -> str:
    """Return HTML for the leaderboard panel (content filled by JS on load)."""
    tab_style = (
        f"padding:5px 10px;border:none;border-radius:4px;"
        f"cursor:pointer;font-weight:bold;"
    )
    active_style = tab_style + f"background:{ACCENT};color:white;"
    inactive_style = tab_style + f"background:{BG2};color:{TEXT_DIM};"
    loading = f"<i style='color:{TEXT_DIM}'>Loading...</i>"

    return f"""
<div id="pw-panel" style="
    position:fixed; top:20px; left:12px;
    width:220px; max-height:60vh; overflow-y:auto;
    background:{BG}; border-radius:8px;
    box-shadow:0 4px 16px rgba(0,0,0,0.5);
    padding:12px; z-index:1000; font-family:sans-serif;
    color:{TEXT};
">
  <div style="font-weight:bold;font-size:14px;margin-bottom:8px;
              border-bottom:1px solid {BORDER};padding-bottom:6px">
    &#127942; Leaderboard
  </div>
  <div style="display:flex;gap:4px;margin-bottom:10px">
    <button id="pw-tab-days" onclick="pwShowTab('days')"
      style="{active_style}">&#128197; Days</button>
    <button id="pw-tab-pistes" onclick="pwShowTab('pistes')"
      style="{inactive_style}">&#127956;&#65039; Runs</button>
    <button id="pw-tab-medals" onclick="pwShowTab('medals')"
      style="{inactive_style}">&#129351; Medals</button>
  </div>
  <div id="pw-body-days">{loading}</div>
  <div id="pw-body-pistes" style="display:none">{loading}</div>
  <div id="pw-body-medals" style="display:none">{loading}</div>
</div>
<script>
  var _pwTabs = ['days','pistes','medals'];
  var _pwActive = '{active_style}';
  var _pwInactive = '{inactive_style}';
  function pwShowTab(name) {{
    _pwTabs.forEach(function(t) {{
      document.getElementById('pw-body-'+t).style.display = (t===name)?'':'none';
      document.getElementById('pw-tab-'+t).style.cssText = (t===name)?_pwActive:_pwInactive;
    }});
  }}
</script>
"""


def build_map(db_path: Path, piste_path: Path) -> folium.Map:
    """Build and return the Folium leaderboard map."""
    pistes = gpd.read_file(piste_path).to_crs("EPSG:4326")

    map_extent = pistes.total_bounds  # [minx, miny, maxx, maxy]
    map_centre = [
        (map_extent[1] + map_extent[3]) / 2,
        (map_extent[0] + map_extent[2]) / 2,
    ]

    m = folium.Map(
        location=map_centre,
        zoom_start=MAP_ZOOM,
        tiles="CartoDB Positron",
        zoom_control=False,
    )

    # Map from OSM id → DB piste id so we can embed piste_db_id in each feature
    osm_to_db: dict[str, int] = {}
    if db_path.exists():
        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
        for r in con.execute("SELECT id, osm_id FROM pistes").fetchall():
            osm_to_db[r["osm_id"]] = r["id"]
        con.close()

    for _, row in pistes.iterrows():
        difficulty = str(row.get("piste:difficulty", "")).lower()
        colour = DIFFICULTY_COLOURS.get(difficulty, "#888888")
        label = piste_label(row)
        osm_id = str(row.get("id", ""))
        db_piste_id = osm_to_db.get(osm_id)

        # Wrap as a GeoJSON Feature so JS can read piste_db_id from layer.feature.properties
        feature = {
            "type": "Feature",
            "geometry": row.geometry.__geo_interface__,
            "properties": {"piste_db_id": db_piste_id, "label": label},
        }

        gj = folium.GeoJson(
            feature,
            style_function=lambda _, c=colour: {
                "color": c,
                "weight": 3,
                "opacity": 0.85,
            },
            tooltip=label,
        )
        # Pistes not yet in the DB get a static popup; DB pistes are handled by JS
        if db_piste_id is None:
            gj.add_child(
                folium.Popup(f"<b>{label}</b><br><i>No runs yet</i>", max_width=280)
            )
        gj.add_to(m)

    title_html = f"""
    <div id="pw-title" style="
        position: fixed;
        top: 16px; left: 50%; transform: translateX(-50%);
        background: {BG};
        color: {TEXT};
        padding: 8px 20px;
        border-radius: 8px;
        box-shadow: 0 4px 16px rgba(0,0,0,0.5);
        font-family: sans-serif;
        font-weight: bold;
        z-index: 1000;
        pointer-events: none;
    ">
        ⛷️ Vichères-Liddes | Quack Quack Season 2025/26 🦆
    </div>
    """

    centre_html = f"""
    <div id="pw-centre" style="position: fixed; bottom: 120px; right: 12px; z-index: 1000;">
        <button onclick="map_{m._id}.setView([{map_centre[0]}, {map_centre[1]}], {MAP_ZOOM});"
            style="
                background: {BG};
                color: {TEXT};
                border: 1px solid {BORDER};
                border-radius: 6px;
                width: 36px; height: 36px;
                padding: 0;
                cursor: pointer;
                font-size: 18px;
                line-height: 36px;
                text-align: center;
                box-shadow: 0 4px 16px rgba(0,0,0,0.5);
            ">
            &#127919;
        </button>
    </div>
    """  # noqa: SLF001

    m.get_root().header.add_child(folium.Element(_build_nouislider_deps()))
    m.get_root().html.add_child(folium.Element(_build_data_script(db_path)))
    m.get_root().html.add_child(folium.Element(title_html))
    m.get_root().html.add_child(folium.Element(centre_html))
    m.get_root().html.add_child(folium.Element(_build_meta_panel()))
    m.get_root().html.add_child(folium.Element(_build_slider_panel()))
    m.get_root().html.add_child(folium.Element(_build_mobile_sheet()))
    m.get_root().html.add_child(folium.Element(_build_js_engine(m._id)))  # noqa: SLF001

    return m


def main() -> None:
    """Render the powpal leaderboard map."""
    parser = argparse.ArgumentParser(
        description="Render the powpal leaderboard map."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output HTML path (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args()

    print("Building map...")
    m = build_map(DB_PATH, PISTE_GEOJSON)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(args.output))
    print(f"Saved to {args.output}")


if __name__ == "__main__":
    main()
