/* 未完待续 —— 结局彩蛋（独立页面） */

const $ = (id) => document.getElementById(id);
const bridge = window.AstrBotPluginPage || null;

async function apiGet(ep) {
  if (bridge) {
    const r = await bridge.apiGet(ep);
    return r && r.data !== undefined && r.status ? r.data : r;
  }
  const r = await fetch(`/api/plugins/extensions/astrbot_plugin_omphalos/${ep}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

/* ---------- 全屏 ---------- */

/**
 * 尝试进入全屏。
 * 浏览器要求全屏必须由用户手势触发，所以：
 *   1. 先试 element.requestFullscreen()（iframe 内需 allow=fullscreen）
 *   2. 失败则退化成"铺满整个页面"的伪全屏
 */
async function tryFullscreen() {
  const el = document.documentElement;
  try {
    if (el.requestFullscreen) {
      await el.requestFullscreen({ navigationUI: "hide" });
      return true;
    }
    if (el.webkitRequestFullscreen) {
      el.webkitRequestFullscreen();
      return true;
    }
  } catch (e) {
    console.warn("[epilogue] 真全屏不可用，使用伪全屏", e);
  }
  document.body.classList.add("pseudo-full");
  return false;
}

function exitFullscreen() {
  if (document.fullscreenElement) {
    document.exitFullscreen().catch(() => {});
  }
  document.body.classList.remove("pseudo-full");
}

/* ---------- 星光背景 ---------- */

function startStars(canvas) {
  const ctx = canvas.getContext("2d");
  let w = (canvas.width = canvas.offsetWidth * devicePixelRatio);
  let h = (canvas.height = canvas.offsetHeight * devicePixelRatio);
  const N = 140;
  const stars = Array.from({ length: N }, () => ({
    x: Math.random() * w,
    y: Math.random() * h,
    r: Math.random() * 1.6 + 0.3,
    a: Math.random(),
    da: (Math.random() * 0.012 + 0.003) * (Math.random() > 0.5 ? 1 : -1),
    vy: Math.random() * 0.12 + 0.02,
  }));

  function frame() {
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
    requestAnimationFrame(frame);
  }
  frame();

  window.addEventListener("resize", () => {
    w = canvas.width = canvas.offsetWidth * devicePixelRatio;
    h = canvas.height = canvas.offsetHeight * devicePixelRatio;
  });
}

/* ---------- 逐字显现 ---------- */

function showLine(text, turnToPlayer) {
  return new Promise((resolve) => {
    const el = $("line");
    el.className = turnToPlayer ? "line to-player" : "line";
    el.textContent = "";
    let i = 0;
    const timer = setInterval(() => {
      el.textContent = text.slice(0, ++i);
      if (i >= text.length) {
        clearInterval(timer);
        setTimeout(resolve, turnToPlayer ? 3600 : 1500);
      }
    }, turnToPlayer ? 120 : 42);
  });
}

/* ---------- 主流程 ---------- */

async function main() {
  startStars($("stars"));

  let data;
  try {
    data = await apiGet("epilogue");
  } catch (e) {
    $("line").textContent = `无法读取结局：${e.message}`;
    return;
  }

  // 开场：先给一个可点的"开始"按钮，用户点了才能进真全屏
  $("subtitle").textContent = data.ending_title || "";
  $("enter").classList.add("show");
  await new Promise((resolve) => {
    $("enter").addEventListener("click", async () => {
      $("enter").classList.remove("show");
      await tryFullscreen();
      resolve();
    }, { once: true });
  });
  await new Promise((r) => setTimeout(r, 700));

  // 十二位黄金裔依次出现
  for (const w of data.wishes) {
    const who = $("who");
    who.textContent = `${w.name} · ${w.path}`;
    who.classList.add("show");
    await new Promise((r) => setTimeout(r, 520));
    await showLine(w.text, w.turn_to_player);
    who.classList.remove("show");
    await new Promise((r) => setTimeout(r, 260));
  }

  // 昔涟的语音
  if (data.cyrene_audio) {
    const audio = new Audio(`data:audio/wav;base64,${data.cyrene_audio}`);
    audio.volume = 0.95;
    audio.play().catch(() => {});
  }

  // 收尾
  await new Promise((r) => setTimeout(r, 1200));
  $("who").classList.remove("show");
  $("line").className = "line";
  $("line").textContent = "";
  $("finale").classList.add("show");
  $("exit").classList.add("show");
}

// ESC 退出
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") exitFullscreen();
});
document.addEventListener("DOMContentLoaded", () => {
  $("exit").addEventListener("click", exitFullscreen);
});

main();
