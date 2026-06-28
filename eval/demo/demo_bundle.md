# headroom-zh AutoDL 演示交接 bundle（现场 demo 专用）

> 本文件是给 PPT 现场 demo 用的"长中文上下文阅读"材料：一份连贯的中文项目交接说明，
> 体量较大、锚点（端口/路径/命令/模型/数字/步骤）密布，专门用来让 codex 先通读、再回答 gist 问题，
> 从而在 dashboard 上看到有说服力的 kompress_zh 压缩率。内容为演示构造，但风格与真实交接文档一致。

## 一、项目目标与当前定位

本项目 headroom-zh 是上下文压缩中间件 headroom 的中文分支，核心新增是中文压缩通道 kompress_zh。
当前阶段目标只有一个：在已经证明"能省 token"的基础上，补齐"大幅压缩中文上下文时任务准确率不下降"的证据。
范围严格限定在中文为主、单块不少于 500 字、以工具输出形式进入上下文的内容；英文与结构化内容仍走原有通道，
不在本次范围。演示的最高优先级是：让评委一眼看到"中文长材料被压缩后，agent 仍能正确作答"。

当前验证路径是 Codex CLI 加本地 headroom 代理，上游走 OpenAI 兼容接口 https://yunwu.ai/v1，
模型固定为 gpt-5.4-2026-03-05，中文阅读型负载经 /v1/responses 流转，仪表板在 /dashboard 与 /stats-history 查看。
推荐的演示端口是 8790，整套演示在单机当天即可跑完，不依赖长时间训练。

## 二、已完成的工作

第一，本机 Windows 环境已修复，kompress_zh 中文压缩通道真正生效。此前的根因是 venv 建在了 Anaconda 的
base Python 上，Anaconda 注入的 MKL 与 Intel-OpenMP 和 torch 自带的 libiomp5md.dll 冲突，导致 torch 的
c10.dll 初始化失败（报错 WinError 1114），中文压缩被静默跳过。修复办法是改用干净的 uv 托管解释器
cpython-3.12.13 重建 venv，并安装 cu128 的 GPU 构建 torch，外加 ms-swift 的 Qwen 加载器隐式依赖
torchvision、qwen-vl-utils 与 av。修复后真实压缩验证：一条 1647 token 的中文样本压到 315 token，约省 81%。

第二，评测体系已经搭好并跑出主结果。共设计四类共二十题中文上下文任务，分别是长中文日志排错、
中文交接文档问答、中文多步操作指令复述、以及中文笔记语义三分类；每题都埋了不可丢失的锚点。
评测分三个对照条件：不压缩的 baseline、正常档（压缩预算 1024）、以及破坏档（压缩预算 64，仅用于自检指标区分度）。
主指标是任务正确率，采用人工盲判二值；辅助指标是答案锚点命中率；压缩则报告节省百分比。

第三，主结果已经出来：baseline 正确率 100%；正常档正确率 95%，平均节省约 38.5% token；
破坏档把压缩推到约 95.6% 节省时，正确率直接归零、锚点命中崩到 14%。这组对比同时证明了两件事：
正常档的"准确率基本保持"是真实的，而不是题目太简单送分；以及评测指标本身有区分度，一旦压坏立刻反映出来。

## 三、下一步的三项优先工作

第一项，准备 PPT 现场演示链路：用本 bundle 作为中文重负载，让 codex 先完整读取本文件，再回答四个 gist 问题，
确认 /dashboard 的 token 压缩量随中文输入增大而明显上升。注意启动命令必须用 zh 版，即
.\.venv\Scripts\python.exe -m headroom.cli wrap codex，不要用全局上游 headroom，否则中文通道不生效。

第二项，把正常档的压缩预算固化为环境变量 HEADROOM_KOMPRESS_ZH_MAX_NEW_TOKENS，
在保真与节省之间取一个稳定操作点；演示时如果更看重压缩率可调低，更看重答对率可调高到 1024 或以上。

第三项，整理交付物并归档：评测方案、构思与审核纪要、评测结果、Windows 部署修复记录等
记录文档放在 eval_docs 目录下；评测代码（harness）、材料（materials）、演示（demo）与
requirements-windows.txt 依赖清单放在 eval 目录下，确保可复核、可复现。

## 四、风险与依赖

