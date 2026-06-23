"use strict";

// --------------------------------------------------------------------------
// Helpers
// --------------------------------------------------------------------------
// The backend is reached through PyWebView's js_api bridge when available
// (desktop mode); otherwise through fetch against the fallback server (web mode).
function _useBridge() { return !!(window.pywebview && window.pywebview.api); }

const _whenReady = new Promise((resolve) => {
  if (_useBridge()) return resolve();
  let done = false;
  const finish = () => { if (!done) { done = true; resolve(); } };
  window.addEventListener("pywebviewready", finish, { once: true });
  setTimeout(finish, 1000); // safeguard for web mode
});

async function api(path, body) {
  const name = path.replace("/api/", "").replaceAll("/", "_");
  await _whenReady;
  if (_useBridge()) {
    return window.pywebview.api[name](body || {});
  }
  const r = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return r.json();
}

function h(tag, props, ...children) {
  const e = document.createElement(tag);
  if (props) for (const [k, v] of Object.entries(props)) {
    if (k === "class") e.className = v;
    else if (k === "html") e.innerHTML = v;
    else if (k.startsWith("on") && typeof v === "function") e.addEventListener(k.slice(2), v);
    else if (v === true) e.setAttribute(k, "");
    else if (v !== false && v != null) e.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    e.append(c.nodeType ? c : document.createTextNode(c));
  }
  return e;
}

const $ = (sel) => document.querySelector(sel);
function setStatus(t) { $("#status").textContent = t; }

// The game's own trade-good symbol for good `g` (or null for the weapons,
// which have no icon). `goodLabel` pairs it with the name for use as children.
function goodIcon(g) {
  const src = META && META.goods.icons && META.goods.icons[g];
  return src ? h("img", { class: "good-icon", src, alt: "", loading: "lazy" }) : null;
}
function goodLabel(g) { return [goodIcon(g), META.goods.names[g]]; }

const RULE_MODES = ["None", "Buy", "Sell", "Withdraw", "Deposit"];
const STOP_MODES = ["Dock", "Repair", "Skip"];

let META = null;
const state = {
  folder: "",
  routeNames: [],
  routeName: null,     // currently open route
  route: null,         // {name, stops:[...]}
  selectedStop: -1,
  showWeapons: false,
  pricings: [],
  sortings: [],
};

// --------------------------------------------------------------------------
// Dialogs
// --------------------------------------------------------------------------
function modal(node) {
  const backdrop = h("div", { class: "backdrop" }, node);
  backdrop.addEventListener("mousedown", (ev) => { if (ev.target === backdrop) close(); });
  function close() { backdrop.remove(); }
  $("#modal-root").append(backdrop);
  return close;
}

function promptDialog(title, initial = "") {
  return new Promise((resolve) => {
    const input = h("input", { type: "text", value: initial, style: "width:100%" });
    const node = h("div", { class: "modal" },
      h("h2", null, title),
      input,
      h("div", { class: "modal-actions" },
        h("button", { onclick: () => { close(); resolve(null); } }, "Cancel"),
        h("button", { class: "primary", onclick: ok }, "OK")));
    function ok() { close(); resolve(input.value.trim() || null); }
    const close = modal(node);
    input.focus(); input.select();
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") ok(); });
  });
}

function confirmDialog(message) {
  return new Promise((resolve) => {
    const node = h("div", { class: "modal" },
      h("h2", null, "Confirm"),
      h("p", null, message),
      h("div", { class: "modal-actions" },
        h("button", { onclick: () => { close(); resolve(false); } }, "Cancel"),
        h("button", { class: "primary danger", onclick: () => { close(); resolve(true); } }, "Yes")));
    const close = modal(node);
  });
}

// --------------------------------------------------------------------------
// Generic drag & drop (reordering lists)
// --------------------------------------------------------------------------
function moveItem(arr, from, to) {
  const [x] = arr.splice(from, 1);
  arr.splice(to, 0, x);
}

function makeDraggable(el, type, index, onDrop) {
  el.setAttribute("draggable", "true");
  el.addEventListener("dragstart", (e) => {
    e.dataTransfer.setData("text/plain", `${type}:${index}`);
    e.dataTransfer.effectAllowed = "move";
  });
  el.addEventListener("dragover", (e) => {
    e.preventDefault();
    el.classList.add("dragover");
  });
  el.addEventListener("dragleave", () => el.classList.remove("dragover"));
  el.addEventListener("drop", (e) => {
    e.preventDefault();
    el.classList.remove("dragover");
    const raw = e.dataTransfer.getData("text/plain");
    if (!raw.startsWith(type + ":")) return;
    const from = parseInt(raw.slice(type.length + 1), 10);
    if (from === index) return;
    onDrop(from, index);
  });
}

// --------------------------------------------------------------------------
// Tabs
// --------------------------------------------------------------------------
function setupTabs() {
  document.querySelectorAll("#tabs button").forEach((b) => {
    b.addEventListener("click", () => {
      document.querySelectorAll("#tabs button").forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
      for (const t of document.querySelectorAll("main .tab")) t.classList.add("hidden");
      $("#tab-" + b.dataset.tab).classList.remove("hidden");
      if (b.dataset.tab === "sortings") renderSortingsTab();
      if (b.dataset.tab === "pricings") renderPricingsTab();
    });
  });
}

