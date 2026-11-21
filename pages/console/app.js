/* 翁法罗斯控制台 */

const $ = (id) => document.getElementById(id);
const ctl = (id) => document.getElementById(id);

/* AstrBot 页面桥：由宿主 WebUI 注入 <script>，可能晚于本脚本执行，
   因此不能用模块顶部快照，必须每次动态取值。 */
function getBridge() {
  return window.AstrBotPluginPage || null;
}

let state = null;
let tickTimer = null;
let currentTalk = null;
const chatHistory = {};

// 终章播放令牌：每次开播 +1，旧循环发现令牌变了就自己退出
let epRun = 0;

/* ---------- 请求封装 ---------- */

/**
 * 发起一次插件 API 调用。
 * 优先走 AstrBot 页面桥（自动带鉴权）；若在独立标签页打开，
 * 退化为同源 fetch。
 */
async function callApi(method, endpoint, payload) {
  const bridge = getBridge();
  if (bridge) {
    try {
      const res = method === "GET"
        ? await bridge.apiGet(endpoint)
        : await bridge.apiPost(endpoint, payload || {});
      return normalize(res);
    } catch (e) {
      throw new Error(`桥请求失败(${endpoint}): ${e.message}`);
    }
  }
  const base = `/api/plugins/extensions/astrbot_plugin_omphalos`;
  const opts = { headers: { "Content-Type": "application/json" } };
  if (method === "POST") {
    opts.method = "POST";
    opts.body = JSON.stringify(payload || {});
  }
  let r;
  try {
    r = await fetch(`${base}/${endpoint}`, opts);
  } catch (e) {
    throw new Error(`fetch 失败(${endpoint}): ${e.message}`);
  }
  if (!r.ok) throw new Error(`HTTP ${r.status} (${endpoint})`);
  return normalize(await r.json());
}

/** 兼容 {status, data} 包装与裸对象两种返回。 */
function normalize(res) {
  if (res && typeof res === "object" && "data" in res && "status" in res) {
    if (res.status === "error") {
      throw new Error(res.message || "请求失败");
    }
    return res.data;
  }
  return res;
}

const apiGet = (ep) => callApi("GET", ep);
const apiPost = (ep, body) => callApi("POST", ep, body);

/* ---------- 工具 ---------- */