第一，依赖远端模型与网络：base 模型 Qwen/Qwen3.5-0.8B 走 ModelScope 缓存，
LoRA adapter Deserveall/kompress_zh-baseline-v1-lora 只能直连 https://huggingface.co 下载，
hf-mirror.com 的 blob 端点本机不通，因此涉及 adapter 时必须设置 HF_ENDPOINT 为 https://huggingface.co。

第二，演示任务体量风险：如果给 agent 的中文内容太小，压缩量摊到 codex 的庞大系统提示与历史里，
dashboard 的百分比会很低，使系统看起来没用，即使链路其实是通的。所以演示必须用足够大的中文阅读材料。

第三，环境一致性风险：不要用 Anaconda 的 Python 做 venv 基底；Windows 训练或推理涉及多进程时，
还要注意 dataloader 的 worker 数设为 0，避免 spawn 无法 pickle 闭包的问题。

第四，关键路径与凭据：AutoDL 上 Python 解释器默认在 /root/autodl-tmp/qwen_ws/.venv/bin/python，
代理脚本读取 /root/.config/headroom-zh/env.sh 获取密钥，Rust core 在该路径下被显式设为
HEADROOM_REQUIRE_RUST_CORE=false。本地凭据不要明文写进任何提交文件，用完及时轮换。

## 五、给接手同学的建议顺序

先读本文件，再看 eval_docs/评测方案_v1.md 与 eval_docs/评测结果_v1.md；
随后按 eval_docs/Windows部署修复记录.md 确认本机环境；
最后用本 bundle 做一次现场 demo，确认 dashboard 的压缩量随中文输入显著上升。
任何新踩的环境坑，请追加到 Windows 部署修复记录里，不要在多处分散改写。

## 附录：相关中文材料汇编（节选）

### contexts\A1

本文档记录 headroom-zh 代理服务于 2026年6月22日早晨八时在宿主机 dev-node-07 上的启动尝试。宿主机操作系统为 Ubuntu 22.04.3 LTS，内核版本 5.15.0-105-generic。启动由脚本 scripts/start_proxy.sh 发起，以下为完整的运行日志与分析说明。

一、系统初始化与基本配置加载

脚本启动后首先读取主配置文件 /etc/headroom-zh/proxy.conf，获取到的关键配置如下：监听地址设置为 0.0.0.0，监听端口配置为 7421，日志级别为 INFO。随后脚本初始化日志目录 /var/log/headroom-zh/，检测宿主机磁盘剩余空间为 84.3 GB，满足最低 10 GB 的空间要求，初始化阶段全部通过。

二、Python 环境与依赖包校验

脚本加载 Python 虚拟环境 /opt/headroom-zh/venv/，解释器版本为 Python 3.11.6，包管理工具 pip 版本为 23.3.1。随后逐一核验 requirements.txt 中列出的 47 个依赖包，主要包括：fastapi 0.110.0、uvicorn 0.29.0、httpx 0.27.0、tiktoken 0.6.0、pydantic 2.7.1 等，全部已安装且版本与要求一致，无任何缺失或版本冲突。依赖校验阶段耗时约 2 秒，全部通过。

三、环境变量解析

脚本读取配置文件 /root/.config/headroom-zh/env.sh，解析出以下变量：HEADROOM_LISTEN_PORT 值为 7421（有效），HEADROOM_LOG_LEVEL 值为 INFO（有效），HEADROOM_MAX_TOKENS 值为 8192（有效），HEADROOM_CACHE_DIR 值为 /tmp/headroom-zh/cache（有效）。以上变量均成功解析，脚本继续执行。

接下来脚本尝试读取上游 API 密钥，用于将用户请求转发至 OpenAI 兼容接口。脚本在配置文件 /root/.config/headroom-zh/env.sh 中搜索变量 OPENAI_API_KEY，未找到任何定义；随即回退至系统环境变量，同样未检测到 OPENAI_API_KEY 被设置（unset）。脚本输出警告但仍继续进入预检阶段。

四、预检模块执行过程