// --------------------------------------------------------------------------
// Routes tab — folder and list
// --------------------------------------------------------------------------
async function openFolder() {
  const path = $("#folder-path").value.trim();
  if (!path) return;
  const res = await api("/api/folder/open", { path });
  if (!res.ok) { setStatus("Error: " + res.error); return; }
  state.folder = path;
  state.routeNames = res.names;
  $("#new-route").disabled = false;
  $("#close-folder").disabled = false;
  setStatus(`Folder opened — ${res.names.length} route(s)`);
  renderRouteList();
}

async function pickFolder() {
  const res = await api("/api/pick_folder");
  if (!res.ok) { setStatus(res.error || "Picker not available"); return; }
  $("#folder-path").value = res.path;
  state.folder = res.path;
  state.routeNames = res.names;
  $("#new-route").disabled = false;
  $("#close-folder").disabled = false;
  setStatus(`Folder opened — ${res.names.length} route(s)`);
  renderRouteList();
}

function closeFolder() {
  state.folder = ""; state.routeNames = [];
  state.routeName = null; state.route = null; state.selectedStop = -1;
  $("#new-route").disabled = true;
  $("#close-folder").disabled = true;
  renderRouteList();
  renderEditor();
  setStatus("Folder closed");
}

// Theme (light by default, switchable to dark, persisted).
function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  const btn = $("#theme-toggle");
  if (btn) btn.textContent = t === "dark" ? "☀️" : "🌙";
  try { localStorage.setItem("p3theme", t); } catch (e) { /* ignore */ }
}
function toggleTheme() {
  const cur = document.documentElement.dataset.theme === "dark" ? "dark" : "light";
  applyTheme(cur === "dark" ? "light" : "dark");
}
function initTheme() {
  let saved = "light";
  try { saved = localStorage.getItem("p3theme") || "light"; } catch (e) { /* ignore */ }
  applyTheme(saved === "dark" ? "dark" : "light");
}

// Weapons visibility (off by default, persisted). When off, the 4 weapon goods
// are hidden everywhere they are listed: the stop editor, pricings and sortings.
function applyShowWeapons(on) {
  state.showWeapons = on;
  const cb = $("#weapons-toggle");
  if (cb) cb.checked = on;
  try { localStorage.setItem("p3showweapons", on ? "1" : "0"); } catch (e) { /* ignore */ }
}
function initWeapons() {
  let on = false;
  try { on = localStorage.getItem("p3showweapons") === "1"; } catch (e) { /* ignore */ }
  applyShowWeapons(on);
}
function onToggleWeapons(e) {
  applyShowWeapons(e.target.checked);
  // Re-render whichever good-listing view is currently on screen.
  if (state.route && state.selectedStop >= 0) renderStopEditor();
  const active = document.querySelector("#tabs button.active");
  if (active && active.dataset.tab === "pricings") renderPricingsTab();
  else if (active && active.dataset.tab === "sortings") renderSortingsTab();
}

async function refreshFolder() {
  if (!state.folder) return;
  const res = await api("/api/folder/open", { path: state.folder });
  if (res.ok) state.routeNames = res.names;
  renderRouteList();
}

function renderRouteList() {
  const ul = $("#route-list");
  ul.replaceChildren();
  const q = $("#route-search").value.toLowerCase();
  let count = 0;
  for (const name of state.routeNames) {
    if (q && !name.toLowerCase().includes(q)) continue;
    count++;
    const li = h("li", { class: state.routeName === name ? "selected" : "" },
      h("span", { class: "rname", title: name, onclick: () => loadRoute(name) }, name),
      h("button", { class: "icon", title: "Rename", onclick: () => renameRoute(name) }, "✎"),
      h("button", { class: "icon", title: "Duplicate", onclick: () => duplicateRoute(name) }, "⧉"),
      h("button", { class: "icon danger", title: "Delete", onclick: () => deleteRoute(name) }, "🗑"));
    ul.append(li);
  }
  $("#routes-count").textContent = `${count} shown`;
}

async function loadRoute(name) {
  const res = await api("/api/route/load", { path: state.folder, name });
  if (!res.ok) { setStatus("Read error: " + res.error); return; }
  state.routeName = name;
  state.route = res.route;
  state.selectedStop = res.route.stops.length ? 0 : -1;
  setStatus(`Route "${name}" loaded (${res.route.stops.length} stops)`);
  renderRouteList();
  renderEditor();
}

async function newRoute() {
  const name = await promptDialog("Name of the new route", "My Auto Route");
  if (!name) return;
  const res = await api("/api/route/create", { path: state.folder, name });
  if (!res.ok) { setStatus("Error: " + res.error); return; }
  await refreshFolder();
  loadRoute(name);
}

async function renameRoute(name) {
  const nn = await promptDialog("Rename route", name);
  if (!nn || nn === name) return;
  const res = await api("/api/route/rename", { path: state.folder, old: name, new: nn });
  if (!res.ok) { setStatus("Error: " + res.error); return; }
  if (state.routeName === name) state.routeName = nn;
  await refreshFolder();
  if (state.routeName === nn) loadRoute(nn);
}

