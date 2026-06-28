# headroom-zh Windows 本地部署修复记录

> 目的：记录把 `kompress_zh`（中文压缩通道）在 Windows 本机真正跑通的完整排障与修复过程，
> 沉淀为后续 Windows 用户可复用的部署指南，补足上游项目在 Windows 上的部署缺陷。
> 配套文件：项目 eval 目录下的 [`requirements-windows.txt`](../eval/requirements-windows.txt)。

- 机器：Windows 11 家庭中文版，RTX 4060 Laptop GPU（8GB），CUDA 12.8
- 项目路径：`<repo>`（注意：含中文字符）
- 结论先行：**根因是 venv 建在了 Anaconda 的 base Python 上**，导致 Anaconda 注入的
  MKL / Intel-OpenMP 与 torch 自带 `libiomp5md.dll` 冲突，torch 的 `c10.dll` 初始化失败
  （`OSError [WinError 1114]`）→ `is_kompress_zh_available()` 为假 → 中文压缩被静默跳过。

---

## 1. 现象

- `headroom wrap codex` 发消息后，dashboard 只显示约 **1.4%** 的 token 节省。
- 中文压缩本应有几十个百分点的节省，故怀疑 `kompress_zh` 根本没生效（1.4% 来自其他
  非 ML 的轻量变换）。

## 2. 诊断过程（逐步）

1. **直接验证可用性**：在该 venv 下 `import torch` 抛 `OSError [WinError 1114] 动态链接库(DLL)
   初始化例程失败。Error loading ...\torch\lib\c10.dll or one of its dependencies`。
   → `is_kompress_zh_available()`（`import peft, swift, torch`）因此失败，中文压缩通道不可用。

2. **附带发现的代码缺陷**：`kompress_zh_compressor.is_kompress_zh_available()` 只
   `except ImportError`，而坏掉的 torch 抛的是 `OSError`，所以这个"可用性守卫"在 Windows DLL
   失败时**不会优雅降级**（应改为捕获更宽的异常并记日志）。

3. **排除 torch 版本/损坏**：重装同版本（2.12.1+cpu，清华镜像）→ 仍失败；降到 2.11.0+cpu →
   仍失败。说明与具体版本无关。

4. **排除常见环境因素**：
   - VC++ 运行库为 14.44.35211（最新），非缺失/过旧；
   - CPU 为 Intel Raptor Lake，支持 AVX2；
   - `libiomp5md.dll`、`uv.dll` 用 ctypes 直接加载均成功，**唯独 `c10.dll` 初始化失败**；
   - `KMP_DUPLICATE_LIB_OK=TRUE` 无效；清空 PATH 到仅 System32 仍失败。

5. **路径因素**：把同一个 `torch 2.12.1+cpu` 装到纯 ASCII 路径 `C:\hrzh_ascii_test` →
   **导入成功**。说明 cpu 构建在**非 ASCII（中文）路径**下还有一个独立的加载缺陷。
   （用 junction 把中文路径映射成 ASCII 无效——Windows 加载依赖时会解析回真实中文路径。）

6. **关键对照（来自已验证的 `lora-finetune-qwen` 环境）**：该环境 torch 为
   **2.11.0+cu128**，在**同样的中文路径**下导入正常。对比两个 venv：
   - `torch/lib` 内容**字节级相同**（37 个 DLL，`c10.dll` 均 1088000 字节）；
   - 差异在解释器：headroom 的 `.venv` 为 **Python 3.12.4，`home = C:\ProgramData\anaconda3`**
     （Anaconda base）；lora 的 `.venv` 为 **Python 3.12.13，`home = ...\uv\python\cpython-3.12.13`**
     （干净的 uv 托管 CPython）。

7. **定性根因**：Anaconda 的 Python 会把 MKL / Intel-OpenMP 等 DLL 引入解释器的加载环境，
   与 torch 自带的 `libiomp5md.dll` 冲突，导致 `c10.dll` 的初始化例程返回失败（WinError 1114）。
   叠加 cpu 构建在非 ASCII 路径下的缺陷，两者共同造成本机 torch 完全不可用。

## 3. 根因总结

