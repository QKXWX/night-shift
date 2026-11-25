const $ = (id) => document.getElementById(id);
let state = null;
let localRemaining = 0;
let timerHandle = null;

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  return response.json();
}

function fmt(seconds) {
  const safe = Math.max(0, Number(seconds) || 0);
  return `${String(Math.floor(safe / 60)).padStart(2, "0")}:${String(safe % 60).padStart(2, "0")}`;
}

function renderChecks(checks) {
  $("checks").innerHTML = checks.map((item) => `
    <div class="check ${item.ok ? "ok" : "bad"}">
      <span class="dot"></span>
      <div><b>${item.label}</b><small>${item.detail}</small></div>
      <span class="tag">${item.ok ? "正常" : "异常"}</span>
    </div>`).join("");
}

function renderEvidence(lines) {
  $("evidence").textContent = lines.length ? lines.join("\n") : "没有输出。";
}

function renderFix(state) {
  const box = $("fixBox");
  if (state.fix_action === "clean_disk") {
    box.innerHTML = `<p class="muted">缓存文件占满了磁盘预算。清理后服务会在下一次请求时恢复。</p>
      <button id="btnFix" class="primary wide">清理 cache.bin</button>`;
  } else {
    const placeholder = state.fix_action === "dns_ip" ? "例如 127.0.0.1" : "例如 18080";
    box.innerHTML = `<label>${state.fix_label}</label>
      <div class="fixrow"><input id="fixValue" autocomplete="off" placeholder="${placeholder}">
      <button id="btnFix" class="primary">写入并检查</button></div>
      <p class="muted">写入后会立刻用真实请求验收，不会“假装成功”。</p>`;
  }
  $("btnFix").addEventListener("click", applyFix);
}

async function refresh() {
  const data = await api("/api/state");
  state = data.state;
  $("caseNo").textContent = `#NS-${state.scenario.toUpperCase()}`;
  $("title").textContent = state.title;
  $("subtitle").textContent = state.subtitle;
  $("ticket").textContent = state.ticket;
  $("brief").innerHTML = state.brief.map((line) => `<li>${line}</li>`).join("");
  renderChecks(state.checks);
  renderFix(state);
  localRemaining = state.remaining;
  $("timer").textContent = fmt(localRemaining);
  if (state.submitted) {
    showReport(state.submitted);
  }
}

async function check() {
  const data = await api("/api/check", { method: "POST", body: "{}" });
  renderChecks(data.checks);
  renderEvidence(data.evidence);
}

async function applyFix() {
  const action = state.fix_action;
  const value = action === "clean_disk" ? "" : ($("fixValue")?.value || "");
  if (action !== "clean_disk" && !value.trim()) return;
  const data = await api("/api/action", {
    method: "POST",
    body: JSON.stringify({ action, value }),
  });
  renderChecks(data.checks || []);
  renderEvidence((data.checks || []).map((item) => `[${item.ok ? "OK" : "FAIL"}] ${item.label}：${item.detail}`));
  const note = document.createElement("p");
  note.className = data.ok ? "flash good" : "flash bad";
  note.textContent = data.message;
  $("fixBox").appendChild(note);
  if (data.ok) setTimeout(check, 500);
}

async function hint() {
  const data = await api("/api/hint", { method: "POST", body: "{}" });
  if (!data.hint) {
    $("hints").textContent = "没有更多线索了。";
    return;
  }
  const row = document.createElement("p");
  row.className = "hint";
  row.textContent = `线索 ${data.hints_used}：${data.hint}`;
  $("hints").appendChild(row);
  $("btnHint").classList.add("used");
}

async function submit() {
  const data = await api("/api/submit", { method: "POST", body: "{}" });
  showReport(data.report);
  if (timerHandle) clearInterval(timerHandle);
}

function showReport(report) {
  const panel = $("report");
  panel.classList.remove("hidden");
  const checks = report.checks.map((item) => `<li class="${item.ok ? "ok" : "bad"}">${item.ok ? "✓" : "✗"} ${item.label}：${item.detail}</li>`).join("");
  panel.innerHTML = `
    <div class="report-head"><h2>结案报告</h2><span class="stamp ${report.passed ? "pass" : "fail"}">${report.passed ? "已结案" : "未通过"}</span></div>
    <div class="scoreline"><b>${report.score}</b><span>分 / 用时 ${fmt(report.elapsed_seconds)} / 线索 ${report.hints_used} 条</span></div>
    <p class="muted">${report.passed ? "验收通过：所有真实检查均返回正常。" : "验收未通过：至少一项真实检查仍然异常，继续排查。根因暂不公布。"}</p>
    <ul class="report-checks">${checks}</ul>
    ${report.passed ? `<h3>根因</h3><p>${report.root_cause}</p>` : ""}
    <p class="muted">完整记录已写入 lab/report.json。</p>`;
  panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

$("btnCheck").addEventListener("click", check);
$("btnHint").addEventListener("click", hint);
$("btnSubmit").addEventListener("click", submit);

function tickClock() {
  const now = new Date();
  $("clock").textContent = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
}
tickClock();
setInterval(tickClock, 1000);

refresh().then(() => {
  if (timerHandle) clearInterval(timerHandle);
  timerHandle = setInterval(() => {
    localRemaining = Math.max(0, localRemaining - 1);
    $("timer").textContent = fmt(localRemaining);
  }, 1000);
});
