import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// Nodes that produce an encoded output — we show the result video here.
const OUTPUT_PREVIEW_NODES = new Set([
    "SophonDownloadOutput",
    "SophonEncodeVideo",
]);

// Nodes that take a source video via the "video" combo — we preview the
// source so picking / uploading a file resizes the node immediately.
const SOURCE_PREVIEW_NODES = new Set([
    "SophonUpload",
    "SophonEncodeVideo",
]);

// Nodes that render side-by-side comparison of two videos.
const COMPARE_NODES = new Set(["SophonCompare"]);

function buildViewUrl(entry) {
    const p = new URLSearchParams();
    p.set("filename", entry.filename);
    if (entry.subfolder) p.set("subfolder", entry.subfolder);
    p.set("type", entry.type || "output");
    return api.apiURL(`/view?${p.toString()}&t=${Date.now()}`);
}

function splitInputPath(value) {
    // Combo values may include a subfolder prefix (e.g. "sub/clip.mp4").
    if (!value) return null;
    const norm = value.replace(/\\/g, "/");
    const idx = norm.lastIndexOf("/");
    return idx < 0
        ? { filename: norm, subfolder: "" }
        : { filename: norm.slice(idx + 1), subfolder: norm.slice(0, idx) };
}

function cleanupOrphanElements() {
    // A DOM widget whose node was removed can leave its element floating in
    // the document. Sweep for any sophon preview containers whose tagged
    // node is gone and detach them.
    for (const el of document.querySelectorAll("[data-sophon-preview]")) {
        const nodeId = el.dataset.sophonNodeId;
        const stillAlive = nodeId && app.graph?._nodes?.some((n) => String(n.id) === nodeId);
        if (!stillAlive) el.remove();
    }
}

function ensureVideoDom(node) {
    if (node._sophonDom?.container?.isConnected) return node._sophonDom;
    // Clear stale DOM pointer if the previous container was detached.
    if (node._sophonDom) node._sophonDom = null;
    cleanupOrphanElements();

    const container = document.createElement("div");
    container.dataset.sophonPreview = "1";
    container.dataset.sophonNodeId = String(node.id);
    container.style.display = "flex";
    container.style.flexDirection = "column";
    container.style.alignItems = "center";
    container.style.padding = "4px";
    container.style.boxSizing = "border-box";

    const video = document.createElement("video");
    video.controls = true;
    video.playsInline = true;
    video.muted = true;
    video.loop = true;
    video.preload = "metadata";
    video.style.width = "100%";
    video.style.height = "auto";
    video.style.maxWidth = "100%";
    video.style.display = "block";
    video.style.background = "#000";
    container.appendChild(video);

    const stats = document.createElement("pre");
    stats.style.margin = "4px 0 0 0";
    stats.style.padding = "4px 6px";
    stats.style.fontFamily = "monospace";
    stats.style.fontSize = "11px";
    stats.style.lineHeight = "1.35";
    stats.style.whiteSpace = "pre-wrap";
    stats.style.color = "#ddd";
    stats.style.background = "rgba(0,0,0,0.25)";
    stats.style.borderRadius = "3px";
    stats.style.width = "100%";
    stats.style.boxSizing = "border-box";
    container.appendChild(stats);

    const widget = node.addDOMWidget("sophon_preview", "preview", container, {
        serialize: false,
        hideOnZoom: false,
    });
    // Height is derived deterministically from the known aspect ratio and
    // stats line count. scrollHeight measurement is unreliable because the
    // DOM may not have laid out by the time ComfyUI asks for the size.
    const measure = () => {
        const width = Math.max(128, node.size?.[0] || 256);
        const aspect = node._sophonAspect || 16 / 9;
        const inner = Math.max(64, width - 16);
        const videoH = video.src ? Math.round(inner / aspect) : 0;
        const lines = stats.textContent ? stats.textContent.split("\n").length : 0;
        const statsH = lines ? lines * 15 + 12 : 0;
        return { width, height: videoH + statsH + 12 };
    };
    widget.computeSize = function () {
        const { width, height } = measure();
        return [width, height];
    };
    // V3 layout engine uses this one; legacy computeSize is ignored.
    widget.computeLayoutSize = function () {
        const { width, height } = measure();
        return { minHeight: height, minWidth: Math.min(width, 128) };
    };

    node._sophonDom = { container, video, stats, widget };
    return node._sophonDom;
}