async function duplicateRoute(name) {
  const nn = await promptDialog("Duplicate route as…", "Copy of " + name);
  if (!nn) return;
  const res = await api("/api/route/duplicate", { path: state.folder, name, new: nn });
  if (!res.ok) { setStatus("Error: " + res.error); return; }
  await refreshFolder();
}

async function deleteRoute(name) {
  if (!(await confirmDialog(`Delete route "${name}"?`))) return;
  const res = await api("/api/route/delete", { path: state.folder, name });
  if (!res.ok) { setStatus("Error: " + res.error); return; }
  if (state.routeName === name) { state.routeName = null; state.route = null; }
  await refreshFolder();
  renderEditor();
}

// --------------------------------------------------------------------------
// Route editor — stops
// --------------------------------------------------------------------------
function defaultSorting() {
  return state.sortings.find((s) => s.is_default) || state.sortings[0];
}

function newStop(town = 0) {
  const order = defaultSorting() ? defaultSorting().goods : [...Array(META.goods.count).keys()];
  const rules = [];
  for (let g = 0; g < META.goods.count; g++) rules.push({ good: g, mode: 0, quantity: 0, price: 0 });
  rules.sort((a, b) => order.indexOf(a.good) - order.indexOf(b.good));
  return { town, mode: 0, rules };
}

function renderEditor() {
  const ed = $("#route-editor");
  const sm = $("#stops-manager");
  if (!state.route) { ed.classList.add("hidden"); sm.classList.add("hidden"); return; }
  ed.classList.remove("hidden");
  sm.classList.remove("hidden");
  $("#route-title").textContent = state.route.name;
  $("#stops-count").textContent = `(${state.route.stops.length}/${META.maxStops})`;
  renderStops();
  renderStopEditor();
}

function renderStops() {
  const strip = $("#stops-strip");
  strip.replaceChildren();
  state.route.stops.forEach((stop, i) => {
    const townSel = h("select", {
      onchange: (e) => { stop.town = parseInt(e.target.value, 10); },
    }, META.towns.names.map((n, idx) => h("option", { value: idx, selected: idx === stop.town }, n)));
    const modeSel = h("select", {
      class: "mode-" + STOP_MODES[stop.mode].toUpperCase(),
      onchange: (e) => { stop.mode = parseInt(e.target.value, 10); renderStops(); },
    }, STOP_MODES.map((n, idx) => h("option", { value: idx, selected: idx === stop.mode }, n)));

    const card = h("div", { class: "stop-card" + (i === state.selectedStop ? " selected" : "") },
      h("div", { class: "num" }, h("span", null, "#" + (i + 1)), h("span", { class: "grip", title: "Drag" }, "⠿")),
      townSel, modeSel,
      h("div", { class: "card-actions" },
        h("button", { title: "Edit", onclick: () => selectStop(i) }, "✎"),
        h("button", { title: "Duplicate", onclick: () => duplicateStop(i) }, "⧉"),
        h("button", { class: "danger", title: "Delete", onclick: () => deleteStop(i) }, "🗑")));
    card.addEventListener("click", (e) => { if (e.target === card) selectStop(i); });
    makeDraggable(card, "stop", i, (from, to) => {
      moveItem(state.route.stops, from, to);
      if (state.selectedStop === from) state.selectedStop = to;
      renderEditor();
    });
    strip.append(card);
  });
}

function selectStop(i) { state.selectedStop = i; renderStops(); renderStopEditor(); }

function duplicateStop(i) {
  if (state.route.stops.length >= META.maxStops) { setStatus("Maximum number of stops reached"); return; }
  const copy = JSON.parse(JSON.stringify(state.route.stops[i]));
  state.route.stops.splice(i + 1, 0, copy);
  renderEditor();
}

function deleteStop(i) {
  state.route.stops.splice(i, 1);
  if (state.selectedStop >= state.route.stops.length) state.selectedStop = state.route.stops.length - 1;
  renderEditor();
}

// Copy the previous stop's trade configuration (its stop mode and 24 rules)
// onto stop `i`, keeping this stop's own town. Deep-copied so the two stops
// stay independent afterwards.
function copyPrevStop(i) {
  if (i <= 0) return;
  const prev = state.route.stops[i - 1];
  const cur = state.route.stops[i];
  cur.mode = prev.mode;
  cur.rules = JSON.parse(JSON.stringify(prev.rules));
  renderEditor();
  setStatus(`Stop #${i + 1} copied the config of stop #${i}`);
}

function addStop() {
  if (state.route.stops.length >= META.maxStops) { setStatus("Maximum number of stops reached"); return; }
  state.route.stops.push(newStop(0));
  state.selectedStop = state.route.stops.length - 1;
  renderEditor();
}

// Visual feedback for the Save button: a spinner while writing, then a green
// "wax seal" stamp with a self-drawing checkmark on success, or a red shake on
// error. The button reverts to its idle "Save" label after a short beat.
let _saveResetTimer = null;
function resetSaveButton() {
  const btn = $("#save-route");
  if (!btn) return;
  btn.classList.remove("is-saving", "is-saved", "is-error");
  btn.textContent = "Save";
  _saveResetTimer = null;
}