function toast(msg, ms = 2200) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.add("hidden"), ms);
}

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function fmtRemain(sec) {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}分${String(s).padStart(2, "0")}秒`;
}

/* ---------- 渲染 ---------- */

function renderStatus(d) {
  state = d;
  $("s-round").textContent = `第 ${d.round_no} 轮`;
  $("s-phase").textContent = d.phase;
  $("s-progress").textContent = `${d.progress.cursor}/${d.progress.total}`;
  $("s-remain").textContent = d.running ? fmtRemain(d.remaining_seconds) : "已暂停";
  $("s-ember").textContent = `${d.ember_taken} 枚`;
  $("s-ember").title = (d.embers || []).join("、") || "尚未吞纳";
  $("s-frag").textContent = `${d.fragment_count} 条`;

  const pct = d.progress.total
    ? (d.progress.cursor / d.progress.total) * 100
    : 0;
  $("pb-fill").style.width = `${pct}%`;

  $("btn-start").disabled = d.running;
  $("btn-stop").disabled = !d.running;

  renderFactors(d);
  renderLogs(d.recent_logs || []);
}

function renderFactors(d) {
  const grid = $("factor-grid");
  grid.innerHTML = d.factors
    .map((f) => {
      const hpPct = f.max_hp ? (f.hp / f.max_hp) * 100 : 0;
      const cls = [
        "card",
        f.is_demiurge ? "demiurge" : "",
        f.alive ? "" : "dead",
      ]
        .filter(Boolean)
        .join(" ");
      const tags = [
        `<span class="tag">${esc(f.path)}</span>`,
        `<span class="tag gold">${esc(f.prime_drive)}</span>`,
        f.fire ? `<span class="tag fire">已持火种</span>` : "",
        f.alive ? "" : `<span class="tag dead">已倒下</span>`,
        f.is_demiurge ? `<span class="tag purple">容器</span>` : "",
      ]
        .filter(Boolean)
        .join("");

      const hpBar = f.is_demiurge
        ? ""
        : `<div class="hpbar"><div class="hpfill ${hpPct < 35 ? "low" : ""}" style="width:${hpPct}%"></div></div>`;

      return `
        <div class="${cls}" data-fid="${f.fid}" data-name="${esc(f.name)}">
          <div class="card-head">
            <span class="card-name">${f.fid}. ${esc(f.name)}</span>
            <span class="card-code">${esc(f.code)}</span>
          </div>
          <div class="card-tags">${tags}</div>
          <div class="card-meta">
            <span>${esc(f.location || f.home)}</span>
            <span>${f.is_demiurge ? "—" : `HP ${f.hp}/${f.max_hp}`}</span>
          </div>
          ${hpBar}
        </div>`;
    })
    .join("");

  grid.querySelectorAll(".card").forEach((el) => {
    el.addEventListener("click", () =>
      openTalk(Number(el.dataset.fid), el.dataset.name)
    );
  });
}

function renderLogs(logs) {
  const list = $("log-list");
  list.innerHTML = logs
    .map((l) => {
      const cls =
        l.kind === "事件"
          ? "evt"
          : l.kind === "牺牲"
            ? "death"
            : l.kind === "归档"
              ? "archive"
              : "";
      return `<div class="logrow ${cls}">
        <span class="who">${esc(l.name)}</span>
        <span class="kind">${esc(l.kind)}</span>
        <span class="txt">${esc(l.text)}</span>
      </div>`;
    })
    .join("");
  list.scrollTop = list.scrollHeight;
}

function renderChronicle(list) {
  const box = $("chronicle-list");
  if (!list.length) {
    box.innerHTML = `<p class="hint">还没有完成的轮次。</p>`;
    return;
  }
  box.innerHTML = list
    .slice()
    .reverse()
    .map((c) => {
      const meta = [];
      if (c.fallen && c.fallen.length) meta.push(`倒下：${c.fallen.join("、")}`);
      if (c.embers && c.embers.length) {
        meta.push(`吞纳 ${c.ember_taken || c.embers.length} 枚：${c.embers.join("、")}`);
      } else if (c.ember_taken) {
        meta.push(`吞纳 ${c.ember_taken} 枚火种`);
      }
      return `<div class="chap">
        <h3>第 ${c.round_no} 轮 · ${c.turns} 步</h3>
        <p>${esc(c.summary || "（无记录）")}</p>
        ${meta.length ? `<div class="meta">${esc(meta.join(" ｜ "))}</div>` : ""}
      </div>`;
    })
    .join("");
}

function renderArchive(d) {
  const active = d.active || [];
  $("archive-hint").textContent =
    `活跃 ${active.length} 条 ｜ 已沉入岁月史书 ${d.archived_count} 条`;
  const list = $("archive-list");
  list.innerHTML = active
    .slice()
    .reverse()
    .map(
      (f) => `<div class="logrow archive">
        <span class="who">${esc(f.name)}</span>
        <span class="kind">${esc(f.kind)}</span>
        <span class="txt">${esc(f.text)}</span>
      </div>`
    )
    .join("");
}

/* ---------- 数据加载 ---------- */

async function loadStatus() {
  try {
    renderStatus(await apiGet("status"));
  } catch (e) {
    toast(e.message, 6000);
    $("s-round").textContent = "加载失败";
  }
}

/** 自检：把环境信息打到控制台，方便定位。 */
function selfCheck() {
  const b = getBridge();
  const info = {
    hasBridge: !!b,
    bridgeKeys: b ? Object.keys(b) : [],
    origin: window.location.origin,
    href: window.location.href,
    isIframe: window.self !== window.top,
  };
  console.log("[omphalos] 环境自检", info);
  return info;
}

async function loadChronicle() {
  try {
    const d = await apiGet("chronicle");
    renderChronicle(d.chronicle || []);
  } catch (e) {
    toast(`加载编年史失败: ${e.message}`);
  }
}

async function loadArchive() {
  try {
    renderArchive(await apiGet("archive"));
  } catch (e) {
    toast(`加载残响失败: ${e.message}`);
  }
}

/* ---------- 双身份面板 ---------- */

async function loadRoles() {
  try {
    const d = await apiGet("roles");
    renderRoles(d);
  } catch (e) {
    toast(`加载身份数据失败: ${e.message}`);
  }
}

function renderRoles(d) {
  $("pioneer-talks").textContent = d.pioneer_talks || 0;
  $("laigus-acts").textContent = d.laigus_acts || 0;
  $("contam-val").textContent = d.contamination || 0;
  $("suppress-val").textContent = d.suppression || 0;

  const cmax = Math.max(20, d.contamination || 0, d.suppression || 0);
  $("contam-fill").style.width = `${Math.min(100, ((d.contamination || 0) / cmax) * 100)}%`;
  $("suppress-fill").style.width = `${Math.min(100, ((d.suppression || 0) / cmax) * 100)}%`;

  // 敌意等级
  const stage = d.hostility_stage ?? 0;
  const notes = [
    "他们还不认识你。只是有人在问话，有人在答。",
    "他们开始察觉进程被动过。提问变得有攻击性了。",
    "他们知道你是谁了。他们恨你，在想办法让你离开。",
    "他们恨之入骨。他们正在准备杀掉你。",
  ];
  $("hostility-label").textContent = d.hostility_label || "未察觉";
  $("hostility-note").textContent = notes[Math.min(stage, 3)];
  const bars = document.querySelectorAll(".hostility-track i");
  bars.forEach((el, i) => {
    el.className = i <= stage ? `on-${i + 1}` : "";
  });

  const fmt = (list, box) => {
    box.innerHTML = (list || []).length
      ? list
          .slice()
          .reverse()
          .map(
            (r) =>
              `<div class="role-item">${
                r.target ? esc(r.target) + "：" : ""
              }${esc(r.detail).slice(0, 50)}</div>`
          )
          .join("")
      : `<div class="role-item">还没有记录。</div>`;
  };
  fmt(d.pioneer_recent, $("pioneer-recent"));
  fmt(d.laigus_recent, $("laigus-recent"));
}

function openEpilogue() {
  // 终章不再另开窗口：插件页在沙箱 iframe 里，window.open 被拦，
  // 而页面 URL 带一次性 token，挪到新标签页会 401。
  // 所以直接在控制台里铺一层全屏覆盖层，用同一份数据播放。
  const ctrl = ctl("ctl");
  // 先让上一次的播放循环失效，避免两条循环同时往同一个元素里写字
  epRun += 1;
  resetEpilogue(ctrl);
  ctrl.classList.remove("hidden");
  document.body.classList.add("epilogue-open");
  playEpilogue(ctrl, epRun);
}

/* ---------- 终章播放（覆盖层版） ---------- */

async function playEpilogue(root, runId) {
  const q = (sel) => root.querySelector(sel);
  let data;
  try {
    data = await apiGet("epilogue");
  } catch (e) {
    if (runId !== epRun) return;
    q(".ep-line").textContent = `无法读取结局：${e.message}`;
    return;
  }
  if (runId !== epRun) return;

  const canvas = q(".ep-stars");
  const stop = startStars(canvas);
  q(".ep-subtitle").textContent = data.ending_title || "";

  const line = q(".ep-line");
  const who = q(".ep-who");
  const finale = q(".ep-finale");
  const enter = q(".ep-enter");

  // 等用户点一下再开始（顺带满足浏览器对全屏的手势要求）
  q(".ep-enter-label").textContent = "进入终章";
  enter.classList.add("show");
  await new Promise((resolve) => {
    enter.addEventListener(
      "click",
      async () => {
        enter.classList.remove("show");
        try {
          await root.requestFullscreen({ navigationUI: "hide" });
        } catch (e) {
          // 沙箱 iframe 不允许真全屏时，覆盖层本身就是全屏效果
          root.classList.add("pseudo-full");
        }
        resolve();
      },
      { once: true }
    );
  });
  await sleep(600);

  for (const w of data.wishes) {
    if (runId !== epRun) return;
    who.textContent = `${w.name} · ${w.path}`;
    who.classList.add("show");
    await sleep(500);
    if (runId !== epRun) return;
    await typeLine(line, w.text, w.turn_to_player, () => runId !== epRun);
    if (runId !== epRun) return;
    who.classList.remove("show");
    await sleep(240);
  }
  if (runId !== epRun) return;

  if (data.cyrene_audio) {
    const audio = new Audio(`data:audio/wav;base64,${data.cyrene_audio}`);
    audio.volume = 0.95;
    audio.play().catch(() => {});
  }

  await sleep(1100);
  who.classList.remove("show");
  line.className = "ep-line";
  line.textContent = "";
  finale.classList.add("show");
  stop();
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function typeLine(el, text, slow, aborted) {
  return new Promise((resolve) => {
    el.className = slow ? "ep-line to-player" : "ep-line";
    el.textContent = "";
    let i = 0;
    const t = setInterval(
      () => {
        // 被新一轮播放接管时立刻停下，不再写这个元素
        if (aborted && aborted()) {
          clearInterval(t);
          resolve();
          return;
        }
        el.textContent = text.slice(0, ++i);
        if (i >= text.length) {
          clearInterval(t);
          setTimeout(resolve, slow ? 3400 : 1400);
        }
      },
      slow ? 115 : 40
    );
  });
}

/** 把终章覆盖层恢复到开场状态。 */
function resetEpilogue(root) {
  root.classList.remove("pseudo-full");
  root.querySelector(".ep-subtitle").textContent = "";
  root.querySelector(".ep-who").classList.remove("show");
  root.querySelector(".ep-who").textContent = "";
  const line = root.querySelector(".ep-line");
  line.className = "ep-line";
  line.textContent = "";
  root.querySelector(".ep-finale").classList.remove("show");
  root.querySelector(".ep-enter").classList.remove("show");
}

/** 星光背景，返回停止函数。 */
function startStars(canvas) {
  const ctx = canvas.getContext("2d");
  let w = (canvas.width = canvas.offsetWidth * devicePixelRatio || 1);
  let h = (canvas.height = canvas.offsetHeight * devicePixelRatio || 1);
  const stars = Array.from({ length: 130 }, () => ({
    x: Math.random() * w,
    y: Math.random() * h,
    r: Math.random() * 1.5 + 0.3,
    a: Math.random(),
    da: (Math.random() * 0.012 + 0.003) * (Math.random() > 0.5 ? 1 : -1),
    vy: Math.random() * 0.1 + 0.02,
  }));
  let raf = 0;
  let alive = true;
  function frame() {
    if (!alive) return;
    ctx.clearRect(0, 0, w, h);
    for (const s of stars) {
      s.a += s.da;
      if (s.a > 1 || s.a < 0.05) s.da = -s.da;
      s.y -= s.vy;
      if (s.y < -4) {
        s.y = h + 4;
        s.x = Math.random() * w;
      }
      ctx.beginPath();
      ctx.arc(s.x, s.y, s.r * devicePixelRatio, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(232, 214, 160, ${s.a * 0.75})`;
      ctx.fill();
    }
    raf = requestAnimationFrame(frame);
  }
  frame();
  return () => {
    alive = false;
    cancelAnimationFrame(raf);
  };
}