function relayout(node) {
    // Ask ComfyUI for the minimum size then grow to it. Width stays whatever
    // the user already set; only height expands to fit the widget stack.
    requestAnimationFrame(() => {
        const [minW, minH] = node.computeSize();
        const curW = Math.max(node.size?.[0] || 0, minW);
        node.setSize([curW, minH]);
        node.onResize?.(node.size);
        node.setDirtyCanvas(true, true);
    });
}

function setVideoSrc(node, url) {
    const dom = ensureVideoDom(node);
    if (dom.video.src === url) return;
    dom.video.src = url;
    dom.video.addEventListener(
        "loadedmetadata",
        () => {
            if (dom.video.videoWidth && dom.video.videoHeight) {
                node._sophonAspect = dom.video.videoWidth / dom.video.videoHeight;
                relayout(node);
            }
        },
        { once: true }
    );
    relayout(node);
}

function ensureCompareDom(node) {
    if (node._sophonCompareDom?.container?.isConnected) return node._sophonCompareDom;
    if (node._sophonCompareDom) node._sophonCompareDom = null;
    cleanupOrphanElements();

    const container = document.createElement("div");
    container.dataset.sophonPreview = "1";
    container.dataset.sophonNodeId = String(node.id);
    container.style.display = "flex";
    container.style.flexDirection = "column";
    container.style.padding = "4px";
    container.style.boxSizing = "border-box";
    container.style.width = "100%";

    const row = document.createElement("div");
    row.style.display = "flex";
    row.style.gap = "4px";
    row.style.width = "100%";
    container.appendChild(row);

    const makeSide = () => {
        const wrap = document.createElement("div");
        wrap.style.flex = "1 1 0";
        wrap.style.minWidth = "0";
        wrap.style.display = "flex";
        wrap.style.flexDirection = "column";
        wrap.style.alignItems = "center";

        const label = document.createElement("div");
        label.style.fontFamily = "monospace";
        label.style.fontSize = "11px";
        label.style.color = "#ddd";
        label.style.padding = "0 0 2px 0";
        label.textContent = "";
        wrap.appendChild(label);

        const video = document.createElement("video");
        video.controls = true;
        video.playsInline = true;
        video.muted = true;
        video.loop = true;
        video.preload = "metadata";
        video.style.width = "100%";
        video.style.height = "auto";
        video.style.display = "block";
        video.style.background = "#000";
        wrap.appendChild(video);

        const stats = document.createElement("pre");
        stats.style.margin = "2px 0 0 0";
        stats.style.padding = "3px 6px";
        stats.style.fontFamily = "monospace";
        stats.style.fontSize = "10px";
        stats.style.lineHeight = "1.3";
        stats.style.whiteSpace = "pre-wrap";
        stats.style.color = "#ddd";
        stats.style.background = "rgba(0,0,0,0.25)";
        stats.style.borderRadius = "3px";
        stats.style.width = "100%";
        stats.style.boxSizing = "border-box";
        stats.style.textAlign = "center";
        stats.textContent = "";
        wrap.appendChild(stats);

        row.appendChild(wrap);
        return { wrap, label, video, stats };
    };
    const left = makeSide();
    const right = makeSide();

    const savings = document.createElement("pre");
    savings.style.margin = "4px 0 0 0";
    savings.style.padding = "4px 6px";
    savings.style.fontFamily = "monospace";
    savings.style.fontSize = "11px";
    savings.style.color = "#8df28d";
    savings.style.background = "rgba(0,0,0,0.3)";
    savings.style.borderRadius = "3px";
    savings.style.textAlign = "center";
    savings.textContent = "";
    container.appendChild(savings);

    // Playback sync — guard against re-entrance so mirroring one event onto
    // the other <video> doesn't bounce back and cause a feedback loop.
    let syncing = false;
    const mirror = (src, dst, fn) => {
        if (syncing) return;
        syncing = true;
        try { fn(src, dst); } finally { syncing = false; }
    };
    const pair = [left.video, right.video];
    pair.forEach((v, i) => {
        const other = pair[1 - i];
        v.addEventListener("play", () =>
            mirror(v, other, (s, d) => { if (d.paused) d.play().catch(() => {}); }));
        v.addEventListener("pause", () =>
            mirror(v, other, (s, d) => { if (!d.paused) d.pause(); }));
        v.addEventListener("seeked", () =>
            mirror(v, other, (s, d) => { if (Math.abs(d.currentTime - s.currentTime) > 0.03) d.currentTime = s.currentTime; }));
        v.addEventListener("ratechange", () =>
            mirror(v, other, (s, d) => { if (d.playbackRate !== s.playbackRate) d.playbackRate = s.playbackRate; }));
    });

    const widget = node.addDOMWidget("sophon_compare", "preview", container, {
        serialize: false,
        hideOnZoom: false,
    });
    const measure = () => {
        const width = Math.max(320, node.size?.[0] || 512);
        const aspect = node._sophonCompareAspect || 16 / 9;
        // Each video takes half the inner width minus the gap, minus padding.
        const inner = Math.max(120, width - 8);
        const perVideoW = (inner - 4) / 2;
        const perVideoH = Math.round(perVideoW / aspect);
        const labelH = 14;
        const statsH = 30; // 2 lines of per-side stats
        const savingsH = 22; // savings summary row
        const height = labelH + perVideoH + statsH + savingsH + 12;
        return { width, height };
    };
    widget.computeSize = function () {
        const { width, height } = measure();
        return [width, height];
    };
    widget.computeLayoutSize = function () {
        const { width, height } = measure();
        return { minHeight: height, minWidth: Math.min(width, 320) };
    };

    node._sophonCompareDom = { container, left, right, savings, widget };
    return node._sophonCompareDom;
}