async function saveRoute() {
  const btn = $("#save-route");
  if (btn.dataset.busy === "1") return; // ignore re-entrant clicks while saving
  btn.dataset.busy = "1";
  if (_saveResetTimer) { clearTimeout(_saveResetTimer); _saveResetTimer = null; }

  btn.classList.remove("is-saved", "is-error");
  btn.classList.add("is-saving");
  btn.innerHTML = '<span class="spinner" aria-hidden="true"></span>Saving…';

  let res;
  try {
    res = await api("/api/route/save", { path: state.folder, route: state.route });
  } catch (e) {
    res = { ok: false, error: String(e) };
  }

  btn.classList.remove("is-saving");
  btn.dataset.busy = "0";

  if (!res || !res.ok) {
    setStatus("Save error: " + (res ? res.error : "unknown"));
    btn.classList.add("is-error");
    btn.textContent = "✗ Error";
    _saveResetTimer = setTimeout(resetSaveButton, 2200);
    return;
  }

  setStatus(`Route "${state.route.name}" saved`);
  btn.classList.add("is-saved");
  btn.innerHTML = '<svg class="check" viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">' +
    '<path d="M4 12.5l5 5L20 6"/></svg>Saved';
  _saveResetTimer = setTimeout(resetSaveButton, 1800);
  refreshFolder();
}

// --------------------------------------------------------------------------
// Stop editor — rules
// --------------------------------------------------------------------------
function renderStopEditor() {
  const box = $("#stop-editor");
  if (state.selectedStop < 0 || !state.route.stops[state.selectedStop]) {
    box.classList.add("hidden"); box.replaceChildren(); return;
  }
  box.classList.remove("hidden");
  const stop = state.route.stops[state.selectedStop];

  const bulkMode = h("select", null,
    h("option", { value: "" }, "Set mode for all…"),
    RULE_MODES.map((n, idx) => h("option", { value: idx }, n)));
  bulkMode.addEventListener("change", () => {
    if (bulkMode.value === "") return;
    const m = parseInt(bulkMode.value, 10);
    stop.rules.forEach((r) => { r.mode = m; });
    bulkMode.value = ""; renderStopEditor();
  });

  const sortSel = h("select", null,
    h("option", { value: "" }, "Sort by…"),
    state.sortings.map((s) => h("option", { value: s.id }, s.id)));
  sortSel.addEventListener("change", () => {
    const s = state.sortings.find((x) => x.id === sortSel.value);
    if (s) { stop.rules.sort((a, b) => s.goods.indexOf(a.good) - s.goods.indexOf(b.good)); renderStopEditor(); }
    sortSel.value = "";
  });

  const priceSel = h("select", null,
    h("option", { value: "" }, "Apply pricing…"),
    state.pricings.map((p) => h("option", { value: p.id }, p.id)));
  priceSel.addEventListener("change", () => {
    const p = state.pricings.find((x) => x.id === priceSel.value);
    if (p) {
      stop.rules.forEach((r) => {
        if (r.mode === 1) r.price = p.buying[r.good];
        else if (r.mode === 2) r.price = p.selling[r.good];
      });
      renderStopEditor();
    }
    priceSel.value = "";
  });

  const toolbar = h("div", { class: "stop-toolbar" },
    h("strong", null, "Stop #" + (state.selectedStop + 1) + " — " + META.towns.names[stop.town]),
    h("div", { class: "group" },
      h("button", { onclick: () => navStop(-1) }, "‹ Previous"),
      h("button", { onclick: () => navStop(1) }, "Next ›"),
      h("button", {
        title: "Copy config from the previous stop (keeps this stop's town)",
        disabled: state.selectedStop === 0,
        onclick: () => copyPrevStop(state.selectedStop),
      }, "↧ Copy previous")),
    h("div", { class: "group" }, bulkMode),
    h("div", { class: "group" },
      h("button", { onclick: () => { stop.rules.forEach((r) => r.quantity = 0); renderStopEditor(); } }, "Qty 0"),
      h("button", { onclick: () => { stop.rules.forEach((r) => r.quantity = -1); renderStopEditor(); } }, "Qty max")),
    h("div", { class: "group" }, sortSel),
    h("div", { class: "group" }, priceSel));

  const tbody = h("tbody");
  stop.rules.forEach((rule, ri) => {
    if (!META.goods.visibility[rule.good] && !state.showWeapons) return;
    const priceInp = h("input", {
      type: "number", min: 0, max: 9999, value: rule.price,
      onchange: (e) => { rule.price = parseInt(e.target.value || "0", 10); },
    });
    const qtyInp = h("input", {
      type: "number", min: -1, max: 9999, value: rule.quantity,
      title: "-1 = maximum",
      onchange: (e) => { rule.quantity = parseInt(e.target.value || "0", 10); },
    });
    // Each option is tinted with its mode colour (mode-opt-N), matching the
    // colour the closed <select> takes once that mode is picked (mode-sel-N).
    const modeSel = h("select", {
      class: "mode-sel-" + rule.mode,
      onchange: (e) => {
        rule.mode = parseInt(e.target.value, 10);
        e.target.className = "mode-sel-" + rule.mode;
        // Choosing any of the 4 trade modes (Buy/Sell/Withdraw/Deposit)
        // resets the amount to the "maximum" sentinel (-1); only "None" is
        // left untouched.
        if (rule.mode !== 0) { rule.quantity = -1; qtyInp.value = -1; }
      },
    }, RULE_MODES.map((n, idx) => h("option", { value: idx, class: "mode-opt-" + idx, selected: idx === rule.mode }, n)));
    const tr = h("tr", { class: "rule" },
      h("td", { class: "grip-cell", title: "Drag to reorder" }, "⠿"),
      h("td", { class: "good-name" }, goodLabel(rule.good)),
      h("td", null, modeSel),
      h("td", null, priceInp),
      h("td", null, qtyInp));
    makeDraggable(tr, "rule", ri, (from, to) => { moveItem(stop.rules, from, to); renderStopEditor(); });
    tbody.append(tr);
  });

  const table = h("table", { class: "rules" },
    h("thead", null, h("tr", null,
      h("th", null, ""), h("th", null, "Good"), h("th", null, "Mode"),
      h("th", null, "Price"), h("th", null, "Quantity"))),
    tbody);

  box.replaceChildren(toolbar, table);
}

