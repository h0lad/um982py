const byId = (id) => document.getElementById(id);
const number = new Intl.NumberFormat("en", { maximumFractionDigits: 1 });
const REPORT_SECONDS = 15;
let report = null;
let receivedAt = 0;
let initialAge = 0;
let controller = null;
let pollTimer;
let toastTimer;
let unavailable = false;

function put(id, value) {
  byId(id).textContent = value;
}

function age(seconds) {
  if (seconds === null) return "Not received";
  if (seconds < 60) return `${number.format(seconds)} s`;
  if (seconds < 3600) return `${number.format(seconds / 60)} min`;
  return `${number.format(seconds / 3600)} h`;
}

function bitrate(bps) {
  if (bps >= 1000000) return `${number.format(bps / 1000000)} Mbit/s`;
  return `${number.format(bps / 1000)} kbit/s`;
}

function bytes(value) {
  if (value >= 1000000000) return `${number.format(value / 1000000000)} GB`;
  if (value >= 1000000) return `${number.format(value / 1000000)} MB`;
  return `${number.format(value / 1000)} kB`;
}

function elapsed() {
  return initialAge + (performance.now() - receivedAt) / 1000;
}

function currentAge(value) {
  return value === null ? null : value + elapsed();
}

function showState() {
  if (!report) return;
  const stale = unavailable || elapsed() > REPORT_SECONDS;
  const state = stale ? "unreachable" : report.state;
  const labels = {
    online: ["LIVE", "Corrections available", "Receiving the configured correction profile."],
    degraded: ["PARTIAL PROFILE", "Corrections available", "Some message types are missing or stale. Check your rover's requirements."],
    offline: ["UNAVAILABLE", "Correction source unavailable", "Current observations or reference coordinates are missing."],
    waiting: ["WAITING", "Waiting for the source", "Observations and reference coordinates are not ready yet."],
    unreachable: ["REPORT UNAVAILABLE", "Status could not be confirmed", "This report is out of date. Check reception with your NTRIP client."],
  };
  const [label, headline, detail] = labels[state] || labels.unreachable;
  document.body.dataset.state = state;
  put("state-label", label);
  put("headline", headline);
  put("state-detail", detail);
  put("report-age", `${age(elapsed())} ago`);
  put("observation-age", age(currentAge(report.service.observation_age_seconds)));
  put("coordinate-age", age(currentAge(report.service.coordinate_age_seconds)));
  byId("notice").hidden = !stale;
  put("notice", stale ? "Values are historical until a fresh report arrives." : "");
}

function renderMessages(messages) {
  const rows = messages.map((message) => {
    const row = document.createElement("tr");
    const name = document.createElement("td");
    const identifier = document.createElement("strong");
    identifier.textContent = String(message.type);
    const description = document.createElement("small");
    description.textContent = message.name;
    name.append(identifier, description);
    row.append(name);
    const counts = message.satellites === null
      ? "—" : `${message.satellites} / ${message.signals}`;
    for (const value of [`${message.interval_seconds} s`, age(message.age_seconds), counts]) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    }
    const status = document.createElement("td");
    const label = document.createElement("span");
    label.className = "message-state";
    if (message.fresh) {
      label.textContent = "Receiving";
    } else if (message.age_seconds === null) {
      label.classList.add("waiting");
      label.textContent = "Not received";
    } else {
      label.classList.add("stale");
      label.textContent = "Stale";
    }
    status.append(label);
    row.append(status);
    return row;
  });
  byId("messages").replaceChildren(...rows);
}

function renderAvailability(availability) {
  put("availability-value", availability.ready_percent === null
    ? "—" : `${number.format(availability.ready_percent)}%`);
  put("availability-note", `Based on ${number.format(availability.sample_count)} samples, excluding unobserved time. History resets on restart.`);
  const blocks = availability.buckets.map((ready) => {
    const block = document.createElement("span");
    block.className = ready === null ? "unknown" : ready ? "up" : "down";
    block.title = ready === null ? "No sample"
      : ready ? "Ready at every sample" : "Unavailable at one or more samples";
    return block;
  });
  byId("timeline").replaceChildren(...blocks);
  byId("timeline").setAttribute("aria-label",
    `Readiness: ${availability.ready_percent ?? "unknown"} percent across ${availability.sample_count} samples. Grey intervals are unobserved.`);
}

function renderStation(station) {
  document.title = `${station.mountpoint} · Reference station status`;
  put("station-name", station.mountpoint);
  put("location", `${station.country} · ${station.latitude.toFixed(5)}°, ${station.longitude.toFixed(5)}°`);
  put("coordinates", `${station.latitude.toFixed(5)}°, ${station.longitude.toFixed(5)}°`);
  put("height", `${station.height_m.toFixed(1)} m · ARP`);
  put("reference-frame", station.reference_frame);
  put("coordinate-epoch", String(station.coordinate_epoch));
  put("station-id", String(station.station_id));
  put("position-review", station.position_reviewed ? "OPERATOR REVIEWED" : "NOT REVIEWED");
}

