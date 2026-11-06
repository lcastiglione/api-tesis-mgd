"use strict";
const byId = (id) => document.getElementById(id);
const titles = {pending:"Preparando la base",downloading:"Descargando la base",extracting:"Descomprimiendo",verifying:"Verificando integridad",ready:"Base lista para consultar",error:"Descarga pendiente"};
const databaseLabels = {pending:"Preparando",downloading:"Descargando",extracting:"Extrayendo",verifying:"Verificando",ready:"Lista",error:"Pendiente"};
const number = (value, digits = 0) => new Intl.NumberFormat("es-AR",{maximumFractionDigits:digits}).format(value);
function bytes(value) {
  if (value >= 1024 ** 3) return number(value / 1024 ** 3,2) + "GiB";
  if (value >= 1024 ** 2) return number(value / 1024 ** 2,1) + "MiB";
  return number(value / 1024,0) + "KiB";
}
function fitScreen() {
  const screen = byId("screen");
  const panel = byId("dashboard");
  const style = getComputedStyle(screen);
  const availableHeight = screen.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom);
  const availableWidth = screen.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
  const scale = Math.min(1,availableHeight / panel.offsetHeight,availableWidth / panel.offsetWidth);
  panel.style.setProperty("--fit",String(scale));
}
new ResizeObserver(fitScreen).observe(byId("dashboard"));
window.addEventListener("resize",fitScreen);
window.visualViewport?.addEventListener("resize",fitScreen);
function metric(name, text, level) {
  byId(name + "-label").textContent = text;
  byId(name + "-metric").className = "metric " + level;
}
function enableData(enabled) {
  document.querySelectorAll("[data-requires-database]").forEach((link) => {
    link.setAttribute("aria-disabled",String(!enabled));
    link.tabIndex = enabled ? 0 : -1;
    link.title = enabled ? "" : "Disponible al terminar la preparación de la base";
  });
}
document.querySelectorAll("[data-requires-database]").forEach((link) => link.addEventListener("click",(event) => {
  if (link.getAttribute("aria-disabled") === "true") event.preventDefault();
}));
function render(state, health) {
  const phase = state.phase;
  const operational = state.ready && health?.ok && health.body?.status === "ok";
  metric("server","En línea","good");
  metric("health",operational ? "Operativa" : state.ready ? "Revisar" : "En espera",operational ? "good" : state.ready || phase === "error" ? "warning" : "wait");
  metric("database",databaseLabels[phase] || "Preparando",state.ready ? "good" : phase === "error" ? "warning" : "wait");
  byId("version").textContent = "v" + state.api_version;
  byId("state-title").textContent = titles[phase] || titles.pending;
  const received = state.download.received_bytes;
  const total = state.download.total_bytes;
  const percent = state.ready ? 100 : state.download.percent;
  const measurable = state.ready || received > 0;
  const ring = byId("ring");
  byId("ring-fill").style.strokeDashoffset = String(314.1593 * (1 - (measurable ? percent : 0) / 100));
  if (measurable) ring.setAttribute("aria-valuenow",String(percent));
  else ring.removeAttribute("aria-valuenow");
  byId("percent").textContent = state.ready ? "100%" : phase === "downloading" ? number(percent || 0,1) + "%" : "—";
  ring.setAttribute("aria-valuetext",phase === "downloading" ? "Descarga: " + number(percent || 0,1) + "%" : titles[phase] || titles.pending);
  byId("transfer").className = "transfer " + (state.ready ? "ready" : phase === "error" ? "warning" : "");
  byId("bytes").textContent = phase === "downloading" ? bytes(received) + " / " + bytes(total) : state.ready ? bytes(state.database.bytes) + " · SQLite v" + state.database.version + " r" + state.database.storage_revision : phase === "verifying" ? "Tamaño · SHA-256 · SQLite" : "data/study.sqlite";
  const step = state.ready ? 3 : ["verifying","extracting"].includes(phase) ? 2 : phase === "downloading" ? 1 : 0;
  ["download","verify","ready"].forEach((name,index) => {
    byId("step-" + name).className = state.ready || index + 1 < step ? "done" : index + 1 === step ? "active" : "";
  });
  byId("status-note").textContent = phase === "error" ? "Reintento automático en " + state.retry_in_seconds + " segundos" : state.ready && !operational ? "La consulta de salud no respondió correctamente" : "";
  enableData(operational);
  fitScreen();
}
async function read(path) {
  const response = await fetch(path,{cache:"no-store",signal:AbortSignal.timeout(5000)});
  return {ok:response.ok,body:await response.json()};
}
async function refresh() {
  try {
    const [state,health] = await Promise.allSettled([read("/status"),read("/health")]);
    if (state.status !== "fulfilled" || !state.value.ok) throw new Error("Sin conexión");
    render(state.value.body,health.status === "fulfilled" ? health.value : null);
  } catch (_) {
    metric("server","Sin conexión","warning");
    metric("health","Sin señal","warning");
    metric("database","Sin señal","warning");
    byId("state-title").textContent = "Esperando al servidor";
    byId("bytes").textContent = "Reconexión automática";
    byId("percent").textContent = "—";
    byId("ring-fill").style.strokeDashoffset = "314.1593";
    byId("ring").removeAttribute("aria-valuenow");
    byId("ring").setAttribute("aria-valuetext","Sin conexión");
    byId("transfer").className = "transfer warning";
    byId("status-note").textContent = "";
    ["download","verify","ready"].forEach(name => {byId("step-" + name).className = "";});
    enableData(false);
    fitScreen();
  } finally {
    setTimeout(refresh,1500);
  }
}
enableData(false);
fitScreen();
refresh();
