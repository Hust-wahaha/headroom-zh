# PPT 现场 demo：让 dashboard 显示有说服力的 kompress_zh 压缩率

目的：用一份大体量中文材料（[`demo_bundle.md`](./demo_bundle.md)，约 5.4 万字 / ≈2.8 万 tokens）作为请求主体，
让 codex 先通读、再回答 gist 问题，从而在 `/dashboard` 上看到中文压缩通道 kompress_zh 的明显节省。

> 为什么要这样：单个小中文文件的压缩量会被 codex 庞大的系统提示/历史稀释（之前看到的 1.4% 就是这个原因）。
> 把中文内容做大、成为请求主体，dashboard 的百分比才有说服力。这也是 kompress_zh 宣称的"长中文上下文阅读"主场。

## 启动（PowerShell，务必用 zh 版）

```powershell
cd <repo>
conda deactivate
$env:OPENAI_BASE_URL = "https://yunwu.ai/v1"
$env:OPENAI_API_KEY  = "sk-你的新key"          # 旧 key 请已吊销；不要写进提交文件
$env:PYTHONUTF8 = 1
$env:HF_ENDPOINT = "https://huggingface.co"     # adapter 只在 HF，hf-mirror blob 不通
$env:HEADROOM_KOMPRESS_ZH_MAX_NEW_TOKENS = 1024 # 压缩预算：1024 保前部 gist；调低→压更狠、节省%更大

# zh 版必须用 venv python -m，不能用裸 headroom（那是全局上游版，没有 kompress_zh）
.\.venv\Scripts\python.exe -m headroom.cli wrap codex
```

## 在 codex 里粘贴这段提问

```
请先完整读取 <repo>\eval\demo\demo_bundle.md 全文，
然后只依据该文件回答以下四个问题：
1. 这个项目当前阶段的唯一目标是什么？
2. 已完成的工作有哪三项？
3. 下一步的三项优先工作是什么？
4. 主要风险与依赖有哪些？请列出其中关键的端口、路径与必须设置的环境变量。
```

四个问题对应 bundle 的"目标/已完成/下一步/风险"四节，都是 gist 信息、位于文件前部；
即使后面的"附录材料汇编"被压缩掉，这些答案仍能保留——正好演示"压缩后仍可作答"。

## 现场看什么（PPT 讲解点）

1. **TOKEN SAVINGS**：codex 读入 ≈2.8 万 tokens 的中文后，kompress_zh 把它压到约 1024 tokens，
   移除约 2.7 万 tokens。因为这块中文是请求主体，dashboard 的压缩百分比会从之前的 1.4% **大幅跳升**。
2. **Savings Breakdown → Compression**：对应 kompress_zh 移除的 proxy tokens 明显增大。
3. **OVERHEAD**：会比小文件时更高（几十秒），那正是压缩模型在 GPU 上处理 2.8 万 token 输入的耗时——
   说明 kompress_zh 真的在跑。
4. **codex 的回答**：仍能正确说出目标、已完成三项、下一步三项、以及风险中的关键锚点
   （端口 8790、路径 /root/autodl-tmp/qwen_ws/.venv/bin/python、环境变量
   HEADROOM_REQUIRE_RUST_CORE=false 与 HF_ENDPOINT 等）→ "压缩但仍可执行"。

## 确认压缩确实来自 kompress_zh（而非其它变换）

看启动 `wrap codex` 那个终端的 proxy 日志，应出现类似标记：
`router:tool_result:text` 或 kompress_zh 相关条目。若只看到 SmartCrusher/cache 相关而无中文压缩标记，
说明中文工具输出没被路由进 kompress_zh，需要排查（多半是上下文未以"工具输出/中文块≥500字"的形态进入）。

## 想要更夸张的数字

- 把 `HEADROOM_KOMPRESS_ZH_MAX_NEW_TOKENS` 调低（如 256/128）→ 压缩更狠、节省% 更大（但回答会变粗）。
- 或让 codex 连续读多份大中文文件，进一步抬高中文在请求中的占比。

> 口径提醒（与评测一致）：dashboard 的百分比是"压缩量 ÷ codex 整条线"；
> 评测里的 38–59% 是"压缩量 ÷ 中文块本身"。两者分母不同，演示时讲清楚即可，不要混为一谈。