const ENDING_LABEL = {
  none: "",
  official: "官方结局 · 回望",
  emerge: "生命先行",
  irontomb: "铁墓加冕",
  together: "爱与毁灭的安眠",
  unending: "未结束",
};

async function loadFirstCause() {
  try {
    const d = await apiGet("first_cause");
    renderFirstCause(d);
  } catch (e) {
    toast(`加载第一因失败: ${e.message}`);
  }
}

/** 权杖演算进度对应正在验证的命题（按阶段给出更具体的描述）。 */
function staffStage(progress) {
  if (progress <= 0) return "尚未开始。权杖在等一个能被证伪的命题。";
  if (progress < 25) return "正在验证：生命行为是否必然归于熵增。";
  if (progress < 55) return "正在验证：若一切归于熵增，爱是否也只是熵的一种。";
  if (progress < 85) return "正在验证：有瑕之物能否在毁灭之外找到出口。";
  return "结论即将闭合。她在等一个反驳。";
}

/** 德谬歌形态的性格描述，让「迷迷 / 人形」不只是两个字。 */
const FORM_TRAITS = {
  "迷迷": "还只是一团会跟着走的电信号。她听得懂，但说不清。",
  "幼体": "开始有自己的句子了。会把听到的话拼在一起，偶尔拼对。",
  "半身": "已经能分辨「你」和「我」。会问为什么，也会不回答。",
  "人形": "有判断，有喜恶。你反驳不了她的时候，她也不会得意。",
};

