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

function ensureVideoDom(node) {
    if (node._sophonDom) return node._sophonDom;

    const container = document.createElement("div");
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

    const widget = node.addDOMWidget("sophon_preview", "div", container, {
        serialize: false,
        hideOnZoom: false,
    });
    // Height is derived deterministically from the known aspect ratio and
    // stats line count. scrollHeight measurement is unreliable because the
    // DOM may not have laid out by the time ComfyUI asks for the size.
    widget.computeSize = function (width) {
        const aspect = node._sophonAspect || 16 / 9;
        const inner = Math.max(64, width - 16);
        const videoH = video.src ? Math.round(inner / aspect) : 0;
        const lines = stats.textContent ? stats.textContent.split("\n").length : 0;
        const statsH = lines ? lines * 15 + 12 : 0;
        return [width, videoH + statsH + 12];
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

function onExecutedMessage(node, message) {
    const entries = message.sophon_video || [];
    const statsLines = message.sophon_stats || [];
    if (!entries.length && !statsLines.length) return;
    const dom = ensureVideoDom(node);
    if (entries.length) setVideoSrc(node, buildViewUrl(entries[0]));
    dom.stats.textContent = statsLines.join("\n");
    relayout(node);
}

function hookSourcePreview(node) {
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

        if (OUTPUT_PREVIEW_NODES.has(name)) {
            const origOnExecuted = nodeType.prototype.onExecuted;
            nodeType.prototype.onExecuted = function (message) {
                origOnExecuted?.apply(this, arguments);
                if (message) onExecutedMessage(this, message);
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
    },
});
