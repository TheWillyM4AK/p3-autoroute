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
  difficulty: 1,       // live-price difficulty (0/1/2), persisted in settings
  pricings: [],
  sortings: [],
};

// --------------------------------------------------------------------------
// Dialogs
// --------------------------------------------------------------------------
function modal(node, onBeforeClose) {
  const backdrop = h("div", { class: "backdrop" }, node);
  function close() { backdrop.remove(); }
  // Click-outside closes, unless onBeforeClose() vetoes it (it may be async, e.g.
  // an "unsaved changes" confirm). The returned close() bypasses the guard, so
  // programmatic closers (a dialog's OK button) keep working as before.
  backdrop.addEventListener("mousedown", async (ev) => {
    if (ev.target !== backdrop) return;
    if (onBeforeClose && (await onBeforeClose()) === false) return;
    close();
  });
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
  loadRoute(nn);
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

// The order every goods-keyed view lists goods in: the user's default sorting,
// so the Prices modal's three tabs ("Universal", "By town (live)", "Mis precios")
// all agree. Falls back to the natural good-id order when no sorting exists.
function goodsOrder() {
  return defaultSorting() ? defaultSorting().goods : [...Array(META.goods.count).keys()];
}

// Sort a copy of `rows` by goodsOrder(); `keyFn` extracts each row's good id.
// Rows whose good isn't in the order keep their relative position at the end.
function byGoodsOrder(rows, keyFn) {
  const order = goodsOrder();
  const rank = new Map(order.map((g, i) => [g, i]));
  const at = (x) => (rank.has(keyFn(x)) ? rank.get(keyFn(x)) : order.length);
  return rows.slice().sort((a, b) => at(a) - at(b));
}

// The pricing whose buy/sell prices auto-fill a rule when its mode is set to
// Buy/Sell: the user's default preset, falling back to the built-in defaults.
// Both shapes expose .buying/.selling indexed by good id.
function defaultPricing() {
  return state.pricings.find((p) => p.is_default) || state.pricings[0] || META.defaultPricing;
}

// Buy mode (1) takes the default buy price; Sell (2) the default sell price;
// any other mode leaves the price untouched. Returns null when unchanged.
function autoPriceFor(good, mode) {
  const dp = defaultPricing();
  if (!dp) return null;
  if (mode === 1) return dp.buying[good];
  if (mode === 2) return dp.selling[good];
  return null;
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
      onchange: (e) => {
        stop.town = parseInt(e.target.value, 10);
        // Re-adjust the route's traded goods (Buy/Sell/price) to the new town so
        // a stop always trades the route set as fits where it now docks.
        const traded = routeTradedGoods();
        if (traded.size) { applyRouteTradeToStop(stop, traded); renderEditor(); }
      },
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
  const stop = newStop(0);
  // Carry over the goods already being traded in this route so a new stop need
  // not be reconfigured from scratch — they re-adjust when its town is picked.
  const traded = routeTradedGoods();
  applyRouteTradeToStop(stop, traded);
  state.route.stops.push(stop);
  state.selectedStop = state.route.stops.length - 1;
  renderEditor();
  if (traded.size) {
    setStatus(`New stop added with the route's ${traded.size} traded good(s) — set its town to adjust Buy/Sell`);
  }
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
    stop.rules.forEach((r) => {
      r.mode = m;
      if (m === 0) {
        // None clears each rule: price and quantity back to zero.
        r.price = 0; r.quantity = 0;
      } else {
        // The 4 trade modes reset the amount to the "maximum" sentinel (-1),
        // and set the price: Buy/Sell auto-fill the matching default, while
        // Withdraw/Deposit carry no price and must reset it to 0 (a nonzero
        // price there would be re-read as Buy/Sell on save — see rou.py). This
        // mirrors the per-rule path.
        r.quantity = -1;
        const ap = autoPriceFor(r.good, m);
        r.price = ap != null ? ap : 0;
      }
    });
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
    h("strong", { class: "stop-title" }, "Stop #" + (state.selectedStop + 1) + " — " + META.towns.names[stop.town]),
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
        if (rule.mode === 0) {
          // None clears the rule: price and quantity go back to zero.
          rule.price = 0; priceInp.value = 0;
          rule.quantity = 0; qtyInp.value = 0;
        } else {
          // The 4 trade modes (Buy/Sell/Withdraw/Deposit) reset the amount to
          // the "maximum" sentinel (-1)...
          rule.quantity = -1; qtyInp.value = -1;
          // ...and set the price: Buy/Sell auto-fill the matching default,
          // while Withdraw/Deposit carry no price and reset it to 0 (a nonzero
          // price there would be re-read as Buy/Sell on save — see rou.py).
          const ap = autoPriceFor(rule.good, rule.mode);
          rule.price = ap != null ? ap : 0;
          priceInp.value = rule.price;
        }
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
// Trade a good — mark Buy/Sell across the open route's existing stops
// --------------------------------------------------------------------------
// Producing towns become Buy (at the default buy price), the rest that consume
// the good become Sell (at the default sell price). Only existing DOCK stops
// are touched; no stops are added. Production/demand comes from META.production.
function tradeActionFor(town, good) {
  const prod = (META.production && META.production.producers[good]) || [];
  if (prod.includes(town)) return "buy";
  if (META.production && META.production.consumable[good]) return "sell";
  return null; // weapons / non-consumable goods have no town demand
}

// The route's "trade set": every good currently traded (Buy/Sell) in any dock
// stop, mapped to a representative quantity (the first one found). These are the
// goods the user has chosen via "Trade a good"; new stops inherit them.
function routeTradedGoods() {
  const m = new Map();
  if (!state.route) return m;
  state.route.stops.forEach((s) => {
    if (s.mode !== 0) return; // only dockable stops trade
    s.rules.forEach((r) => {
      if ((r.mode === 1 || r.mode === 2) && !m.has(r.good)) m.set(r.good, r.quantity);
    });
  });
  return m;
}

// Apply the route's trade set to a single stop, adjusting each good to *this*
// stop's town: produced → Buy, consumed → Sell, neither → cleared. Prices follow
// the default pricing; a good that was already trading keeps its own quantity,
// otherwise it takes the route's representative quantity. Returns how many goods
// ended up trading. Lets a freshly added stop carry the route's goods without
// re-running "Trade a good", and re-syncs them when its town changes.
function applyRouteTradeToStop(stop, traded) {
  if (!stop || stop.mode !== 0) return 0; // skips/repairs don't trade
  traded = traded || routeTradedGoods();
  let n = 0;
  traded.forEach((qty, good) => {
    const rule = stop.rules.find((r) => r.good === good);
    if (!rule) return;
    const act = tradeActionFor(stop.town, good);
    if (!act) {
      // This town neither produces nor consumes it: drop any stale Buy/Sell left
      // over from a previous town so the stop stays consistent.
      if (rule.mode === 1 || rule.mode === 2) { rule.mode = 0; rule.price = 0; rule.quantity = 0; }
      return;
    }
    const wasTrading = rule.mode === 1 || rule.mode === 2;
    rule.mode = act === "buy" ? 1 : 2;
    const ap = autoPriceFor(good, rule.mode);
    if (ap != null) rule.price = ap;
    if (!wasTrading) rule.quantity = qty;
    n++;
  });
  return n;
}

// The modal edits the route's *trade set* declaratively: each good is a toggle,
// the ones already trading start on. One "Apply" then reconciles every dock stop
// to the chosen set — turning each selected good into Buy/Sell per the town's
// production (default price) and clearing goods that were switched off.
function openTradeGood() {
  if (!state.route) { setStatus("Open a route first."); return; }
  // Only dockable stops trade; skips/repairs are left alone.
  const dockStops = state.route.stops
    .map((s, i) => ({ s, i }))
    .filter((x) => x.s.mode === 0);

  // Goods trading at open (the starting set) and the live target set the user
  // edits via the chips. ``selected`` starts as a copy of what's already traded.
  const initiallyTraded = new Set(routeTradedGoods().keys());
  const selected = new Set(initiallyTraded);
  const chipByGood = new Map();
  // Per-good direction override: "auto" (Buy where produced, Sell where consumed),
  // "buy" (only buy in producing towns), or "sell" (only sell in consuming towns).
  // Absent good = "auto". Lets the user force a single direction across the route.
  const goodMode = new Map();

  const preview = h("div", { class: "trade-preview" });
  const qtyInp = h("input", { type: "number", min: -1, max: 9999, value: -1, title: "-1 = maximum" });
  const applyBtn = h("button", { class: "primary" }, "Apply to route");

  // For one good, how many dock stops would Buy vs Sell it given their towns.
  function stopCounts(good) {
    let buy = 0, sell = 0;
    dockStops.forEach(({ s }) => {
      const a = tradeActionFor(s.town, good);
      if (a === "buy") buy++; else if (a === "sell") sell++;
    });
    return { buy, sell };
  }

  // The action a good takes at a town once its direction override is applied:
  // "auto" follows production; "buy"/"sell" keep only the matching towns — the
  // opposite ones fall through to null, so Apply leaves/clears them (does nothing).
  function effectiveAction(town, good) {
    const act = tradeActionFor(town, good);
    const mode = goodMode.get(good) || "auto";
    if (mode === "buy") return act === "buy" ? "buy" : null;
    if (mode === "sell") return act === "sell" ? "sell" : null;
    return act;
  }

  // A 3-way Auto/Buy/Sell segmented control for one good's direction override.
  function modeControl(g) {
    const cur = goodMode.get(g) || "auto";
    const opts = [
      ["auto", "Auto", "Buy where the town produces it, Sell where it's consumed"],
      ["buy", "Buy", "Only buy (in producing towns); do nothing in the rest"],
      ["sell", "Sell", "Only sell (in consuming towns); do nothing in the rest"],
    ];
    return h("div", { class: "tp-mode" }, opts.map(([val, label, title]) => {
      const b = h("button", { type: "button", title,
        class: "tp-mode-btn" + (cur === val ? " active" : "") }, label);
      b.addEventListener("click", () => { goodMode.set(g, val); renderPreview(); });
      return b;
    }));
  }

  function paintChip(g) {
    const chip = chipByGood.get(g);
    if (!chip) return;
    const sel = selected.has(g);
    const was = initiallyTraded.has(g);
    chip.classList.toggle("selected", sel);
    chip.classList.toggle("traded", was);
    chip.classList.toggle("removing", was && !sel);
    chip.title = sel
      ? (was ? "Trading in this route" : "Will start trading")
      : (was ? "Will be removed from the route" : "");
    chip.querySelector(".chip-mark").textContent = sel ? "✓" : (was ? "✕" : "");
  }

  function renderPreview() {
    preview.replaceChildren();
    if (!dockStops.length) {
      preview.append(h("p", { class: "hint" }, "This route has no dockable stops to mark yet."));
      applyBtn.disabled = true; return;
    }
    const added = [...selected].filter((g) => !initiallyTraded.has(g));
    const removed = [...initiallyTraded].filter((g) => !selected.has(g));
    if (!selected.size && !removed.length) {
      preview.append(h("p", { class: "hint" },
        "Toggle goods above. Each one you turn on trades across the route (Buy where "
        + "produced, Sell where consumed); turning an already-traded one off removes it."));
      applyBtn.disabled = true; return;
    }
    preview.append(h("p", { class: "trade-summary" },
      `On apply: ${selected.size} good(s) traded `,
      h("span", { class: "ts-add" }, `+${added.length} added`), ", ",
      h("span", { class: "ts-rm" }, `−${removed.length} removed`), "."));

    const rows = [];
    [...selected].sort((a, b) => a - b).forEach((g) => {
      const { buy, sell } = stopCounts(g);
      const mode = goodMode.get(g) || "auto";
      const parts = [];
      if (mode !== "sell" && buy) parts.push(h("span", { class: "tp-buy-c" }, `Buy ×${buy}`));
      if (mode !== "buy" && sell) parts.push(h("span", { class: "tp-sell-c" }, `Sell ×${sell}`));
      const none = mode === "buy" ? "— no town on this route produces it"
        : mode === "sell" ? "— no town on this route consumes it"
        : "— no town on this route trades it";
      rows.push(h("tr", { class: initiallyTraded.has(g) ? "" : "tp-added" },
        h("td", { class: "tp-good" }, goodIcon(g), h("span", null, META.goods.names[g])),
        h("td", { class: "tp-act" },
          parts.length ? parts.flatMap((p, idx) => idx ? [", ", p] : [p])
            : h("span", { class: "tp-none" }, none)),
        h("td", { class: "tp-dir" }, modeControl(g))));
    });
    removed.sort((a, b) => a - b).forEach((g) => {
      let n = 0;
      dockStops.forEach(({ s }) => {
        const r = s.rules.find((x) => x.good === g);
        if (r && (r.mode === 1 || r.mode === 2)) n++;
      });
      rows.push(h("tr", { class: "tp-removed" },
        h("td", { class: "tp-good" }, goodIcon(g), h("span", null, META.goods.names[g])),
        h("td", { class: "tp-act" }, h("span", { class: "tp-rm" }, `Remove from ${n} stop(s)`)),
        h("td", { class: "tp-dir" })));
    });
    preview.append(h("table", { class: "trade-table" },
      h("thead", null, h("tr", null,
        h("th", null, "Good"), h("th", null, "What happens"), h("th", null, "Direction"))),
      h("tbody", null, rows)));
    applyBtn.disabled = false;
  }

  const picker = h("div", { class: "good-picker" });
  for (let g = 0; g < META.goods.count; g++) {
    if (!META.goods.visibility[g] && !state.showWeapons) continue;
    const chip = h("button", { class: "good-chip", type: "button" },
      goodIcon(g), h("span", { class: "chip-name" }, META.goods.names[g]),
      h("span", { class: "chip-mark" }, ""));
    chip.addEventListener("click", () => {
      if (selected.has(g)) selected.delete(g); else selected.add(g);
      paintChip(g);
      renderPreview();
    });
    chipByGood.set(g, chip);
    picker.append(chip);
    paintChip(g);
  }

  // Bulk helpers for working with many goods at once.
  const selectAllBtn = h("button", { type: "button" }, "Select all");
  selectAllBtn.addEventListener("click", () => {
    chipByGood.forEach((_c, g) => selected.add(g));
    chipByGood.forEach((_c, g) => paintChip(g));
    renderPreview();
  });
  const clearBtn = h("button", { type: "button" }, "Clear");
  clearBtn.addEventListener("click", () => {
    selected.clear();
    chipByGood.forEach((_c, g) => paintChip(g));
    renderPreview();
  });

  const node = h("div", { class: "modal trade-modal" },
    h("h2", null, "📦 Start trading a good"),
    h("p", { class: "hint" },
      "Toggle the goods this route should trade. Each one on is set to Buy where "
      + "its town produces it and Sell where consumed, at its default price. Use the "
      + "Direction control below to force a good to only Buy or only Sell across the "
      + "whole route (towns going the other way are left untouched). ✓ = will trade, "
      + "✕ = will be removed. Apply reconciles every stop in one go."),
    h("div", { class: "trade-bulk" }, selectAllBtn, clearBtn),
    picker,
    h("div", { class: "dialog-row" },
      h("label", null, "Quantity:"), qtyInp,
      h("small", { class: "hint" }, "-1 = maximum · used for goods you add")),
    preview,
    h("div", { class: "modal-actions" },
      h("button", { onclick: () => close() }, "Cancel"), applyBtn));
  const close = modal(node);

  applyBtn.addEventListener("click", () => {
    const q = parseInt(qtyInp.value || "-1", 10);
    const changedStops = new Set();
    dockStops.forEach(({ s, i }) => {
      // Selected goods → Buy/Sell per this town (clearing where the town trades
      // neither). New goods take the chosen quantity; kept ones keep their own.
      selected.forEach((g) => {
        const rule = s.rules.find((r) => r.good === g);
        if (!rule) return;
        const act = effectiveAction(s.town, g);
        if (!act) {
          if (rule.mode === 1 || rule.mode === 2) {
            rule.mode = 0; rule.price = 0; rule.quantity = 0; changedStops.add(i);
          }
          return;
        }
        const wasTrading = rule.mode === 1 || rule.mode === 2;
        rule.mode = act === "buy" ? 1 : 2;
        const ap = autoPriceFor(g, rule.mode);
        if (ap != null) rule.price = ap;
        if (!wasTrading) rule.quantity = q;
        changedStops.add(i);
      });
      // Goods switched off that were trading → cleared everywhere.
      initiallyTraded.forEach((g) => {
        if (selected.has(g)) return;
        const rule = s.rules.find((r) => r.good === g);
        if (rule && (rule.mode === 1 || rule.mode === 2)) {
          rule.mode = 0; rule.price = 0; rule.quantity = 0; changedStops.add(i);
        }
      });
    });
    const added = [...selected].filter((g) => !initiallyTraded.has(g)).length;
    const removed = [...initiallyTraded].filter((g) => !selected.has(g)).length;
    close();
    setStatus(`Trade set updated (+${added}, −${removed}) across ${changedStops.size} stop(s) — remember to Save`);
    renderEditor();
  });

  renderPreview();
}

// --------------------------------------------------------------------------
// Apply pricing — reprice every Buy/Sell rule across the whole route
// --------------------------------------------------------------------------
// The per-stop "Apply pricing…" select only touches the stop being edited; this
// does the same across every dockable stop at once, using the default pricing
// template (the one marked ★). Trade modes and quantities are left untouched —
// only the prices of rules already set to Buy/Sell change, Buy taking the
// template's buy price and Sell its sell price.
function applyRoutePricing() {
  if (!state.route) { setStatus("Open a route first."); return; }
  const p = defaultPricing();
  if (!p) { setStatus("No pricing template set — create one in the Pricings tab."); return; }
  const dockStops = state.route.stops.filter((s) => s.mode === 0);
  let n = 0;
  dockStops.forEach((s) => s.rules.forEach((r) => {
    if (r.mode === 1) { r.price = p.buying[r.good]; n++; }
    else if (r.mode === 2) { r.price = p.selling[r.good]; n++; }
  }));
  if (!n) { setStatus("No Buy/Sell rules to reprice — use “Trade a good…” first."); return; }
  setStatus(`Repriced ${n} rule(s) across ${dockStops.length} stop(s) with "${p.id || "default"}" — remember to Save`);
  renderEditor();
}

// --------------------------------------------------------------------------
// Prices — universal reference table + optional live per-town view
// --------------------------------------------------------------------------
// The game stores the month 0-indexed (January = 0), so this lookup is 0-indexed too.
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function priceError(data) {
  const msg = (data && data.error) || "Couldn't read the game.";
  return h("div", { class: "prices-msg" },
    h("p", { class: "error" }, msg),
    h("p", { class: "hint" },
      "The live view reads the running Patrician III — open the game with a "
      + "savegame loaded. (The universal table doesn't need the game.)"));
}

// Per-good reference prices, cheapest → dearest. Floor / Base / Ceiling are the
// constant neutral anchors of the scale (single theoretical value). The six
// "per-N-weeks" columns (Buy 3/2.5/2wk, Sell 2/1.5/1wk) carry a DUAL value —
// theoretical (faint, top) over the
// live median from the running game (bold, coloured) — because that is where
// the additive threshold bonus makes theory and reality diverge. ``liveMap`` maps
// good id → its live row, or is null when the game isn't readable (live → "—").
function buildUniversalTable(data, liveMap) {
  const fmt = (v) => (v == null ? "—" : String(v));
  const dual = (theo, live, cls) => h("td", { class: "pr-dual" },
    h("div", { class: "t-val" }, fmt(theo)),
    h("div", { class: "l-val " + cls }, fmt(live)));
  // Value density bar — width relative to the densest good (Skins).
  const maxDen = Math.max(1, ...data.goods.map((g) => g.density || 0));
  const trs = byGoodsOrder(data.goods, (g) => g.good).map((g) => {
    const lv = liveMap ? liveMap[g.good] : null;
    return h("tr", null,
      h("td", { class: "pr-good" }, g.approx
        ? [...goodLabel(g.good), h("span", { class: "pr-approx",
            title: "Material de construcción: el precio real a N semanas difiere del teórico "
              + "(bono aditivo). Fíjate en el valor en vivo (abajo) de las columnas dobles." }, " *")]
        : goodLabel(g.good)),
      h("td", { class: "pr-density",
        style: `--den:${Math.round(100 * (g.density || 0) / maxDen)}%`,
        title: "Densidad de valor = precio base ÷ volumen en bodega. Oro por barril "
          + "(un fardo ocupa 10 barriles). Más alto = rinde más por espacio de carga." },
        String(g.density)),
      h("td", { class: "pr-floor" }, String(g.floor)),
      dual(g.buy3wk, lv && lv.buy3wk, "buy"),
      dual(g.buy2_5wk, lv && lv.buy2_5wk, "buy"),
      dual(g.buy2wk, lv && lv.buy2wk, "buy"),
      h("td", { class: "pr-base" }, String(g.base)),
      dual(g.sell2wk, lv && lv.sell2wk, "sell"),
      dual(g.sell1_5wk, lv && lv.sell1_5wk, "sell"),
      dual(g.sell1wk, lv && lv.sell1wk, "sell"),
      h("td", { class: "pr-ceiling" }, String(g.ceiling)));
  });
  const dualTitle = (txt) => txt + " Celda doble: arriba el teórico, abajo el real de tu "
    + "partida (mediana de ciudades; — si el juego no está abierto).";
  return h("table", { class: "prices-table" },
    h("thead", null, h("tr", null,
      h("th", null, "Good"),
      h("th", { title: "Densidad de valor: precio base ÷ volumen que ocupa en bodega. "
        + "Oro por barril (un fardo = 10 barriles). Alto = más valor por espacio de carga." },
        "Valor/barril"),
      h("th", { title: "Cheapest you'll ever pay — a deep-glut town (0.6× base)" }, "Floor"),
      h("th", { title: dualTitle("Compra al pivote de 3 semanas (teórico ≈ base).") }, "Buy 3wk"),
      h("th", { title: dualTitle("Compra drenando a 2,5 semanas (teórico 1,125× base, entre el pivote y la compra agresiva).") }, "Buy 2.5wk"),
      h("th", { title: dualTitle("Compra agresiva drenando a 2 semanas (teórico 1,25× base).") }, "Buy 2wk"),
      h("th", { title: "Pivote neutral (1.0×): a 3 semanas compra = venta = base" }, "Base"),
      h("th", { title: dualTitle("Venta hasta 2 semanas, lo habitual (teórico 1,2× base).") }, "Sell 2wk"),
      h("th", { title: dualTitle("Venta hasta 1,5 semanas (teórico 1,3× base, entre lo habitual y el premium).") }, "Sell 1.5wk"),
      h("th", { title: dualTitle("Venta premium hasta 1 semana (teórico 1,4× base).") }, "Sell 1wk"),
      h("th", { title: "Dearest you'll ever get — an empty town (2× base, ajustado a la dificultad)" }, "Ceiling"))),
    h("tbody", null, trs));
}

// Live per-town quotes for one good, sorted scarce → glut.
function buildTownTable(g) {
  const rows = g.towns.slice().sort((a, b) => b.sell - a.sell);  // dearest (scarcest) first
  const trs = rows.map((t) => h("tr", null,
    h("td", { class: "pr-town" },
      t.produces ? [t.town, h("span", { class: "pr-prod", title: "Produced here" }, " 🏭")] : t.town),
    h("td", { class: "pr-weeks" }, t.weeks == null ? "∞" : String(t.weeks)),
    h("td", { class: "pr-buy" }, t.buy == null ? "—" : String(t.buy)),
    h("td", { class: "pr-sell" }, String(t.sell))));
  return h("table", { class: "prices-table" },
    h("thead", null, h("tr", null,
      h("th", null, "Town"),
      h("th", { title: "Semanas de stock = stock ÷ consumo semanal (igual que el juego). Bajo = escaso (vender), alto = saturado (comprar). ∞ = no lo consume" }, "Supply"),
      h("th", { title: "Price to buy one load here" }, "Buy"),
      h("th", { title: "Price you get selling one load here" }, "Sell"))),
    h("tbody", null, trs));
}

// Persist a price clicked in the Range chart into the default pricing preset and
// flash a confirmation toast.
async function setRangePrice(good, side, price) {
  let res;
  try { res = await api("/api/pricings/set_price", { good, side, price }); }
  catch (e) { res = null; }
  if (!res || !res.ok) return;
  reloadPricings();  // keep the Pricings tab's state in sync (fire-and-forget)
  const t = h("div", { class: "pr-saved-toast" },
    `✓ ${META.goods.names[good]} · ${side === "buy" ? "compra" : "venta"} → ${price.toLocaleString("es-ES")}`);
  document.body.append(t);
  setTimeout(() => t.remove(), 1600);
}

// Live price-range chart for one good: two stacked lanes (buy on top, sell
// below), each city a dot (green = producer). Both lanes share ONE axis centred
// on the base price — base sits at 50% and lines up vertically between the lanes,
// so the left half is "cheap, where you buy" and the right half "dear, where you
// sell". The axis is symmetric around base out to the ceiling (or a higher winter
// cost); anything past it (an empty town's buy price, ~4× base) is clamped to the
// edge and flagged "fuera de escala". Same /api/prices/live payload as the
// by-town table — no extra backend call.
function buildRangeChart(g) {
  const fmt = (n) => Math.round(n).toLocaleString("es-ES");
  const per = g.base;
  // Shared axis from the floor (cheapest, hard left) to the ceiling — or a higher
  // winter cost — (dearest, hard right), so there's no wasted empty span. Same
  // scale in both lanes, so the base lines up vertically. Prices outside this
  // range (an empty town's buy ~4× base) are clamped to the edge and flagged with
  // a fade so the wide near-empty tail doesn't squash everything.
  const axMin = g.floor;
  const axMax = Math.max(g.ceiling, g.prodCost || 0, g.prodCostWinter || 0);
  const X = (v) => Math.max(0, Math.min(100, (v - axMin) / (axMax - axMin) * 100));
  const inRange = (v) => v != null && v >= axMin && v <= axMax;

  function lane(isSell) {
    const lk = isSell ? "sell" : "buy";
    const wrap = h("div", { class: "pr-lane" });
    const vals = g.towns.map((t) => (isSell ? t.sell : t.buy)).filter((v) => v != null);
    if (!vals.length) return wrap;
    const minV = Math.min(...vals), maxV = Math.max(...vals);
    let anchors, live;
    if (isSell) {
      anchors = [[per, "base"], [g.ceiling, "techo"]];
      // Live medians at N weeks of supply (same numbers as the Universal tab).
      live = [[g.sell2wk, "2s"], [g.sell1_5wk, "1.5s"], [g.sell1wk, "1s"]];
    } else {
      anchors = [[g.floor, "suelo"], [per, "base"]];
      // Theoretical cost to make it yourself: one latón mark per season.
      if (g.prodCost != null) anchors.push([g.prodCost, "coste", "cost"]);
      if (g.prodCostWinter != null) anchors.push([g.prodCostWinter, "inv", "cost"]);
      live = [[g.buy3wk, "3s"], [g.buy2_5wk, "2.5s"], [g.buy2wk, "2s"]];
    }
    const outHi = vals.filter((v) => v > axMax);
    const outLo = vals.filter((v) => v < axMin);
    const bandLo = Math.max(minV, axMin), bandHi = Math.min(maxV, axMax);
    wrap.append(h("div", { class: "pr-band",
      style: `left:${X(bandLo)}%;width:${X(bandHi) - X(bandLo)}%` }));
    // Cursor shade (sits under the dots): the captured range, filled toward the
    // cheap/buy side (left) or the dear/sell side (right).
    const shade = h("div", { class: "pr-cursor-shade " + lk });
    wrap.append(shade);
    // Fade the edge where towns are clamped, so a wide off-scale tail reads as cut.
    if (outHi.length) wrap.append(h("div", { class: "pr-clip r" }));
    if (outLo.length) wrap.append(h("div", { class: "pr-clip l" }));
    // Two fixed rows of anchors: structural marks (suelo/base/techo) on the top
    // row, the production-cost marks (verano + invierno) on a second row.
    anchors.filter(([v]) => inRange(v)).forEach(([v, n, cls]) => {
      const top = cls === "cost" ? 28 : 2;
      wrap.append(h("div", { class: "pr-anchor" + (cls ? " " + cls : ""), style: `left:${X(v)}%` }));
      wrap.append(h("div", { class: "pr-anchor-label" + (cls ? " " + cls : ""),
        style: `left:${X(v)}%;top:${top}px` }, n, h("br"), h("b", null, fmt(v))));
    });
    const pts = g.towns
      .map((t) => ({ town: t.town, v: isSell ? t.sell : t.buy, w: t.weeks, p: t.produces }))
      .filter((o) => o.v != null).sort((a, b) => a.v - b.v);
    let lastX = -99, row = 0;
    for (const o of pts) {
      const off = o.v > axMax || o.v < axMin;
      const x = X(o.v);
      if (x - lastX < 3.4) row = (row + 1) % 4; else row = 0;
      lastX = x;
      const wk = o.w == null ? "∞" : (o.w >= 100 ? Math.round(o.w) : o.w.toFixed(1));
      wrap.append(h("div", {
        class: "pr-dot" + (o.p ? " prod" : "") + (off ? " out" : ""),
        style: `left:${x}%;top:${58 + row * 11}px`,
        title: `${o.town} — ${fmt(o.v)} oro/carga · ${wk} sem`
          + (o.p ? " · produce" : "") + (off ? " · fuera de escala" : ""),
      }));
    }
    wrap.append(h("div", { class: "pr-axis" }));
    live.filter(([v]) => inRange(v)).forEach(([v, n]) => {
      wrap.append(h("div", { class: `pr-tick ${lk}`, style: `left:${X(v)}%` }));
      wrap.append(h("div", { class: `pr-tick-label ${lk}`, style: `left:${X(v)}%;top:114px`,
        title: "Precio mediano en vivo a esas semanas de stock" }, n, h("br"), h("b", null, fmt(v))));
    });
    if (outHi.length) wrap.append(h("div", { class: "pr-out r" },
      `${outHi.length} fuera » hasta ${fmt(Math.max(...outHi))}`));
    if (outLo.length) wrap.append(h("div", { class: "pr-out l" },
      `« ${outLo.length} fuera desde ${fmt(Math.min(...outLo))}`));
    // Mouse cursor: a vertical bar + price readout following the pointer, shading
    // the captured range; a click writes that price into the default preset.
    const bar = h("div", { class: "pr-cursor" });
    const tag = h("div", { class: "pr-cursor-price " + lk });
    wrap.append(bar, tag);
    const priceAt = (xp) => Math.round(axMin + (xp / 100) * (axMax - axMin));
    const xOf = (e) => {
      const r = wrap.getBoundingClientRect();
      return Math.max(0, Math.min(100, (e.clientX - r.left) / r.width * 100));
    };
    wrap.addEventListener("mousemove", (e) => {
      const xp = xOf(e);
      bar.style.left = tag.style.left = xp + "%";
      tag.textContent = fmt(priceAt(xp));
      shade.style.left = isSell ? xp + "%" : "0";
      shade.style.width = (isSell ? 100 - xp : xp) + "%";
      bar.style.display = tag.style.display = shade.style.display = "block";
    });
    wrap.addEventListener("mouseleave", () => {
      bar.style.display = tag.style.display = shade.style.display = "none";
    });
    wrap.addEventListener("click", (e) => setRangePrice(g.good, isSell ? "sell" : "buy", priceAt(xOf(e))));
    return wrap;
  }
  return h("div", { class: "pr-range" },
    h("div", { class: "pr-lane-title buy" }, "Comprar — pagas (busca a la izquierda) ←"),
    lane(false),
    h("div", { class: "pr-lane-title sell" }, "Vender — te pagan (busca a la derecha) →"),
    lane(true));
}

function openPrices() {
  let mode = "table";   // "table" | "live" | "range" | "edit"
  let liveData = null;  // cached live response
  let liveGood = 0;     // selected good index in the live view
  let liveTimer = null; // setInterval handle for auto-refresh
  let chartHover = false; // mouse over the chart -> pause refresh so the cursor lives

  const diffSel = h("select", null,
    h("option", { value: "0" }, "Easy"),
    h("option", { value: "1" }, "Normal"),
    h("option", { value: "2" }, "Hard"));
  diffSel.value = String(state.difficulty);   // restore the remembered difficulty
  const tabTable = h("button", { class: "active" }, "Universal");
  const tabLive = h("button", null, "By town (live)");
  const tabRange = h("button", null, "Range (live)");
  const tabEdit = h("button", null, "✏️ Mis precios");
  const goodSel = h("select", { class: "pr-goodsel" });
  const goodWrap = h("label", { class: "hint", style: "display:none" }, "Good: ", goodSel);
  const diffWrap = h("label", { class: "hint", style: "display:none" }, "Difficulty: ", diffSel);
  const btnRefresh = h("button", { class: "pr-refresh", style: "display:none" }, "↻ Refrescar");
  const autoChk = h("input", { type: "checkbox", checked: true });
  const autoWrap = h("label", { class: "hint", style: "display:none" },
    autoChk, " Auto (1s)");
  const note = h("p", { class: "prices-summary" });
  const body = h("div", { class: "prices-body" });
  // Pause the 1 s auto-refresh while the pointer is over the chart, so a re-render
  // doesn't wipe the interactive cursor the user is reading/aiming with.
  body.addEventListener("mouseenter", () => { chartHover = true; });
  body.addEventListener("mouseleave", () => { chartHover = false; });

  const node = h("div", { class: "modal prices-modal" },
    h("h2", null, "💰 Trade prices"),
    h("div", { class: "modal-tabs" }, tabTable, tabLive, tabRange, tabEdit),
    h("div", { class: "prices-controls" }, diffWrap, goodWrap, btnRefresh, autoWrap),
    note, body);
  // Warn before discarding unsaved price edits when closing by click-outside.
  modal(node, async () => {
    if (pricingsDirty &&
        !(await confirmDialog("Hay cambios sin guardar en los precios. ¿Cerrar igualmente?")))
      return false;
    pricingsHost = null;
    return true;
  });

  function stopAuto() { if (liveTimer) { clearInterval(liveTimer); liveTimer = null; } }
  function startAuto() {
    stopAuto();
    if (!autoChk.checked) return;
    liveTimer = setInterval(() => {
      if (!document.body.contains(node)) { stopAuto(); return; }  // modal was closed
      if (autoChk.checked && (mode === "live" || mode === "range")
          && !(mode === "range" && chartHover)) refreshLive(true);
    }, 1000);
  }

  async function showTable() {
    stopAuto();                         // auto-refresh is only for the live tab
    pricingsHost = null;
    goodWrap.style.display = "none";
    diffWrap.style.display = "";        // the live "Sell 1wk" column depends on it
    btnRefresh.style.display = "none";
    autoWrap.style.display = "none";
    body.replaceChildren(h("p", { class: "hint" }, "Computing…"));
    let data, live;
    try { data = await api("/api/prices/table", { difficulty: Number(diffSel.value) }); }
    catch (e) { data = { ok: false, error: "Unexpected error: " + e }; }
    try { live = await api("/api/prices/live", { difficulty: Number(diffSel.value) }); }
    catch (e) { live = null; }
    const liveMap = (live && live.ok)
      ? Object.fromEntries(live.goods.map((g) => [g.good, g])) : null;
    note.textContent = "Oro por carga (barril/bulto), de barato a caro. Valor/barril es la densidad de "
      + "valor (precio base ÷ volumen; un fardo = 10 barriles), para comparar qué rinde más por espacio. "
      + "Floor · Base · Ceiling son los anclajes fijos de la escala (× base). Las 6 columnas a-N-semanas "
      + "llevan doble valor: arriba el teórico, abajo el real de tu partida "
      + (liveMap ? "(mediana de las ciudades en vivo)." : "(abre el juego para ver el valor en vivo).")
      + " * = material de construcción: ahí teoría y realidad divergen.";
    body.replaceChildren(data && data.ok ? buildUniversalTable(data, liveMap) : priceError(data));
  }

  function renderLive() {
    if (!liveData || !liveData.ok) return;
    liveGood = Number(goodSel.value);
    const g = liveData.goods[liveGood];
    const d = liveData.date;
    note.textContent = `${g.name} — floor ${g.floor} · base ${g.base} · ceiling ${g.ceiling} `
      + `gold/load · ${d.day} ${MONTHS[d.month]} ${d.year}. Scarce → glut: sell up top, buy at the bottom.`;
    goodWrap.style.display = "";
    body.replaceChildren(buildTownTable(g));
  }

  // Same data as renderLive, drawn as the two-axis range chart instead of a table.
  function renderRange() {
    if (!liveData || !liveData.ok) return;
    liveGood = Number(goodSel.value);
    const g = liveData.goods[liveGood];
    // The chart labels everything itself, so the text summary is hidden here to
    // give the dot band more vertical room.
    note.textContent = "";
    note.style.display = "none";
    goodWrap.style.display = "";
    body.replaceChildren(buildRangeChart(g));
  }

  // ``silent`` (auto-refresh tick): re-read without the "Reading…" flicker, keep
  // the selected good, and on failure keep showing the last good data.
  async function refreshLive(silent) {
    if (!silent) body.replaceChildren(h("p", { class: "hint" }, "Reading the game…"));
    let d;
    try { d = await api("/api/prices/live", { difficulty: Number(diffSel.value) }); }
    catch (e) { d = { ok: false, error: "Unexpected error: " + e }; }
    liveData = d;
    if (d && d.ok) {
      if (goodSel.options.length !== d.goods.length) {
        // Show goods in the user's sorting order, but keep each option's value as
        // its index into d.goods so renderLive()'s `liveData.goods[value]` still hits.
        const ordered = byGoodsOrder(d.goods.map((g, i) => ({ g, i })), (x) => x.g.good);
        goodSel.replaceChildren(...ordered.map(({ g, i }) => h("option", { value: String(i) }, g.name)));
        goodSel.value = String(Math.min(liveGood, d.goods.length - 1));
      }
      (mode === "range" ? renderRange : renderLive)();
    } else if (!silent) {
      note.textContent = "";
      body.replaceChildren(priceError(d));
    }
  }

  async function loadLive() {
    pricingsHost = null;
    diffWrap.style.display = "";
    goodWrap.style.display = "none";
    btnRefresh.style.display = "";
    autoWrap.style.display = "";
    await refreshLive(false);
    startAuto();
  }

  // "Mis precios" — the pricing-preset editor, moved into this modal. It reuses
  // renderPricingsTab() by handing it `body` as its paint host (see pricingsHost).
  function showEdit() {
    stopAuto();
    diffWrap.style.display = "none";
    goodWrap.style.display = "none";
    btnRefresh.style.display = "none";
    autoWrap.style.display = "none";
    note.textContent = "Fija tu compra/venta por bien. Crea varias plantillas; "
      + "la marcada con ★ es la que usa «Apply pricing» en las rutas.";
    pricingsHost = body;
    renderPricingsTab();
  }

  function setMode(m) {
    mode = m;
    note.style.display = "";   // renderRange hides it; restore for the other tabs
    tabTable.classList.toggle("active", m === "table");
    tabLive.classList.toggle("active", m === "live");
    tabRange.classList.toggle("active", m === "range");
    tabEdit.classList.toggle("active", m === "edit");
    if (m === "table") showTable();
    else if (m === "live" || m === "range") loadLive();
    else if (m === "edit") showEdit();
  }
  tabTable.addEventListener("click", () => setMode("table"));
  tabLive.addEventListener("click", () => setMode("live"));
  tabRange.addEventListener("click", () => setMode("range"));
  tabEdit.addEventListener("click", () => setMode("edit"));
  btnRefresh.addEventListener("click", loadLive);
  autoChk.addEventListener("change", () => {
    if (autoChk.checked && (mode === "live" || mode === "range")) startAuto(); else stopAuto();
  });
  goodSel.addEventListener("change", () => (mode === "range" ? renderRange : renderLive)());
  diffSel.addEventListener("change", () => {
    state.difficulty = Number(diffSel.value);
    api("/api/settings/set", { difficulty: state.difficulty });  // remember it
    setMode(mode);
  });
  setMode("table");
}

// --------------------------------------------------------------------------
// Ships — live view of the player's ships and convoys
// --------------------------------------------------------------------------
// Reads the running game (Api.ships_live) and shows, per ship, its hold, the
// goods aboard with their average purchase price, and where it is heading.
// Auto-refreshing once a second turns the snapshot into a live view: each cargo
// line flashes green when it grows (a buy) and orange when it shrinks (a sell),
// so you can watch a ship fill and empty as the game runs at high speed.
// Days-until-arrival as a short label: hours under a day, whole days otherwise.
function fmtEta(d) {
  if (d == null) return null;
  if (d < 1) { const hrs = Math.max(1, Math.round(d * 24)); return "~" + hrs + " h"; }
  const days = Math.round(d);
  return "~" + days + (days === 1 ? " día" : " días");
}

function shipsError(data) {
  const msg = (data && data.error) || "Couldn't read the game.";
  return h("div", { class: "prices-msg" },
    h("p", { class: "error" }, msg),
    h("p", { class: "hint" },
      "This view reads the running Patrician III — open the game with a "
      + "savegame loaded, then press ↻ Refrescar."));
}

function openShips() {
  let liveTimer = null;
  // ship name -> Map(good -> loads) from the previous tick, to diff against.
  let prev = new Map();

  const autoChk = h("input", { type: "checkbox", checked: true });
  const autoWrap = h("label", { class: "hint" }, autoChk, " Auto (1s)");
  const btnRefresh = h("button", { class: "pr-refresh" }, "↻ Refrescar");
  const note = h("p", { class: "prices-summary" });
  const body = h("div", { class: "prices-body ships-body" });

  const node = h("div", { class: "modal prices-modal ships-modal" },
    h("h2", null, "🚢 Ships & convoys"),
    h("div", { class: "prices-controls" }, btnRefresh, autoWrap),
    note, body);
  modal(node);

  function stopAuto() { if (liveTimer) { clearInterval(liveTimer); liveTimer = null; } }
  function startAuto() {
    stopAuto();
    if (!autoChk.checked) return;
    liveTimer = setInterval(() => {
      if (!document.body.contains(node)) { stopAuto(); return; }  // modal closed
      if (autoChk.checked) refresh(true);
    }, 1000);
  }

  function shipCard(s, next) {
    // Location: docked at a town, or at sea heading to its destination. Only
    // show the "→ dest" when it adds information (not when already docked there).
    const showDest = s.dest && s.destIndex !== s.townIndex;
    const eta = fmtEta(s.etaDays);
    const loc = h("span", { class: "ship-loc" },
      s.atSea ? "🌊 En el mar" : (s.town ? "⚓ En " + s.town : "—"),
      showDest ? h("span", { class: "ship-dest" }, " → " + s.dest) : null,
      eta ? h("span", { class: "ship-eta", title: "Días que faltan para llegar al destino" }, " · ⏳ " + eta) : null);

    const bar = h("div", { class: "hold-bar", title: `${s.holdPct}% llena` },
      h("div", { class: "hold-fill", style: "width:" + s.holdPct + "%" }));
    const holdLabel = h("div", { class: "hold-label" },
      `Bodega ${s.holdUsed}/${s.holdTotal}`,
      h("span", { class: "hold-free" }, ` · ${s.holdFree} libre`));

    // Diff this ship's cargo against the previous tick to flag buys/sells.
    const before = prev.get(s.name);
    const cargoMap = new Map();
    s.cargo.forEach((c) => cargoMap.set(c.good, c.loads));
    next.set(s.name, cargoMap);

    const rows = [];
    if (s.cargo.length) {
      s.cargo.forEach((c) => {
        const old = before ? before.get(c.good) : undefined;
        const delta = old != null ? Math.round((c.loads - old) * 10) / 10 : 0;
        const dir = delta > 0 ? "buy" : delta < 0 ? "sell" : "";
        rows.push(h("tr", { class: dir ? "cargo-change " + dir : "" },
          h("td", { class: "cargo-good" }, goodIcon(c.good), META.goods.names[c.good]),
          h("td", { class: "cargo-loads" }, String(c.loads),
            dir ? h("span", { class: "cargo-delta " + dir },
              (delta > 0 ? " ▲+" + delta : " ▼" + Math.abs(delta))) : null),
          h("td", { class: "cargo-price" }, c.avgPrice == null ? "—" : String(c.avgPrice)),
          h("td", { class: "cargo-value" }, c.value == null ? "—" : c.value.toLocaleString())));
      });
    }
    // Goods that were aboard last tick but are gone now → just sold off.
    if (before) {
      before.forEach((oldLoads, g) => {
        if (cargoMap.has(g)) return;
        rows.push(h("tr", { class: "cargo-change sell" },
          h("td", { class: "cargo-good" }, goodIcon(g), META.goods.names[g]),
          h("td", { class: "cargo-loads" }, "0",
            h("span", { class: "cargo-delta sell" }, " ▼" + oldLoads)),
          h("td", { class: "cargo-price" }, "—"),
          h("td", { class: "cargo-value" }, "—")));
      });
    }
    if (!rows.length) rows.push(h("tr", null, h("td", { class: "cargo-empty", colspan: 4 }, "Bodega vacía")));

    const table = h("table", { class: "cargo-table" },
      h("thead", null, h("tr", null,
        h("th", null, "Mercancía"), h("th", null, "Cargas"),
        h("th", null, "Precio medio"), h("th", null, "Valor"))),
      h("tbody", null, rows));

    return h("div", { class: "ship-card" },
      h("div", { class: "ship-head" },
        h("strong", { class: "ship-name" }, s.name),
        h("span", { class: "ship-type" }, s.type),
        s.health != null ? h("span", { class: "ship-health" + (s.health < 50 ? " low" : "") },
          "🛠 " + s.health + "%") : null,
        loc),
      h("div", { class: "hold-row" }, bar, holdLabel),
      table,
      s.cargoValue ? h("div", { class: "ship-foot", title: "Oro total que pagaste por todo lo que lleva a bordo (lo que el juego calcula)" },
        "💰 Capital a bordo: ", h("strong", null, s.cargoValue.toLocaleString())) : null);
  }

  function renderShips(data) {
    const d = data.date;
    const ships = data.ships;
    note.textContent = (ships.length
      ? `${ships.length} barco(s)`
      : "Sin barcos") + ` · ${d.day} ${MONTHS[d.month]} ${d.year}`;

    const next = new Map();
    if (!ships.length) {
      body.replaceChildren(h("p", { class: "hint" }, "Este mercader no tiene barcos."));
      prev = next; return;
    }

    // Loose ships first, then one block per convoy.
    const loose = [];
    const convoys = new Map();
    ships.forEach((s) => {
      if (s.convoyId == null) loose.push(s);
      else { if (!convoys.has(s.convoyId)) convoys.set(s.convoyId, []); convoys.get(s.convoyId).push(s); }
    });
    const cards = loose.map((s) => shipCard(s, next));
    convoys.forEach((group, id) => {
      cards.push(h("div", { class: "convoy-group" },
        h("div", { class: "convoy-head" }, `⚓ Convoy #${id} — ${group.length} barco(s)`),
        ...group.map((s) => shipCard(s, next))));
    });
    body.replaceChildren(...cards);
    prev = next;
  }

  // ``silent`` (auto-refresh tick): re-read without the "Reading…" flicker and
  // keep showing the last good data on a transient failure.
  async function refresh(silent) {
    if (!silent) body.replaceChildren(h("p", { class: "hint" }, "Reading the game…"));
    let d;
    try { d = await api("/api/ships/live"); }
    catch (e) { d = { ok: false, error: "Unexpected error: " + e }; }
    if (d && d.ok) renderShips(d);
    else if (!silent) { note.textContent = ""; body.replaceChildren(shipsError(d)); }
  }

  btnRefresh.addEventListener("click", () => refresh(false));
  autoChk.addEventListener("change", () => { if (autoChk.checked) startAuto(); else stopAuto(); });
  refresh(false).then(startAuto);
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
      h("button", { class: "icon danger", title: "Delete", onclick: () => deleteSorting(s.id) }, "🗑")))),
    h("div", { class: "preset-io" },
      h("button", { title: "Import sortings from a .json file", onclick: importSortingsFile }, "Import…"),
      h("button", { title: "Export every sorting to a .json file",
        onclick: () => exportPresets("sortings", null, "sortings.json") }, "Export all")));

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
        h("button", { title: "Export this sorting to a .json file",
          onclick: () => exportPresets("sortings", [preset.id], `sorting-${safeFilename(preset.id)}.json`) }, "Export"),
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
async function importSortingsFile() {
  const r = await importPresets("sortings");
  if (!r) return;
  await reloadSortings();
  if (r.imported.length) selectedSorting = r.imported[r.imported.length - 1];
  renderSortingsTab();
}

