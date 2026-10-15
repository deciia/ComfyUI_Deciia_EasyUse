import { app } from "../../scripts/app.js";

// DeciiaChunkedPass2V2: two master switches (temporal_chunking /
// spatial_chunking) toggle visibility of their dependent widget groups.
// Mechanism: widget.hidden — the Vue frontend filters widgets with
// getLayoutWidgets() = widgets.filter(e => !e.hidden), so setting
// w.hidden = true both removes it from layout AND from DOM.
// The backend ignores hidden widgets' values via routing; this extension
// is cosmetic and safe to fail (all widgets just stay visible).

const TYPE = "DeciiaChunkedPass2V2";

const TEMPORAL_GROUP = new Set([
    "temporal_chunk_frames",
    "temporal_overlap_frames",
    "anchor_strength",
]);

const SPATIAL_GROUP = new Set([
    "spatial_n_tiles",
    "spatial_overlap_px",
    "spatial_feather",
    "spatial_global_pos",
]);

app.registerExtension({
    name: "decia-local.chunked-pass2-v2-switch-ui",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== TYPE) return;
        const created = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = created?.apply(this, arguments);

            const apply = () => {
                const temporal = this.widgets?.find((w) => w.name === "temporal_chunking");
                const spatial = this.widgets?.find((w) => w.name === "spatial_chunking");
                const showTemporal = temporal ? temporal.value !== false : true;
                const showSpatial = spatial ? spatial.value !== false : true;
                for (const w of this.widgets ?? []) {
                    if (TEMPORAL_GROUP.has(w.name)) w.hidden = !showTemporal;
                    if (SPATIAL_GROUP.has(w.name)) w.hidden = !showSpatial;
                }
                this.setSize?.(this.computeSize?.());
                this.setDirtyCanvas?.(true, true);
            };

            const hookSwitch = (widget) => {
                if (!widget || widget._switchHooked) return;
                widget._switchHooked = true;
                const orig = widget.callback;
                widget.callback = function () {
                    const r = orig?.apply(this, arguments);
                    apply();
                    return r;
                };
                // boolean toggles may route through onValueChanged in Vue frontend
                const origOIV = widget.onValueChanged;
                if (origOIV) {
                    widget.onValueChanged = function (v) {
                        const r = origOIV.call(this, v);
                        apply();
                        return r;
                    };
                }
            };

            this._pass2ApplySwitchUI = apply;
            hookSwitch(this.widgets?.find((w) => w.name === "temporal_chunking"));
            hookSwitch(this.widgets?.find((w) => w.name === "spatial_chunking"));
            apply();
            setTimeout(apply, 60);
            setTimeout(apply, 600);
            return result;
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = onConfigure?.apply(this, arguments);
            setTimeout(() => this._pass2ApplySwitchUI?.(), 30);
            return result;
        };
    },
});
