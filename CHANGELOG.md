# 更新日志 / Changelog

本项目记录用户可感知的变化。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [未发布 / Unreleased]

## [0.2.0] — 2026-06-20

首个可插拔 OCR 后端版本。**默认引擎从 PaddleOCR 改为 RapidOCR(ONNX)**,PaddleOCR 保留为可选。基于实测数据(RapidOCR 在 Apple Silicon 上比 PaddleOCR 快约 3 倍且更鲁棒)。

> ⚠️ **Breaking(破坏性变更):安装方式变了**
> `paddleocr`/`paddlepaddle` 从主依赖降为**可选 extra**,`rapidocr_onnxruntime` 也是可选 extra。原来的 `uv sync --extra dev` 不再安装任何 OCR 引擎。
> 新的安装方式:
> ```bash
> uv sync --extra dev --extra rapidocr              # 默认引擎(推荐)
> uv sync --extra dev --extra rapidocr --extra paddleocr   # 两个都要
> ```
> 默认引擎由 `PADDLEOCR_ENGINE` 控制(默认 `rapidocr`)。

### 新增

- **可插拔 OCR 后端**:统一的 `OCREngine` 协议 + 注册表,`PaddleOCREngine` 与 `RapidOCREngine` 都实现它。新增引擎只需实现协议并注册。
- **默认引擎改为 RapidOCR(ONNX)**:Mac 实测中位延迟 240ms(对比 PaddleOCR 786ms),大图/密集多行场景更鲁棒。
- **运行时热切换**:`PATCH /settings {"engine":"paddleocr"}` 不重启切换引擎。原子替换引擎引用,不打断在跑的 OCR。
- **缺失库快速失败**:切换到未安装的引擎立即返回 `422` + 安装提示(`uv sync --extra <engine>`),不再静默成功。
- **异步后台预热**:切换后后台加载新引擎模型,PATCH 立即返回(不再卡 12-27 秒)。`/health` 的 `warmup` 块上报状态机进度(`idle` / `warming` / `failed` + 开始时间 + 错误)。
  - 注意:PaddleOCR/RapidOCR 的构造函数是模型加载黑盒,无进度回调——上报的是**离散状态阶段,不是百分比**。
- **预热软取消**:切换到一个新引擎时,取消上一个在途的后台预热(asyncio 软取消;底层库调用可能仍跑完,但不再追踪结果)。
- **预热失败自动回退**:后台预热失败时,自动回退到切换前最后一个**已确认就绪**的引擎。带 generation 防护(不覆盖更新的用户切换)+ 无限循环防护(只回退到已验证引擎)。
- **`GET /engines` 端点**:返回可用引擎列表 + 当前引擎,供前端动态填充下拉框。
- **前端引擎选择 + 预热状态 UI**:设置面板新增 OCR 引擎下拉框;"模型"状态卡显示引擎名 + 预热状态 badge(就绪 / 预热中 / 预热失败 / 未加载),切换后短期轮询实时刷新。
- **OCR 引擎对比基准**:`scripts/benchmark_*` + `scripts/benchmark_adapters/`,带标准答案的合成图,跨平台(含中文字体回退),生成 `docs/verification/<date>-engine-benchmark.{json,md}`。

### 变更

- **依赖结构**:`paddleocr`/`paddlepaddle` → 可选 extra `paddleocr`;新增可选 extra `rapidocr`(`rapidocr_onnxruntime`)。
- **`pypdfium2` 提升为主依赖**:原来是 paddleocr 的传递依赖,paddleocr 降级后会消失;但 PDF 渲染是核心功能,必须显式依赖。
- **代码重构**:`src/paddleocr_service/ocr_engine.py`(原 161 行,混 4 个职责)删除,拆成 `engines/base.py`(协议 + 共享工具)+ `registry.py` + `engines/paddleocr/{engine,parser}.py` + `engines/rapidocr/{engine,parser}.py`。一文件一职责。
- **`/health` 字段**:`ocr_loaded` 改名为 `engine_ready`,新增 `engine`(当前引擎名)和 `warmup`(预热状态)。
- **默认引擎**:`PADDLEOCR_ENGINE` 默认值从 `paddleocr`(隐式)改为 `rapidocr`。

### 修复

- **生产崩溃(无文本结果)**:`ocr_engine.py` 用 `a or b or c` 链处理 PaddleOCR 的 box 字段,而 PaddleOCR 在**检测不到文本**的图上返回空 numpy 数组——空数组的布尔转换抛 `ValueError: truth value of an empty array is ambiguous`。任何 OCR 检测不到文本的图(空白、低对比、大图)都会让服务 **500 崩溃**。改用 numpy 安全的 `_first_present()`(显式 `is None` 检查,不触发布尔转换)。**同时修了生产服务和基准适配器两处。**
- **RapidOCR 元组解包**:基准适配器假设 `RapidOCR()` 返回 lines 列表,实际返回 `(lines, elapse)` 二元组。
- **前端"模型"卡回归**:改名 `ocr_loaded`→`engine_ready` 时漏改前端,模型卡一直显示"未加载"。改为 `renderEngineStatus` 渲染引擎名 + 预热 badge。

### 验证

- 78 个自动化测试全过(新增:registry、两个引擎(mock)、引擎切换、缺失库 422、后台预热 phase + 取消、自动回退、`/engines` 端点)。
- ruff lint 干净。
- Mac(Apple Silicon, Python 3.13)端到端实测:默认 RapidOCR OCR 正常;热切换到 PaddleOCR 后真实 OCR 正常;缺失库切换 → 422;预热中切换取消;t+100ms 抓到 `warming` phase;`uv sync --extra rapidocr` 不装 PaddlePaddle 也能跑。
- 完整对比数据见 `docs/verification/2026-06-19-engine-benchmark.json`。

## [0.1.0] — 2026-06-17

初始版本:把本机 PaddleOCR 封装成局域网 OCR 工作台。

- 单图 OCR(`POST /ocr`)、批量图片(`POST /jobs/images`)、PDF(`POST /jobs/pdf`)
- 进程内队列 + SQLite 历史记录,JSON/TXT/Markdown 导出
- 重试 / 取消 / 删除 / 暂停 / 恢复
- 运行时设置页,shadcn/ui 风格的无构建静态前端
- 上传大小/类型校验,可选原始文件保留,CORS 白名单,访问日志(不含 OCR 文本)