function navStop(delta) {
  const ni = state.selectedStop + delta;
  if (ni >= 0 && ni < state.route.stops.length) selectStop(ni);
}

// --------------------------------------------------------------------------
// Generators (route templates)
// --------------------------------------------------------------------------
const GENERATORS = [
  { id: "day_trader", name: "Day Trader", towns: 1, fields: ["buying", "selling"], help: "Buys/sells alternating in one town." },
  { id: "seller", name: "Seller", towns: 1, fields: ["selling"], help: "Cycles withdraw/sell/deposit (mod 3)." },
  { id: "supplier", name: "Supplier", towns: 1, fields: ["buying"], help: "Buys at maximum in one town." },
  { id: "sucker", name: "Sucker", towns: 1, fields: ["buying"], maximum: true, help: "Buys up to N distinct goods and deposits the rest." },
  { id: "sucker_to_warehouse", name: "Sucker → Warehouse", towns: 2, fields: ["quantity"], help: "Moves goods between two towns via a warehouse." },
];

// --------------------------------------------------------------------------
// Captains — where can I hire a captain right now? (reads the live game)
// --------------------------------------------------------------------------
const MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function skillCell(level) {
  // Skills are shown on the game's own 0–5 scale, with a little bar to compare.
  return h("td", { class: "skill" },
    h("span", { class: "skill-bar" },
      h("span", { class: "skill-fill", style: `width:${level / 5 * 100}%` })),
    h("span", { class: "skill-num" }, String(level)));
}

function renderCaptains(data) {
  if (!data || !data.ok) {
    const msg = (data && data.error) || "Couldn't read the game.";
    return h("div", { class: "captains-msg" },
      h("p", { class: "error" }, msg),
      h("p", { class: "hint" },
        "This feature reads the running Patrician III to see which taverns "
        + "have a captain waiting. Make sure the game is open with a savegame loaded."));
  }
  const d = data.date;
  const wrap = h("div", { class: "captains-result" });
  wrap.append(h("p", { class: "captains-summary" },
    `${data.totalCaptains} captain${data.totalCaptains === 1 ? "" : "s"} for hire across `
    + `${data.townsWithCaptains} town${data.townsWithCaptains === 1 ? "" : "s"} `
    + `— game date ${d.day} ${MONTHS[d.month]} ${d.year}.`));

  const rows = [];
  for (const e of data.towns) {
    e.captains.forEach((c, i) => {
      rows.push(h("tr", null,
        h("td", { class: "cap-town" }, i === 0 ? e.town : ""),
        skillCell(c.trade),
        skillCell(c.sailing),
        skillCell(c.fighting),
        h("td", { class: "cap-wage" }, String(c.wage))));
    });
  }
  wrap.append(h("table", { class: "captains-table" },
    h("thead", null, h("tr", null,
      h("th", null, "Town"),
      h("th", { title: "Trade skill (0–5)" }, "Trade"),
      h("th", { title: "Sailing skill (0–5)" }, "Sailing"),
      h("th", { title: "Fighting skill (0–5)" }, "Fighting"),
      h("th", { title: "Daily wage" }, "Wage"))),
    h("tbody", null, rows)));

  if (data.emptyTowns && data.emptyTowns.length) {
    wrap.append(h("p", { class: "hint captains-empty" },
      "No captain in: " + data.emptyTowns.join(", ") + "."));
  }
  return wrap;
}

