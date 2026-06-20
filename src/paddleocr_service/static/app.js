const output = document.querySelector("#output");
const serviceStatus = document.querySelector("#serviceStatus");
const modelStatus = document.querySelector("#modelStatus");
const queueStatus = document.querySelector("#queueStatus");
const diskStatus = document.querySelector("#diskStatus");
const jobs = document.querySelector("#jobs");
const detailMeta = document.querySelector("#detailMeta");
const jobError = document.querySelector("#jobError");
const pageNav = document.querySelector("#pageNav");
const versionInfo = document.querySelector("#versionInfo");
const modelCachePath = document.querySelector("#modelCachePath");
const databasePath = document.querySelector("#databasePath");
const accessLogPath = document.querySelector("#accessLogPath");
const corsOrigins = document.querySelector("#corsOrigins");
const downloadJson = document.querySelector("#downloadJson");
const downloadTxt = document.querySelector("#downloadTxt");
const downloadMarkdown = document.querySelector("#downloadMarkdown");
const toast = document.querySelector("#toast");

let selectedJob = null;
let selectedPageIndex = 0;
let toastTimer = null;

function show(value) {
  output.textContent =
    typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

function notify(message) {
  toast.textContent = message;
  toast.classList.add("visible");
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => toast.classList.remove("visible"), 2400);
}

function showError(message) {
  jobError.textContent = message;
  jobError.classList.remove("hidden");
}

function clearError() {
  jobError.textContent = "";
  jobError.classList.add("hidden");
}

async function jsonFetch(url, options) {
  const response = await fetch(url, options);
  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json")
    ? await response.json()
    : await response.text();
  if (!response.ok) {
    throw new Error(data.detail || data || response.statusText);
  }
  return data;
}

async function safeAction(action, fallbackMessage = "操作失败") {
  try {
    clearError();
    return await action();
  } catch (error) {
    const message = error.message || fallbackMessage;
    showError(message);
    notify(message);
    return null;
  }
}

function formatBytes(bytes) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

async function refreshHealth() {
  return safeAction(async () => {
    const data = await jsonFetch("/health");
    serviceStatus.textContent = data.status;
    renderEngineStatus(data);
    queueStatus.textContent = `${data.queue.queued} 等待 / ${data.queue.running} 运行${
      data.queue.paused ? " / 已暂停" : ""
    }`;
    diskStatus.textContent = formatBytes(data.storage.output_bytes);
    versionInfo.textContent = data.version;
    modelCachePath.textContent = data.model_cache_path;
    databasePath.textContent = data.storage.database_path;
    accessLogPath.textContent = data.settings.access_log_path || "-";
    corsOrigins.textContent = data.settings.cors_origins?.length
      ? data.settings.cors_origins.join(", ")
      : "未启用";
    return data;
  }, "刷新状态失败");
}

// Render the current engine + warmup phase into the "模型" status card.
// phase ∈ {idle, warming, failed}; "ready" is idle && engine_ready.
function renderEngineStatus(data) {
  const engineName = data.engine || "-";
  const phase = data.warmup?.phase || "idle";
  const ready = data.engine_ready;
  let badgeClass = "badge";
  let label = "未加载";
  if (phase === "warming") {
    badgeClass = "badge badge-blue";
    label = "预热中";
  } else if (phase === "failed") {
    badgeClass = "badge badge-danger";
    label = "预热失败";
  } else if (ready) {
    badgeClass = "badge badge-success";
    label = "就绪";
  } else {
    badgeClass = "badge badge-amber";
  }
  const title = data.warmup?.error ? ` title="${data.warmup.error}"` : "";
  modelStatus.innerHTML = `${engineName} <span class="${badgeClass}"${title}>${label}</span>`;
}

async function loadSettings() {
  return safeAction(async () => {
    const [settings, engines] = await Promise.all([
      jsonFetch("/settings"),
      jsonFetch("/engines"),
    ]);
    const engineSelect = document.querySelector("#settingEngine");
    engineSelect.innerHTML = engines.engines
      .map(
        (name) =>
          `<option value="${name}"${name === engines.current ? " selected" : ""}>${name}</option>`,
      )
      .join("");
    // Remember the server's current engine so saveSettings can detect a change.
    engineSelect.dataset.current = engines.current;
    document.querySelector("#settingLanguage").value = settings.language;
    document.querySelector("#settingPdfScale").value = settings.pdf_render_scale;
    document.querySelector("#settingMaxUploadMb").value = Math.max(
      1,
      Math.round(settings.max_upload_bytes / 1024 / 1024),
    );
    document.querySelector("#settingRetentionDays").value = settings.retention_days;
    document.querySelector("#settingSaveUploads").checked = settings.save_uploads;
    document.querySelector("#settingWarmup").checked = settings.warmup_on_startup;
    accessLogPath.textContent = settings.access_log_path || accessLogPath.textContent;
    corsOrigins.textContent = settings.cors_origins?.length
      ? settings.cors_origins.join(", ")
      : "未启用";
    return settings;
  }, "加载设置失败");
}

