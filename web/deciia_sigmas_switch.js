/* ===== Deciia Easy Sigmas Switch（2026-10-12）============================
   修复版多选一开关：rgthree Fast Muter 在新版前端下创建空名拨钮时，
   widgetValueStore 以 "un-keyable widget id"（uuid:nodeId: 空名字段）
   忽略，导致新接的链路不出拨钮。
   本节点创建拨钮时立即带唯一名（enable_<index>_<nodeid>），规避该问题。
   继承 rgthree BaseNodeModeChanger，保留 always-one 互斥逻辑。
   ======================================================================== */
import { app } from "/scripts/app.js";
import { BaseNodeModeChanger } from "/extensions/rgthree-comfy/base_node_mode_changer.js";

class DeciiaEasySigmasSwitch extends BaseNodeModeChanger {
    constructor(title = "Easy Sigmas Switch (Deciia)") {
        super(title);
        this.comfyClass = "easy deciiaSigmasSwitch";
        this.modeOn = 0;
        this.modeOff = 2;
        // rgthree 子类契约（MuterNode 同款，muter.js L12）：构造函数必须显式调用
        // onConstructed()。不调用时基类 RgthreeBaseNode 构造函数里的 setTimeout
        // 兜底（base_node.js L26-34 checkAndRunOnConstructed）会落到 configure 之后
        // 才执行——每次加载工作流都会在已恢复的输出槽之上追加 1 个
        // OPT_CONNECTION，这就是输出槽逐次累积的根因。显式调用后 __constructed__
        // 在构造期即为 true，兜底检查变成空操作，加载即稳定。
        this.onConstructed();
    }
    handleLinkedNodesStabilization(linkedNodes) {
        let changed = false;
        for (const [index, node] of linkedNodes.entries()) {
            let widget = this.widgets && this.widgets[index];
            if (!widget) {
                this._tempWidth = this.size[0];
                // 修复点：创建时立即带唯一名（rgthree 原版为空名+事后改名，
                // 新版前端 widgetValueStore 会在空名创建瞬间以 un-keyable 忽略）
                widget = this.addWidget("toggle", `enable_${index}_${node.id}`, false, "", { on: "yes", off: "no" });
                changed = true;
            }
            if (node) {
                changed = this.setWidget(widget, node) || changed;
            }
        }
        if (this.widgets && this.widgets.length > linkedNodes.length) {
            this.widgets.length = linkedNodes.length;
            changed = true;
        }
        return changed;
    }
}


// 修复：rgthree 基类 RgthreeBaseVirtualNode.setUp 会校验 static type，
// 缺失则抛 "Missing type" 且节点不注册。必须与 comfyClass 一致。
DeciiaEasySigmasSwitch.type = "easy deciiaSigmasSwitch";
DeciiaEasySigmasSwitch.title = "Easy Sigmas Switch (Deciia)";

app.registerExtension({
    name: "Deciia.EasySigmasSwitch",
    registerCustomNodes() {
        DeciiaEasySigmasSwitch.setUp();
    },
});
/* ===== End Deciia Easy Sigmas Switch ===== */