function openCaptains() {
  const body = h("div", { class: "captains-body" }, h("p", { class: "hint" }, "Reading the game…"));
  const refreshBtn = h("button", null, "↻ Refresh");
  const node = h("div", { class: "modal captains-modal" },
    h("h2", null, "⚓ Hireable captains"),
    body, h("div", { class: "modal-actions" }, refreshBtn));
  modal(node);

  async function load() {
    body.replaceChildren(h("p", { class: "hint" }, "Reading the game…"));
    let data;
    try { data = await api("/api/captains/locate", {}); }
    catch (e) { data = { ok: false, error: "Unexpected error: " + e }; }
    body.replaceChildren(renderCaptains(data));
  }
  refreshBtn.addEventListener("click", load);
  load();
}

function openTemplates() {
  let current = GENERATORS[0];
  const body = h("div");
  const tabs = h("div", { class: "modal-tabs" },
    GENERATORS.map((g) => h("button", {
      class: g === current ? "active" : "",
      onclick: (e) => {
        current = g;
        tabs.querySelectorAll("button").forEach((b) => b.classList.remove("active"));
        e.target.classList.add("active");
        body.replaceChildren(buildGenForm(current));
      },
    }, g.name)));
  body.append(buildGenForm(current));
  const node = h("div", { class: "modal" },
    h("h2", null, "Generate route from template"),
    tabs, body);
  const close = modal(node);
  node._close = close;
}

function genGoodTable(fields, defaults) {
  // defaults: use the default pricing preset to prefill prices.
  const dp = state.pricings.find((p) => p.is_default) || state.pricings[0];
  const rows = [];
  const refs = [];
  for (let g = 0; g < META.goods.count; g++) {
    if (!META.goods.visibility[g]) continue;
    const enabled = h("input", { type: "checkbox" });
    const inputs = { good: g, enabled };
    const cells = [h("td", null, enabled), h("td", { class: "good-name" }, goodLabel(g))];
    if (fields.includes("buying")) {
      inputs.buying = h("input", { type: "number", min: 0, max: 9999, value: dp ? dp.buying[g] : 1 });
      cells.push(h("td", null, inputs.buying));
    }
    if (fields.includes("selling")) {
      inputs.selling = h("input", { type: "number", min: 0, max: 9999, value: dp ? dp.selling[g] : 1 });
      cells.push(h("td", null, inputs.selling));
    }
    if (fields.includes("quantity")) {
      inputs.quantity = h("input", { type: "number", min: -1, max: 9999, value: 1 });
      cells.push(h("td", null, inputs.quantity));
    }
    refs.push(inputs);
    rows.push(h("tr", null, cells));
  }
  const head = [h("th", null, ""), h("th", null, "Good")];
  if (fields.includes("buying")) head.push(h("th", null, "Buy"));
  if (fields.includes("selling")) head.push(h("th", null, "Sell"));
  if (fields.includes("quantity")) head.push(h("th", null, "Quantity"));
  const table = h("div", { class: "gen-goods" },
    h("table", null, h("thead", null, h("tr", null, head)), h("tbody", null, rows)));
  return { table, refs };
}

function readGoodData(refs) {
  return refs.map((r) => ({
    good: r.good,
    enabled: r.enabled.checked,
    quantity: r.quantity ? parseInt(r.quantity.value || "0", 10) : 0,
    buying_price: r.buying ? parseInt(r.buying.value || "0", 10) : 0,
    selling_price: r.selling ? parseInt(r.selling.value || "0", 10) : 0,
  }));
}

function townSelect() {
  return h("select", null, META.towns.names.map((n, i) => h("option", { value: i }, n)));
}

function buildGenForm(gen) {
  const wrap = h("div");
  wrap.append(h("p", { class: "hint" }, gen.help));

  if (gen.id === "sucker_to_warehouse") {
    const t1 = townSelect(), t2 = townSelect();
    const g1 = genGoodTable(["quantity"]);
    const g2 = genGoodTable(["quantity"]);
    wrap.append(
      h("div", { class: "dialog-row" }, h("label", null, "Main town:"), t1),
      h("strong", null, "Goods of main town"), g1.table,
      h("div", { class: "dialog-row" }, h("label", null, "Second town:"), t2),
      h("strong", null, "Goods of second town"), g2.table);
    wrap.append(genActions(() => ({
      kind: gen.id,
      first_town: parseInt(t1.value, 10), second_town: parseInt(t2.value, 10),
      first_goods: readGoodData(g1.refs), second_goods: readGoodData(g2.refs),
    })));
    return wrap;
  }

  const town = townSelect();
  wrap.append(h("div", { class: "dialog-row" }, h("label", null, "Town:"), town));
  let maxInput = null;
  if (gen.maximum) {
    maxInput = h("input", { type: "number", min: 1, max: 24, value: 3 });
    wrap.append(h("div", { class: "dialog-row" }, h("label", null, "Max. distinct goods:"), maxInput));
  }
  const goods = genGoodTable(gen.fields);
  wrap.append(goods.table);
  wrap.append(genActions(() => {
    const payload = { kind: gen.id, town: parseInt(town.value, 10), goods: readGoodData(goods.refs) };
    if (maxInput) payload.maximum_goods = parseInt(maxInput.value || "1", 10);
    return payload;
  }));
  return wrap;
}