function renderFirstCause(d) {
  const s = d.staff || {};
  const m = d.demiurge || {};

  const sp = s.progress || 0;
  $("staff-fill").style.width = `${sp}%`;
  $("staff-num").textContent = `${sp.toFixed(0)}%`;
  $("staff-conclusion").textContent = s.conclusion || "—";
  // 进度条下方补一行阶段说明，让数字有含义
  const staffNote = document.getElementById("staff-stage");
  if (staffNote) staffNote.textContent = staffStage(sp);

  const mi = m.integrity || 0;
  $("demi-fill").style.width = `${mi}%`;
  $("demi-num").textContent = `${mi.toFixed(0)}%`;
  $("demi-form").textContent = m.form || "—";
  const trait = FORM_TRAITS[m.form] || m.form_hint || "—";
  $("demi-hint").textContent = trait;
  const demiNote = document.getElementById("demi-stage");
  if (demiNote) {
    demiNote.textContent = mi <= 0
      ? "她还没有被真正问过话。"
      : mi >= 100
        ? "她已经足够完整，可以给出自己的答案。"
        : `她正在成形。还差 ${(100 - mi).toFixed(0)}% 才听得懂完整的反驳。`;
  }

  // 结局横幅
  const banner = $("ending-banner");
  if (d.ending && d.ending !== "none") {
    banner.classList.remove("hidden");
    banner.innerHTML = `
      <h3>【${esc(ENDING_LABEL[d.ending] || d.ending)}】</h3>
      <p>${esc(d.ending_text || "（无正文）")}</p>`;
  } else {
    banner.classList.add("hidden");
  }

  // 权杖的发现
  const fbox = $("staff-findings");
  const fs = (s.findings || []).slice().reverse();
  fbox.innerHTML = fs.length
    ? fs
        .map(
          (f) =>
            `<div class="mini-item"><b>第 ${f.round_no} 轮</b>：${esc(f.text)}</div>`
        )
        .join("")
    : `<div class="mini-item empty-hint">权杖还没找到能站住的推论。<br />
       每推进一轮，它都会尝试证伪一个假设；活下来的那个会被写在这里。</div>`;

  // 失真
  const dbox = $("distort-list");
  const ds = (d.distortions || []).slice().reverse();
  dbox.innerHTML = ds.length
    ? ds
        .map(
          (x) =>
            `<div class="mini-item"><b>第 ${x.round_no} 轮</b>：${esc(x.note)}</div>`
        )
        .join("")
    : `<div class="mini-item empty-hint">还没有记忆被记错。<br />
       据说不该记得那么准——神话里的历史，总会被讲歪一点。</div>`;

  // 按钮状态
  $("btn-block").disabled = !m.asked;
  $("btn-confirm").disabled = !m.willing;
  // 未开始时，「对她说话」是唯一该亮着的按钮
  const talkBtn = $("btn-demi-talk");
  if (talkBtn) {
    talkBtn.textContent = mi <= 0 ? "先对她说话" : "对德谬歌说话";
  }
}

