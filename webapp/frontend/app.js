const statusBadge = document.getElementById("status-badge");
const pairBtn = document.getElementById("pair-btn");
const phaseLine = document.getElementById("phase-line");
const countDownloaded = document.getElementById("count-downloaded");
const countSkipped = document.getElementById("count-skipped");
const countSeen = document.getElementById("count-seen");
const currentFileEl = document.getElementById("current-file");
const logEl = document.getElementById("log");
const photoGrid = document.getElementById("photo-grid");
const configLine = document.getElementById("config-line");

const BUSY_STATES = new Set(["starting", "joining_wifi", "verifying_camera", "transferring"]);

function badgeClassFor(state) {
	if (BUSY_STATES.has(state)) return "badge-busy";
	if (state === "done") return "badge-done";
	if (state === "error") return "badge-error";
	return "badge-idle";
}

function applyStatus(status) {
	statusBadge.textContent = status.state;
	statusBadge.className = "badge " + badgeClassFor(status.state);
	pairBtn.disabled = BUSY_STATES.has(status.state);
	pairBtn.textContent = BUSY_STATES.has(status.state) ? "Working…" : "Pair & Sync";
	countDownloaded.textContent = status.counts.downloaded;
	countSkipped.textContent = status.counts.skipped;
	countSeen.textContent = status.counts.seen;
	currentFileEl.textContent = status.current_file ? `Current file: ${status.current_file}` : "";
	if (status.state === "error" && status.last_error) {
		phaseLine.textContent = `Error: ${status.last_error}`;
	}
}

function appendLog(event) {
	const li = document.createElement("li");
	li.textContent = `[${new Date(event.timestamp).toLocaleTimeString()}] ${event.message}`;
	logEl.prepend(li);
	while (logEl.children.length > 30) {
		logEl.removeChild(logEl.lastChild);
	}
}

async function fetchStatus() {
	const res = await fetch("/api/status");
	applyStatus(await res.json());
}

async function fetchPhotos() {
	const res = await fetch("/api/photos");
	const photos = await res.json();
	photoGrid.innerHTML = "";
	for (const photo of photos) {
		const img = document.createElement("img");
		img.src = `/api/photos/${encodeURIComponent(photo.path)}`;
		img.alt = photo.name;
		img.loading = "lazy";
		photoGrid.appendChild(img);
	}
}

async function fetchConfig() {
	const res = await fetch("/api/config");
	const cfg = await res.json();
	configLine.textContent = `Interface: ${cfg.wifi_interface} · Camera: ${cfg.camera_ip}:${cfg.camera_port} · SSID: ${cfg.wifi_ssid_masked}`;
}

pairBtn.addEventListener("click", async () => {
	const res = await fetch("/api/pair", { method: "POST" });
	if (res.status === 409) {
		phaseLine.textContent = "Sync already in progress.";
		return;
	}
	fetchStatus();
});

function connectEvents() {
	const source = new EventSource("/api/events");

	source.addEventListener("snapshot", (e) => {
		applyStatus(JSON.parse(e.data));
	});

	source.addEventListener("progress", (e) => {
		const event = JSON.parse(e.data);
		applyStatus({
			state: event.state,
			counts: event.counts,
			current_file: event.current_file,
			last_error: null,
		});
		phaseLine.textContent = event.message;
		appendLog(event);
		if (event.type === "download_done" || event.state === "done") {
			fetchPhotos();
		}
	});

	source.onerror = () => {
		source.close();
		setTimeout(connectEvents, 3000);
	};
}

fetchStatus();
fetchPhotos();
fetchConfig();
connectEvents();