function genActions(buildPayload) {
  return h("div", { class: "modal-actions" },
    h("button", { onclick: (e) => closestModal(e.target)._close() }, "Cancel"),
    h("button", {
      class: "primary",
      onclick: async (e) => {
        const res = await api("/api/generate", buildPayload());
        if (!res.ok) { setStatus("Error: " + res.error); return; }
        state.route.stops = res.stops;
        state.selectedStop = 0;
        closestModal(e.target)._close();
        setStatus(`Template applied (${res.stops.length} stops) — remember to Save`);
        renderEditor();
      },
    }, "Generate and apply"));
}

function closestModal(el) { while (el && !el._close) el = el.parentElement; return el; }

// --------------------------------------------------------------------------
// Sortings tab (sorting presets)
// --------------------------------------------------------------------------
let selectedSorting = null;

async function reloadSortings() {
  state.sortings = await api("/api/sortings");
}

function renderSortingsTab() {
  const root = $("#tab-sortings");
  if (!state.sortings.length) reloadSortings().then(() => renderSortingsTab());
  if (selectedSorting && !state.sortings.find((s) => s.id === selectedSorting)) selectedSorting = null;
  if (!selectedSorting && state.sortings[0]) selectedSorting = state.sortings[0].id;
  const preset = state.sortings.find((s) => s.id === selectedSorting);

  const list = h("div", { class: "preset-list" },
    h("div", { class: "panel-head" }, h("strong", null, "Sortings"),
      h("button", { onclick: createSorting }, "+ New")),
    h("ul", null, state.sortings.map((s) => h("li", { class: s.id === selectedSorting ? "selected" : "" },
      h("span", { class: "pname", onclick: () => { selectedSorting = s.id; renderSortingsTab(); } },
        s.id, " ", s.is_default ? h("span", { class: "badge" }, "def") : ""),
      h("button", { class: "icon", title: "Set default", onclick: () => setDefaultSorting(s.id) }, "★"),
      h("button", { class: "icon", title: "Rename", onclick: () => renameSorting(s.id) }, "✎"),
      h("button", { class: "icon danger", title: "Delete", onclick: () => deleteSorting(s.id) }, "🗑")))));

  let editor;
  if (preset) {
    const ul = h("div");
    const renderGoods = () => {
      ul.replaceChildren();
      preset.goods.forEach((g, i) => {
        if (!META.goods.visibility[g] && !state.showWeapons) return;
        const row = h("div", { class: "sorting-good" },
          h("span", null, "⠿ "), goodIcon(g), h("span", null, META.goods.names[g]));
        makeDraggable(row, "sgood", i, (from, to) => { moveItem(preset.goods, from, to); renderGoods(); });
        ul.append(row);
      });
    };
    renderGoods();
    editor = h("div", { class: "preset-editor" },
      h("div", { class: "editor-head" }, h("strong", null, "Edit: " + preset.id),
        h("div", { class: "spacer" }),
        h("button", { class: "primary", onclick: () => saveSorting(preset) }, "Save")),
      h("p", { class: "hint" }, "Drag to change the order of goods."),
      ul);
  } else {
    editor = h("div", { class: "preset-editor" }, h("p", { class: "hint" }, "Select or create a sorting."));
  }

  root.replaceChildren(h("div", { class: "preset-layout" }, list, editor));
}

async function createSorting() {
  const id = await promptDialog("Name of the sorting", "");
  if (!id) return;
  await api("/api/sortings/save", { sorting: { id, is_default: false, goods: [...Array(META.goods.count).keys()] } });
  await reloadSortings(); selectedSorting = id; renderSortingsTab();
}
async function saveSorting(preset) {
  await api("/api/sortings/save", { sorting: preset });
  await reloadSortings(); setStatus(`Sorting "${preset.id}" saved`);
}
async function setDefaultSorting(id) { await api("/api/sortings/setdefault", { id }); await reloadSortings(); renderSortingsTab(); }
async function renameSorting(id) {
  const nn = await promptDialog("Rename sorting", id); if (!nn || nn === id) return;
  await api("/api/sortings/rename", { old: id, new: nn });
  await reloadSortings(); selectedSorting = nn; renderSortingsTab();
}
async function deleteSorting(id) {
  if (!(await confirmDialog(`Delete sorting "${id}"?`))) return;
  await api("/api/sortings/delete", { id });
  if (selectedSorting === id) selectedSorting = null;
  await reloadSortings(); renderSortingsTab();
}

// --------------------------------------------------------------------------
// Pricings tab (pricing presets)
// --------------------------------------------------------------------------
let selectedPricing = null;

async function reloadPricings() { state.pricings = await api("/api/pricings"); }