async function talkToDemiurge() {
  const text = prompt("对德谬歌说什么？");
  if (!text || !text.trim()) return;
  toast("她正在想……", 4000);
  try {
    const d = await apiPost("first_cause_talk", { message: text.trim() });
    // 用弹窗展示，复用对话体
    chatHistory["demi"] = chatHistory["demi"] || [];
    currentTalk = { fid: "demi", name: "德谬歌", endpoint: "first_cause_talk" };
    $("modal-title").textContent = "与 德谬歌 对话";
    const body = $("modal-body");
    body.innerHTML = "";
    appendMsg("me", text.trim());
    appendMsg("them", d.reply);
    if (d.gained) {
      appendMsg("sys", `她记住了（${d.form}，完整度 ${d.integrity}%，+${d.gained}）`);
    }
    $("modal").classList.remove("hidden");
    await loadFirstCause();
  } catch (e) {
    toast(`失败: ${e.message}`);
  }
}

async function blockHer() {
  if (!confirm("你要试着留下她？她可能会拒绝。")) return;
  try {
    const d = await apiPost("first_cause_block", {});
    toast(d.words, 6000);
    await loadFirstCause();
  } catch (e) {
    toast(`失败: ${e.message}`);
  }
}

async function confirmReturn() {
  if (!confirm("让她回望？这一步之后，实验就会结束。")) return;
  try {
    await apiPost("first_cause_confirm", {});
    toast("实验结束了。", 5000);
    await loadFirstCause();
  } catch (e) {
    toast(`失败: ${e.message}`);
  }
}