function renderService(service, messages) {
  put("source-rate", bitrate(service.source_bps));
  put("output-rate", bitrate(service.output_bps));
  put("stream-count", number.format(service.streams));
  put("capacity", `${service.max_connections} connections max`);
  const observed = messages.filter((message) => message.type !== 1005 && message.satellites !== null);
  put("satellite-count", observed.length
    ? number.format(observed.reduce((total, message) => total + message.satellites, 0)) : "—");
  put("uptime", age(service.uptime_seconds));
  put("source-kind", service.source === "relay" ? "TLS relay" : "Serial receiver");
  put("frames", number.format(service.frames));
  put("sent-bytes", bytes(service.sent_bytes));
  put("source-failures", number.format(service.source_failures));
  put("slow-clients", number.format(service.slow_clients));
  put("rejections", number.format(service.admission_rejections));
  put("connections", `${service.connections} / ${service.max_connections}`);
  put("limits", `The limit is ${service.per_ip_limit} connections per IP and ${service.per_user_limit} streams per account. Shared networks use the same IP budget.`);
}

function renderConnection(connection, mountpoint) {
  put("host", connection.host);
  put("port", String(connection.port));
  put("mountpoint", mountpoint);
  put("transport", connection.tls ? "TLS required" : "Loopback HTTP");
  put("access", connection.public ? "Guest access" : "Account required");
  put("access-help", connection.public
    ? "Leave username and password empty. Invalid credentials are rejected."
    : "Obtain NTRIP credentials from the station operator.");
  byId("contact").hidden = !connection.contact_url;
  if (connection.contact_url) byId("contact").href = connection.contact_url;
  put("command", `curl --no-buffer${connection.public ? "" : " --user YOUR_USER"} \\\n  -H 'Ntrip-Version: Ntrip/2.0' \\\n  '${connection.url}' \\\n  --output corrections.rtcm`);
}

async function refresh() {
  clearTimeout(pollTimer);
  if (controller || document.hidden) return;
  controller = new AbortController();
  const started = performance.now();
  const timeout = setTimeout(() => controller?.abort(), 4000);
  byId("refresh").disabled = true;
  try {
    const response = await fetch("/status.json", {
      signal: controller.signal, credentials: "omit",
    });
    if (!response.ok) throw new Error("Status response unavailable");
    const data = await response.json();
    if (data.schema_version !== 1 || !["online", "degraded", "offline", "waiting"].includes(data.state)) {
      throw new Error("Unsupported telemetry report");
    }
    const responseDate = Date.parse(response.headers.get("Date"));
    const generated = Date.parse(data.generated_at);
    const sharedAge = Number(response.headers.get("Age") || "0");
    if (!Number.isFinite(responseDate) || !Number.isFinite(generated) || !Number.isFinite(sharedAge)) {
      throw new Error("Missing freshness metadata");
    }
    renderStation(data.station);
    renderService(data.service, data.messages);
    renderMessages(data.messages);
    renderAvailability(data.availability);
    renderConnection(data.connection, data.station.mountpoint);
    put("report-time", `${new Date(data.generated_at).toLocaleTimeString("en-GB", { timeZone: "UTC" })} UTC`);
    receivedAt = performance.now();
    initialAge = Math.max(0, (responseDate - generated) / 1000)
      + Math.max(0, sharedAge) + (receivedAt - started) / 1000;
    report = data;
    unavailable = false;
    showState();
  } catch {
    if (!document.hidden) {
      unavailable = true;
      if (report) {
        showState();
      } else {
        document.body.dataset.state = "unreachable";
        put("state-label", "REPORT UNAVAILABLE");
        put("headline", "Status could not be confirmed");
        put("state-detail", "No current report is reachable. Try again shortly.");
      }
    }
  } finally {
    clearTimeout(timeout);
    controller = null;
    byId("refresh").disabled = false;
    if (!document.hidden) pollTimer = setTimeout(refresh, 10000 + Math.random() * 2000);
  }
}

byId("refresh").addEventListener("click", refresh);
document.addEventListener("visibilitychange", () => {
  clearTimeout(pollTimer);
  if (document.hidden) {
    controller?.abort();
  } else {
    showState();
    refresh();
  }
});
for (const button of document.querySelectorAll("[data-copy]")) {
  button.addEventListener("click", async () => {
    const value = byId(button.dataset.copy).textContent;
    if (value === "—") return;
    try {
      await navigator.clipboard.writeText(value);
      put("toast", "Copied to clipboard");
    } catch {
      put("toast", "Clipboard unavailable. Select and copy the value.");
    }
    clearTimeout(toastTimer);
    byId("toast").hidden = false;
    toastTimer = setTimeout(() => { byId("toast").hidden = true; }, 2500);
  });
}
setInterval(() => {
  put("clock", `${new Date().toLocaleTimeString("en-GB", { timeZone: "UTC" })} UTC`);
  if (!document.hidden) showState();
}, 1000);
refresh();