| 层级 | 问题 | 证据 |
|---|---|---|
| **主因** | venv 建在 Anaconda base Python 上，MKL/OpenMP 与 torch `libiomp5md.dll` 冲突 → `c10.dll` 初始化失败 | 干净 uv Python（lora venv）同路径同 torch 文件可正常导入 |
| 叠加因 | torch **cpu** 构建在非 ASCII(中文)路径下加载失败 | 同一 cpu wheel 在 ASCII 路径成功、中文路径失败 |
| 代码缺陷 | `is_kompress_zh_available()` 只 `except ImportError`，torch 抛 `OSError` 不被捕获，无法优雅降级 | 源码 `headroom/transforms/kompress_zh_compressor.py` |

## 4. 修复方案

核心：**用干净（非 Anaconda）的 uv 托管 CPython 重建 venv + 安装 cu128 的 GPU 构建 torch**。

1. `conda deactivate`（退出可能默认激活的 base conda，避免其 DLL 干扰）。
2. 删除基于 Anaconda 的旧 `.venv`。
3. 用干净解释器建 venv：`uv venv --python cpython-3.12.13-windows-x86_64-none .venv`
   （与已验证的 lora 环境同款）。
4. 安装依赖：`uv pip install --index-strategy unsafe-best-match -r eval\requirements-windows.txt`
   - torch/torchvision 走 **cu128** 的 Windows wheel（`--extra-index-url https://download.pytorch.org/whl/cu128`）；
   - 显式加 `qwen-vl-utils`、`av`（ms-swift 4.1.3 的 Qwen 加载器隐式依赖，Windows 不会被传递依赖带上）。
5. **editable 挂载（绕开无 cargo 的 maturin 构建）**：headroom 是 maturin/Rust 工程，本机无 cargo，
   无法重编译；但源码内已有**预编译的 `headroom/_core.pyd`**。因此手动在
   `.venv\Lib\site-packages\headroom_ai.pth` 写入一行源码根路径即可完成 editable 挂载。
   - 注意：F: 盘禁用了 8.3 短文件名，且 **Python 3.12 按本地编码（cp936）读取 `.pth`**，
     故该 `.pth` 必须用 **GBK(936)** 编码写入（否则中文路径会乱码、`import headroom` 失败）。
     （Python 3.13+ 改为按 UTF-8 读 `.pth`；本机是 3.12.13 故用 cp936。）

## 5. 前后环境对比

| 项 | 修复前（坏） | 修复后（好） |
|---|---|---|
| venv base Python | `C:\ProgramData\anaconda3` (3.12.4) | 干净 uv `cpython-3.12.13` |
| torch | 2.12.1+**cpu**（c10.dll 1114 失败） | 2.11.0+**cu128**（CUDA 可用） |
| `torch.cuda.is_available()` | 不可用（torch 都导入不了） | True，RTX 4060 Laptop GPU |
| `is_kompress_zh_available()` | False（torch OSError） | **True** |
| ms-swift Qwen 加载器依赖 | 缺 torchvision/qwen-vl-utils/av | 已显式安装 |
| headroom 挂载 | uv 原始 editable（anaconda venv） | `.pth`(GBK) 指向源码 + 预编译 `_core.pyd` |
| 中文压缩实际效果 | 未生效（dashboard ≈1.4%） | 真实压缩（见 §7） |

## 6. 给 Windows 用户的标准部署步骤（可复用）

```powershell
# 0. 退出 base conda（关键！不要用 Anaconda 的 Python 做 venv base）
conda deactivate

# 1. 准备干净的 uv 托管 Python
uv python install 3.12

# 2. 在 headroom-zh 仓库根目录建干净 venv
cd <你的>\headroom-zh
uv venv --python cpython-3.12.13-windows-x86_64-none .venv

# 3. 安装 Windows 依赖（cu128 torch + ms-swift Qwen 隐式依赖 + headroom 全部依赖）
uv pip install --python .venv\Scripts\python.exe `
  --index-strategy unsafe-best-match -r eval\requirements-windows.txt

# 4. editable 挂载：把【仓库根目录绝对路径】写入 .pth（一行）
#    - 若路径含中文且 Python 为 3.12.x：用 GBK(936) 编码写入
#    - 路径纯 ASCII 或 Python>=3.13：用 UTF-8/ASCII 即可
#    （本仓库已用脚本写好 .venv\Lib\site-packages\headroom_ai.pth）