function fmtBytes(n) {
    if (!Number.isFinite(n) || n <= 0) return "—";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let i = 0;
    let v = n;
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
    return i === 0 ? `${n} B` : `${v.toFixed(2)} ${units[i]}`;
}

function fmtKbps(v) {
    if (!Number.isFinite(v) || v <= 0) return "—";
    return `${Math.round(v).toLocaleString()} kbps`;
}

function onCompareMessage(node, message) {
    const entries = message.sophon_compare || [];
    if (!entries.length) return;
    const entry = entries[0];
    const {
        left: leftSrc,
        right: rightSrc,
        label_left,
        label_right,
        size_left,
        size_right,
        bitrate_left_kbps,
        bitrate_right_kbps,
        savings_pct,
    } = entry;
    const dom = ensureCompareDom(node);
    dom.left.label.textContent = label_left || "left";
    dom.right.label.textContent = label_right || "right";
    if (leftSrc) dom.left.video.src = buildViewUrl(leftSrc);
    if (rightSrc) dom.right.video.src = buildViewUrl(rightSrc);

    dom.left.stats.textContent =
        `${fmtBytes(size_left)}\n${fmtKbps(bitrate_left_kbps)}`;
    dom.right.stats.textContent =
        `${fmtBytes(size_right)}\n${fmtKbps(bitrate_right_kbps)}`;

    if (Number.isFinite(savings_pct)) {
        // Negative savings = bigger output; show both cases with the right color.
        const sign = savings_pct >= 0 ? "" : "";
        dom.savings.style.color = savings_pct >= 0 ? "#8df28d" : "#f28d8d";
        dom.savings.textContent = `Savings: ${sign}${savings_pct.toFixed(1)}%`;
    } else {
        dom.savings.textContent = "";
    }
    // First <loadedmetadata> wins for aspect — we render at a shared ratio so
    // both videos frame identically even if one is slightly off.
    const onMeta = (v) => {
        if (!v.videoWidth || !v.videoHeight) return;
        if (!node._sophonCompareAspect) {
            node._sophonCompareAspect = v.videoWidth / v.videoHeight;
            relayout(node);
        }
    };
    dom.left.video.addEventListener("loadedmetadata", () => onMeta(dom.left.video), { once: true });
    dom.right.video.addEventListener("loadedmetadata", () => onMeta(dom.right.video), { once: true });
    relayout(node);
}