function renderPricingsTab() {
  const root = $("#tab-pricings");
  if (!state.pricings.length) reloadPricings().then(() => renderPricingsTab());
  if (selectedPricing && !state.pricings.find((p) => p.id === selectedPricing)) selectedPricing = null;
  if (!selectedPricing && state.pricings[0]) selectedPricing = state.pricings[0].id;
  const preset = state.pricings.find((p) => p.id === selectedPricing);

  const list = h("div", { class: "preset-list" },
    h("div", { class: "panel-head" }, h("strong", null, "Pricings"),
      h("button", { onclick: createPricing }, "+ New")),
    h("ul", null, state.pricings.map((p) => h("li", { class: p.id === selectedPricing ? "selected" : "" },
      h("span", { class: "pname", onclick: () => { selectedPricing = p.id; renderPricingsTab(); } },
        p.id, " ", p.is_default ? h("span", { class: "badge" }, "def") : ""),
      h("button", { class: "icon", title: "Set default", onclick: () => setDefaultPricing(p.id) }, "★"),
      h("button", { class: "icon", title: "Rename", onclick: () => renamePricing(p.id) }, "✎"),
      h("button", { class: "icon danger", title: "Delete", onclick: () => deletePricing(p.id) }, "🗑")))));

  let editor;
  if (preset) {
    const def = META.defaultPricing;
    const order = defaultSorting() ? defaultSorting().goods : [...Array(META.goods.count).keys()];
    const rows = [];
    for (const g of order) {
      if (!META.goods.visibility[g] && !state.showWeapons) continue;
      const b = h("input", { type: "number", min: 0, max: 9999, value: preset.buying[g],
        onchange: (e) => { preset.buying[g] = parseInt(e.target.value || "0", 10); } });
      const s = h("input", { type: "number", min: 0, max: 9999, value: preset.selling[g],
        onchange: (e) => { preset.selling[g] = parseInt(e.target.value || "0", 10); } });
      const defBuy = def.buying[g], defSell = def.selling[g];
      const cBuy = h("td", { class: "default-price" + (preset.buying[g] !== defBuy ? " diff" : ""),
        title: "Default buy price" }, defBuy);
      const cSell = h("td", { class: "default-price" + (preset.selling[g] !== defSell ? " diff" : ""),
        title: "Default sell price" }, defSell);
      rows.push(h("tr", null, h("td", { class: "good-name" }, goodLabel(g)),
        h("td", null, b), h("td", null, s), cBuy, cSell));
    }
    editor = h("div", { class: "preset-editor" },
      h("div", { class: "editor-head" }, h("strong", null, "Edit: " + preset.id),
        h("div", { class: "spacer" }),
        h("button", { class: "primary", onclick: () => savePricing(preset) }, "Save")),
      h("table", { class: "pricing-grid" },
        h("thead", null, h("tr", null, h("th", null, "Good"), h("th", null, "Buy"), h("th", null, "Sell"),
          h("th", { class: "default-price" }, "Def. Buy"),
          h("th", { class: "default-price" }, "Def. Sell"))),
        h("tbody", null, rows)));
  } else {
    editor = h("div", { class: "preset-editor" }, h("p", { class: "hint" }, "Select or create a pricing preset."));
  }

  root.replaceChildren(h("div", { class: "preset-layout" }, list, editor));
}

async function createPricing() {
  const id = await promptDialog("Name of the pricing preset", "");
  if (!id) return;
  await api("/api/pricings/save", { pricing: { id, is_default: false } });
  await reloadPricings(); selectedPricing = id; renderPricingsTab();
}
async function savePricing(preset) {
  await api("/api/pricings/save", { pricing: preset });
  await reloadPricings(); setStatus(`Pricing "${preset.id}" saved`);
}
async function setDefaultPricing(id) { await api("/api/pricings/setdefault", { id }); await reloadPricings(); renderPricingsTab(); }
async function renamePricing(id) {
  const nn = await promptDialog("Rename pricing", id); if (!nn || nn === id) return;
  await api("/api/pricings/rename", { old: id, new: nn });
  await reloadPricings(); selectedPricing = nn; renderPricingsTab();
}
async function deletePricing(id) {
  if (!(await confirmDialog(`Delete preset "${id}"?`))) return;
  await api("/api/pricings/delete", { id });
  if (selectedPricing === id) selectedPricing = null;
  await reloadPricings(); renderPricingsTab();
}

// --------------------------------------------------------------------------
// Init
// --------------------------------------------------------------------------
async function init() {
  initTheme();
  $("#theme-toggle").addEventListener("click", toggleTheme);
  initWeapons();
  $("#weapons-toggle").addEventListener("change", onToggleWeapons);
  META = await api("/api/meta");
  await Promise.all([reloadSortings(), reloadPricings()]);
  setupTabs();
  $("#open-folder").addEventListener("click", openFolder);
  $("#pick-folder").addEventListener("click", pickFolder);
  $("#close-folder").addEventListener("click", closeFolder);
  $("#folder-path").addEventListener("keydown", (e) => { if (e.key === "Enter") openFolder(); });
  $("#route-search").addEventListener("input", renderRouteList);
  $("#new-route").addEventListener("click", newRoute);
  $("#add-stop").addEventListener("click", addStop);
  $("#save-route").addEventListener("click", saveRoute);
  $("#templates-btn").addEventListener("click", openTemplates);
  $("#captains-btn").addEventListener("click", openCaptains);
  setStatus("Ready. Open your game's Save\\AutoRoute folder.");

  // Remember the last opened folder and reopen it automatically.
  const cfg = await api("/api/settings");
  if (cfg && cfg.last_folder) {
    $("#folder-path").value = cfg.last_folder;
    await openFolder();
  }
}

init();