// --------------------------------------------------------------------------
// Preset import / export (shared by the pricings and sortings tabs)
// --------------------------------------------------------------------------
// Filesystem-safe filename from a free-text preset id.
function safeFilename(s) { return String(s).replace(/[^\w.-]+/g, "_") || "preset"; }

// Web-mode fallback: hand the browser a file to save (desktop uses a native
// Save dialog in the backend instead).
function downloadText(filename, text) {
  const blob = new Blob([text], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = h("a", { href: url, download: filename });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// Open the OS file picker and resolve with the chosen file's text (or null if
// the dialog is dismissed without a selection). Works in both desktop and web.
function pickTextFile(accept = ".json,application/json") {
  return new Promise((resolve) => {
    const input = h("input", { type: "file", accept, style: "display:none" });
    input.addEventListener("change", () => {
      const file = input.files && input.files[0];
      if (!file) { input.remove(); return resolve(null); }
      const reader = new FileReader();
      reader.onload = () => { input.remove(); resolve(String(reader.result)); };
      reader.onerror = () => { input.remove(); resolve(null); };
      reader.readAsText(file);
    });
    document.body.append(input);
    input.click();
  });
}

// kind: "pricings" | "sortings". ids: array to export a subset, or null for all.
async function exportPresets(kind, ids, filename) {
  const r = await api(`/api/${kind}/export`, { ids: ids || null, filename });
  if (!r || !r.ok) {
    if (r && r.error && r.error !== "cancelled") setStatus("Export failed: " + r.error);
    return;
  }
  if (r.data != null) downloadText(r.filename || filename, r.data); // web mode
  setStatus(r.path ? `Exported ${r.count} → ${r.path}` : `Exported ${r.count} ${kind}`);
}

// Reads a file via the OS picker and merges it; returns the backend result
// (or undefined if cancelled / failed) so callers can reload and re-select.
async function importPresets(kind) {
  const text = await pickTextFile();
  if (text == null) return;
  const r = await api(`/api/${kind}/import`, { data: text });
  if (!r || !r.ok) { setStatus("Import failed: " + ((r && r.error) || "unknown")); return; }
  setStatus(`Imported ${r.imported.length} ${kind}` +
    (r.skipped.length ? `, skipped ${r.skipped.length} duplicate(s)` : ""));
  return r;
}

// --------------------------------------------------------------------------
// Pricings tab (pricing presets)
// --------------------------------------------------------------------------
let selectedPricing = null;
// The pricing editor now lives inside the Prices modal ("Mis precios" sub-tab),
// so it paints into a host element the modal hands it (null when not editing),
// and tracks unsaved edits so closing the modal can warn about losing them.
let pricingsHost = null;
let pricingsDirty = false;

async function reloadPricings() { state.pricings = await api("/api/pricings"); }

// A price number-input flanked by quick step buttons (−10 −5 −1 … +1 +5 +10).
// `commit(v)` receives the clamped value on every edit, typed or stepped.
function priceStepper(value, commit) {
  const inp = h("input", { type: "number", min: 0, max: 9999, value });
  const cur = () => parseInt(inp.value || "0", 10);
  const set = (v) => {
    v = Math.max(0, Math.min(9999, v));
    inp.value = v; commit(v);
  };
  inp.addEventListener("change", () => set(cur()));
  const step = (d) => h("button", { type: "button", class: "step",
    title: (d > 0 ? "Add " : "Subtract ") + Math.abs(d),
    onclick: () => set(cur() + d) }, (d > 0 ? "+" : "−") + Math.abs(d));
  return h("div", { class: "price-stepper" },
    step(-10), step(-5), step(-1), inp, step(1), step(5), step(10));
}

function renderPricingsTab() {
  const root = pricingsHost;          // set by the Prices modal's "Mis precios" tab
  if (!root) return;                  // editor is closed — nothing to paint into
  if (!state.pricings.length) reloadPricings().then(() => renderPricingsTab());
  if (selectedPricing && !state.pricings.find((p) => p.id === selectedPricing)) selectedPricing = null;
  if (!selectedPricing && state.pricings[0]) selectedPricing = state.pricings[0].id;
  const preset = state.pricings.find((p) => p.id === selectedPricing);

  // Preset picker + actions as a top bar — so this sub-tab reads like the others
  // (controls on top, full-width table below) instead of a sidebar layout.
  const sel = h("select", { class: "pp-preset" },
    state.pricings.map((p) => h("option", { value: p.id }, p.id + (p.is_default ? " ★" : ""))));
  sel.value = selectedPricing || "";
  sel.addEventListener("change", () => { selectedPricing = sel.value; renderPricingsTab(); });

  const editbar = h("div", { class: "prices-editbar" },
    h("label", { class: "hint" }, "Plantilla: ", sel),
    h("button", { onclick: createPricing, title: "Nueva plantilla" }, "+ New"),
    h("button", { class: "icon", title: "Renombrar", onclick: () => preset && renamePricing(preset.id) }, "✎"),
    h("button", { class: "icon danger", title: "Borrar", onclick: () => preset && deletePricing(preset.id) }, "🗑"),
    h("button", { class: "icon", title: "Marcar como predeterminada (★ — la que usa «Apply pricing»)",
      onclick: () => preset && setDefaultPricing(preset.id) }, "★"),
    preset && preset.is_default ? h("span", { class: "badge" }, "def") : "",
    h("div", { class: "spacer" }),
    h("button", { title: "Importar plantillas desde un .json", onclick: importPricingsFile }, "Import…"),
    h("button", { title: "Exportar esta plantilla a un .json",
      onclick: () => preset && exportPresets("pricings", [preset.id], `pricing-${safeFilename(preset.id)}.json`) }, "Export"),
    h("button", { title: "Exportar todas las plantillas a un .json",
      onclick: () => exportPresets("pricings", null, "pricings.json") }, "Export all"),
    h("button", { class: "primary", title: "Guardar cambios",
      onclick: () => preset && savePricing(preset) }, "Guardar"));

  let grid;
  if (preset) {
    const def = META.defaultPricing;
    const order = goodsOrder();
    const rows = [];
    for (const g of order) {
      if (!META.goods.visibility[g] && !state.showWeapons) continue;
      const b = priceStepper(preset.buying[g], (v) => { preset.buying[g] = v; pricingsDirty = true; });
      const s = priceStepper(preset.selling[g], (v) => { preset.selling[g] = v; pricingsDirty = true; });
      const defBuy = def.buying[g], defSell = def.selling[g];
      const cBuy = h("td", { class: "default-price" + (preset.buying[g] !== defBuy ? " diff" : ""),
        title: "Default buy price" }, defBuy);
      const cSell = h("td", { class: "default-price" + (preset.selling[g] !== defSell ? " diff" : ""),
        title: "Default sell price" }, defSell);
      rows.push(h("tr", null, h("td", { class: "good-name" }, goodLabel(g)),
        h("td", null, b), h("td", null, s), cBuy, cSell));
    }
    grid = h("table", { class: "pricing-grid" },
      h("thead", null, h("tr", null, h("th", null, "Good"),
        h("th", { class: "price-col" }, "Buy"), h("th", { class: "price-col" }, "Sell"),
        h("th", { class: "default-price" }, "Def. Buy"),
        h("th", { class: "default-price" }, "Def. Sell"))),
      h("tbody", null, rows));
  } else {
    grid = h("p", { class: "hint" }, "Crea una plantilla para empezar.");
  }

  root.replaceChildren(editbar, grid);
}

async function createPricing() {
  const id = await promptDialog("Name of the pricing preset", "");
  if (!id) return;
  await api("/api/pricings/save", { pricing: { id, is_default: false } });
  await reloadPricings(); selectedPricing = id; renderPricingsTab();
}
async function savePricing(preset) {
  await api("/api/pricings/save", { pricing: preset });
  await reloadPricings(); pricingsDirty = false; setStatus(`Pricing "${preset.id}" saved`);
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
async function importPricingsFile() {
  const r = await importPresets("pricings");
  if (!r) return;
  await reloadPricings();
  if (r.imported.length) selectedPricing = r.imported[r.imported.length - 1];
  renderPricingsTab();
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
  $("#trade-good-btn").addEventListener("click", openTradeGood);
  $("#apply-pricing-btn").addEventListener("click", applyRoutePricing);
  $("#templates-btn").addEventListener("click", openTemplates);
  $("#prices-btn").addEventListener("click", openPrices);
  $("#ships-btn").addEventListener("click", openShips);
  setStatus("Ready. Open your game's Save\\AutoRoute folder.");

  // Remember the last opened folder and reopen it automatically.
  const cfg = await api("/api/settings");
  if (cfg && cfg.difficulty != null) state.difficulty = Number(cfg.difficulty);
  if (cfg && cfg.last_folder) {
    $("#folder-path").value = cfg.last_folder;
    await openFolder();
  }
}

init();