# 5. 验证
$env:PYTHONUTF8=1; $env:HF_ENDPOINT="https://hf-mirror.com"
.venv\Scripts\python.exe -c "import torch;print(torch.cuda.is_available());from headroom.transforms.kompress_zh_compressor import is_kompress_zh_available;print(is_kompress_zh_available())"
```

> 前提：本机已装 NVIDIA 驱动（支持 CUDA 12.8）。无 GPU 的机器需另寻方案——cpu 构建的 torch
> 在中文路径下也会 c10.dll 失败，此时应把仓库放到纯 ASCII 路径，或在 AutoDL/Linux 上跑。

## 7. 验证结果

环境层（已确认）：

- `torch 2.11.0+cu128`，`torch.cuda.is_available() = True`，设备 `NVIDIA GeForce RTX 4060 Laptop GPU`
- `import headroom` / `headroom._core` 成功（预编译 Rust core）
- `is_kompress_zh_available() = True`

真实压缩验证（kompress_zh 对中文样本 `eval/materials/contexts/A4.md`）：

| 指标 | 数值 |
|---|---|
| 模型 | `Deserveall/kompress_zh-baseline-v1-lora`（base `Qwen/Qwen3.5-0.8B`，GPU bfloat16） |
| 原始 tokens | 1647 |
| 压缩后 tokens | **315** |
| 压缩率 | **0.191**（压到原文 19.1%） |
| 节省 | **1332 tokens（约 81%）** |
| 是否真实压缩 | **True**（非透传） |
| 耗时 | 约 26s（含首次模型+adapter 加载，稳态推理远快于此） |

对比修复前 dashboard 仅 ≈1.4% 的"节省"，可确认：**修复后 kompress_zh 中文压缩通道真正生效**。
完整压缩前后样本见 [`_kompress_zh_sample.json`](./_kompress_zh_sample.json)。

> 补充：LoRA adapter `Deserveall/kompress_zh-baseline-v1-lora` 在本机**只能直连 `huggingface.co` 下载成功**，
> `hf-mirror.com` 镜像的 blob/LFS 端点不通（文件列表 API 通、实际下载 0% 失败）。所以涉及该 adapter 时
> 用 `HF_ENDPOINT=https://huggingface.co`（base 模型则可走 ModelScope 缓存）。

压缩前后片段（锚点保留可见）：

```
原文(节选)：…工具 scripts/bind_check.sh 于 2026年6月22日上午九时三十分在生产网关节点 prod-gw-01 …
            目标端口 8790 … 读取服务配置文件 /etc/headroom-gateway/gateway.conf …
            listen_port 设置为 8790，backlog 设置为 1024，worker_processes 设置为 8 …
压缩后(节选)：…工具 scripts/bind_check.sh 于 2026 年 6 月 22 日上午 9 时 30 分在生产网关节点 prod-gw-01 …
            目标端口 8790 … 读取服务配置文件 /etc/headroom-gateway/gateway.conf，获取到
            listen_port 为 8790，backlog 为 1024，worker_processes 为 8 …
```

> 评测调参注意：默认 `max_new_tokens=192`（环境变量 `HEADROOM_KOMPRESS_ZH_MAX_NEW_TOKENS`）会限制
> 压缩输出长度。对本例 1647→315 的长材料，输出在中段即被截断（后续章节如 `EADDRINUSE`、修复建议未被保留）。
> 正式评测长中文材料时应**调高该值**（否则"准确率下降"会是输出截断所致，而非压缩本身）；反过来**调低它**
> 正好是评测方案 v1 §3.2 破坏组的天然旋钮。

## 8. 给上游项目的改进建议（Windows 部署缺陷）

1. **`is_kompress_zh_available()` 应捕获更宽异常**：当前只 `except ImportError`，torch 在
   Windows 上常抛 `OSError`（DLL 初始化失败），导致守卫不优雅降级、且无日志。建议
   `except (ImportError, OSError) as e: log; return False`。