function onExecutedMessage(node, message) {
    const entries = message.sophon_video || [];
    const statsLines = message.sophon_stats || [];
    if (!entries.length && !statsLines.length) return;
    const dom = ensureVideoDom(node);
    if (entries.length) setVideoSrc(node, buildViewUrl(entries[0]));
    dom.stats.textContent = statsLines.join("\n");
    relayout(node);
}

function suppressNativeVideoPreview(node) {
    // The core frontend's useNodeVideo auto-creates a DOM widget named
    // "video-preview" for any video_upload combo, bundled with the upload
    // button. Intercept addDOMWidget and return a dummy for that widget so
    // only our own preview renders.
    if (node.__sophonSuppressed) return;
    node.__sophonSuppressed = true;
    const origAddDom = node.addDOMWidget.bind(node);
    node.addDOMWidget = function (name, type, element, options) {
        if (name === "video-preview") {
            return {
                name,
                type,
                value: "",
                serialize: false,
                computeSize: () => [0, -4],
                computeLayoutSize: () => ({ minHeight: 0, minWidth: 0 }),
                onRemove: () => {},
            };
        }
        return origAddDom(name, type, element, options);
    };
}

function hookSourcePreview(node) {
    suppressNativeVideoPreview(node);
    const widget = node.widgets?.find((w) => w.name === "video");
    if (!widget) return;

    const render = (value) => {
        const parts = splitInputPath(value);
        if (!parts) return;
        setVideoSrc(node, buildViewUrl({ ...parts, type: "input" }));
    };

    // Wrap the combo's callback so both dropdown-selection and upload-completion
    // drive the preview. ComfyUI's upload widget calls this callback after the
    // file is registered in input/.
    const origCallback = widget.callback;
    widget.callback = function (value) {
        const r = origCallback?.apply(this, arguments);
        render(value);
        return r;
    };

    // Also render immediately on load if there is already a value.
    if (widget.value) render(widget.value);
}

app.registerExtension({
    name: "sophon.preview",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        const name = nodeData?.name;
        if (!name) return;

        // Guard against double registration (e.g. if the extension file is
        // loaded twice). Each wrapper would otherwise chain and fire twice.
        if (nodeType.prototype.__sophonWrapped) return;
        nodeType.prototype.__sophonWrapped = true;

        if (OUTPUT_PREVIEW_NODES.has(name)) {
            const origOnExecuted = nodeType.prototype.onExecuted;
            nodeType.prototype.onExecuted = function (message) {
                origOnExecuted?.apply(this, arguments);
                if (message) onExecutedMessage(this, message);
            };
        }

        if (COMPARE_NODES.has(name)) {
            const origOnExecuted = nodeType.prototype.onExecuted;
            nodeType.prototype.onExecuted = function (message) {
                origOnExecuted?.apply(this, arguments);
                if (message) onCompareMessage(this, message);
            };
        }

        if (SOURCE_PREVIEW_NODES.has(name)) {
            const origOnNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                const r = origOnNodeCreated?.apply(this, arguments);
                hookSourcePreview(this);
                return r;
            };
        }

        const origOnRemoved = nodeType.prototype.onRemoved;
        nodeType.prototype.onRemoved = function () {
            if (this._sophonDom?.container) {
                this._sophonDom.container.remove();
                this._sophonDom = null;
            }
            if (this._sophonCompareDom?.container) {
                this._sophonCompareDom.container.remove();
                this._sophonCompareDom = null;
            }
            origOnRemoved?.apply(this, arguments);
        };
    },
});