脚本启动预检模块 preflight_check.py，共执行十二项检查。第一项：网络连通性检查，目标 api.openai.com:443，可达，通过。第二项：DNS 解析检查，api.openai.com 解析为 104.18.6.166，通过。第三项：本地端口 7421 占用检查，当前未被占用，通过。第四项：缓存目录 /tmp/headroom-zh/cache 写权限，通过。第五项：TLS 证书 /etc/headroom-zh/tls/server.crt 存在性，通过。第六项：TLS 私钥 /etc/headroom-zh/tls/server.key 存在性，通过。第七项：Redis 连接检查，地址 127.0.0.1:6379，连接成功，通过。第八项：磁盘 inode 检查，剩余 1,847,332 个，通过。第九项：CPU 核心数 16，满足最低 2 核要求，通过。第十项：内存可用 28.6 GB，满足最低 2 GB 要求，通过。第十一项：Python 版本 3.11.6 满足最低 3.9 要求，通过。

第十二项为上游 API 密钥有效性验证，这是最关键的一项检查。由于变量 OPENAI_API_KEY 在配置文件 /root/.config/headroom-zh/env.sh 中未定义，且系统环境变量中同样未设置该变量，预检模块无法完成密钥验证，第十二项检查以失败告终，错误码为 CFG-4031。

五、失败结论与处置建议

预检模块因第十二项失败而判定整个预检流程不通过，代理服务拒绝启动。错误信息明确提示：请在 /root/.config/headroom-zh/env.sh 中补充定义 OPENAI_API_KEY 后重新执行 scripts/start_proxy.sh。preflight_check.py 以退出码 1 退出，脚本 scripts/start_proxy.sh 随即终止执行，未进入服务绑定和 uvicorn 启动流程。

六、收尾处理

脚本清理了临时文件 /tmp/headroom-zh/preflight_tmp_*（共 3 个），并将本次启动日志归档至 /var/log/headroom-zh/startup_20260622_080116.log。本次启动尝试失败，总耗时约 13 秒，请运维人员尽快补充配置后重新尝试启动。

### contexts\A2

以下是模型缓存拉取任务 pull-task-20260622-003 的完整执行日志，任务由调度器 cache_puller.py 于 2026年6月22日 10:15 发起，目标模型为 qwen2.5-72b-instruct-q4_k_m，上游仓库地址 https://hf-mirror.internal.cluster/qwen2-5-72b，超时设置 3600 秒。

任务初始化阶段，调度器读取拉取配置文件 /opt/model-cache/pull_config.yaml，确认本地缓存目录 /data/model-cache/qwen2-5-72b/ 不存在，判断需要执行全量下载。脚本随即创建目标目录并设置权限为 755，准备工作完成。

元数据文件拉取阶段，首先拉取模型元数据文件 config.json（约 4.2 KB），MD5 校验通过，校验值 a3f7c291de48b6e1f002d39a0145c8d7；随后拉取分词器文件 tokenizer.json（约 11.3 MB），MD5 校验通过，校验值 7b82de3041a9f1c6e58d702344b9c01a。元数据文件下载完毕。

权重分片下载阶段，模型共有 41 个权重分片，每个分片大小约 4.96 GB。第 1 号分片 model-00001-of-00041.safetensors 下载耗时 422 秒，校验通过；第 2 号分片耗时 431 秒，校验通过；第 3 号分片耗时 445 秒，校验通过。前 3 个分片完成时，磁盘已用 14.9 GB，剩余可用 52.1 GB，估计剩余时间约 16,910 秒。

此后任务分批次继续下载：第 4 至 10 号分片批次于 11:24 完成，7 个文件全部通过 MD5 校验，磁盘剩余 47.8 GB；第 11 至 20 号分片批次于 12:49 完成，10 个文件全部通过校验，磁盘剩余 36.2 GB；第 21 至 30 号分片批次于 14:19 完成，10 个文件全部通过校验，磁盘剩余 24.5 GB。至此前 30 个分片均已成功下载并通过完整性校验。

第 31 至 35 号分片于 14:20 至 14:56 之间逐一拉取完成，均通过 MD5 校验。

第 36 号分片 model-00036-of-00041.safetensors 于 15:03 首次下载完成后，MD5 校验失败，预期校验值为 8f2c1a9d3e57b04f6c8a21d9b34e7f50，实际计算值为 c4a37b8e1d20f96a5b3e0c14d72f9381，两者不一致。系统自动发起第 2 次重试，下载完成后再次计算 MD5 值，得到相同的不一致结果 c4a37b8e1d20f96a5b3e0c14d72f9381，第 2 次重试失败。系统继续发起第 3 次重试，15:18 再次下载完成，MD5 值依然为 c4a37b8e1d20f96a5b3e0c14d72f9381，与预期值 8f2c1a9d3e57b04f6c8a21d9b34e7f50 不符，已超出最大重试次数 3 次，系统放弃该分片，记录错误码 CACHE-7712。

