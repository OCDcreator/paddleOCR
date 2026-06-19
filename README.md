# PaddleOCR LAN Service

把本机 PaddleOCR 封装成局域网私有 OCR 中台/工作台。它提供浏览器控制台、HTTP API、后台队列、SQLite 历史记录，以及 JSON/TXT/Markdown 结果导出。

产品规划与路线见 [PRODUCT_SPEC.md](PRODUCT_SPEC.md)。

## 能力

- `GET /`：打开局域网 OCR 工作台。
- `GET /health`：服务、模型、队列、设置、磁盘占用、版本和模型缓存路径。
- `POST /ocr`：上传一张图片并立即返回 OCR 文本。
- `POST /jobs/images`：上传多张图片，加入后台队列。
- `POST /jobs/pdf`：上传 PDF，按页渲染并 OCR。
- `GET /jobs` / `GET /jobs/{job_id}`：查看历史和任务详情。
- `GET /jobs/{job_id}/download/{json|txt|markdown}`：下载保存的 OCR 结果。
- `POST /jobs/{job_id}/retry`：重试失败或已取消的任务。
- `POST /jobs/{job_id}/cancel`：取消 queued/running 任务。
- `DELETE /jobs/{job_id}`：删除任务记录和输出文件。
- `POST /queue/pause` / `POST /queue/resume`：暂停或恢复队列。
- `GET /settings` / `PATCH /settings`：查看和调整运行设置。
- `POST /operations/warmup`：预热 OCR 模型。
- `POST /operations/retention/cleanup`：按保留天数删除过期任务和输出文件。

默认保存 OCR 结果和任务元数据；默认不保存原始上传文件。若需要保存原文件以便重启后重试，显式开启 `PADDLEOCR_SAVE_UPLOADS=true`。

## 环境

推荐 Python `3.11` 到 `3.13`。项目使用 `uv` 管理依赖。

```bash
cd /Volumes/SDD2T/obsidian-vault-write/custom-project/paddleOCR
uv sync --extra dev
cp .env.example .env
```

首次运行 PaddleOCR 会下载模型，耗时取决于网络和机器性能。

## 启动

```bash
cd /Volumes/SDD2T/obsidian-vault-write/custom-project/paddleOCR
uv run paddleocr-lan-service
```

等价命令：

```bash
uv run uvicorn paddleocr_service.main:app --host 0.0.0.0 --port 8866
```

浏览器工作台：

```text
http://127.0.0.1:8866/
```

局域网其他设备访问时，把 `127.0.0.1` 换成本机局域网 IP。

## 配置

`.env` 支持：

- `PADDLEOCR_SERVICE_HOST`：默认 `0.0.0.0`
- `PADDLEOCR_SERVICE_PORT`：默认 `8866`
- `PADDLEOCR_LANGUAGE`：默认 `ch`
- `PADDLEOCR_USE_ANGLE_CLS`：默认 `true`
- `PADDLEOCR_WARMUP_ON_STARTUP`：默认 `false`
- `PADDLEOCR_DATABASE_PATH`：默认 `data/paddleocr.sqlite3`
- `PADDLEOCR_OUTPUT_DIR`：默认 `outputs`
- `PADDLEOCR_UPLOAD_DIR`：默认 `uploads`
- `PADDLEOCR_SAVE_UPLOADS`：默认 `false`
- `PADDLEOCR_MAX_UPLOAD_BYTES`：默认 `52428800`，批量上传会按整个 multipart 请求大小限制
- `PADDLEOCR_PDF_RENDER_SCALE`：默认 `2.0`
- `PADDLEOCR_RETENTION_DAYS`：默认 `0`，`0` 表示不清理；大于 `0` 时可调用保留清理接口删除过期任务
- `PADDLEOCR_CORS_ORIGINS`：默认空，不启用跨来源；多个来源用英文逗号分隔
- `PADDLEOCR_ACCESS_LOG_PATH`：默认 `logs/access.log`，记录 method/path/status/耗时，不记录上传内容或 OCR 文本

设置页可在运行时调整语言、PDF 渲染倍率、上传限制、是否保存原文件、保留天数和启动预热。语言变化会使 OCR 引擎下次识别时重新加载。

运行时设置会校验范围：上传限制必须大于 `0`，PDF 渲染倍率必须大于 `0`，保留天数不能为负数。

## API 示例

生成样例文件：

```bash
uv run python scripts/create_sample_image.py
uv run python scripts/create_sample_pdf.py
```

单图 OCR：

```bash
curl -X POST http://127.0.0.1:8866/ocr \
  -F "image=@samples/ocr_sample.png"
```

批量图片：

```bash
curl -X POST http://127.0.0.1:8866/jobs/images \
  -F "images=@samples/ocr_sample.png" \
  -F "images=@samples/ocr_sample.png"
```

PDF：

```bash
curl -X POST http://127.0.0.1:8866/jobs/pdf \
  -F "pdf=@samples/ocr_sample.pdf"
```

下载结果：

```bash
curl -O http://127.0.0.1:8866/jobs/<job_id>/download/txt
curl -O http://127.0.0.1:8866/jobs/<job_id>/download/markdown
curl -O http://127.0.0.1:8866/jobs/<job_id>/download/json
```

按保留策略清理：

```bash
curl -X POST http://127.0.0.1:8866/operations/retention/cleanup
```

任务状态：

- `queued`：等待处理
- `running`：正在处理
- `succeeded`：完成
- `failed`：失败，查看 `error`
- `canceled`：用户取消

## 验证

自动化测试：

```bash
uv run --extra dev pytest -q
uv run ruff check .
```

功能测试需要先启动服务：

```bash
uv run python scripts/create_sample_image.py
uv run python scripts/create_sample_pdf.py
uv run python scripts/functional_check.py
```

功能脚本覆盖 health、设置、设置校验、CORS preflight、单图、批量图片、PDF、历史、导出下载、删除、暂停/取消/重试、保留清理。

## 运维

- SQLite 数据库默认在 `data/paddleocr.sqlite3`。
- OCR 输出默认在 `outputs/<job_id>/result.{json,txt,md}`。
- 原始上传文件默认不保存；开启后保存到 `uploads/<job_id>/`。
- 访问日志默认写入 `logs/access.log`，只包含请求元数据，不包含 OCR 结果文本。
- CORS 默认关闭；只在明确配置 `PADDLEOCR_CORS_ORIGINS` 后对指定来源开放。
- 保留清理通过 `/operations/retention/cleanup` 主动执行，适合放进本机定时任务。
- `/health` 显示队列统计、磁盘占用、数据库路径、输出目录、模型缓存路径和版本信息。
- 队列仍是单进程本地队列；不要把该服务直接暴露到公网。

## 可参考

- shadcn/ui: https://github.com/shadcn-ui/ui
- PaddleOCR GitHub: https://github.com/PaddlePaddle/PaddleOCR
- PaddleOCR PP-OCR 文档: https://paddlepaddle.github.io/PaddleOCR/latest/en/version3.x/pipeline_usage/OCR.html
- FastAPI 文件上传: https://fastapi.tiangolo.com/tutorial/request-files/
