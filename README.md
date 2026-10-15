# ComfyUI_Deciia_EasyUse

作者 deciia 的 ComfyUI 自定义节点合集。当前聚焦 **MiniMax-H3 视频生成**：
二采分块执行器、跨插件桥接节点、LoRA 串管理，以及配套前端面板。

> 本仓库所有节点均为**运行时互操作**设计：不修改、不复制任何上游插件代码，
> 上游插件可独立正常更新。删除本包不影响既有工作流；各节点说明见
> [docs/node-reference.md](docs/node-reference.md)，
> 上游依赖关系见 [docs/upstream-dependencies.md](docs/upstream-dependencies.md)。

## 节点总览

| 节点 | 模块 | 用途 |
|---|---|---|
| `DeciiaChunkedPass2SamplerLegacy` | minimax_h3/h3_sampling | H3 二采**时间分块**执行器：低显存跑高分辨率/长时长二采，支持 `refined_exp` 音频精修（截获二采精修音频按绝对时间对位拼回，替代默认的一采原声直通）（T8 v1.85 起官方同 ID 节点并存，本包节点加 Legacy 后缀） |
| `DeciiaTiledSecondPass` | minimax_h3/h3_sampling | H3 二采空间分块执行器（GH `TiledSamplerLegacy.sample_tiled` 薄壳，备援路线） |
| `DeciiaLoraStack` | stacks | 动态 LoRA 串：槽位增删/重排/旁路模式，前端自动伸缩 |
| `DeciiaVramSafeLoraStack` | stacks | 显存安全 LoRA 串：加载即测显存余量，超限自动旁路 |
| `MiniMaxH3GHGuideT8` | minimax_h3/ght8_bridge | GH 导演台素材面板 → T8 双采链（1 节点替代 2 个 AudioConditioningT8） |
| `MiniMaxRefGuideT8` | minimax_h3/reft8_bridge | MiniMaxRefDirector 时间线 → T8 条件编码（6 槽与 AudioConditioningT8 同契约） |
| `MiniMaxRefSegTrimT8` | minimax_h3/reft8_bridge | Ref 分镜段落裁帧 |

## 工作台（Workstation）

ComfyUI 左侧栏「工作台」启动器：把本机各服务/工具收进一个面板，条目完全自定义。

- **两种入口**：左侧栏「工作台」标签；或画布节点 `DeciiaWorkstation` 上的「打开工作台」按钮。
- **两种打开方式**（每条独立）：`embed` = ComfyUI 内浮层 iframe（同曜石导演台体验）；`new_window` = 浏览器新窗口。
- **四种添加方式**：手动填写 / 粘贴一行解析（`名称 | 地址 | 图标 | 备注 | 模式`）/ 粘贴 JSON 批量导入 / 扫描本机常见端口自动发现。
- **状态探测**：可选，支持「HTTP 200 即在线」或「JSON 字段」（如 DirectorDeck 的 `backend=ready`）。
- **存储**：`ComfyUI/user/deciia_workstation/tools.json`（`folder_paths.get_user_directory()`，不在本仓库内）（与工作流无关，带 revision 冲突检测，多标签页不会静默覆盖）。

内置默认四条：曜石导演台（内浮层）、Director、Dreamifly、NEXUS BTA Studio（后三条新窗口）。

## 安装

```bash
cd ComfyUI/custom_nodes
git clone <repo-url> ComfyUI_Deciia_All
```

重启 ComfyUI 即可。依赖只有 ComfyUI 本体 + 你已安装的上游插件
（按需：comfyui-minimax-h3-audio-T8 / Goohai-MiniMax-H3_Integration /
MiniMaxRefDirector-ComfyUI，用到哪个装哪个，桥接节点在上游缺失时给出明确报错）。

## 目录结构

```
ComfyUI_Deciia_All/
├── minimax_h3/          H3 专属（以后其它模型平行扩展 wan/ ltx/ …）
│   ├── h3_sampling/     分块二采执行器 + 兼容垫片
│   ├── ght8_bridge/
│   └── reft8_bridge/
├── stacks/              模型无关的 LoRA 串
├── web/                 前端 JS
├── examples/            示例工作流
└── docs/                上游依赖 / 节点说明
```

## 兼容性说明

- H3Sampling 通过**上下文作用域垫片**兼容不同 ComfyUI 核心的
  `PackedLayout` 签名差异与 comfy_kitchen Sol-Attn 新旧签名
  （进程级幂等包装，仅在采样窗口内生效，`finally` 必还原）。
- T8 的 `chunked_two_pass_upscale_advanced` 等内部模块按
  「sys.modules 真实路径比对优先，合成包加载兜底」策略动态 import，
  随当前安装版本工作。

## License

GPL-3.0-or-later，见 [LICENSE](LICENSE)。
本仓库不包含、不分发任何上游插件的代码；与上游的互操作通过运行时
动态 import 与类型名匹配完成。
