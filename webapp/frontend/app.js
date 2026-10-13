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
const lightbox = document.getElementById("lightbox");
const lightboxStage = document.getElementById("lightbox-stage");
const lightboxName = document.getElementById("lightbox-name");
const lightboxDownload = document.getElementById("lightbox-download");
const lightboxClose = document.getElementById("lightbox-close");
const lightboxPrev = document.getElementById("lightbox-prev");
const lightboxNext = document.getElementById("lightbox-next");

const BUSY_STATES = new Set(["starting", "joining_wifi", "verifying_camera", "transferring"]);
const VIDEO_EXTS = new Set(["mp4", "mov", "m4v", "avi", "mts", "m2ts", "webm", "mkv"]);
const MAX_LOG_ENTRIES = 200;
const PHOTO_LIMIT = 500;

let currentPhotos = [];

function isVideo(name) {
	const dot = name.lastIndexOf(".");
	return dot !== -1 && VIDEO_EXTS.has(name.slice(dot + 1).toLowerCase());
}

function photoUrl(path) {
	// encode each path segment but keep the slashes between folders
	return "/api/photos/" + path.split("/").map(encodeURIComponent).join("/");
}

async function apiFetch(url, opts) {
	const res = await fetch(url, opts);
	if (res.status === 401) {
		window.location.href = "/login";
		throw new Error("Not authenticated");
	}
	return res;
}

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
	while (logEl.children.length > MAX_LOG_ENTRIES) {
		logEl.removeChild(logEl.lastChild);
	}
}

async function fetchStatus() {
	const res = await apiFetch("/api/status");
	applyStatus(await res.json());
}

function buildTile(photo, index) {
	const tile = document.createElement("button");
	tile.type = "button";
	tile.className = "frames__tile";
	tile.dataset.index = String(index);
	tile.setAttribute("aria-label", `Open ${photo.name}`);

	const url = photoUrl(photo.path);
	let media;
	if (isVideo(photo.name)) {
		tile.classList.add("frames__tile--video");
		media = document.createElement("video");
		media.src = url;
		media.muted = true;
		media.playsInline = true;
		media.preload = "metadata";
		const badge = document.createElement("span");
		badge.className = "frames__badge";
		badge.setAttribute("aria-hidden", "true");
		tile.append(media, badge);
	} else {
		media = document.createElement("img");
		media.src = url;
		media.alt = photo.name;
		media.loading = "lazy";
		media.decoding = "async";
		tile.appendChild(media);
	}
	// anything that fails to load gets a visible, labelled placeholder
	// instead of a silently blank tile
	media.addEventListener("error", () => {
		tile.classList.add("frames__tile--broken");
		if (!tile.querySelector(".frames__broken")) {
			const label = document.createElement("span");
			label.className = "frames__broken";
			label.textContent = photo.name;
			tile.appendChild(label);
		}
	});

	tile.addEventListener("click", () => openLightbox(index));
	return tile;
}

async function fetchPhotos() {
	const res = await apiFetch(`/api/photos?limit=${PHOTO_LIMIT}`);
	const photos = await res.json();
	currentPhotos = photos;
	photoGrid.innerHTML = "";
	photos.forEach((photo, index) => photoGrid.appendChild(buildTile(photo, index)));
	framesEmpty.hidden = photos.length > 0;
	framesCount.textContent = photos.length > 0 ? String(photos.length) : "";
}

// During a transfer, download_done fires rapidly; rebuilding the whole grid on
// every event thrashes in-flight requests (and some tiles never finish loading).
// Coalesce into at most one refresh every few seconds, with a trailing refresh.
let photoRefreshTimer = null;
let photoRefreshPending = false;
function schedulePhotoRefresh() {
	if (photoRefreshTimer) {
		photoRefreshPending = true;
		return;
	}
	fetchPhotos();
	photoRefreshTimer = setTimeout(() => {
		photoRefreshTimer = null;
		if (photoRefreshPending) {
			photoRefreshPending = false;
			schedulePhotoRefresh();
		}
	}, 4000);
}

async function fetchConfig() {
	const res = await apiFetch("/api/config");
	const cfg = await res.json();
	tmIface.innerHTML = `IF <strong>${cfg.wifi_interface}</strong>`;
	tmCamera.innerHTML = `CAM <strong>${cfg.camera_ip}:${cfg.camera_port}</strong>`;
	tmSsid.innerHTML = `SSID <strong>${cfg.wifi_ssid_masked}</strong>`;
}

/* ============ lightbox ============ */

let lightboxIndex = -1;

function renderLightbox() {
	const photo = currentPhotos[lightboxIndex];
	if (!photo) return;
	const url = photoUrl(photo.path);
	lightboxStage.innerHTML = "";
	if (isVideo(photo.name)) {
		const video = document.createElement("video");
		video.src = url;
		video.controls = true;
		video.autoplay = true;
		video.playsInline = true;
		lightboxStage.appendChild(video);
	} else {
		const img = document.createElement("img");
		img.src = url;
		img.alt = photo.name;
		lightboxStage.appendChild(img);
	}
	lightboxName.textContent = photo.name;
	lightboxDownload.href = url;
	const hasPrev = lightboxIndex > 0;
	const hasNext = lightboxIndex < currentPhotos.length - 1;
	lightboxPrev.hidden = !hasPrev;
	lightboxNext.hidden = !hasNext;
}

function openLightbox(index) {
	lightboxIndex = index;
	lightbox.hidden = false;
	document.body.style.overflow = "hidden";
	renderLightbox();
	lightboxClose.focus();
}

function closeLightbox() {
	lightbox.hidden = true;
	lightboxStage.innerHTML = ""; // stops any playing video
	document.body.style.overflow = "";
	lightboxIndex = -1;
}

function stepLightbox(delta) {
	const next = lightboxIndex + delta;
	if (next < 0 || next >= currentPhotos.length) return;
	lightboxIndex = next;
	renderLightbox();
}

lightboxClose.addEventListener("click", closeLightbox);
lightboxPrev.addEventListener("click", () => stepLightbox(-1));
lightboxNext.addEventListener("click", () => stepLightbox(1));
lightbox.addEventListener("click", (e) => {
	if (e.target === lightbox) closeLightbox();
});
document.addEventListener("keydown", (e) => {
	if (lightbox.hidden) return;
	if (e.key === "Escape") closeLightbox();
	else if (e.key === "ArrowLeft") stepLightbox(-1);
	else if (e.key === "ArrowRight") stepLightbox(1);
});

shutter.addEventListener("click", async () => {
	shutter.classList.remove("is-pressed");
	// force reflow so the ripple can re-trigger on consecutive clicks
	void shutter.offsetWidth;
	shutter.classList.add("is-pressed");

	const res = await apiFetch("/api/pair", { method: "POST" });
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
		if (event.state === "done") {
			fetchPhotos(); // final, authoritative refresh
		} else if (event.type === "download_done") {
			schedulePhotoRefresh(); // coalesced during the burst
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