2. **文档/依赖应区分平台 torch**：`[ml]` extra 只写 `torch>=2.0.0`，Windows 用户默认装到 cpu
   构建（非 ASCII 路径下还会 c10.dll 失败）。应在 Windows 文档中指明 cu128 GPU 构建，并显式列出
   `torchvision` / `qwen-vl-utils` / `av`（ms-swift Qwen 加载器隐式依赖）。
3. **明确禁止用 Anaconda base Python 建 venv**（OpenMP/MKL 冲突），推荐 uv 托管的干净 CPython。
4. **maturin/Rust 构建对无 cargo 的 Windows 用户不友好**：应提供预编译 wheel，或文档说明
   "源码内已带 `_core.pyd` 时如何免构建做 editable 挂载（写 `.pth`，注意 cp936 编码）"。
5. **（修订）Codex Responses 路径其实会压 `function_call_output`**：见 §9.4。真正问题是
   首次中文压缩超 30s 超时，而非完全没路由。
6. **应预加载 kompress_zh 并让压缩超时可配**：`eager_load_compressors` 目前只预加载英文 Kompress；
   kompress_zh 懒加载导致首个中文块必超 30s 超时（尤其消费级 GPU）。建议：① 启动一并预加载 kompress_zh；
   ② 把 `COMPRESSION_TIMEOUT_SECONDS` 改为可配置环境变量；③ 文档给出按 GPU 选择
   `HEADROOM_KOMPRESS_ZH_MAX_NEW_TOKENS` 的建议（弱 GPU 用更小预算以卡进超时）。

## 9. 命令入口与 proxy 注意事项（本机最终配置）

修复后，为避免"用错版本/旧 proxy 干扰"，做了以下收尾：