由于第 36 号分片持续校验失败，错误信息提示上游仓库返回的文件可能已损坏或网络传输存在系统性问题，任务判定无法继续，第 37 至 41 号分片均未执行下载。

任务 pull-task-20260622-003 于 15:18 异常终止，任务状态写入文件 /opt/model-cache/task_status/pull-task-20260622-003.json，退出码为 2。本次共成功拉取 35 个分片，第 36 号分片（model-00036-of-00041.safetensors）因 MD5 校验三次失败而终止，错误码 CACHE-7712，第 37 至 41 号分片未执行。建议联系仓库管理员确认 /data/model-cache/qwen2-5-72b/ 中已下载分片的完整性。任务总耗时 18,211 秒，完整日志保存至 /var/log/model-cache/pull-task-20260622-003.log。

### contexts\A3

本文档记录持续集成流水线 ci-pipeline-#8841 的完整构建过程与失败原因分析。本次构建由提交哈希 3d7a9f2c 触发，来源分支为 feature/add-zh-compress，构建机器为 build-agent-04，于 2026年6月22日下午两时整启动，项目版本号 0.8.3-dev，构建后端为 hatchling。本文档适用于排查该次构建失败的工程师。

一、构建准备阶段

流水线首先读取项目构建配置文件 pyproject.toml，确认项目名称为 headroom-zh，版本号为 0.8.3-dev，构建后端为 hatchling。激活 Python 虚拟环境 .venv/，解释器版本为 Python 3.11.9，包管理工具 pip 版本为 24.0。准备工作完成后，流水线执行命令 pip install -e ".[dev]"，开始解析依赖树，解析完成后确认需安装或更新的软件包共 63 个。

二、常规依赖包安装情况

以下依赖包均已成功安装，安装过程无任何异常或警告，可视为正常通过：annotated-types 0.6.0、anyio 4.3.0、certifi 2024.2.2、charset-normalizer 3.3.2、click 8.1.7、colorama 0.4.6、fastapi 0.110.2、h11 0.14.0、httpcore 1.0.5、httpx 0.27.0、idna 3.6、jieba 0.42.1、opencc-python-reimplemented 0.1.7、pydantic 2.7.1、pydantic-core 2.18.2、regex 2024.4.16、rich 13.7.1、starlette 0.37.2、tiktoken 0.6.0、typing-extensions 4.11.0、uvicorn 0.29.0。以上二十一个核心依赖包全部成功安装，累计耗时约十七秒。

三、可选依赖 fugashi 安装失败（不影响核心功能）

流水线尝试安装可选包 fugashi 1.3.0，该包提供日语分词支持，在 pyproject.toml 中标记为可选（optional）。安装过程中，fugashi 需要系统库 libmecab-dev 的支持，流水线调用系统包管理器检查该系统库是否已安装，检查结果为 build-agent-04 上缺少 libmecab-dev，apt-get 返回错误码 E_PKG_NOT_FOUND，fugashi 的安装过程因此失败，报错信息为 libmecab.so.2: cannot open shared object file: No such file or directory。由于该包仅为可选依赖，流水线在输出一条警告信息后选择跳过，日语分词功能将不可用，但中文压缩的核心处理流程不受任何影响，流水线继续执行后续安装步骤。

四、核心依赖 sentencepiece 安装失败（致命错误）

流水线成功安装 transformers 4.40.1，耗时约三秒，安装完成。随后流水线尝试安装核心依赖包 sentencepiece 0.2.0，该包是项目中文分词功能不可缺少的核心组件，在 pyproject.toml 中被明确标记为强制必须安装的依赖（required）。

sentencepiece 0.2.0 的安装过程如下：流水线首先从 PyPI 检索适用于 Python 3.11、linux 平台、x86_64 架构的预编译 wheel 文件，检索结果为不存在对应的预编译 wheel 包，流水线随即转为尝试从源码在本机进行编译安装。源码包 sentencepiece-0.2.0.tar.gz（文件大小 1.87 MB）下载完毕后，流水线执行 setup.py bdist_wheel 命令并检查编译所需的工具链。工具链检查的关键发现：build-agent-04 上未安装 cmake，文件路径 /usr/bin/cmake 不存在。cmake 是 sentencepiece 源码编译过程中不可缺少的构建工具，缺少该工具导致编译过程无法启动，流水线报告错误码 BUILD-2051，sentencepiece 0.2.0 安装失败并终止。