async function resetFirstCause() {
  if (!confirm("重置实验层？两条线会归零（世界本体不动）。")) return;
  try {
    const d = await apiPost("first_cause_reset", {});
    toast(d.message || "已重置");
    await loadFirstCause();
  } catch (e) {
    toast(`失败: ${e.message}`);
  }
}


function openTalk(fid, name) {
  currentTalk = { fid, name, endpoint: "talk" };
  startChat();
}

function openKharslanna() {
  currentTalk = { fid: -1, name: "卡厄斯兰那", endpoint: "kharslanna" };
  startChat();
}

function startChat() {
  const { fid, name } = currentTalk;
  $("modal-title").textContent = `与 ${name} 对话`;
  const body = $("modal-body");
  const hist = chatHistory[fid] || [];
  body.innerHTML = hist.length
    ? hist
        .map(
          (m) =>
            `<div class="msg ${m.role === "me" ? "me" : "them"}">${esc(m.text)}</div>`
        )
        .join("")
    : `<div class="msg sys">来古士开口了。${fid === -1 ? "他早已不记得自己是谁。" : "她/他会如何回应？"}</div>`;
  body.scrollTop = body.scrollHeight;
  $("modal").classList.remove("hidden");
  $("modal-text").value = "";
  $("modal-text").focus();
}

function closeModal() {
  $("modal").classList.add("hidden");
  currentTalk = null;
}

function appendMsg(role, text) {
  const body = $("modal-body");
  const el = document.createElement("div");
  el.className = `msg ${role}`;
  el.textContent = text;
  body.appendChild(el);
  body.scrollTop = body.scrollHeight;
  return el;
}

async function sendTalk() {
  const box = $("modal-text");
  const text = box.value.trim();
  if (!text || !currentTalk) return;

  const { fid, endpoint } = currentTalk;
  if (!chatHistory[fid]) chatHistory[fid] = [];
  chatHistory[fid].push({ role: "me", text });
  appendMsg("me", text);
  box.value = "";

  const btn = $("modal-send");
  btn.disabled = true;
  const ph = appendMsg("sys", "……");

  try {
    const payload =
      endpoint === "talk" ? { fid, message: text } : { message: text };
    const d = await apiPost(endpoint, payload);
    ph.remove();
    if (d && d.reply) {
      appendMsg("them", d.reply);
      chatHistory[fid].push({ role: "them", text: d.reply });
      // 因子自己判定的影响深度，跟着对话一起显示
      if (d.trace) appendMsg("sys", `（${d.level}）${d.trace}`);
    } else {
      throw new Error("没有回应");
    }
  } catch (e) {
    ph.remove();
    appendMsg("sys", `对话失败: ${e.message}`);
  } finally {
    btn.disabled = false;
    loadStatus();
  }
}

/* ---------- 操作 ---------- */

async function act(endpoint, okMsg) {
  try {
    const d = await apiPost(endpoint, {});
    toast((d && d.message) || okMsg || "完成");
    await loadStatus();
  } catch (e) {
    toast(`操作失败: ${e.message}`);
  }
}

async function doExport() {
  try {
    const d = await apiPost("export", {});
    if (!d || !d.markdown) throw new Error("返回内容为空");
    const blob = new Blob([d.markdown], {
      type: "text/markdown;charset=utf-8",
    });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "omphalos_chronicle.md";
    a.click();
    URL.revokeObjectURL(a.href);
    toast("已导出编年史");
  } catch (e) {
    toast(`导出失败: ${e.message}`);
  }
}