1. **卸载全局官方版**：`uv tool uninstall headroom-ai`。原因——全局上游版（`uv\tools\headroom-ai\`）
   **不含 `kompress_zh`**（只有英文 `kompress_compressor.py`）、且其 torch 同样 c10.dll 1114 坏掉；
   它常驻的 proxy 还会被 `wrap` 复用、干扰 zh 版。卸载前需先杀掉其所有进程（运行中会锁文件，
   报 os error 5）。
2. **zh 版命令入口 `headroom.cmd`**：因为本机是"预编译 `_core.pyd` + 手写 `.pth`"的免构建安装，
   **不会生成 `[project.scripts]` 的 `headroom` 控制台脚本**。故在
   `.venv\Scripts\headroom.cmd` 手动加了一行转发：`"%~dp0python.exe" -m headroom.cli %*`。
   激活 `.venv` 后 `headroom wrap codex` 即指向 zh 版（`(Get-Command headroom).Source` 应为该 .cmd）。
3. **proxy 按端口常驻、`wrap` 会复用**：proxy 是本地 HTTP/WS 服务器（默认端口 8787），`wrap` 见到
   端口被占就**复用**而非新建。所以每次启动前要 **先清端口**，否则你新设的环境变量
   （如 `HEADROOM_KOMPRESS_ZH_MAX_NEW_TOKENS`）不会生效：
   `Get-NetTCPConnection -LocalPort 8787 -State Listen -EA SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }`
   日常启动链见仓库根目录 `command.txt`。proxy 日志在 `C:\Users\<user>\.headroom\logs\proxy.log`。
4. **Codex 实时路径打通（compression 超时问题）**。经 wire-debug 抓包确认：Codex（gpt-5.x，
   WebSocket /v1/responses）**确实会把工具读取的中文内容以 `function_call_output` 送进来**，proxy
   也**确实路由进了 kompress_zh**（responses 路径只压 `function_call_output`/`local_shell_call_output`
   等"工具输出"，不压 user/system 消息，以保护 prefix 缓存）。真正卡点是 **30s 压缩超时**
   （`COMPRESSION_TIMEOUT_SECONDS=30`，写死）：
   - `eager_load_compressors` 启动时**只预加载英文 Kompress(ONNX)，不预加载 kompress_zh**，
     首次中文压缩要先加载 Qwen0.8B+adapter（本机实测 ~24.7s）+ 推理 → 超 30s → 超时 → 原样转发
     （日志 `compression failed; forwarding original: TimeoutError`，`opt_ms=30007`）。
   - 本机（RTX 4060 Laptop）warm 压缩 9000 字中文块耗时：预算 1024→59.5s、512→31.7s、**256→16.8s**。
     即使预热，512 也会超 30s。
   **修复（两件一起）**：
   - 代码补丁：在 `content_router.eager_load_compressors()` 增加 kompress_zh 预加载（启动多花 ~25s，
     消除首次请求的加载耗时）。见本仓库已应用的补丁。
   - 运行时：实时 Codex 路径设 `HEADROOM_KOMPRESS_ZH_MAX_NEW_TOKENS=256`（warm 压 9000 字块 16.8s，
     稳进 30s，省 ~95%）。1024/512 留给评测或更快的 GPU（AutoDL 4090 不超时）。
   （注：此"超时修复"是必要但**不充分**——见 §10，在本机即使预热 + 256 预算 + 90s 超时，
   实时压缩仍卡死，最终未在本笔记本上跑通；kompress_zh 能力本身另由评测 harness 38.5%@95%、
   直接样本 1647→315 省 81% 独立证实。）

## 10. 实时 Codex 路径"中文不压缩"的假设排查全记录

> 按时间顺序记录排查"为什么 `headroom wrap codex` 下 kompress_zh 不压缩中文"时的各种假设、验证与结论，
> 供后续 Windows 用户/维护者参考。
>
> **贯穿始终的前提**：**kompress_zh 本体没问题**——离线 harness（38.5% 节省 @ 95% 正确率）、
> 单样本（1647→315 省 81%）都证实它能压。问题只出在"**实时经 proxy 时不压缩**"。
> 现象演进：dashboard 一直显示 ~1.3% 节省（实为 `tool_schema_compaction` 固定省 109，kompress_zh 贡献为 0）。

| # | 假设 | 验证方式 | 结论 |
|---|---|---|---|
| H1 | 跑着的是**全局上游 proxy**（不含 kompress_zh、torch 还坏） | 查 8787 进程 = `uv\tools\headroom-ai` 的 anaconda python；proxy.log 报 c10.dll 1114 | ✅ **确认（早期主因之一）**。上游版无 `kompress_zh_compressor.py`，torch 坏 → 压不了。已卸载全局版、改用 zh proxy（§9.1） |
| H2 | dashboard % 被 codex 巨大上下文**稀释**（分母问题） | 算账：单中文块 ~1076 token，占 codex 整轮 ~28k token 的极小份额 | ⚠️ **部分成立**，但不是主因——后续发现 kompress_zh 压根没参与 |
| H3 | Responses API 路径**完全不路由**中文内容（只压 tool schema） | 看 PERF：`msgs=0`、`transforms=tool_schema_compaction` | ❌ **排除（最初判断有误）**。那是 codex *读文件前* 的帧没有工具输出；读完后确实路由（见 H6） |
| H4 | codex 没把文件作为可压缩 tool output 送来 / 内容被缓存 | wire-debug 抓包看 `input` items | ❌ **排除**。抓到 `function_call_output` 含 9090 中文字，确实送进来了 |
| H5 | 超大块被某**尺寸上限 / skip 集**跳过 | 读 `content_router.py` 找 max-size/skip 逻辑 | ❌ **排除**。有 skip 集/缓存/analysis-protect，但都不是此处原因 |
| H6 | **30s 压缩超时**（kompress_zh 首次懒加载 ~15-25s + 推理 > 30s） | proxy.log：`compression failed; TimeoutError`、`opt_ms=30007`；`eager_load_compressors` 只预加载英文 Kompress | ✅ **确认是直接现象**。打补丁预加载 kompress_zh + 把超时改可配（§9.4、改进建议 #6） |
| H7 | 块太大（prefill 太长），即使预热也超时 | 缩 bundle 到 ~10K 字后计时；测不同预算耗时 | ⚠️ **部分成立但不稳**。256 预算 9000 字=16.8s，但 10500 字飙到 44.8s（热降频，时间飘） |
| H8 | **多进程抢 GPU** 导致卡死 | 查进程：同时跑着 2 个 proxy + 2 个 wrap + 2 个 mcp | ❌ **被用户证伪**——最初"清掉 8787 单实例干净跑"也没压成，单 proxy 也卡 |
| H9 | **kompress_zh 在 proxy 工作线程里跑会卡死**（GPU 模型在非主线程/异步 executor 里线程不安全） | 关键证据：2528 字中文块（离线仅 ~8s）在 proxy 里也卡满 90s 超时——远超正常耗时 = "卡死"而非"慢"。计划用"主线程 vs 后台线程"对比实验最终确认（因工具中断未跑完） | ⚠️ **当前最可能、未最终实锤**。最能解释"离线能压、proxy 卡死"+"体感无等待"（codex 不同步等那条卡死线程） |
| H10 | **kompress_zh 未被干净"隔离"进 proxy，仍沿用 ms-swift 原生 Swift 推理框架** → proxy 里的调用方式偏离 AutoDL 上被验证的原生路径，适配性差 | 组员（AutoDL 跑通方）反馈：AutoDL 能跑是因为"compresszh 直接用那个 Swift 框架、没把它独立出来整" | ⚠️ **很可能是 H9 的根因层面**。把 Swift 引擎当 Transform 塞进 server 反复调用，偏离了它被验证的原生执行上下文 |
| H11 | ms-swift 的 Swift 推理引擎对**执行上下文有隐含假设**（主线程 / 单进程 / 自己的 CUDA stream 管理），proxy 每请求把它丢进临时 executor 线程反复调 → 违反假设 → 卡死 | 与 H9 同现象，但归因到"Swift 框架未隔离 + 上下文假设被破坏"，而非泛泛的"线程不安全" | ⚠️ 待验证；直接指向修复方向（见下） |

### 当前理解（截至排查暂停）

- **机制是通的**：codex 中文工具输出 → 路由 → kompress_zh，链路 1~4 步全部正常（H3/H4/H5 排除）。
- **卡点在第 5 步**：kompress_zh 的 GPU 推理**在 proxy 这个异步/多线程服务器环境里卡死**（连离线 8s 的小块也卡满超时），而离线同步脚本里正常。**最可能是线程安全/CUDA 上下文问题（H9）**，本机（RTX 4060 Laptop 8GB）上未跑通。
- **不是产品缺陷**：AutoDL/Linux + 4090 上同一条路队友已跑通（dashboard 48.9%）。本机问题是 Windows + 弱 GPU + 异步 proxy 的实时集成 bug。
- **务实结论**：**实时 dashboard 演示用 AutoDL；Windows 笔记本用离线 harness 评测**（已完成、严谨）。两条腿都有。
- 若要在 Windows 真正修通实时路径，需改 proxy 集成：让 kompress_zh 推理固定在主线程或一个常驻 worker（引擎也在该线程构建），而非每请求丢进 executor——属 fork 的代码改动，不在本次范围。

### 组员（AutoDL 跑通方）视角补充

组员判断"仍是环境/集成问题"：**AutoDL 上 kompress_zh 是"直接用 ms-swift 那个 Swift 框架、没把它独立出来整"才跑得通**；而 headroom 把它"独立"成 proxy 的一个 `Transform`、在异步 server 的 executor 线程里**按请求反复调用**，**偏离了 Swift 推理引擎被验证的原生执行上下文**，所以适配性差、在本机卡死。

这把根因从笼统的"Windows 线程不安全（H9）"进一步收敛到：**ms-swift 的 Swift 推理引擎没有被干净地隔离/适配进 proxy 的异步多线程模型（H10/H11）**。它解释了三件事的一致性：① 离线同步脚本（贴合 Swift 原生用法）能压；② AutoDL/Linux 上 proxy 也能压（Linux 线程/CUDA 行为更宽容 + GPU 快）；③ 本机 Windows proxy 卡死。

**据此细化的修复方向**（供后续工程）：
- 不要每请求把 Swift `TransformersEngine` 丢进临时 executor 线程；改为在**一个固定的常驻 worker 线程或独立子进程**里初始化引擎并**串行**处理压缩请求（贴合 Swift/transformers 引擎"单上下文、单线程"的隐含假设）。
- 或把 kompress_zh 压缩做成一个**独立的本地推理微服务**（HTTP/IPC），proxy 只发请求——彻底把 Swift 框架与 proxy 的异步事件循环隔离开。
- 这两种都是"把它真正独立出来整"，正是组员所说缺失的那一步。