由于 sentencepiece 0.2.0 在项目中标记为强制依赖（required），其安装失败直接导致整条构建流水线 ci-pipeline-#8841 无法继续执行，流水线以退出码 1 终止。

五、失败结论与修复建议

构建失败的根本原因清晰明确：构建机器 build-agent-04 缺少 cmake，导致强制依赖 sentencepiece 0.2.0 无法从源码编译安装。修复方法同样简单：请在构建机器 build-agent-04 上执行 apt-get install cmake 安装 cmake，安装成功后重新触发构建流水线 ci-pipeline-#8841，届时 sentencepiece 的源码编译流程将能够顺利完成，整个构建流水线预计可正常通过。本次构建总耗时三十三秒，构建日志已完整保存至 /var/log/ci/ci-pipeline-8841.log，请相关工程师参阅日志并尽快完成修复。

### contexts\A4

本文档记录端口检测与服务绑定工具 scripts/bind_check.sh 于 2026年6月22日上午九时三十分在生产网关节点 prod-gw-01 上的完整执行过程与失败分析。节点操作系统为 CentOS Stream 9，内核版本 5.14.0-362.8.1.el9.x86_64，目标服务为 headroom-gateway，预期绑定地址 0.0.0.0，目标端口 8790，协议为 TCP。

一、配置读取阶段

脚本首先读取服务配置文件 /etc/headroom-gateway/gateway.conf，获取到以下关键配置：listen_port 设置为 8790，backlog 设置为 1024，worker_processes 设置为 8，配置文件读取过程顺利，无任何异常。

二、端口占用预检阶段

脚本调用 ss -tlnp 工具对目标端口 8790 进行扫描。扫描结果显示：协议 TCP，状态为 LISTEN，本地监听地址 0.0.0.0:8790，当前持有该端口的进程名为 nginx，进程标识号（PID）为 31847。这意味着端口 8790 已被 nginx 进程占用，headroom-gateway 在未释放该端口的情况下无法完成绑定。

为进一步明确占用进程的身份，脚本读取 /proc/31847/cmdline 的内容，显示为 nginx: master process /usr/sbin/nginx -c /etc/nginx/nginx.conf，确认该进程是系统 nginx 主进程，属于系统基础服务而非 headroom 服务栈的组件，脚本判断不可自动强制终止该进程。通过检查 systemd 单元 nginx.service 的状态，确认其处于 active (running)，该服务于 2026年6月20日 03:12:44 启动，已持续稳定运行约五十四小时。

三、备用端口回退尝试

脚本尝试读取环境变量 HEADROOM_FALLBACK_PORT，以期自动切换至备用端口，但该变量当前未设置（unset），无法自动降级，脚本继续尝试强制绑定 0.0.0.0:8790 进行确认。

四、绑定失败详情

脚本调用 Python socket 接口执行 socket.bind(('0.0.0.0', 8790))，绑定操作立即失败。系统返回错误信息：[Errno 98] Address already in use，对应 POSIX 系统错误码 EADDRINUSE，端口 8790 仍被 nginx（PID 31847）持有，headroom-gateway 服务无法启动。

完整错误消息为：OSError: [Errno 98] EADDRINUSE — bind() 调用失败，目标地址 0.0.0.0:8790。脚本提供三条修复建议：其一，停止 nginx 服务，执行 systemctl stop nginx；其二，在配置文件 /etc/headroom-gateway/gateway.conf 中将 listen_port 字段修改为其他可用端口；其三，设置环境变量 HEADROOM_FALLBACK_PORT 为可用端口号后重新启动 headroom-gateway 服务。

五、自动端口诊断

脚本自动扫描 8791 至 8799 范围内各端口的可用性：端口 8791 已被进程 frpc（PID 22103）占用；端口 8792 当前空闲可用；端口 8793 当前空闲可用。脚本建议将配置文件 /etc/headroom-gateway/gateway.conf 中的 listen_port 字段修改为 8792 或 8793 以绕过冲突，或采用 nginx 反向代理方案，将外部流量转发至 headroom-gateway 在内部端口上的监听