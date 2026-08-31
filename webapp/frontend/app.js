const afFrame = document.getElementById("af-frame");
const statusWord = document.getElementById("status-word");
const shutter = document.getElementById("pair-btn");
const phaseLine = document.getElementById("phase-line");
const countDownloaded = document.getElementById("count-downloaded");
const countSkipped = document.getElementById("count-skipped");
const countSeen = document.getElementById("count-seen");
const currentFileEl = document.getElementById("current-file");
const logEl = document.getElementById("log");
const photoGrid = document.getElementById("photo-grid");
const framesEmpty = document.getElementById("frames-empty");
const framesCount = document.getElementById("frames-count");
const tmIface = document.getElementById("tm-iface");
const tmCamera = document.getElementById("tm-camera");
const tmSsid = document.getElementById("tm-ssid");

const BUSY_STATES = new Set(["starting", "joining_wifi", "verifying_camera", "transferring"]);

function frameState(state) {
	if (BUSY_STATES.has(state)) return "busy";
	if (state === "done") return "done";
	if (state === "error") return "error";
	return "idle";
}

function applyStatus(status) {
	const fState = frameState(status.state);
	afFrame.dataset.state = fState;
	statusWord.textContent = status.state.replace(/_/g, " ").toUpperCase();

	shutter.disabled = fState === "busy";
	shutter.querySelector(".shutter__label").textContent = fState === "busy" ? "BUSY" : "PAIR";

	countDownloaded.textContent = status.counts.downloaded;
	countSkipped.textContent = status.counts.skipped;
	countSeen.textContent = status.counts.seen;
	currentFileEl.textContent = status.current_file ? status.current_file : "";

	if (fState === "error" && status.last_error) {
		phaseLine.textContent = `Error: ${status.last_error}`;
	}
}

function appendLog(event) {
	const li = document.createElement("li");
	const time = document.createElement("time");
	time.textContent = new Date(event.timestamp).toLocaleTimeString([], { hour12: false });
	const message = document.createElement("span");
	message.textContent = event.message;
	li.append(time, message);
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
		const figure = document.createElement("figure");
		const img = document.createElement("img");
		img.src = `/api/photos/${encodeURIComponent(photo.path)}`;
		img.alt = photo.name;
		img.loading = "lazy";
		img.width = 200;
		img.height = 200;
		figure.appendChild(img);
		photoGrid.appendChild(figure);
	}
	framesEmpty.hidden = photos.length > 0;
	framesCount.textContent = photos.length > 0 ? String(photos.length) : "";
}

async function fetchConfig() {
	const res = await fetch("/api/config");
	const cfg = await res.json();
	tmIface.innerHTML = `IF <strong>${cfg.wifi_interface}</strong>`;
	tmCamera.innerHTML = `CAM <strong>${cfg.camera_ip}:${cfg.camera_port}</strong>`;
	tmSsid.innerHTML = `SSID <strong>${cfg.wifi_ssid_masked}</strong>`;
}

shutter.addEventListener("click", async () => {
	shutter.classList.remove("is-pressed");
	// force reflow so the ripple can re-trigger on consecutive clicks
	void shutter.offsetWidth;
	shutter.classList.add("is-pressed");

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