async function saveSettings(event) {
  event.preventDefault();
  return safeAction(async () => {
    const maxUploadMb = Number(document.querySelector("#settingMaxUploadMb").value || 1);
    const engineBefore = document.querySelector("#settingEngine").dataset.current || "";
    const payload = {
      engine: document.querySelector("#settingEngine").value,
      language: document.querySelector("#settingLanguage").value.trim() || "ch",
      pdf_render_scale: Number(document.querySelector("#settingPdfScale").value || 2),
      max_upload_bytes: maxUploadMb * 1024 * 1024,
      retention_days: Number(document.querySelector("#settingRetentionDays").value || 0),
      save_uploads: document.querySelector("#settingSaveUploads").checked,
      warmup_on_startup: document.querySelector("#settingWarmup").checked,
    };
    const saved = await jsonFetch("/settings", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    show(saved);
    notify("设置已保存");
    await refreshHealth();
    // If the engine changed, the new one warms in the background; poll /health
    // until the phase leaves "warming" so the badge updates live.
    if (saved.engine && saved.engine !== engineBefore) {
      pollWarmup();
    }
    return saved;
  }, "保存设置失败");
}

// Bounded poll loop for warmup progress. Clears itself once the phase is no
// longer "warming" or after ~60s (40 ticks * 1.5s). Only started after an engine
// swap, so it never runs continuously.
let warmupPollTimer = null;
function pollWarmup() {
  if (warmupPollTimer) {
    clearInterval(warmupPollTimer);
  }
  let ticks = 0;
  warmupPollTimer = setInterval(async () => {
    ticks += 1;
    const data = await refreshHealth().catch(() => null);
    const phase = data?.warmup?.phase;
    if (phase !== "warming" || ticks >= 40) {
      clearInterval(warmupPollTimer);
      warmupPollTimer = null;
    }
  }, 1500);
}

async function refreshJobs() {
  return safeAction(async () => {
    const data = await jsonFetch("/jobs");
    jobs.innerHTML = "";
    if (!data.jobs.length) {
      const empty = document.createElement("div");
      empty.className = "detail-meta";
      empty.textContent = "暂无历史任务";
      jobs.append(empty);
      return data;
    }
    for (const job of data.jobs) {
      const button = document.createElement("button");
      button.className = `job status-${job.status}`;
      button.type = "button";
      button.innerHTML = `<strong>${labelJobKind(job.kind)}</strong><div class="job-meta">${statusBadgeHtml(
        job.status,
      )} ${job.completed_units}/${job.total_units}</div>`;
      button.addEventListener("click", async () => {
        const detail = await jsonFetch(`/jobs/${job.id}`);
        renderJob(detail);
        scrollToPanel("resultPanel");
      });
      jobs.append(button);
    }
    return data;
  }, "刷新历史失败");
}

function statusBadgeHtml(status) {
  const badgeClass = {
    succeeded: "badge badge-success",
    failed: "badge badge-danger",
    canceled: "badge badge-danger",
    running: "badge badge-blue",
    queued: "badge",
  }[status] || "badge";
  return `<span class="${badgeClass}">${status}</span>`;
}

function labelJobKind(kind) {
  return kind === "image_batch" ? "批量图片" : "PDF";
}

function setDownloadLinks(job) {
  downloadJson.href = job.outputs?.json || "#";
  downloadTxt.href = job.outputs?.txt || "#";
  downloadMarkdown.href = job.outputs?.markdown || "#";
  for (const link of [downloadJson, downloadTxt, downloadMarkdown]) {
    link.classList.toggle("disabled", link.getAttribute("href") === "#");
  }
}

function allPages(job) {
  return job.documents.flatMap((document) =>
    document.pages.map((page) => ({
      filename: document.filename,
      ...page,
    })),
  );
}

function renderJob(job) {
  selectedJob = job;
  selectedPageIndex = Math.min(selectedPageIndex, Math.max(0, allPages(job).length - 1));
  detailMeta.textContent = `${labelJobKind(job.kind)} · ${job.status} · ${
    job.completed_units
  }/${job.total_units}`;
  if (job.error) {
    showError(job.error);
  } else {
    clearError();
  }
  setDownloadLinks(job);
  renderPageNav(job);
  renderSelectedPage();
}

function renderPageNav(job) {
  pageNav.innerHTML = "";
  const pages = allPages(job);
  pages.forEach((page, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = index === selectedPageIndex ? "active" : "";
    button.textContent = `${page.filename} · ${page.page_number}`;
    button.addEventListener("click", () => {
      selectedPageIndex = index;
      renderPageNav(job);
      renderSelectedPage();
    });
    pageNav.append(button);
  });
}

function renderSelectedPage() {
  if (!selectedJob) {
    show("等待操作...");
    return;
  }
  const pages = allPages(selectedJob);
  if (!pages.length) {
    show(selectedJob.error || "任务尚无结果。");
    return;
  }
  const page = pages[selectedPageIndex] || pages[0];
  const boxLines = page.items
    .map((item) => `${item.text} (${Math.round(item.confidence * 100)}%)`)
    .join("\n");
  const pageError = page.error ? `\n\n页面错误：${page.error}` : "";
  show(`${page.filename} / Page ${page.page_number}\n\n${page.text}${pageError}\n\n${boxLines}`);
}

async function pollJob(jobId) {
  for (;;) {
    const job = await jsonFetch(`/jobs/${jobId}`);
    renderJob(job);
    await refreshHealth();
    await refreshJobs();
    if (["succeeded", "failed", "canceled"].includes(job.status)) {
      return job;
    }
    await new Promise((resolve) => setTimeout(resolve, 800));
  }
}

async function retryJob() {
  if (!selectedJob) return;
  await safeAction(async () => {
    const job = await jsonFetch(`/jobs/${selectedJob.id}/retry`, { method: "POST" });
    notify("任务已重新加入队列");
    await pollJob(job.id);
  }, "重试失败");
}

async function cancelJob() {
  if (!selectedJob) return;
  await safeAction(async () => {
    const job = await jsonFetch(`/jobs/${selectedJob.id}/cancel`, { method: "POST" });
    renderJob(job);
    await refreshJobs();
    await refreshHealth();
    notify("任务已取消");
  }, "取消失败");
}

async function deleteJob() {
  if (!selectedJob) return;
  await safeAction(async () => {
    await jsonFetch(`/jobs/${selectedJob.id}`, { method: "DELETE" });
    selectedJob = null;
    detailMeta.textContent = "任务已删除";
    pageNav.innerHTML = "";
    clearError();
    show("任务和输出文件已删除。");
    await refreshJobs();
    await refreshHealth();
    notify("任务已删除");
  }, "删除失败");
}

async function copyText() {
  if (!selectedJob) return;
  await safeAction(async () => {
    const text = allPages(selectedJob)
      .map((page) => page.text)
      .filter(Boolean)
      .join("\n\n");
    await navigator.clipboard.writeText(text);
    notify("文本已复制");
  }, "复制失败");
}

async function runRetentionCleanup() {
  await safeAction(async () => {
    const result = await jsonFetch("/operations/retention/cleanup", { method: "POST" });
    show(result);
    await refreshJobs();
    await refreshHealth();
    notify(`已清理 ${result.deleted_jobs} 个过期任务`);
  }, "保留清理失败");
}

function scrollToPanel(id) {
  document.querySelector(`#${id}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  for (const trigger of document.querySelectorAll(".tabs-trigger")) {
    trigger.classList.toggle("active", trigger.dataset.scrollTarget === id);
  }
}

document.querySelector("#refreshHealth").addEventListener("click", refreshHealth);
document.querySelector("#refreshJobs").addEventListener("click", refreshJobs);
document.querySelector("#pauseQueue").addEventListener("click", async () => {
  await safeAction(async () => {
    await jsonFetch("/queue/pause", { method: "POST" });
    await refreshHealth();
    notify("队列已暂停");
  }, "暂停队列失败");
});
document.querySelector("#resumeQueue").addEventListener("click", async () => {
  await safeAction(async () => {
    await jsonFetch("/queue/resume", { method: "POST" });
    await refreshHealth();
    notify("队列已恢复");
  }, "恢复队列失败");
});
document.querySelector("#settingsForm").addEventListener("submit", saveSettings);
document.querySelector("#warmupModel").addEventListener("click", async () => {
  await safeAction(async () => {
    show(await jsonFetch("/operations/warmup", { method: "POST" }));
    await refreshHealth();
    notify("模型预热完成");
  }, "模型预热失败");
});
document.querySelector("#runRetentionCleanup").addEventListener("click", runRetentionCleanup);
document.querySelector("#retryJob").addEventListener("click", retryJob);
document.querySelector("#cancelJob").addEventListener("click", cancelJob);
document.querySelector("#deleteJob").addEventListener("click", deleteJob);
document.querySelector("#copyText").addEventListener("click", copyText);

for (const trigger of document.querySelectorAll(".tabs-trigger")) {
  trigger.addEventListener("click", () => scrollToPanel(trigger.dataset.scrollTarget));
}

document.querySelector("#singleForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  await safeAction(async () => {
    const file = document.querySelector("#singleImage").files[0];
    const formData = new FormData();
    formData.append("image", file);
    show(await jsonFetch("/ocr", { method: "POST", body: formData }));
    await refreshHealth();
    notify("单图识别完成");
  }, "单图识别失败");
});

document.querySelector("#batchForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  await safeAction(async () => {
    const formData = new FormData();
    for (const file of document.querySelector("#batchImages").files) {
      formData.append("images", file);
    }
    const job = await jsonFetch("/jobs/images", { method: "POST", body: formData });
    notify("批量任务已加入队列");
    scrollToPanel("resultPanel");
    await pollJob(job.id);
  }, "批量任务提交失败");
});

document.querySelector("#pdfForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  await safeAction(async () => {
    const file = document.querySelector("#pdfFile").files[0];
    const formData = new FormData();
    formData.append("pdf", file);
    const job = await jsonFetch("/jobs/pdf", { method: "POST", body: formData });
    notify("PDF 任务已加入队列");
    scrollToPanel("resultPanel");
    await pollJob(job.id);
  }, "PDF 任务提交失败");
});

refreshHealth();
refreshJobs();
loadSettings();
