"use strict";
const byId = (id) => document.getElementById(id);
const titles = {pending:"Preparando la base de datos",downloading:"Descargando la base de datos",extracting:"Descomprimiendo la base",verifying:"Verificando la base de datos",ready:"La API está lista para usar",error:"La base necesita atención"};
const labels = {pending:"Preparando",downloading:"Descarga en curso",extracting:"Descompresión",verifying:"Verificación en curso",ready:"Disponible",error:"Reintento pendiente"};
const formatNumber = (value, digits = 0) => new Intl.NumberFormat("es-AR", {maximumFractionDigits:digits}).format(value);
function formatBytes(value) {
  if (value >= 1024 ** 3) return formatNumber(value / 1024 ** 3, 2) + "GiB";
  if (value >= 1024 ** 2) return formatNumber(value / 1024 ** 2, 1) + "MiB";
  return formatNumber(value / 1024, 0) + "KiB";
}
function setDocsEnabled(enabled) {
  const link = byId("docs-link");
  link.setAttribute("aria-disabled", String(!enabled));
  link.tabIndex = enabled ? 0 : -1;
}
byId("docs-link").addEventListener("click", (event) => {
  if (event.currentTarget.getAttribute("aria-disabled") === "true") event.preventDefault();
});
function render(state) {
  const phase = state.phase;
  const ready = state.ready;
  byId("server-label").textContent = "Servidor en línea";
  byId("server-dot").className = "dot online";
  byId("status-card").className = "status-card " + (ready ? "ready" : phase === "error" ? "error" : "");
  byId("status-card").setAttribute("aria-busy", String(!ready));
  byId("state-title").textContent = titles[phase] || titles.pending;
  byId("state-badge").textContent = labels[phase] || labels.pending;
  byId("state-message").textContent = state.message;
  byId("state-icon").textContent = ready ? "✓" : phase === "error" ? "!" : ["verifying","extracting"].includes(phase) ? "◇" : "↓";
  byId("version").textContent = "API v" + state.api_version;
  const downloaded = state.download.received_bytes;
  const total = state.download.total_bytes;
  const percent = ready ? 100 : state.download.percent;
  const progress = byId("progress");
  if (ready || downloaded > 0) progress.value = percent;
  else progress.removeAttribute("value");
  byId("percent").textContent = ready ? "100%" : phase === "downloading" ? formatNumber(percent || 0, 1) + "%" : "—";
  byId("progress-label").textContent = ready ? "Base descargada y verificada" : phase === "downloading" ? "Avance de la descarga" : phase === "verifying" ? "Comprobación de integridad" : phase === "extracting" ? "Preparando la copia local" : "Preparación de la base";
  byId("bytes").textContent = ready ? formatBytes(state.database.bytes) + " · SQLite v" + state.database.version + " r" + state.database.storage_revision : phase === "downloading" ? formatBytes(downloaded) + " de " + formatBytes(total) : phase === "verifying" ? "Se comprueban tamaño, SHA-256 e integridad." : "La base se guarda en data/study.sqlite.";
  byId("transfer-note").textContent = phase === "error" ? "Reintento en " + state.retry_in_seconds + " segundos" : "Actualización automática";
  const step = ready ? 4 : ["verifying","extracting"].includes(phase) ? 3 : phase === "downloading" ? 2 : 1;
  ["connect","download","verify","ready"].forEach((name, index) => {
    byId("step-" + name).className = index + 1 < step || ready ? "done" : index + 1 === step ? "active" : "";
  });
  byId("notice-text").textContent = ready ? "La base se consulta en modo de solo lectura y se reutiliza en los próximos arranques. Ya se pueden explorar las consultas." : phase === "error" ? "La página volverá a intentarlo automáticamente. El detalle del problema se puede revisar con docker compose logs -f api." : phase === "verifying" ? "La descarga puede estar completa y la verificación seguir en curso. Las consultas se habilitan al finalizar la comprobación." : "La página permanece disponible durante la descarga. Las consultas se habilitan cuando la base está verificada.";
  byId("database-label").textContent = ready ? "Instalada y verificada" : phase === "downloading" ? "Descargando copia pública" : phase === "error" ? "Pendiente de preparación" : "Preparación en curso";
  byId("database-detail").textContent = ready ? "Disponible en data/study.sqlite, sin nuevas descargas." : "La copia se guarda en data/study.sqlite del proyecto.";
  setDocsEnabled(ready);
}
async function refresh() {
  try {
    const response = await fetch("/status", {cache:"no-store", signal:AbortSignal.timeout(5000)});
    if (!response.ok) throw new Error("Estado no disponible");
    render(await response.json());
  } catch (_) {
    byId("server-label").textContent = "Sin conexión con el servidor";
    byId("server-dot").className = "dot offline";
    byId("status-card").className = "status-card offline";
    byId("state-badge").textContent = "Conexión pendiente";
    byId("state-title").textContent = "Esperando al servidor";
    byId("state-message").textContent = "No se pudo actualizar el estado. La página volverá a intentar la conexión automáticamente.";
    byId("state-icon").textContent = "!";
    byId("notice-text").textContent = "Si el contenedor se está reiniciando, la conexión se recuperará cuando vuelva a estar disponible.";
    setDocsEnabled(false);
  } finally {
    setTimeout(refresh, 1000);
  }
}
refresh();
