/**
 * 意识海 · 记忆星图（Three.js 版）
 *
 * 为什么换成 Three.js：
 *   Canvas 2D 逐帧画几万颗粒子撑不住帧率，也没法做真正的 HDR + tone mapping。
 *   Three.js 的 Points + 自定义 shader 能一次绘制十万级粒子，
 *   ACESFilmicToneMapping 天然处理亮度压缩（这是解决过曝的正解）。
 *
 * 视觉还原目标（对照原型实测）：
 *   环：一条极细的 8 字曲线，靠高密度粒子发光
 *   粒子：十字星芒（不是圆点），1~3 物理像素
 *   中心：极小极亮的点 + 贯穿全屏的十字光芒
 *   色调：紫 → 青 → 绿 沿曲线渐变，高对比
 */

import * as THREE from './vendor/three.module.min.js';

const StarMap = (function () {
  'use strict';

  const TIER_ORDER = ['core', 'long', 'chronicle', 'daily', 'archive'];

  // ---------- 8 字曲线（与后端 core/starmap.py 一致） ----------
  let RING_R = 1.0;
  let RING_SQUASH = 0.78;
  let RING_TWIST = 0.45;

  // 粒子沿曲线流动的速度（弧度/秒）：0.70 ≈ 9 秒走完一圈
  // 注意：只有粒子在动，环本身不旋转
  let FLOW_SPEED = 0.70;   // 可在面板里实时调整

  /**
   * 8 字环参数方程。
   * @param {number} t 0→2π
   * @returns {{x:number,y:number,z:number}} 世界坐标
   */
  function eightCurve(t) {
    return {
      x: RING_R * Math.sin(t),
      y: RING_R * RING_SQUASH * Math.sin(2 * t) / 2,
      z: RING_R * RING_TWIST * Math.cos(t),
    };
  }


  // ---------- 色谱 ----------
  /**
   * 沿曲线的连续色相。
   *
   * 配色依据：对原型画面做高饱和像素直方图统计，
   * 结果是粉红 57.7%、蓝紫 11.9%、紫 9.1%、蓝 7.9%、品红 5.4%，
   * 即「粉红为主、蓝紫为辅」，色相主要活动在 190°~355° 这段弧上，
   * 而不是整圈彩虹。
   *
   * 用两个不同频率的正弦叠加得到非周期、严格连续的变化：
   * 相邻位置色相差 ≤ 2°，不会出现可见的分段。
   *
   * @param {number} u 归一化位置（任意 t，内部取模）
   * @returns {{h: number, l: number}} 色相度数 与 亮度
   */
  function hueAt(u) {
    const t = (u - Math.floor(u)) * Math.PI * 2;
    let v = 0.62 * Math.sin(t) + 0.38 * Math.sin(2 * t + 0.9);
    if (v > 1) v = 1;
    else if (v < -1) v = -1;
    // 色相起伏 + 亮度轻微起伏，避免整条带子一个明度
    return {
      h: (272.5 + 82.5 * v) / 360,
      l: 0.60 + 0.05 * Math.sin(t * 1.5),
    };
  }

  // ---------- 状态 ----------
  let container = null;
  let renderer = null;
  let scene = null;
  let camera = null;
  let points = null;       // 环体粒子
  let pointsGeo = null;
  let starsPoints = null;  // 记忆星点
  let starsGeo = null;
  let coreSprite = null;
  let dust = null;
  let coreGroup = null;
  let coreRays = null;

  let stars = [];          // 记忆数据
  let starsData = [];      // 每颗星的原始数据
  let tierMeta = {};
  let maxRound = 1;
  let rafId = null;
  let startTime = 0;
  let hovered = null;
  let selected = null;

  let dragging = false;
  let dragStart = null;
  const view = {
    yaw: 0, pitch: -0.10, zoom: 1.0,
    targetYaw: 0, targetPitch: -0.10, targetZoom: 1.0,
    panX: 0, panY: 0, targetPanX: 0, targetPanY: 0,
  };

  // ---------- 星芒贴图 ----------
  /**
   * 生成粒子纹理：实心柔光圆打底 + 十字尖芒。
   *
   * 关键：必须先铺一层覆盖整个正方形的柔光圆。
   * 早期版本只画了 0.16 半径的中心核和 0.55 半径的淡外晕，
   * 贴图外圈是透明的；当 gl_PointSize 只有 1~2px 时，
   * gl_PointCoord 采样几乎全落在透明区，配合 discard 阈值
   * 就会把所有粒子都丢掉——表现为「一颗都没有」。
   *
   * @param {number} size 贴图边长
   * @returns {THREE.Texture} 纹理
   */
  function makeStarTexture(size = 128) {
    const c = document.createElement('canvas');
    c.width = c.height = size;
    const g = c.getContext('2d');
    const cx = size / 2;

    // 覆盖全图的柔光圆，保证任意采样位置都有非零 alpha
    const halo = g.createRadialGradient(cx, cx, 0, cx, cx, cx);
    halo.addColorStop(0.00, 'rgba(255,255,255,1.0)');
    halo.addColorStop(0.22, 'rgba(255,255,255,0.85)');
    halo.addColorStop(0.45, 'rgba(255,255,255,0.45)');
    halo.addColorStop(0.75, 'rgba(255,255,255,0.14)');
    halo.addColorStop(1.00, 'rgba(255,255,255,0)');
    g.fillStyle = halo;
    g.beginPath();
    g.arc(cx, cx, cx, 0, Math.PI * 2);
    g.fill();

    // 再叠十字尖芒，制造「星」的锐利感
    g.save();
    g.translate(cx, cx);
    g.globalCompositeOperation = 'lighter';
    for (let i = 0; i < 4; i++) {
      const len = i % 2 === 0 ? cx * 0.98 : cx * 0.66;
      const grd = g.createLinearGradient(0, 0, len, 0);
      grd.addColorStop(0, 'rgba(255,255,255,0.85)');
      grd.addColorStop(0.35, 'rgba(255,255,255,0.22)');
      grd.addColorStop(1, 'rgba(255,255,255,0)');
      g.fillStyle = grd;
      g.rotate(Math.PI / 2);
      g.beginPath();
      g.moveTo(0, -size * 0.024);
      g.lineTo(len, 0);
      g.lineTo(0, size * 0.024);
      g.closePath();
      g.fill();
    }
    g.restore();

    const tex = new THREE.CanvasTexture(c);
    tex.needsUpdate = true;
    return tex;
  }

  // ---------- 环体粒子 shader ----------
  // 普通版顶点着色器：直接用 position（用于记忆星点与背景星尘）
  const VERT_PLAIN = `
    uniform float uScale;
    attribute float aSize;
    attribute vec3 aColor;
    attribute float aBright;
    varying vec3 vColor;
    varying float vBright;
    void main() {
      vColor = aColor;
      vBright = aBright;
      vec4 mv = modelViewMatrix * vec4(position, 1.0);
      gl_Position = projectionMatrix * mv;
      gl_PointSize = max(aSize * uScale / -mv.z, 1.0);
    }
  `;

  const VERT = `
    uniform float uScale;
    uniform float uTime;
    uniform float uFlow;
    uniform float uRingR;
    uniform float uSquash;
    uniform float uTwist;
    attribute float aSize;
    attribute vec3 aColor;
    attribute float aBright;
    attribute float aT;
    attribute float aLat;
    attribute float aVer;
    varying vec3 vColor;
    varying float vBright;

    // 8 字曲线：与 JS 端 eightCurve 完全一致
    vec3 eightCurve(float t) {
      return vec3(
        uRingR * sin(t),
        uRingR * uSquash * sin(2.0 * t) / 2.0,
        uRingR * uTwist * cos(t)
      );
    }

    void main() {
      // 沿曲线不断推进，形成流动感
      float t = aT + uTime * uFlow;
      vec3 p = eightCurve(t);

      // 切线差分 -> 横向法向（与 JS 端算法一致）
      vec3 p2 = eightCurve(t + 0.001);
      vec3 tg = normalize(p2 - p + vec3(1e-6));
      vec2 nrm = normalize(vec2(tg.y, -tg.x) + vec2(1e-6));

      vec3 pos = vec3(p.x + nrm.x * aLat, p.y + nrm.y * aLat, p.z + aVer);

      vColor = aColor;
      vBright = aBright;
      vec4 mv = modelViewMatrix * vec4(pos, 1.0);
      gl_Position = projectionMatrix * mv;
      gl_PointSize = max(aSize * uScale / -mv.z, 1.0);
    }
  `;

  const FRAG = `
    uniform sampler2D uTex;
    varying vec3 vColor;
    varying float vBright;
    void main() {
      vec4 tex = texture2D(uTex, gl_PointCoord);
      // 阈值必须很低：十字星芒的尖角 alpha 本来就小
      if (tex.a < 0.004) discard;
      // alpha 只取贴图，亮暗全部交给 rgb —— 否则乘法会把 alpha 压到阈值下
      gl_FragColor = vec4(vColor * tex.a * vBright, tex.a);
    }
  `;

  /**
   * 沿 8 字曲线生成环体粒子。
   * 密度按原型实测：亮像素需覆盖画面约 25%，要 8 万+ 颗。
   * @param {number} count 粒子数
   * @returns {THREE.Points} 粒子对象
   */
  function buildRibbon(count) {
    const pos = new Float32Array(count * 3);
    const col = new Float32Array(count * 3);
    const size = new Float32Array(count);
    const bright = new Float32Array(count);
    // 流动用：曲线参数与偏移，交给 vertex shader 重算位置
    const tArr = new Float32Array(count);
    const latArr = new Float32Array(count);
    const verArr = new Float32Array(count);

    const c = new THREE.Color();

    for (let i = 0; i < count; i++) {
      const t = (i / count) * 2 * Math.PI;
      const p = eightCurve(t);

      // 横向散布：三点平均近似高斯，中间密两边疏
      const k = (Math.random() + Math.random() + Math.random() - 1.5);
      const lateral = k * 0.062;
      const vert = (Math.random() - 0.5) * 0.022;

      // 法向：切线叉乘 up
      const dt = 1e-3;
      const p2 = eightCurve(t + dt);
      let tx = p2.x - p.x, ty = p2.y - p.y, tz = p2.z - p.z;
      const tl = Math.hypot(tx, ty, tz) || 1;
      tx /= tl; ty /= tl; tz /= tl;
      let nx = ty, ny = -tx;
      const nl = Math.hypot(nx, ny) || 1;
      nx /= nl; ny /= nl;

      pos[i * 3] = p.x + nx * lateral;
      pos[i * 3 + 1] = p.y + ny * lateral;
      pos[i * 3 + 2] = p.z + vert;
      tArr[i] = t;
      latArr[i] = lateral;
      verArr[i] = vert;

      // 沿曲线取连续色相（见 hueAt）
      const hc = hueAt(t / (2 * Math.PI));
      c.setHSL(hc.h, 0.82, hc.l);
      col[i * 3] = c.r;
      col[i * 3 + 1] = c.g;
      col[i * 3 + 2] = c.b;

      // 越靠内圈越亮越大
      const inner = 1 - Math.min(1, Math.abs(lateral) / 0.062);
      // 世界空间尺寸：0.0016~0.0060，对应屏幕 1~3px（实测原型值）
      size[i] = 0.0040 + inner * 0.0060 + Math.random() * 0.0020;
      // 白芯概率极低：原型里 >240 的像素只占 0.48%
      // 亮度不能太高，否则叠加后颜色被冲成白色（彩色会全丢）
      // 窄带里粒子重叠密集，单颗不用太亮，靠叠加出实体感
      bright[i] = inner > 0.90 && Math.random() < 0.12
        ? 0.80
        : 0.30 + inner * 0.45;
    }

    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    geo.setAttribute('aColor', new THREE.BufferAttribute(col, 3));
    geo.setAttribute('aSize', new THREE.BufferAttribute(size, 1));
    geo.setAttribute('aBright', new THREE.BufferAttribute(bright, 1));
    geo.setAttribute('aT', new THREE.BufferAttribute(tArr, 1));
    geo.setAttribute('aLat', new THREE.BufferAttribute(latArr, 1));
    geo.setAttribute('aVer', new THREE.BufferAttribute(verArr, 1));

    const mat = new THREE.ShaderMaterial({
      uniforms: {
        uTex: { value: makeStarTexture(128) },
        uScale: { value: 966 },
        uTime: { value: 0 },
        uFlow: { value: FLOW_SPEED },
        uRingR: { value: RING_R },
        uSquash: { value: RING_SQUASH },
        uTwist: { value: RING_TWIST },
      },
      vertexShader: VERT,
      fragmentShader: FRAG,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });

    const pts = new THREE.Points(geo, mat);
    // 位置在 shader 外算好，包围盒可能为 0 导致被整体剔除，显式关掉
    pts.frustumCulled = false;
    pts.renderOrder = 2;
    return pts;
  }

  /**
   * 生成记忆星点（比环体粒子更大、更亮，代表一条具体记忆）。
   * @returns {THREE.Points} 星点对象
   */
  function buildMemoryStars() {
    const n = starsData.length;
    const pos = new Float32Array(n * 3);
    const col = new Float32Array(n * 3);
    const size = new Float32Array(n);
    const bright = new Float32Array(n);
    const c = new THREE.Color();

    for (let i = 0; i < n; i++) {
      const s = starsData[i];
      pos[i * 3] = s.x;
      pos[i * 3 + 1] = s.y;
      pos[i * 3 + 2] = s.z;

      const meta = tierMeta[s.tier] || { color: '#ffffff', size: 1, brightness: 0.6 };
      c.set(meta.color);
      col[i * 3] = c.r;
      col[i * 3 + 1] = c.g;
      col[i * 3 + 2] = c.b;

      // 记忆星点比环体粒子大一圈，便于点击
      let sz = 0.0045 + meta.size * 0.0032;
      if (s.tier === 'core') {
        const recency = maxRound > 0 ? s.round_no / maxRound : 0;
        sz *= 0.55 + 0.55 * Math.pow(recency, 1.5);
      }
      size[i] = sz;
      bright[i] = 0.55 + meta.brightness * 0.45;
    }

    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    geo.setAttribute('aColor', new THREE.BufferAttribute(col, 3));
    geo.setAttribute('aSize', new THREE.BufferAttribute(size, 1));
    geo.setAttribute('aBright', new THREE.BufferAttribute(bright, 1));

    const mat = new THREE.ShaderMaterial({
      uniforms: {
        uTex: { value: makeStarTexture(128) },
        uScale: { value: 966 },
        uTime: { value: 0 },
        uFlow: { value: 0 },
        uRingR: { value: RING_R },
        uSquash: { value: RING_SQUASH },
        uTwist: { value: RING_TWIST },
      },
      vertexShader: VERT_PLAIN,
      fragmentShader: FRAG,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });

    return new THREE.Points(geo, mat);
  }

  /**
   * 中心恒星：原子式结构。
   *
   * 参照原型放大图的四个特征：
   *   1. 中央白热光球
   *   2. 三组不同倾角的椭圆轨道
   *   3. 轨道是「珠链」——小亮点串成，不是实线
   *   4. 贯穿画面的十字光芒 + 放射细线
   */
  function buildCore() {
    const group = new THREE.Group();

    // ---- 1. 中央白热球 ----
    const sphere = new THREE.Mesh(
      new THREE.SphereGeometry(0.026, 20, 20),
      new THREE.MeshBasicMaterial({ color: 0xffffff })
    );
    group.add(sphere);

    // 光晕：内核极亮，向外迅速衰减
    const glowCanvas = document.createElement('canvas');
    glowCanvas.width = glowCanvas.height = 256;
    const gg = glowCanvas.getContext('2d');
    const grad = gg.createRadialGradient(128, 128, 0, 128, 128, 128);
    grad.addColorStop(0.00, 'rgba(255,255,255,1)');
    grad.addColorStop(0.08, 'rgba(255,253,245,0.92)');
    grad.addColorStop(0.18, 'rgba(240,235,255,0.45)');
    grad.addColorStop(0.36, 'rgba(200,190,255,0.16)');
    grad.addColorStop(0.65, 'rgba(130,120,255,0.05)');
    grad.addColorStop(1.00, 'rgba(60,50,150,0)');
    gg.fillStyle = grad;
    gg.fillRect(0, 0, 256, 256);
    const glowTex = new THREE.CanvasTexture(glowCanvas);
    const sprite = new THREE.Sprite(
      new THREE.SpriteMaterial({
        map: glowTex,
        transparent: true,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      })
    );
    sprite.scale.set(0.72, 0.72, 1);
    group.add(sprite);

    // ---- 2. 星轨：3~4 条闭合光带环，斜着套在一起 ----
    // 每条轨道 = 一个压扁的圆环体（连续光带）+ 稀疏亮点（轨道上的星）
    const ORBITS = [
      { R: 0.62, tube: 0.006, squash: 0.30, rollZ: 0.00, color: 0xdfe6ff, stars: 90 },
      { R: 0.70, tube: 0.005, squash: 0.28, rollZ: 1.05, color: 0xe6d0ff, stars: 100 },
      { R: 0.56, tube: 0.005, squash: 0.32, rollZ: -1.05, color: 0xcfdcff, stars: 80 },
      { R: 0.78, tube: 0.004, squash: 0.24, rollZ: 1.57, color: 0xd8c8ff, stars: 70 },
    ];

    const spins = [0.06, -0.09, 0.10, -0.07];
    group.userData.rings = [];

    ORBITS.forEach((o, idx) => {
      // ---- 光带本体：压扁的圆环体 ----
      const torus = new THREE.Mesh(
        new THREE.TorusGeometry(o.R, o.tube, 8, 180),
        new THREE.MeshBasicMaterial({
          color: o.color,
          transparent: true,
          opacity: 0.55,
          blending: THREE.AdditiveBlending,
          depthWrite: false,
        })
      );
      // 压扁成椭圆，再绕 Z 转成不同朝向
      torus.scale.set(1, o.squash, 1);
      torus.rotation.z = o.rollZ;
      torus.renderOrder = 3;
      group.add(torus);
      group.userData.rings.push({ obj: torus, spin: spins[idx] });

      // ---- 轨道上的稀疏亮点 ----
      const n = o.stars;
      const pos = new Float32Array(n * 3);
      const col = new Float32Array(n * 3);
      const size = new Float32Array(n);
      const bright = new Float32Array(n);
      const c = new THREE.Color(o.color);

      for (let i = 0; i < n; i++) {
        const a = (i / n) * Math.PI * 2;
        const ex = Math.cos(a) * o.R;
        const ey = Math.sin(a) * o.R * o.squash;
        const x = ex * Math.cos(o.rollZ) - ey * Math.sin(o.rollZ);
        const y = ex * Math.sin(o.rollZ) + ey * Math.cos(o.rollZ);
        pos[i * 3] = x;
        pos[i * 3 + 1] = y;
        pos[i * 3 + 2] = 0;
        const e2 = 0.5 + 0.5 * Math.abs(Math.cos(a));
        col[i * 3] = c.r * e2;
        col[i * 3 + 1] = c.g * e2;
        col[i * 3 + 2] = c.b * e2;
        size[i] = 0.0030 + (i % 5 === 0 ? 0.0022 : 0);
        bright[i] = 0.35 + 0.45 * e2;
      }

      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
      geo.setAttribute('aColor', new THREE.BufferAttribute(col, 3));
      geo.setAttribute('aSize', new THREE.BufferAttribute(size, 1));
      geo.setAttribute('aBright', new THREE.BufferAttribute(bright, 1));

      const mat = new THREE.ShaderMaterial({
        uniforms: {
          uTex: { value: makeStarTexture(64) },
          uScale: { value: 966 },
          uTime: { value: 0 },
          uFlow: { value: 0 },
          uRingR: { value: RING_R },
          uSquash: { value: RING_SQUASH },
          uTwist: { value: RING_TWIST },
        },
        vertexShader: VERT_PLAIN,
        fragmentShader: FRAG,
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      });

      const pts = new THREE.Points(geo, mat);
      pts.frustumCulled = false;
      pts.renderOrder = 4;
      group.add(pts);
      group.userData.rings.push({ obj: pts, spin: spins[idx] });
    });

    // ---- 3. 十字光芒：柔光贴图，边缘完全虚化 ----
    // 之前用矩形平面，边缘是硬切线，看起来像蜘蛛网；
    // 这里改成一张「中间实、两头渐隐」的贴图，天然带模糊。
    const rayTex = (horizontal) => {
      const c = document.createElement('canvas');
      c.width = horizontal ? 512 : 64;
      c.height = horizontal ? 64 : 512;
      const g = c.getContext('2d');
      const w = c.width, h = c.height;
      if (horizontal) {
        const grd = g.createLinearGradient(0, 0, w, 0);
        grd.addColorStop(0.00, 'rgba(255,255,255,0)');
        grd.addColorStop(0.32, 'rgba(255,255,255,0.55)');
        grd.addColorStop(0.50, 'rgba(255,255,255,1)');
        grd.addColorStop(0.68, 'rgba(255,255,255,0.55)');
        grd.addColorStop(1.00, 'rgba(255,255,255,0)');
        // 沿 X 铺渐变，再沿 Y 做一次羽毛衰减
        const img = g.createImageData(w, h);
        for (let y = 0; y < h; y++) {
          const dy = Math.abs(y - h / 2) / (h / 2);          // 0 中心 1 边缘
          const feather = Math.pow(Math.max(0, 1 - dy), 2.2); // 软羽化
          for (let x = 0; x < w; x++) {
            const dx = Math.abs(x - w / 2) / (w / 2);
            const along = Math.pow(Math.max(0, 1 - dx), 1.6);
            const a = 255 * feather * along;
            const i = (y * w + x) * 4;
            img.data[i] = 232; img.data[i + 1] = 238;
            img.data[i + 2] = 255; img.data[i + 3] = a;
          }
        }
        g.putImageData(img, 0, 0);
      } else {
        g.translate(w / 2, h / 2);
        g.rotate(Math.PI / 2);
        g.translate(-h / 2, -w / 2);
        const img = g.createImageData(h, w);
        for (let y = 0; y < w; y++) {
          const dx = Math.abs(y - w / 2) / (w / 2);
          const along = Math.pow(Math.max(0, 1 - dx), 1.6);
          for (let x = 0; x < h; x++) {
            const dy = Math.abs(x - h / 2) / (h / 2);
            const feather = Math.pow(Math.max(0, 1 - dy), 2.2);
            const a = 255 * feather * along;
            const i = (y * h + x) * 4;
            img.data[i] = 232; img.data[i + 1] = 238;
            img.data[i + 2] = 255; img.data[i + 3] = a;
          }
        }
        g.putImageData(img, 0, 0);
      }
      const t = new THREE.CanvasTexture(c);
      t.needsUpdate = true;
      return t;
    };

    const rayPlane = (w, h, src, opacity) => {
      const m = new THREE.Mesh(
        new THREE.PlaneGeometry(w, h),
        new THREE.MeshBasicMaterial({
          map: src,
          transparent: true,
          opacity,
          blending: THREE.AdditiveBlending,
          depthWrite: false,
        })
      );
      return m;
    };

    // 横向与纵向各一条，都带完整羽化
    group.add(rayPlane(16.0, 0.55, rayTex(true), 0.42));
    group.add(rayPlane(0.55, 10.5, rayTex(false), 0.42));

    // 斜向次星芒：更淡
    const diagTex = rayTex(true);
    const dA = rayPlane(7.0, 0.32, diagTex, 0.16);
    dA.rotation.z = Math.PI / 4;
    const dB = rayPlane(7.0, 0.32, diagTex, 0.16);
    dB.rotation.z = -Math.PI / 4;
    group.add(dA, dB);

    return group;
    return group;
  }

  /**
   * 背景环境辉光：一层覆盖全屏的径向渐变 + 星云雾。
   *
   * 实测原型：即使远离环带的角落，背景亮度也有 24~38（p50 约 20），
   * 不是纯黑。这层薄雾贡献了画面 43% 的 20-40 灰度像素，
   * 是「通透感」的来源；缺了它画面就会死黑、环看起来像贴上去的。
   */
  function buildBackgroundGlow() {
    const size = 512;
    const c = document.createElement('canvas');
    c.width = c.height = size;
    const g = c.getContext('2d');

    // 中心偏冷的淡紫雾
    const grd = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
    grd.addColorStop(0, 'rgba(96,86,150,0.055)');
    grd.addColorStop(0.35, 'rgba(64,58,112,0.035)');
    grd.addColorStop(0.70, 'rgba(30,28,58,0.014)');
    grd.addColorStop(1, 'rgba(6,8,18,0)');
    g.fillStyle = grd;
    g.fillRect(0, 0, size, size);

    const tex = new THREE.CanvasTexture(c);
    tex.needsUpdate = true;
    return tex;
  }

  /** 背景星尘 */
  function buildDust() {
    const n = 1400;
    const pos = new Float32Array(n * 3);
    const col = new Float32Array(n * 3);
    const size = new Float32Array(n);
    const bright = new Float32Array(n);
    const c = new THREE.Color();
    for (let i = 0; i < n; i++) {
      // 球壳分布
      const r = 6 + Math.random() * 10;
      const th = Math.random() * Math.PI * 2;
      const ph = Math.acos(2 * Math.random() - 1);
      pos[i * 3] = r * Math.sin(ph) * Math.cos(th);
      pos[i * 3 + 1] = r * Math.sin(ph) * Math.sin(th);
      pos[i * 3 + 2] = r * Math.cos(ph);
      c.setHSL(0.62 + Math.random() * 0.12, 0.35, 0.55);
      col[i * 3] = c.r; col[i * 3 + 1] = c.g; col[i * 3 + 2] = c.b;
      size[i] = 0.0020 + Math.random() * 0.0040;
      bright[i] = 0.15 + Math.random() * 0.45;
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    geo.setAttribute('aColor', new THREE.BufferAttribute(col, 3));
    geo.setAttribute('aSize', new THREE.BufferAttribute(size, 1));
    geo.setAttribute('aBright', new THREE.BufferAttribute(bright, 1));
    const mat = new THREE.ShaderMaterial({
      uniforms: {
        uTex: { value: makeStarTexture(32) },
        uScale: { value: 966 },
        uTime: { value: 0 },
        uFlow: { value: 0 },
        uRingR: { value: RING_R },
        uSquash: { value: RING_SQUASH },
        uTwist: { value: RING_TWIST },
      },
      vertexShader: VERT_PLAIN,
      fragmentShader: FRAG,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    return new THREE.Points(geo, mat);
  }


  /** 把背景辉光做成一块始终朝向相机的巨大面片。 */
  function buildBackgroundGlowPlane() {
    const geo = new THREE.PlaneGeometry(26, 26);
    const mat = new THREE.MeshBasicMaterial({
      map: buildBackgroundGlow(),
      transparent: true,
      depthWrite: false,
      depthTest: false,
      blending: THREE.AdditiveBlending,
    });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.z = -6;   // 推到粒子后方
    mesh.renderOrder = -1;  // 最先绘制
    return mesh;
  }

  // ---------- 初始化 ----------
  function initThree() {
    container = document.getElementById('starmap-canvas').parentElement;
    const canvasEl = document.getElementById('starmap-canvas');

    renderer = new THREE.WebGLRenderer({
      canvas: canvasEl,
      antialias: true,
      alpha: false,
      powerPreference: 'high-performance',
    });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    // ACES 色调映射：这是解决过曝的正解（HDR 压缩而非硬截断）
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.85;
    renderer.outputColorSpace = THREE.SRGBColorSpace;

    scene = new THREE.Scene();
    // 底色留一点亮度，纯黑会让环显得像贴纸
    scene.background = new THREE.Color(0x04060c);

    camera = new THREE.PerspectiveCamera(48, 1, 0.1, 100);
    camera.position.set(0, 0, 2.3);

    scene.add(buildBackgroundGlowPlane());
    dust = buildDust();
    scene.add(dust);
    coreGroup = buildCore();
    scene.add(coreGroup);
  }

  function resize() {
    if (!renderer || !container) return;
    const rect = container.getBoundingClientRect();
    const w = Math.max(320, rect.width);
    const h = Math.max(320, rect.height);
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    // uScale 随视口高度变化，保证不同窗口下粒子视觉大小一致
    const sc = (h / 2) / Math.tan((camera.fov * Math.PI / 180) / 2);
    if (points) points.material.uniforms.uScale.value = sc;
    if (starsPoints) starsPoints.material.uniforms.uScale.value = sc;
    if (dust) dust.material.uniforms.uScale.value = sc;
  }

  // ---------- 渲染循环 ----------
  function animate(now) {
    if (!startTime) startTime = now;
    const time = now - startTime;

    // 缓动
    view.yaw += (view.targetYaw - view.yaw) * 0.10;
    view.pitch += (view.targetPitch - view.pitch) * 0.10;
    view.zoom += (view.targetZoom - view.zoom) * 0.12;
    view.panX += (view.targetPanX - view.panX) * 0.12;
    view.panY += (view.targetPanY - view.panY) * 0.12;

    // 相机环绕
    const dist = 2.3 / view.zoom;
    camera.position.set(
      Math.sin(view.yaw) * Math.cos(view.pitch) * dist + view.panX * 0.004,
      Math.sin(view.pitch) * dist - view.panY * 0.004,
      Math.cos(view.yaw) * Math.cos(view.pitch) * dist
    );
    camera.lookAt(0, 0, 0);

    // 环体缓慢自转，让粒子有流动感
    // 只推进流动时间：粒子沿 8 字轨迹向前跑，环本身保持静止。
    // （不要给 points 加 rotation —— 那是整个环绕轴转，和原型的「流动」是两回事）
    if (points) {
      points.material.uniforms.uTime.value = time * 0.001;
      if (points.material.uniforms.uFlow.value !== FLOW_SPEED) {
        points.material.uniforms.uFlow.value = FLOW_SPEED;
      }
    }

    // 星轨缓慢自转：每条轨道转速不同，形成互相错动的层次
    if (coreGroup && coreGroup.userData.rings) {
      const sec = time * 0.001;
      for (const r of coreGroup.userData.rings) {
        r.obj.rotation.z = r.spin * sec;
      }
    }

    renderer.render(scene, camera);
    rafId = requestAnimationFrame(animate);
  }

  // ---------- 交互 ----------
  function bindEvents() {
    const el = renderer.domElement;

    el.addEventListener('pointerdown', (e) => {
      dragging = true;
      dragStart = { x: e.clientX, y: e.clientY, yaw: view.targetYaw, pitch: view.targetPitch,
                    px: view.targetPanX, py: view.targetPanY };
      el.setPointerCapture(e.pointerId);
      el.style.cursor = 'grabbing';
    });

    el.addEventListener('pointermove', (e) => {
      if (dragging && dragStart) {
        const dx = e.clientX - dragStart.x;
        const dy = e.clientY - dragStart.y;
        if (e.shiftKey) {
          view.targetYaw = dragStart.yaw + dx * 0.006;
          view.targetPitch = Math.max(-1.35, Math.min(0.9, dragStart.pitch + dy * 0.005));
        } else {
          view.targetPanX = dragStart.px + dx;
          view.targetPanY = dragStart.py + dy;
        }
        return;
      }
      // 悬停检测
      const hit = hitTest(e);
      if (hit !== hovered) {
        hovered = hit;
        el.style.cursor = hit ? 'pointer' : 'grab';
        if (hit) showStarCard(hit, e.clientX, e.clientY);
        else if (!selected) hideStarCard();
      } else if (hit) {
        showStarCard(hit, e.clientX, e.clientY);
      }
    });

    const end = () => {
      dragging = false;
      dragStart = null;
      el.style.cursor = 'grab';
    };
    el.addEventListener('pointerup', end);
    el.addEventListener('pointercancel', end);

    el.addEventListener('wheel', (e) => {
      e.preventDefault();
      view.targetZoom = Math.max(0.4, Math.min(4.0, view.targetZoom * (e.deltaY > 0 ? 0.92 : 1.08)));
    }, { passive: false });

    el.addEventListener('dblclick', () => {
      view.targetYaw = 0; view.targetPitch = -0.10; view.targetZoom = 1.0;
      view.targetPanX = 0; view.targetPanY = 0;
      selected = null;
      hideStarCard();
    });

    el.addEventListener('click', (e) => {
      const hit = hitTest(e);
      if (hit) { selected = hit; showStarCard(hit, e.clientX, e.clientY); }
      else { selected = null; hideStarCard(); }
    });

    window.addEventListener('resize', resize);
  }

  /** 屏幕坐标命中测试 */
  function hitTest(e) {
    if (!starsData.length) return null;
    const rect = renderer.domElement.getBoundingClientRect();
    const mx = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    const my = -((e.clientY - rect.top) / rect.height) * 2 + 1;
    const ray = new THREE.Raycaster();
    ray.params.Points = { threshold: 0.06 };
    ray.setFromCamera(new THREE.Vector2(mx, my), camera);
    const hits = ray.intersectObject(starsPoints, false);
    if (!hits.length) return null;
    return starsData[hits[0].index] || null;
  }

  // ---------- 星卡 ----------
  function showStarCard(star, mx, my) {
    const meta = tierMeta[star.tier] || { label: '记忆', color: '#8ab4ff' };
    const card = document.getElementById('starmap-card');
    card.style.setProperty('--accent', meta.color);
    document.getElementById('smc-tag').textContent = meta.label;
    document.getElementById('smc-who').textContent = star.name;
    const d = star.ts ? new Date(star.ts * 1000) : null;
    const ds = d
      ? `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
      : '—';
    document.getElementById('smc-meta').textContent = `第 ${star.round_no} 轮 · ${star.kind} · ${ds}`;
    document.getElementById('smc-body').textContent = star.text || '（无正文）';
    card.classList.add('show');

    const rect = container.getBoundingClientRect();
    const lx = mx - rect.left, ly = my - rect.top;
    const cw = card.offsetWidth || 280, ch = card.offsetHeight || 200;
    let x = lx + 22, y = ly - ch / 2;
    if (x + cw + 14 > rect.width) x = lx - cw - 22;
    if (x < 14) x = 14;
    if (y < 14) y = 14;
    if (y + ch + 14 > rect.height) y = rect.height - ch - 14;
    card.style.left = x + 'px';
    card.style.top = y + 'px';
  }

  function hideStarCard() {
    const card = document.getElementById('starmap-card');
    if (card) card.classList.remove('show');
  }

  // ---------- HUD / 档案 / 告警（沿用 DOM 版本） ----------
  const ROMAN = ['Ⅰ', 'Ⅱ', 'Ⅲ', 'Ⅳ', 'Ⅴ'];
  const CAT_COLORS = {
    黄金裔: '#4ea3ff', 劫余: '#f0b429', 岁月: '#b06bff',
    命运: '#ff6ba8', 律令: '#4ecb9b', 世界: '#7dd3ff',
    容器: '#c9a0ff', 浪漫: '#ff9ec4', 理性: '#8fd4ff', 门径: '#7bffd4',
    纷争: '#ff8a6b', 死亡: '#b0a4d8', 疗愈: '#6be0b0',
    海洋: '#5fb8ff', 疾行: '#ffd36b', 持明: '#9fd0c0',
  };

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (ch) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    })[ch]);
  }

  function renderProfiles(list) {
    const box = document.getElementById('starmap-profiles');
    if (!box) return;
    box.innerHTML = list.slice(0, 2).map((p, idx) => {
      const color = CAT_COLORS[p.category] || '#8ab4ff';
      return `
        <div class="prof" style="--pc:${color}">
          <div class="prof-head">
            <span class="prof-idx">${ROMAN[idx]}</span>
            <span class="prof-cat">${p.category}</span>
          </div>
          <div class="prof-portrait"><div class="prof-glyph">${p.name.charAt(0)}</div></div>
          <div class="prof-name">${p.name}</div>
          <div class="prof-code">${p.code}.NO</div>
          <div class="prof-rows">
            <div><span>编号</span><b>No.${String(p.number).padStart(2, '0')}</b></div>
            <div><span>类别</span><b>${p.category} · ${p.dominant}</b></div>
            <div><span>所属</span><b>翁法罗斯 / 逐火之旅</b></div>
            <div><span>代码号</span><b class="mono">${p.serial}</b><i class="status">${p.status}</i></div>
            <div><span>轮次距离</span><b class="num" data-target="${p.distance}">0</b></div>
            <div><span>数据</span><b class="ok">已上传至婆娑</b></div>
          </div>
          <div class="prof-desc">${escapeHtml(p.latest_text || '暂无记录')}</div>
        </div>`;
    }).join('');

    box.querySelectorAll('b.num').forEach((el) => {
      const targetNum = parseInt(el.dataset.target, 10) || 0;
      const t0 = performance.now();
      const dur = 1400;
      function tick(now) {
        const k = Math.max(0, Math.min(1, (now - t0) / dur));
        const eased = 1 - Math.pow(1 - k, 3);
        el.textContent = Math.floor(targetNum * eased).toLocaleString('en-US');
        if (k < 1) requestAnimationFrame(tick);
      }
      requestAnimationFrame(tick);
    });
  }

  const ALERTS = [
    { code: 'MERGE-WARN', title: '记忆上传中断', lines: ['火种采集第 1074 轮校验行切断', '签名校验失败: 0x00 ≠ 0xFF'], tail: 'Refusing to write: index out of range (33558336)', level: 'warn' },
    { code: 'GATE', title: '门径开启', lines: ['三门同时出现，一道渡入明天', '每次开门，总有一个要留下'], tail: '准备下？', level: 'gate' },
    { code: 'THREAD', title: '心弦已断', lines: ['断了……另一项没有回归', '它们……完全……'], tail: '要不要救她？', level: 'warn' },
    { code: 'MERGE-STATUS', title: '黄金裔状态', lines: ['编号 82 星底 · 已消失于黄泉之海', '负世潮 6.1 · 共命率 0.92'], tail: 'restore() returned null', level: 'info' },
    { code: 'BLACK-TIDE', title: '黑潮预警', lines: ['黑潮越过第三道门径', '侵蚀度 73% 并在加快'], tail: '不要回头看看', level: 'warn' },
  ];

  function renderAlerts() {
    const box = document.getElementById('starmap-alerts');
    if (!box) return;
    const picked = ALERTS.slice().sort(() => Math.random() - 0.5).slice(0, 3);
    box.innerHTML = picked.map((a, i) => `
      <div class="alert alert-${a.level}" style="top:${22 + i * 24}%;right:${4 + (i % 2) * 10}%">
        <div class="al-head"><span class="al-code">${a.code} /</span><span class="al-title">${a.title}</span></div>
        <div class="al-body">${a.lines.map((l) => `<div>${escapeHtml(l)}</div>`).join('')}</div>
        <div class="al-tail mono">${escapeHtml(a.tail)}</div>
        <div class="al-actions"><button class="al-btn">重试</button><button class="al-btn al-btn-ghost">放弃</button></div>
      </div>`).join('');
    box.querySelectorAll('.al-btn').forEach((b) => {
      b.addEventListener('click', (e) => {
        e.stopPropagation();
        const card = b.closest('.alert');
        card.style.transition = 'opacity .3s, transform .3s';
        card.style.opacity = '0';
        card.style.transform = 'translateX(20px)';
        setTimeout(() => card.remove(), 320);
      });
    });
  }

  function renderHud(stats) {
    const hud = document.getElementById('starmap-hud');
    const legend = document.getElementById('starmap-legend');
    let h = '', l = '';
    for (const k of TIER_ORDER) {
      const tt = stats.tiers[k];
      if (!tt) continue;
      h += `<div class="row"><span class="dot" style="background:${tt.color}"></span><span>${tt.label} ${tt.count}</span></div>`;
      l += `<span><i style="background:${tt.color};box-shadow:0 0 6px ${tt.color}"></i>${tt.label}</span>`;
    }
    h += `<div class="total">共 ${stats.total} 颗</div>`;
    hud.innerHTML = h;
    legend.innerHTML = l;
  }


  /** 把背景辉光做成一块始终朝向相机的巨大面片。 */
  function buildBackgroundGlowPlane() {
    const geo = new THREE.PlaneGeometry(26, 26);
    const mat = new THREE.MeshBasicMaterial({
      map: buildBackgroundGlow(),
      transparent: true,
      depthWrite: false,
      depthTest: false,
      blending: THREE.AdditiveBlending,
    });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.z = -6;   // 推到粒子后方
    mesh.renderOrder = -1;  // 最先绘制
    return mesh;
  }

  // ---------- 初始化 ----------
  /**
   * 初始化星图。
   * @param {Function} callApi 宿主接口调用函数
   * @returns {Promise<void>}
   */
  async function init(callApi) {
    const canvasEl = document.getElementById('starmap-canvas');
    if (!canvasEl) return;

    const stateEl = document.getElementById('starmap-state');
    try {
      const data = await callApi('starmap');
      if (!data || !data.stars) throw new Error('没有读到记忆数据');

      tierMeta = data.stats.tiers || {};
      maxRound = data.stats.round_no || 1;
      RING_R = data.stats.ring_r || 1.0;
      RING_SQUASH = data.stats.ring_squash || 0.78;
      RING_TWIST = data.stats.ring_twist || 0.45;
      starsData = data.stars;

      if (!renderer) {
        initThree();
        bindEvents();
        resize();
        rafId = requestAnimationFrame(animate);
      }

      // 数据就绪后再建粒子，保证用的是正确的曲线参数
      if (points) { scene.remove(points); pointsGeo = null; }
      points = buildRibbon(150000);
      points.material.uniforms.uScale.value =
        ((renderer.domElement.clientHeight || window.innerHeight) / 2) / Math.tan((camera.fov * Math.PI / 180) / 2);
      scene.add(points);

      if (starsPoints) scene.remove(starsPoints);
      starsPoints = buildMemoryStars();
      starsPoints.material.uniforms.uScale.value =
        ((renderer.domElement.clientHeight || window.innerHeight) / 2) / Math.tan((camera.fov * Math.PI / 180) / 2);
      scene.add(starsPoints);

      // 粒子流速滑块：实时改变 shader 里的 uFlow
      const speedEl = document.getElementById('sm-speed');
      const speedVal = document.getElementById('sm-speed-val');
      if (speedEl) {
        speedEl.value = String(FLOW_SPEED);
        if (speedVal) speedVal.textContent = FLOW_SPEED.toFixed(2);
        speedEl.addEventListener('input', () => {
          FLOW_SPEED = parseFloat(speedEl.value) || 0;
          if (points) points.material.uniforms.uFlow.value = FLOW_SPEED;
          if (speedVal) speedVal.textContent = FLOW_SPEED.toFixed(2);
        });
      }

      renderHud(data.stats);
      renderProfiles(data.profiles || []);
      renderAlerts();
      stateEl.classList.add('hide');
      // 版本标记：控制台里能看到，用来确认浏览器加载的是不是最新文件
      console.log('%c[starmap] build 2026-11-21-1930  rings+flow', 'color:#8ab4ff');
    } catch (e) {
      stateEl.innerHTML = `<div style="color:#d9737f">星图数据读取失败：${e.message}</div>`;
    }
  }

  return { init };
})();

window.StarMap = StarMap;