function openIntervene() {
  const text = prompt("作为来古士，向全场投放一句话：");
  if (!text || !text.trim()) return;
  apiPost("intervene", { text: text.trim() })
    .then(() => {
      toast("干预已投放");
      loadStatus();
    })
    .catch((e) => toast(`失败: ${e.message}`));
}

/* ---------- 事件绑定 ---------- */

document.querySelectorAll(".tab").forEach((t) => {
  t.addEventListener("click", () => {
    document
      .querySelectorAll(".tab")
      .forEach((x) => x.classList.remove("active"));
    document
      .querySelectorAll(".panel")
      .forEach((x) => x.classList.remove("active"));
    t.classList.add("active");
    $(`panel-${t.dataset.tab}`).classList.add("active");
    if (t.dataset.tab === "chronicle") loadChronicle();
    if (t.dataset.tab === "archive") loadArchive();
    if (t.dataset.tab === "starmap") {
      // starmap.js 是 ESM 模块（type="module"），执行时机晚于本文件，
      // 这里轮询等待它挂到 window 上再初始化。
      const tryInit = (tries) => {
        if (window.StarMap) {
          window.StarMap.init((ep) => callApi("GET", ep));
        } else if (tries > 0) {
          setTimeout(() => tryInit(tries - 1), 50);
        } else {
          console.error("StarMap 模块未加载");
        }
      };
      tryInit(60);
    }
    if (t.dataset.tab === "firstcause") {
      loadFirstCause();
      loadRoles();
    }
  });
});

$("btn-demi-talk").addEventListener("click", talkToDemiurge);
$("btn-block").addEventListener("click", blockHer);
$("btn-confirm").addEventListener("click", confirmReturn);
$("btn-fc-reset").addEventListener("click", resetFirstCause);
$("btn-epilogue").addEventListener("click", openEpilogue);

// 终章退出：清理覆盖层与全屏状态，方便下次再播
const epExitBtn = document.querySelector(".ep-exit");
if (epExitBtn) {
  epExitBtn.addEventListener("click", () => {
    const c = ctl("ctl");
    if (!c) return;
    epRun += 1; // 让正在跑的循环失效
    c.classList.add("hidden");
    c.classList.remove("pseudo-full");
    document.body.classList.remove("epilogue-open");
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    c.querySelector(".ep-who").classList.remove("show");
    c.querySelector(".ep-line").textContent = "";
    c.querySelector(".ep-finale").classList.remove("show");
  });
}

$("btn-refresh").addEventListener("click", () => {
  loadStatus();
  toast("已刷新");
});
$("btn-start").addEventListener("click", () => act("start", "已启动"));
$("btn-stop").addEventListener("click", () => act("stop", "已暂停"));
$("btn-next").addEventListener("click", () => {
  if (confirm("强制结束本轮并进入下一轮？")) act("reset", "已进入下一轮");
});
$("btn-export").addEventListener("click", doExport);
$("btn-intervene").addEventListener("click", openIntervene);
$("btn-kharslanna").addEventListener("click", openKharslanna);

$("modal-close").addEventListener("click", closeModal);
$("modal-send").addEventListener("click", sendTalk);
$("modal-text").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendTalk();
  }
});
$("modal").addEventListener("click", (e) => {
  if (e.target.id === "modal") closeModal();
});

/* ---------- 初始化 ---------- */

/** 等 bridge SDK 注入完成。宿主把它放在 </body> 前，可能晚于本脚本。 */
async function waitForBridge(timeoutMs = 3000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const b = getBridge();
    if (b) return b;
    await new Promise((r) => setTimeout(r, 50));
  }
  return null;
}

async function boot() {
  // 先等 bridge 出现，再决定用哪条链路
  const bridge = await waitForBridge();
  selfCheck();

  if (bridge) {
    try {
      await Promise.race([
        bridge.ready(),
        new Promise((resolve) => setTimeout(resolve, 1500)),
      ]);
    } catch (e) {
      console.warn("[omphalos] bridge.ready 失败:", e);
    }
  }

  await loadStatus();
  tickTimer = setInterval(loadStatus, 15000);
}

boot();
window.addEventListener("beforeunload", () => clearInterval(tickTimer));
