/* Bot Office — isometric office where compliance + content bots live and work.
 * Everything is drawn with canvas primitives (no image assets), so it runs by just
 * opening index.html. Swap the draw* functions for sprites later if you buy pixel art.
 */
(() => {
  'use strict';

  // ───────────────────────── Isometric helpers ─────────────────────────
  const TW = 64, TH = 32;              // tile width / height in px
  const W = 24, H = 16;                // grid size (cells)
  const iso = (x, y, z = 0) => ({ x: (x - y) * TW / 2, y: (x + y) * TH / 2 - z });

  const canvas = document.getElementById('office');
  let ctx = canvas.getContext('2d'); // swapped temporarily when drawing portraits
  let dpr = 1, cam = { x: 0, y: 0, zoom: 1 };

  function poly(pts, fill, stroke) {
    ctx.beginPath();
    pts.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
    ctx.closePath();
    if (fill) { ctx.fillStyle = fill; ctx.fill(); }
    if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = 1; ctx.stroke(); }
  }
  function shade(hex, amt) {
    const n = parseInt(hex.slice(1), 16);
    const f = (c) => Math.max(0, Math.min(255, Math.round(c + (amt < 0 ? c * amt : (255 - c) * amt))));
    return '#' + [f(n >> 16), f((n >> 8) & 255), f(n & 255)].map((c) => c.toString(16).padStart(2, '0')).join('');
  }
  // Box with base corner (x,y), footprint w×d, height h (px), lifted z0 (px).
  function box(x, y, w, d, h, z0, col, opts = {}) {
    const top = opts.top || shade(col, 0.18), left = opts.left || shade(col, -0.18), right = opts.right || shade(col, -0.38);
    const A = (z) => iso(x, y, z), B = (z) => iso(x + w, y, z), C = (z) => iso(x + w, y + d, z), D = (z) => iso(x, y + d, z);
    const z1 = z0 + h;
    poly([D(z0), C(z0), C(z1), D(z1)], left, opts.stroke);   // front-left face (y = y+d)
    poly([B(z0), C(z0), C(z1), B(z1)], right, opts.stroke);  // front-right face (x = x+w)
    poly([A(z1), B(z1), C(z1), D(z1)], top, opts.stroke);
  }
  // Quads painted on a face plane.
  const quadY = (yp, x1, x2, z1, z2, fill) => poly([iso(x1, yp, z1), iso(x2, yp, z1), iso(x2, yp, z2), iso(x1, yp, z2)], fill);
  const quadX = (xp, y1, y2, z1, z2, fill) => poly([iso(xp, y1, z1), iso(xp, y2, z1), iso(xp, y2, z2), iso(xp, y1, z2)], fill);
  function ellipse(x, y, z, rx, ry, fill) {
    const p = iso(x, y, z);
    ctx.beginPath(); ctx.ellipse(p.x, p.y, rx, ry, 0, 0, Math.PI * 2); ctx.fillStyle = fill; ctx.fill();
  }

  // ───────────────────────── Map / zones ─────────────────────────
  const zoneOf = (x, y) => (y >= 8 ? 'lounge' : x >= 10 ? 'content' : 'compliance');
  function floorColor(x, y) {
    const z = zoneOf(x, y), alt = (x + y) % 2;
    if (z === 'lounge') return alt ? '#e0569a' : '#d14a8c';
    if (z === 'content') return alt ? '#1f6f74' : '#1c656a';
    return alt ? '#2c4f9e' : '#284892';
  }

  // Walls you can't walk through between cells (glass railings), with doorways.
  const blockedEdges = new Set();
  const edgeKey = (a, b, c, d) => (a < c || (a === c && b < d) ? `${a},${b}|${c},${d}` : `${c},${d}|${a},${b}`);
  const railings = [];
  for (let x = 0; x < W; x++) if (![4, 5, 15, 16].includes(x)) { blockedEdges.add(edgeKey(x, 7, x, 8)); railings.push({ type: 'railH', x, y: 8 }); }
  for (let y = 0; y < 8; y++) if (![5, 6].includes(y)) { blockedEdges.add(edgeKey(9, y, 10, y)); railings.push({ type: 'railV', x: 10, y }); }

  // Furniture. block:true marks the cells it covers as solid.
  const F = [];
  const add = (o) => (F.push(Object.assign({ block: true, z: 0 }, o)), o);
  // Compliance wing
  add({ type: 'shelf', x: 0.1, y: 0.05, w: 2, d: 0.6, h: 74, books: true });
  add({ type: 'shelf', x: 2.2, y: 0.05, w: 2, d: 0.6, h: 74, books: true });
  add({ type: 'docTable', x: 5.4, y: 0.2, w: 2.6, d: 0.9, h: 22 });
  add({ type: 'cabinet', x: 0.05, y: 5.05, w: 0.7, d: 0.9, h: 40 });
  add({ type: 'cabinet', x: 0.05, y: 6.05, w: 0.7, d: 0.9, h: 40 });
  add({ type: 'plant', x: 9.1, y: 0.2, w: 0.7, d: 0.7, h: 14 });
  add({ type: 'roundTable', x: 6.2, y: 6.1, w: 1.5, d: 1.2, h: 18 });
  // Content studio
  add({ type: 'reelShelf', x: 11.1, y: 0.05, w: 2.6, d: 0.6, h: 52 });
  add({ type: 'greenscreen', x: 19.6, y: 0.05, w: 4.2, d: 0.2, h: 84 });
  add({ type: 'camera', x: 21.25, y: 3.25, w: 0.5, d: 0.5, h: 40 });
  add({ type: 'ringlight', x: 22.3, y: 2.3, w: 0.4, d: 0.4, h: 52 });
  add({ type: 'plant', x: 23.1, y: 6.2, w: 0.7, d: 0.7, h: 14 });
  // Lounge
  add({ type: 'rug', x: 2.6, y: 9.6, w: 4.8, d: 4.8, block: false });
  add({ type: 'bar', x: 0.05, y: 9.05, w: 0.85, d: 2.9, h: 30 });
  add({ type: 'sofa', x: 3.1, y: 10.1, w: 2.8, d: 0.85, h: 14, col: '#c8692e' });
  add({ type: 'sofa', x: 3.1, y: 13.05, w: 2.8, d: 0.85, h: 14, col: '#c8692e', flip: true });
  add({ type: 'coffeeTable', x: 3.9, y: 11.5, w: 1.3, d: 0.9, h: 10 });
  add({ type: 'beanbag', x: 7.9, y: 13.9, w: 0.9, d: 0.9, col: '#3fc6d6', block: false });
  add({ type: 'beanbag', x: 9.2, y: 13.0, w: 0.9, d: 0.9, col: '#ffd23d', block: false });
  add({ type: 'beanbag', x: 7.4, y: 11.9, w: 0.9, d: 0.9, col: '#a77bff', block: false });
  add({ type: 'frontDesk', x: 11.1, y: 10.1, w: 1.9, d: 0.8, h: 24 });
  add({ type: 'billiards', x: 14.4, y: 12.1, w: 2.5, d: 1.4, h: 20 });
  add({ type: 'arcade', x: 20.15, y: 9.1, w: 0.8, d: 0.75, h: 50, col: '#3d6bff', screen: '#2ee6c9' });
  add({ type: 'arcade', x: 21.25, y: 9.1, w: 0.8, d: 0.75, h: 50, col: '#c13dff', screen: '#ff6fae' });
  add({ type: 'vending', x: 23.1, y: 11.1, w: 0.8, d: 0.8, h: 56 });
  add({ type: 'plant', x: 23.15, y: 8.15, w: 0.7, d: 0.7, h: 14 });
  add({ type: 'plant', x: 0.15, y: 15.15, w: 0.7, d: 0.7, h: 14 });
  add({ type: 'plant', x: 23.15, y: 15.15, w: 0.7, d: 0.7, h: 14 });
  add({ type: 'plant', x: 9.15, y: 8.15, w: 0.7, d: 0.7, h: 14 });

  // Desks double as each bot's workstation. seat = cell the bot sits in.
  const desks = {};
  function addDesk(id, x, y, opts = {}) {
    const d = add({ type: 'desk', x: x + 0.15, y: y + 0.1, w: 1.7, d: 0.8, h: 22, dual: opts.dual, zone: opts.zone, owner: id });
    add({ type: 'chair', x: x + 0.65, y: y + 1.15, w: 0.6, d: 0.6, h: 10, block: false, owner: id });
    desks[id] = { desk: d, seat: { x: x + 0.95, y: y + 1.45 } };
  }
  addDesk('doc', 1, 3, { zone: 'compliance' });
  addDesk('reg', 4, 3, { zone: 'compliance' });
  addDesk('risk', 7, 3, { zone: 'compliance' });
  addDesk('vid', 11, 3, { dual: true, zone: 'content' });
  addDesk('cap', 14, 3, { dual: true, zone: 'content' });
  addDesk('sched', 17, 3, { zone: 'content' });
  addDesk('post', 11, 6, { zone: 'content' });
  desks.mgr = { seat: { x: 12.05, y: 11.45 } };

  const solid = Array.from({ length: W }, () => new Array(H).fill(false));
  for (const f of F) if (f.block) {
    for (let cx = Math.floor(f.x); cx < Math.ceil(f.x + f.w - 0.01); cx++)
      for (let cy = Math.floor(f.y); cy < Math.ceil(f.y + f.d - 0.01); cy++)
        if (cx >= 0 && cy >= 0 && cx < W && cy < H) solid[cx][cy] = true;
  }

  // Places bots hang out when idle. z = how high they sit.
  const spots = [
    { x: 3.7, y: 10.45, z: 12, n: 'sofa' }, { x: 5.2, y: 10.45, z: 12, n: 'sofa' },
    { x: 3.7, y: 13.5, z: 12, n: 'sofa' }, { x: 5.2, y: 13.5, z: 12, n: 'sofa' },
    { x: 8.35, y: 14.35, z: 8, n: 'beanbag' }, { x: 9.65, y: 13.45, z: 8, n: 'beanbag' }, { x: 7.85, y: 12.35, z: 8, n: 'beanbag' },
    { x: 1.5, y: 10.5, z: 0, n: 'coffee' }, { x: 1.5, y: 9.5, z: 0, n: 'coffee' },
    { x: 20.55, y: 10.3, z: 0, n: 'arcade' }, { x: 21.65, y: 10.3, z: 0, n: 'arcade' },
    { x: 14.0, y: 14.4, z: 0, n: 'billiards' }, { x: 17.4, y: 12.6, z: 0, n: 'billiards' },
    { x: 22.4, y: 11.5, z: 0, n: 'vending' }, { x: 18.5, y: 14.5, z: 0, n: 'wander' }, { x: 11.5, y: 14.2, z: 0, n: 'wander' },
  ];

  // ───────────────────────── Pathfinding (A*) ─────────────────────────
  function findPath(sx, sy, gx, gy) {
    const start = `${sx},${sy}`, goal = `${gx},${gy}`;
    if (start === goal) return [];
    const open = [[sx, sy]], came = {}, g = { [start]: 0 }, f = { [start]: Math.abs(gx - sx) + Math.abs(gy - sy) };
    const inOpen = new Set([start]);
    while (open.length) {
      open.sort((a, b) => f[`${a[0]},${a[1]}`] - f[`${b[0]},${b[1]}`]);
      const [cx, cy] = open.shift(); const ck = `${cx},${cy}`; inOpen.delete(ck);
      if (ck === goal) {
        const path = []; let k = goal;
        while (k !== start) { const [px, py] = k.split(',').map(Number); path.unshift({ x: px + 0.5, y: py + 0.5 }); k = came[k]; }
        return path;
      }
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        const nx = cx + dx, ny = cy + dy, nk = `${nx},${ny}`;
        if (nx < 0 || ny < 0 || nx >= W || ny >= H) continue;
        if (solid[nx][ny] && nk !== goal) continue;
        if (blockedEdges.has(edgeKey(cx, cy, nx, ny))) continue;
        const ng = g[ck] + 1;
        if (ng < (g[nk] ?? Infinity)) {
          came[nk] = ck; g[nk] = ng; f[nk] = ng + Math.abs(gx - nx) + Math.abs(gy - ny);
          if (!inOpen.has(nk)) { open.push([nx, ny]); inOpen.add(nk); }
        }
      }
    }
    return null;
  }

  // ───────────────────────── Bots ─────────────────────────
  const BOT_DEFS = [
    { id: 'doc', name: 'Doc Reader', role: 'Reads & extracts regulation PDFs', team: 'compliance', color: '#3ddc84' },
    { id: 'reg', name: 'Reg Checker', role: 'Checks business rules vs. the law', team: 'compliance', color: '#4da3ff' },
    { id: 'risk', name: 'Risk Scout', role: 'Writes risk-level reports', team: 'compliance', color: '#ff8a3d' },
    { id: 'vid', name: 'Video Editor', role: 'Cuts & edits raw videos', team: 'content', color: '#ff6fae' },
    { id: 'cap', name: 'Caption Writer', role: 'Hooks, captions & hashtags', team: 'content', color: '#ffd23d' },
    { id: 'sched', name: 'Scheduler', role: 'Plans the posting calendar', team: 'content', color: '#a77bff' },
    { id: 'post', name: 'Poster', role: 'Publishes to the platforms', team: 'content', color: '#2ee6c9' },
    { id: 'mgr', name: 'Bot Manager', role: 'Keeps everyone on track', team: 'manager', color: '#e8e8f0' },
  ];
  const LINES = {
    idle: ['Kape muna ☕', 'Micro-chips!', 'Break time!', 'Sino next?', 'G lang 😎', 'Chill muna', 'Beep boop', 'Snack?', '✨'],
    compliance: ['Sec. 12... hmm', 'Checking DPA…', 'May risk dito ⚠️', 'Reading p.4', 'Citing Art. 7', 'Compliant ✅', 'Need clause ref'],
    content: ['Cutting…', 'Hook muna!', 'Rendering…', '#fyp', 'Caption on point', 'Color grade 🎨', '3…2…1 post!'],
    chat: [['Uy, tapos ka na?', 'Oo, ikaw?'], ['Billiards?', 'Tara!'], ['May bagong PDF', 'Ako na bahala'],
      ['Viral \'to promise', 'Sana all 😂'], ['Kain tayo?', 'Mamaya pa'], ['Nice edit!', 'Salamat 🥹']],
  };

  const bots = BOT_DEFS.map((d, i) => {
    const s = desks[d.id].seat;
    return Object.assign({}, d, {
      x: s.x, y: s.y, z: 0, path: [], target: null, state: 'idle', dir: i % 2,
      task: null, queue: [], log: [], done: 0, idleTimer: 1 + Math.random() * 3, breakUntil: 0,
      bubble: null, blink: Math.random() * 4, phase: Math.random() * 6, spot: null, sitZ: 0,
    });
  });
  const botById = Object.fromEntries(bots.map((b) => [b.id, b]));

  const rand = (a) => a[Math.floor(Math.random() * a.length)];
  const now = () => performance.now() / 1000;
  function say(b, text, secs = 2.8) { b.bubble = { text, until: now() + secs }; }

  function walkTo(b, tx, ty, sitZ = 0) {
    const p = findPath(Math.floor(b.x), Math.floor(b.y), Math.floor(tx), Math.floor(ty));
    if (!p) return false;
    if (p.length) p[p.length - 1] = { x: tx, y: ty }; else p.push({ x: tx, y: ty });
    b.path = p; b.sitZ = sitZ; b.z = 0;
    return true;
  }
  const spotTaken = (s, me) => bots.some((o) => o !== me && o.spot === s);

  // ───────────────────────── Tasks ─────────────────────────
  const PIPELINES = {
    compliance: [
      { bot: 'doc', verb: 'Read & extract', secs: 7 },
      { bot: 'reg', verb: 'Compliance check', secs: 10 },
      { bot: 'risk', verb: 'Risk report', secs: 8 },
    ],
    content: [
      { bot: 'vid', verb: 'Edit video', secs: 11 },
      { bot: 'cap', verb: 'Write captions', secs: 6 },
      { bot: 'sched', verb: 'Schedule post', secs: 5 },
      { bot: 'post', verb: 'Publish', secs: 5 },
    ],
  };
  const stats = { done: 0 };

  function assign(botId, text, opts = {}) {
    const b = botById[botId]; if (!b) return null;
    const t = { text, secs: opts.secs || 8, progress: 0, next: opts.next || null, file: opts.file || null,
      external: !!opts.external, id: opts.id || null, finished: false, result: null };
    b.queue.push(t);
    feed(b, `got a task: ${text}`);
    if (!b.task && b.state !== 'break') say(b, 'Ako na! 🙋', 2);
    return t;
  }
  function startPipeline(team, file) {
    const steps = PIPELINES[team]; if (!steps) return;
    const chain = steps.map((s) => ({ bot: s.bot, text: `${s.verb}: ${file}`, secs: s.secs * (0.8 + Math.random() * 0.5), file }));
    for (let i = chain.length - 2; i >= 0; i--) chain[i].next = chain[i + 1];
    assign(chain[0].bot, chain[0].text, chain[0]);
  }
  function finishTask(b) {
    const t = b.task; b.task = null; b.done++; stats.done++;
    const r = t.result || {};
    const failed = r.ok === false;
    b.log.unshift({ text: `${failed ? '⚠️' : '✅'} ${r.text || t.text}`, url: r.url });
    b.log.length = Math.min(b.log.length, 8);
    feed(b, r.text ? r.text : `done — ${t.text}`, r.url);
    if (failed) say(b, 'Hala, may problema 😵', 3);
    else if (r.level === 'HIGH') say(b, 'HIGH risk! 🚩', 3.5);
    else if (r.level === 'MEDIUM') say(b, 'Medium risk ⚠️', 3);
    else if (r.level === 'LOW') say(b, 'Low risk, ayos! ✅', 3);
    else say(b, rand(['Tapos! ✅', 'Done!', 'Next!', 'Ez 😎']), 2);
    if (t.next) setTimeout(() => assign(t.next.bot, t.next.text, t.next), 600);
  }

  // ───────────────────────── Bot brain ─────────────────────────
  function updateBot(b, dt, t) {
    // a new task interrupts a lounge stroll: head back to the desk
    if (b.id !== 'mgr' && b.path.length && !b.task && b.queue.length && b.state !== 'break' && b.state !== 'walking') {
      b.path = []; b.spot = null; b.z = 0;
    }
    // movement
    if (b.path.length) {
      const p = b.path[0], dx = p.x - b.x, dy = p.y - b.y, dist = Math.hypot(dx, dy), sp = 2.4 * dt;
      if (Math.abs(dx - dy) > 0.001) b.face = dx - dy > 0 ? 1 : -1; // screen-x direction
      if (dist <= sp) { b.x = p.x; b.y = p.y; b.path.shift(); } else { b.x += dx / dist * sp; b.y += dy / dist * sp; }
      b.z = Math.abs(Math.sin(t * 14 + b.phase)) * 2.5;
      if (!b.path.length) b.z = 0;
      return;
    }
    const seat = desks[b.id].seat, atDesk = Math.hypot(b.x - seat.x, b.y - seat.y) < 0.05;

    if (b.id === 'mgr') return managerBrain(b, dt, t, atDesk);

    if (b.state === 'break' && t > b.breakUntil) b.state = 'idle';
    if (b.state !== 'break' && !b.task && b.queue.length) { b.task = b.queue.shift(); b.spot = null; }

    if (b.task && b.state !== 'break') {
      if (!atDesk) { b.state = 'walking'; walkTo(b, seat.x, seat.y, 6); return; }
      b.state = 'working'; b.face = 1;
      b.z = 6 + Math.abs(Math.sin(t * 7 + b.phase)) * 1.5;
      // real (server) tasks wait at 92% until the server says they're done
      const cap = b.task.external && !b.task.finished ? 0.92 : 1;
      b.task.progress = Math.min(cap, b.task.progress + dt / b.task.secs);
      if (Math.random() < dt * 0.12 && !b.bubble) say(b, rand(LINES[b.team]));
      if (b.task.progress >= 1) finishTask(b);
      return;
    }

    // idle life: hang out in the lounge, sometimes chat
    if (b.state === 'working' || b.state === 'walking') b.state = 'idle';
    b.z = (b.spot ? b.spot.z : 0) + Math.sin(t * 2.2 + b.phase) * 1.2;
    b.idleTimer -= dt;
    if (b.idleTimer <= 0) {
      b.idleTimer = 6 + Math.random() * 9;
      const r = Math.random();
      const others = bots.filter((o) => o !== b && o.id !== 'mgr' && !o.task && !o.path.length);
      if (r < 0.25 && others.length) {
        const o = rand(others), [a, c] = rand(LINES.chat);
        b.spot = null;
        walkTo(b, Math.min(W - 0.5, Math.max(0.5, o.x + (o.x < 22 ? 0.9 : -0.9))), o.y);
        setTimeout(() => say(b, a), 1800); setTimeout(() => say(o, c), 3600);
      } else {
        const free = spots.filter((s) => !spotTaken(s, b));
        const s = rand(free);
        if (s) { b.spot = s; walkTo(b, s.x, s.y, s.z); }
        if (Math.random() < 0.5) setTimeout(() => !b.task && say(b, rand(LINES.idle)), 2500);
      }
    }
  }

  let mgrTimer = 12;
  function managerBrain(b, dt, t, atDesk) {
    b.z = (atDesk ? 6 : 0) + Math.sin(t * 2 + b.phase) * 1.2;
    mgrTimer -= dt;
    if (mgrTimer > 0) return;
    mgrTimer = 18 + Math.random() * 14;
    const working = bots.filter((x) => x.state === 'working').length;
    const queued = bots.reduce((n, x) => n + x.queue.length, 0);
    const msg = working ? `All ok, ${working} working · ${queued} queued` : `All ok, ${stats.done} tasks done`;
    document.getElementById('managerStatus').textContent = msg;
    feed(b, msg);
    if (Math.random() < 0.5 && atDesk) {
      const busy = bots.filter((x) => x.state === 'working' && x.id !== 'mgr');
      if (busy.length) {
        const v = rand(busy);
        walkTo(b, v.x + (v.x > 1.5 ? -0.9 : 0.9), v.y);
        setTimeout(() => say(b, rand(['Kamusta? 👀', 'Good job!', 'Keep going 💪'])), 3500);
        setTimeout(() => walkTo(b, desks.mgr.seat.x, desks.mgr.seat.y, 6), 8000);
      }
    } else if (!atDesk && !b.path.length) walkTo(b, desks.mgr.seat.x, desks.mgr.seat.y, 6);
    else say(b, rand(['All ok 👍', 'Status check ✔', 'Walang tulog!']));
  }

  // ───────────────────────── Drawing: furniture ─────────────────────────
  const T = { t: 0 };
  function drawFurniture(f) {
    const { x, y, w, d, h } = f;
    switch (f.type) {
      case 'rug': poly([iso(x, y), iso(x + w, y), iso(x + w, y + d), iso(x, y + d)], '#2e8f7c'); poly([iso(x + .3, y + .3), iso(x + w - .3, y + .3), iso(x + w - .3, y + d - .3), iso(x + .3, y + d - .3)], '#37a68f'); break;
      case 'shelf':
        box(x, y, w, d, h, 0, '#7a4a2a');
        for (let r = 0; r < 4; r++) {
          const z1 = 6 + r * 17;
          quadY(y + d, x + .05, x + w - .05, z1, z1 + 2, '#4b2c16');
          if (f.books) for (let i = 0; i < 9; i++) {
            const bx = x + .1 + i * (w - .2) / 9, col = ['#e84a5f', '#ffd23d', '#3ddc84', '#4da3ff', '#ff8a3d', '#a77bff'][(i * 7 + r * 3) % 6];
            quadY(y + d + 0.001, bx, bx + (w - .2) / 9 - .03, z1 + 2, z1 + 12 + ((i + r) % 3) * 1.5, col);
          }
        }
        break;
      case 'reelShelf':
        box(x, y, w, d, h, 0, '#3b3060');
        for (let r = 0; r < 2; r++) for (let i = 0; i < 4; i++) {
          const p = iso(x + .35 + i * .6, y + d, 14 + r * 22);
          ctx.beginPath(); ctx.arc(p.x, p.y, 7, 0, 7); ctx.fillStyle = '#c9c9d6'; ctx.fill();
          ctx.beginPath(); ctx.arc(p.x, p.y, 2.5, 0, 7); ctx.fillStyle = '#3b3060'; ctx.fill();
        }
        break;
      case 'cabinet':
        box(x, y, w, d, h, 0, '#8b93a8');
        for (let r = 0; r < 3; r++) quadX(x + w + .001, y + .15, y + d - .15, 6 + r * 12, 8 + r * 12, '#5d6478');
        break;
      case 'docTable':
        box(x, y, w, d, h, 0, '#a8673a');
        for (let i = 0; i < 4; i++) box(x + .25 + i * .6, y + .2, .4, .45, 4 + (i % 3) * 3, h, '#f4f1e8');
        break;
      case 'roundTable':
        ellipse(x + w / 2, y + d / 2, 0, 18, 9, 'rgba(0,0,0,.25)');
        box(x + w / 2 - .08, y + d / 2 - .08, .16, .16, h, 0, '#5a4030');
        ellipse(x + w / 2, y + d / 2, h, 30, 15, '#c47a45'); ellipse(x + w / 2, y + d / 2, h + 1, 27, 13, '#d88c55');
        break;
      case 'desk': {
        box(x, y, w, d, h, 0, '#b8743f');
        const glow = f.owner && botById[f.owner] && botById[f.owner].state === 'working';
        const screens = f.dual ? [x + .15, x + .9] : [x + .5];
        for (const sx of screens) {
          box(sx, y + .1, .65, .1, 18, h + 3, '#22223a');
          box(sx + .28, y + .14, .08, .05, 3, h, '#22223a');
          const sc = glow ? (f.zone === 'content' ? ['#ff6fae', '#7a5cff'][Math.floor(T.t * 2 + sx) % 2] : '#7fd4ff') : '#2b3350';
          quadY(y + .2 + .001, sx + .05, sx + .6, h + 5, h + 19, sc);
          if (glow) for (let l = 0; l < 3; l++) quadY(y + .2 + .002, sx + .1, sx + .1 + (.2 + ((l * 37 + Math.floor(T.t * 3)) % 5) * .06), h + 15 - l * 4, h + 16 - l * 4, 'rgba(255,255,255,.7)');
        }
        box(x + .45, y + .45, .6, .2, 2, h, '#3a3a52'); // keyboard
        if (f.zone === 'compliance') box(x + 1.25, y + .4, .3, .35, 5, h, '#f4f1e8');
        else { const p = iso(x + 1.45, y + .5, h + 4); ctx.beginPath(); ctx.arc(p.x, p.y, 5, 0, 7); ctx.fillStyle = '#ffd23d'; ctx.fill(); }
        break;
      }
      case 'chair':
        box(x, y, w, d, h, 0, '#5b4bb8');
        box(x, y + d - .12, w, .12, 14, h, '#6a59d1');
        break;
      case 'greenscreen':
        box(x, y, w, d, h, 0, '#2fb35c', { top: '#3fcf6d', left: '#2fb35c' });
        break;
      case 'camera': {
        const c = iso(x + .25, y + .25, 0), top = iso(x + .25, y + .25, 34);
        ctx.strokeStyle = '#1c1c28'; ctx.lineWidth = 2;
        for (const [ox, oy] of [[-8, 4], [8, 4], [0, -3]]) { ctx.beginPath(); ctx.moveTo(c.x + ox, c.y + oy); ctx.lineTo(top.x, top.y); ctx.stroke(); }
        box(x + .05, y + .05, .4, .45, 12, 32, '#1c1c28');
        const rec = Math.floor(T.t * 2) % 2; const p = iso(x + .1, y + .5, 40); ctx.beginPath(); ctx.arc(p.x, p.y, 2, 0, 7); ctx.fillStyle = rec ? '#ff3b3b' : '#5a1a1a'; ctx.fill();
        break;
      }
      case 'ringlight': {
        const c = iso(x + .2, y + .2, 0), top = iso(x + .2, y + .2, 46);
        ctx.strokeStyle = '#2a2a38'; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(c.x, c.y); ctx.lineTo(top.x, top.y); ctx.stroke();
        ctx.beginPath(); ctx.ellipse(top.x, top.y - 8, 9, 12, -0.5, 0, 7); ctx.strokeStyle = '#fff8d8'; ctx.lineWidth = 3;
        ctx.shadowColor = '#fff3b0'; ctx.shadowBlur = 12; ctx.stroke(); ctx.shadowBlur = 0;
        break;
      }
      case 'plant':
        box(x + .15, y + .15, .4, .4, h, 0, '#c2683a');
        for (const [ox, oy, oz, r] of [[.35, .35, 26, 9], [.2, .4, 20, 7], [.5, .3, 21, 7], [.35, .35, 34, 6]]) {
          const p = iso(x + ox, y + oy, oz); ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, 7); ctx.fillStyle = oz > 30 ? '#6fe08a' : '#3fb860'; ctx.fill();
        }
        break;
      case 'bar':
        box(x, y, w, d, h, 0, '#6b3f8f', { top: '#e8d6c4' });
        box(x + .15, y + .4, .5, .5, 18, h, '#30303e'); // coffee machine
        { const s = iso(x + .4, y + .65, h + 22 + Math.sin(T.t * 3) * 3); ctx.fillStyle = 'rgba(255,255,255,.35)'; ctx.beginPath(); ctx.arc(s.x, s.y, 3, 0, 7); ctx.fill(); }
        for (let i = 0; i < 3; i++) box(x + .3, y + 1.3 + i * .5, .25, .25, 6, h, ['#fff', '#ffd23d', '#ff6fae'][i]);
        break;
      case 'sofa': {
        const c = f.col;
        box(x, y, w, d, h, 0, c);
        if (f.flip) box(x, y + d - .25, w, .25, 14, h, shade(c, -.1)); else box(x, y, w, .25, 14, h, shade(c, -.1));
        box(x - .02, y, .25, d, 8, h, shade(c, -.15)); box(x + w - .23, y, .25, d, 8, h, shade(c, -.15));
        break;
      }
      case 'coffeeTable':
        box(x, y, w, d, h, 0, '#7a4a2a');
        box(x + .3, y + .2, .25, .25, 5, h, '#ffffff'); box(x + .7, y + .35, .35, .3, 2, h, '#e84a5f');
        break;
      case 'beanbag': {
        ellipse(x + w / 2, y + d / 2, 0, 20, 10, 'rgba(0,0,0,.25)');
        ellipse(x + w / 2, y + d / 2, 6, 19, 11, shade(f.col, -.2)); ellipse(x + w / 2 - .05, y + d / 2 - .05, 10, 14, 8, f.col);
        break;
      }
      case 'frontDesk':
        box(x, y, w, d, h, 0, '#3b3060', { top: '#ece6ff' });
        box(x + .3, y + .1, .6, .1, 16, h, '#22223a'); quadY(y + .2 + .001, x + .35, x + .85, h + 2, h + 14, '#3ddc84');
        break;
      case 'billiards':
        box(x + .1, y + .1, .2, .2, h - 6, 0, '#4b2c16'); box(x + w - .3, y + d - .3, .2, .2, h - 6, 0, '#4b2c16');
        box(x, y, w, d, 6, h - 6, '#7a3f1d', { top: '#1f9e58' });
        poly([iso(x + .15, y + .15, h), iso(x + w - .15, y + .15, h), iso(x + w - .15, y + d - .15, h), iso(x + .15, y + d - .15, h)], '#27b866');
        [['#fff', .6, .7], ['#ffd23d', 1.5, .5], ['#e84a5f', 1.7, .8], ['#3d6bff', 1.9, .6], ['#111', 2.0, .95]].forEach(([c, bx, by]) => {
          const p = iso(x + bx, y + by, h + 2); ctx.beginPath(); ctx.arc(p.x, p.y, 2.6, 0, 7); ctx.fillStyle = c; ctx.fill();
        });
        break;
      case 'arcade': {
        box(x, y, w, d, h, 0, f.col);
        const flick = 0.75 + 0.25 * Math.sin(T.t * 9 + x);
        ctx.globalAlpha = flick; quadY(y + d + .001, x + .12, x + w - .12, h - 26, h - 8, f.screen); ctx.globalAlpha = 1;
        box(x + .05, y + d - .05, w - .1, .25, 4, h - 34, shade(f.col, -.25));
        const btn = iso(x + w / 2, y + d + .1, h - 29); ctx.beginPath(); ctx.arc(btn.x, btn.y, 2.5, 0, 7); ctx.fillStyle = '#ffd23d'; ctx.fill();
        break;
      }
      case 'vending':
        box(x, y, w, d, h, 0, '#e84a5f');
        quadX(x + w + .001, y + .1, y + d - .25, 14, h - 8, '#bfe9ff');
        for (let r = 0; r < 3; r++) for (let c = 0; c < 2; c++) quadX(x + w + .002, y + .15 + c * .22, y + .3 + c * .22, 20 + r * 10, 26 + r * 10, ['#ffd23d', '#3ddc84', '#ff8a3d'][(r + c) % 3]);
        break;
      case 'railH': case 'railV': {
        const glass = 'rgba(80,220,255,.22)', bar = '#5fe3ff';
        if (f.type === 'railH') { box(x, y - .04, 1, .08, 18, 0, '#000', { top: bar, left: glass, right: glass }); quadY(y + .04, x, x + 1, 16, 18, bar); }
        else { box(x - .04, y, .08, 1, 18, 0, '#000', { top: bar, left: glass, right: glass }); quadX(x + .04, y, y + 1, 16, 18, bar); }
        break;
      }
    }
  }

  // ───────────────────────── Drawing: room shell ─────────────────────────
  function drawFloor() {
    for (let x = 0; x < W; x++) for (let y = 0; y < H; y++) {
      poly([iso(x, y), iso(x + 1, y), iso(x + 1, y + 1), iso(x, y + 1)], floorColor(x, y));
    }
    // slab edge
    poly([iso(0, H), iso(W, H), iso(W, H, -10), iso(0, H, -10)], '#3a1b4f');
    poly([iso(W, 0), iso(W, H), iso(W, H, -10), iso(W, 0, -10)], '#2a1240');
  }
  function signY(text, x, z, color) {
    const p = iso(x, 0, z);
    ctx.save(); ctx.translate(p.x, p.y); ctx.transform(1, 0.5, 0, 1, 0, 0);
    ctx.font = 'bold 13px ui-sans-serif, system-ui, sans-serif'; ctx.fillStyle = color; ctx.shadowColor = color; ctx.shadowBlur = 10;
    ctx.fillText(text, 0, 0); ctx.restore();
  }
  function signX(text, y, z, color) {
    const p = iso(0, y, z);
    ctx.save(); ctx.translate(p.x, p.y); ctx.transform(1, -0.5, 0, 1, 0, 0);
    ctx.font = 'bold 14px ui-sans-serif, system-ui, sans-serif'; ctx.fillStyle = color; ctx.shadowColor = color; ctx.shadowBlur = 12;
    ctx.fillText(text, 0, 0); ctx.restore();
  }
  function drawWalls() {
    const WH = 96;
    box(-0.3, -0.3, W + 0.3, 0.3, WH, 0, '#2a2f6b', { left: '#353b86', top: '#4a51a8' });
    box(-0.3, 0, 0.3, H, WH, 0, '#2a2f6b', { right: '#2c3176', top: '#4a51a8' });
    // windows on back-right wall (night city)
    for (const wx of [4.6, 8.0, 13.9, 17.4]) {
      quadY(0.001, wx, wx + 1.8, 34, 84, '#151a3d');
      quadY(0.002, wx + .1, wx + 1.7, 38, 80, '#1e2a6e');
      for (let i = 0; i < 6; i++) quadY(0.003, wx + .2 + i * .25, wx + .32 + i * .25, 38, 46 + ((i * 13) % 5) * 5, '#3a4cb0');
      for (let i = 0; i < 4; i++) { const p = iso(wx + .3 + i * .4, 0.003, 60 + (i % 2) * 10); ctx.fillStyle = (Math.floor(T.t + i) % 3) ? '#ffe9a0' : '#ffb84d'; ctx.fillRect(p.x, p.y, 2, 2); }
      quadY(0.004, wx + .88, wx + .92, 38, 80, '#151a3d');
    }
    // windows on left wall
    for (const wy of [1.5, 4.0]) { quadX(0.001, wy, wy + 1.6, 34, 84, '#151a3d'); quadX(0.002, wy + .1, wy + 1.5, 38, 80, '#1e2a6e'); }
    // content schedule board
    quadY(0.001, 14.1, 17.2, 26, 32, '#22223a');
    quadY(0.001, 14.15, 17.15, 26, 31, '#22223a');
    // compliance scales icon / content board text
    signY('⚖ COMPLIANCE', 4.9, 92, '#7fd4ff');
    signY('🎬 CONTENT STUDIO', 19.8, 92, '#ff9bd0');
    signX('LOUNGE', 14.5, 70, '#ff6fae');
    // posting calendar board (content wall, between windows)
    quadY(0.001, 10.4, 13.6, 34, 82, '#f1ecff');
    for (let r = 0; r < 4; r++) for (let c = 0; c < 5; c++) {
      const cx = 10.55 + c * .6, z = 74 - r * 11;
      const filled = (r * 5 + c + Math.floor(stats.done / 2)) % 4 === 0;
      quadY(0.002, cx, cx + .5, z - 8, z, filled ? ['#ff6fae', '#ffd23d', '#2ee6c9', '#a77bff'][(r + c) % 4] : '#d9d2f2');
    }
  }

  // ───────────────────────── Drawing: the bots (cartoon kids) ─────────────────────────
  // Each bot is a little chibi character drawn with canvas paths. Local coords: feet at (0,0),
  // +x = the way the character is facing (flipped with scale(-1,1)).
  const LOOKS = {
    doc:   { skin: '#f6d3b3', hair: '#e8c55a', style: 'long',      acc: 'headband', accCol: '#b04fd6', shirt: 'plain' },
    reg:   { skin: '#e9b98f', hair: '#3b2a20', style: 'spiky',     acc: 'glasses',  shirt: 'collar' },
    risk:  { skin: '#a8714c', hair: '#2e1d16', style: 'curly',     acc: 'headband', accCol: '#ffb02e', shirt: 'plain' },
    vid:   { skin: '#f3cfae', hair: '#5fd6d0', style: 'spacebuns', acc: 'clips',    accCol: '#ffe14d', shirt: 'stripes' },
    cap:   { skin: '#f4d0ae', hair: '#ecc35c', style: 'curly',     acc: null,       shirt: 'stripes' },
    sched: { skin: '#d9a57d', hair: '#4a2c1f', style: 'bun',       acc: 'ribbon',   accCol: '#e8336e', shirt: 'dots' },
    post:  { skin: '#f1c7a4', hair: '#e2683a', style: 'braid',     acc: 'ribbon',   accCol: '#3d8bff', shirt: 'overalls' },
    mgr:   { skin: '#8d5a3b', hair: '#1f1410', style: 'swoosh',    acc: 'tie',      accCol: '#e84a5f', shirt: 'collar' },
  };
  let hoverBot = null, selected = null, filter = 'all';
  const HEAD_Y = -35, HR = 13;

  function rr(x, y, w, h, r) {
    ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
  }
  function circ(x, y, r, fill) { ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fillStyle = fill; ctx.fill(); }

  function hairBack(L) {
    const h = L.hair, y = HEAD_Y;
    if (L.style === 'long') { ctx.beginPath(); ctx.ellipse(-3, y + 6, 16, 20, 0, 0, Math.PI * 2); ctx.fillStyle = h; ctx.fill();
      for (let i = 0; i < 5; i++) circ(-15 + i * 2, y + 2 + i * 5, 5, h); }
    if (L.style === 'curly') for (const [cx, cy, r] of [[-12, -8, 7], [-14, 1, 7], [-10, 9, 6], [-4, -14, 7], [5, -14, 6], [11, -9, 5], [-15, -2, 6]]) circ(cx, y + cy, r, h);
    if (L.style === 'braid') { for (let i = 0; i < 5; i++) circ(-11 + i * .3, y + 6 + i * 5.5, 3.6 - i * .25, h);
      if (L.acc === 'ribbon') { ctx.fillStyle = L.accCol; ctx.fillRect(-14, y + 28, 6, 3); } }
  }
  function hairFront(L, t) {
    const h = L.hair, y = HEAD_Y;
    ctx.fillStyle = h;
    // cap over the top/back of the head with a fringe toward the face
    ctx.beginPath(); ctx.arc(0, y, HR + 1.5, Math.PI * 0.82, Math.PI * 2.02);
    ctx.quadraticCurveTo(9, y - 9, 3, y - 6); ctx.quadraticCurveTo(-1, y - 10, -5, y - 4); ctx.quadraticCurveTo(-9, y - 2, -12, y + 4);
    ctx.closePath(); ctx.fill();
    if (L.style === 'spiky') { ctx.beginPath(); ctx.moveTo(-10, y - 9); ctx.lineTo(-6, y - 20); ctx.lineTo(-2, y - 12); ctx.lineTo(3, y - 21); ctx.lineTo(6, y - 12); ctx.lineTo(12, y - 17); ctx.lineTo(11, y - 7); ctx.closePath(); ctx.fill(); }
    if (L.style === 'swoosh') { ctx.beginPath(); ctx.moveTo(-8, y - 11); ctx.quadraticCurveTo(6, y - 24, 17, y - 12); ctx.quadraticCurveTo(8, y - 12, 4, y - 7); ctx.closePath(); ctx.fill(); }
    if (L.style === 'curly') for (const [cx, cy, r] of [[-6, -13, 5], [1, -15, 5], [7, -12, 4.5], [-11, -6, 4.5]]) circ(cx, y + cy, r, h);
    if (L.style === 'bun') circ(-6, y - 16, 7, h);
    if (L.style === 'spacebuns') { circ(-10, y - 12, 6.5, h); circ(5, y - 16, 6.5, h); }
    // accessories
    if (L.acc === 'headband') { ctx.beginPath(); ctx.arc(0, y, HR + 1.6, Math.PI * 1.15, Math.PI * 1.75); ctx.strokeStyle = L.accCol; ctx.lineWidth = 3; ctx.stroke(); }
    if (L.acc === 'ribbon' && L.style === 'bun') { ctx.fillStyle = L.accCol; ctx.beginPath(); ctx.moveTo(-6, y - 10); ctx.lineTo(-12, y - 14); ctx.lineTo(-11, y - 6); ctx.closePath(); ctx.fill(); ctx.beginPath(); ctx.moveTo(-6, y - 10); ctx.lineTo(0, y - 13); ctx.lineTo(-1, y - 6); ctx.closePath(); ctx.fill(); }
    if (L.acc === 'clips') { ctx.fillStyle = L.accCol; rr(-12, y - 15, 5, 3, 1.5); ctx.fill(); rr(3, y - 19, 5, 3, 1.5); ctx.fill(); }
  }
  function face(L, b, t) {
    const y = HEAD_Y;
    const blinking = ((t + b.blink) % 4) < 0.13;
    for (const ex of [1.5, 9]) {
      if (blinking) { ctx.strokeStyle = '#2a1a14'; ctx.lineWidth = 1.6; ctx.beginPath(); ctx.moveTo(ex - 2.5, y + 1); ctx.lineTo(ex + 2.5, y + 1); ctx.stroke(); continue; }
      ctx.beginPath(); ctx.ellipse(ex, y + 0.5, 2.7, 3.6, 0, 0, Math.PI * 2); ctx.fillStyle = '#2a1a14'; ctx.fill();
      circ(ex + 1, y - 1, 1.15, '#fff'); circ(ex - 0.8, y + 1.8, 0.55, '#fff');
    }
    ctx.globalAlpha *= 0.55; circ(-1.5, y + 6, 2.6, '#ff7d9a'); circ(11.5, y + 6, 2.2, '#ff7d9a'); ctx.globalAlpha = ctx.globalAlpha / 0.55;
    circ(12.6, y + 3.5, 1.1, shade(L.skin, -0.18)); // nose
    const talking = b.bubble && b.bubble.until > t && Math.floor(t * 8) % 2;
    ctx.strokeStyle = '#7a2e2e'; ctx.fillStyle = '#7a2e2e'; ctx.lineWidth = 1.4;
    if (talking) { ctx.beginPath(); ctx.ellipse(6.5, y + 8, 2.2, 2, 0, 0, Math.PI * 2); ctx.fill(); }
    else { ctx.beginPath(); ctx.arc(6.5, y + 6.2, 2.8, 0.2 * Math.PI, 0.8 * Math.PI); ctx.stroke(); }
    if (L.acc === 'glasses') { ctx.strokeStyle = '#22223a'; ctx.lineWidth = 1.3; ctx.beginPath(); ctx.arc(1.5, y + 0.5, 4.3, 0, 7); ctx.moveTo(13.3, y + 0.5); ctx.arc(9, y + 0.5, 4.3, 0, 7); ctx.moveTo(5.8, y); ctx.lineTo(4.7, y); ctx.stroke(); }
  }
  function body(L, b, t) {
    const walking = b.path.length > 0, sw = walking ? Math.sin(t * 14 + b.phase) : 0;
    const seated = b.state === 'working';
    // legs + shoes
    ctx.fillStyle = L.shirt === 'overalls' ? '#2f6fd6' : '#3b3d63';
    if (seated) { rr(-5, -9, 13, 5, 2.5); ctx.fill(); circ(9, -6.5, 2.8, '#2a2333'); }
    else for (const [lx, ph] of [[-4.5, sw], [1.5, -sw]]) { rr(lx, -9 + Math.max(0, ph) * -2, 4, 8, 2); ctx.fill(); circ(lx + 2.5 + ph * 1.5, -1 + Math.max(0, ph) * -2, 2.8, '#2a2333'); ctx.fillStyle = L.shirt === 'overalls' ? '#2f6fd6' : '#3b3d63'; }
    // back arm
    ctx.fillStyle = shade(b.color, -0.18); rr(-11 - sw * 2, -21, 5, 11, 2.5); ctx.fill();
    // torso
    ctx.fillStyle = b.color; rr(-9, -23, 18, 15, 6); ctx.fill();
    if (L.shirt === 'stripes') { ctx.fillStyle = 'rgba(255,255,255,.55)'; for (let i = 0; i < 3; i++) ctx.fillRect(-8.5, -19 + i * 4, 17, 1.8); }
    if (L.shirt === 'dots') for (const [dx, dy] of [[-5, -18], [1, -16], [5, -20], [-3, -12], [4, -12]]) circ(dx, dy, 1.1, 'rgba(255,255,255,.75)');
    if (L.shirt === 'overalls') { ctx.fillStyle = '#2f6fd6'; rr(-6, -18, 12, 10, 3); ctx.fill(); ctx.fillRect(-6, -23, 2.4, 6); ctx.fillRect(3.6, -23, 2.4, 6); circ(-4.8, -18, 1, '#ffd23d'); circ(4.8, -18, 1, '#ffd23d'); }
    if (L.shirt === 'collar') { ctx.fillStyle = '#fff'; ctx.beginPath(); ctx.moveTo(-4, -23); ctx.lineTo(2, -19); ctx.lineTo(8, -23); ctx.closePath(); ctx.fill(); }
    if (L.acc === 'tie') { ctx.fillStyle = L.accCol; ctx.beginPath(); ctx.moveTo(1, -21); ctx.lineTo(4, -21); ctx.lineTo(4.5, -12); ctx.lineTo(2.5, -10); ctx.lineTo(0.5, -12); ctx.closePath(); ctx.fill(); }
    // front arm (typing when working)
    const typing = seated ? Math.sin(t * 22 + b.phase) * 1.5 : 0;
    ctx.fillStyle = shade(b.color, -0.05);
    if (seated) { rr(4, -18 + typing, 11, 5, 2.5); ctx.fill(); circ(15, -15.5 + typing, 2.5, L.skin); }
    else { rr(5 + sw * 2, -21, 5, 11, 2.5); ctx.fill(); circ(7.5 + sw * 2, -9.5, 2.5, L.skin); }
  }

  function drawBot(b, t) {
    const L = LOOKS[b.id];
    const g = iso(b.x, b.y, 0);
    const dim = filter !== 'all' && b.team !== filter && b.team !== 'manager';
    ctx.globalAlpha = dim ? 0.3 : 1;
    // shadow (+ glow ring when hovered/selected)
    const sh = Math.max(0.6, 1 - b.z / 40);
    ctx.beginPath(); ctx.ellipse(g.x, g.y, 13 * sh, 6 * sh, 0, 0, 7); ctx.fillStyle = 'rgba(0,0,0,.3)'; ctx.fill();
    if (b === selected || b === hoverBot) {
      ctx.beginPath(); ctx.ellipse(g.x, g.y, 17, 8, 0, 0, 7); ctx.strokeStyle = b.color; ctx.lineWidth = 2.5;
      ctx.shadowColor = b.color; ctx.shadowBlur = 12; ctx.stroke(); ctx.shadowBlur = 0;
    }
    const breathe = b.path.length ? 0 : Math.sin(t * 2.4 + b.phase) * 0.6;
    ctx.save();
    ctx.translate(g.x, g.y - b.z);
    ctx.scale(b.face || 1, 1);
    ctx.scale(1.12, 1.12);
    body(L, b, t);
    ctx.translate(0, breathe);
    hairBack(L);
    circ(-11, HEAD_Y + 2, 3.4, shade(L.skin, -0.06)); // ear
    circ(0, HEAD_Y, HR, L.skin);
    face(L, b, t);
    hairFront(L, t);
    ctx.restore();
    // working sparkle
    if (b.state === 'working' && Math.floor(t * 3 + b.phase) % 3 === 0) {
      const p = iso(b.x + .3, b.y - .3, b.z + 52); ctx.fillStyle = '#fff'; ctx.font = '10px sans-serif'; ctx.fillText('✦', p.x, p.y);
    }
    ctx.globalAlpha = 1;
  }

  function drawOverlay(b, t) {
    const top = iso(b.x, b.y, b.z + 64);
    if (b.bubble && b.bubble.until > t) drawBubble(top.x, top.y - 10, b.bubble.text);
    else b.bubble = null;
    if (b === hoverBot || b === selected) {
      ctx.font = 'bold 11px ui-sans-serif, system-ui, sans-serif';
      const tw = ctx.measureText(b.name).width + 12, p = iso(b.x, b.y, 0);
      roundRect(p.x - tw / 2, p.y + 10, tw, 17, 8, 'rgba(15,12,30,.85)');
      ctx.fillStyle = b.color; ctx.textAlign = 'center'; ctx.fillText(b.name, p.x, p.y + 22); ctx.textAlign = 'left';
    }
    if (b.task && b.state === 'working') {
      const p = iso(b.x, b.y, b.z + 60);
      roundRect(p.x - 16, p.y - 4, 32, 5, 2.5, 'rgba(15,12,30,.8)');
      roundRect(p.x - 15, p.y - 3, 30 * Math.min(1, b.task.progress), 3, 1.5, '#3ddc84');
    }
  }
  function roundRect(x, y, w, h, r, fill) {
    ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath(); ctx.fillStyle = fill; ctx.fill();
  }
  function drawBubble(x, y, text) {
    ctx.font = '600 11px ui-sans-serif, system-ui, sans-serif';
    const w = ctx.measureText(text).width + 14, h = 20;
    ctx.save(); ctx.shadowColor = 'rgba(0,0,0,.35)'; ctx.shadowBlur = 6; ctx.shadowOffsetY = 2;
    roundRect(x - w / 2, y - h, w, h, 9, '#ffffff'); ctx.restore();
    ctx.beginPath(); ctx.moveTo(x - 4, y - 1); ctx.lineTo(x, y + 5); ctx.lineTo(x + 4, y - 1); ctx.fillStyle = '#fff'; ctx.fill();
    ctx.fillStyle = '#2a2350'; ctx.textAlign = 'center'; ctx.fillText(text, x, y - 6); ctx.textAlign = 'left';
  }

  // ───────────────────────── Frame loop ─────────────────────────
  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    const r = canvas.getBoundingClientRect();
    canvas.width = Math.round(r.width * dpr); canvas.height = Math.round(r.height * dpr);
  }
  function fit() {
    const r = canvas.getBoundingClientRect();
    const worldW = (W + H) * TW / 2, worldH = (W + H) * TH / 2 + 110;
    cam.zoom = Math.min(r.width / worldW, r.height / worldH) * 0.96;
    cam.x = r.width / 2 - ((W - H) * TW / 4) * cam.zoom;
    cam.y = (r.height - worldH * cam.zoom) / 2 + 100 * cam.zoom;
  }
  const toWorld = (sx, sy) => ({ x: (sx - cam.x) / cam.zoom, y: (sy - cam.y) / cam.zoom });

  let last = now();
  function frame() {
    const t = now(), dt = Math.min(0.05, t - last); last = t; T.t = t;
    for (const b of bots) updateBot(b, dt, t);
    demoTick(dt);

    ctx.setTransform(1, 0, 0, 1, 0, 0);
    const grd = ctx.createRadialGradient(canvas.width / 2, canvas.height / 2, 50, canvas.width / 2, canvas.height / 2, canvas.width * 0.7);
    grd.addColorStop(0, '#1d1840'); grd.addColorStop(1, '#0b0918');
    ctx.fillStyle = grd; ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.setTransform(cam.zoom * dpr, 0, 0, cam.zoom * dpr, cam.x * dpr, cam.y * dpr);

    drawFloor();
    for (const f of F) if (f.type === 'rug') drawFurniture(f);
    drawWalls();
    const items = [];
    for (const f of F) if (f.type !== 'rug') items.push({ depth: f.x + f.w / 2 + f.y + f.d / 2, draw: () => drawFurniture(f) });
    for (const r of railings) items.push({ depth: r.type === 'railH' ? r.x + .5 + r.y : r.x + r.y + .5, draw: () => drawFurniture(Object.assign({ w: 1, d: 1 }, r)) });
    for (const b of bots) items.push({ depth: b.x + b.y + 0.01, draw: () => drawBot(b, t) });
    items.sort((a, b) => a.depth - b.depth).forEach((i) => i.draw());
    for (const b of bots) drawOverlay(b, t);

    updateStats();
    if (selected) renderPanel();
    requestAnimationFrame(frame);
  }

  // ───────────────────────── UI: feed, stats, panel ─────────────────────────
  // Head-and-shoulders portrait of each character for the feed and panel.
  const portraits = {};
  function makePortraits() {
    const main = ctx;
    for (const b of bots) {
      const c = document.createElement('canvas'); c.width = c.height = 96;
      ctx = c.getContext('2d');
      ctx.fillStyle = shade(b.color, 0.55); ctx.beginPath(); ctx.arc(48, 48, 48, 0, Math.PI * 2); ctx.fill();
      ctx.save(); ctx.beginPath(); ctx.arc(48, 48, 48, 0, Math.PI * 2); ctx.clip();
      ctx.translate(46, 100); ctx.scale(1.75, 1.75);
      const fake = { ...b, path: [], state: 'idle', bubble: null, blink: 1 };
      body(LOOKS[b.id], fake, 0); hairBack(LOOKS[b.id]);
      circ(-11, HEAD_Y + 2, 3.4, shade(LOOKS[b.id].skin, -0.06)); circ(0, HEAD_Y, HR, LOOKS[b.id].skin);
      face(LOOKS[b.id], fake, 0); hairFront(LOOKS[b.id], 0);
      ctx.restore();
      portraits[b.id] = c.toDataURL();
    }
    ctx = main;
  }
  const avatar = (b, cls = 'avatar') => `<img class="${cls}" src="${portraits[b.id]}" alt="">`;

  const feedEl = document.getElementById('feed');
  function feed(b, text, url) {
    const li = document.createElement('li');
    const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    li.innerHTML = `${avatar(b)}<div><b></b><time>${time}</time><br><span class="txt"></span></div>`;
    li.querySelector('b').textContent = b.name; li.querySelector('.txt').textContent = text;
    if (url) { const a = document.createElement('a'); a.href = url; a.target = '_blank'; a.textContent = ' 📄 Open report'; li.querySelector('.txt').after(a); }
    feedEl.prepend(li);
    while (feedEl.children.length > 80) feedEl.lastChild.remove();
  }
  let statTick = 0;
  function updateStats() {
    if (++statTick % 15) return;
    document.getElementById('statWorking').textContent = bots.filter((b) => b.state === 'working').length;
    document.getElementById('statQueue').textContent = bots.reduce((n, b) => n + b.queue.length, 0);
    document.getElementById('statDone').textContent = stats.done;
  }

  const panel = document.getElementById('panel');
  let panelSig = '';
  function renderPanel() {
    const b = selected;
    const pct = b.task ? Math.round(b.task.progress * 100) : 0;
    const status = b.state === 'working' ? 'working' : b.state === 'break' ? 'break' : 'idle';
    const sig = [b.id, status, pct, b.queue.length, b.log.length, b.task && b.task.text].join('|');
    if (sig === panelSig) return; panelSig = sig;
    const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    const label = { working: '● Working', idle: b.path.length ? '● On the move' : '● Chilling', break: '● On break' }[status];
    panel.innerHTML = `
      <div class="head">${avatar(b)}
        <div><h2>${esc(b.name)}</h2><div class="role">${esc(b.role)}</div></div>
        <button class="close" data-act="close">×</button></div>
      <span class="pill ${status}">${label}</span>
      <h4>Current task</h4>
      ${b.task ? `<div class="task">${esc(b.task.text)}<div class="bar"><i style="width:${pct}%"></i></div></div>` : '<div class="muted">Walang ginagawa — nasa lounge 🛋️</div>'}
      <h4>Queue (${b.queue.length})</h4>
      ${b.queue.length ? `<ul>${b.queue.slice(0, 5).map((q) => `<li>⏳ ${esc(q.text)}</li>`).join('')}</ul>` : '<div class="muted">Empty</div>'}
      <h4>Recent (${b.done} done)</h4>
      ${b.log.length ? `<ul>${b.log.map((l) => `<li>${esc(l.text)}${l.url ? ` <a href="${esc(l.url)}" target="_blank">📄 report</a>` : ''}</li>`).join('')}</ul>` : '<div class="muted">Nothing yet</div>'}
      ${b.id === 'mgr' ? '' : `<div class="actions">
        <button class="primary" data-act="task">＋ Give task</button>
        <button data-act="file">📎 Upload</button>
        <button data-act="break">${b.state === 'break' ? '▶ Back to work' : '☕ Break'}</button></div>`}`;
  }
  panel.addEventListener('click', (e) => {
    const act = e.target.dataset.act; if (!act || !selected) return;
    const b = selected;
    if (act === 'close') return select(null);
    if (act === 'task') { const txt = prompt(`New task for ${b.name}:`); if (txt) assign(b.id, txt, { secs: 8 }); }
    if (act === 'file') { pickerTarget = b; picker.click(); }
    if (act === 'break') {
      if (b.state === 'break') { b.state = 'idle'; feed(b, 'back to work 💪'); }
      else { b.state = 'break'; b.breakUntil = now() + 25; b.idleTimer = 0; feed(b, 'on a short break ☕'); say(b, 'Yehey break!'); }
    }
    panelSig = '';
  });
  function select(b) {
    selected = b; panelSig = '';
    panel.classList.toggle('hidden', !b);
    if (b) { renderPanel(); if (!b.bubble) say(b, rand(['Hi! 👋', 'Yes boss?', 'Ano po?']), 1.6); }
  }

  document.getElementById('tabs').addEventListener('click', (e) => {
    const f = e.target.dataset.filter; if (!f) return;
    filter = f; document.querySelectorAll('#tabs button').forEach((x) => x.classList.toggle('active', x.dataset.filter === f));
  });

  // ───────────────────────── Input: pan, zoom, click ─────────────────────────
  function botAt(sx, sy) {
    const w = toWorld(sx, sy);
    let best = null, bd = 26;
    for (const b of bots) { const p = iso(b.x, b.y, b.z + 24), dd = Math.hypot(p.x - w.x, p.y - w.y); if (dd < bd) { bd = dd; best = b; } }
    return best;
  }
  let drag = null;
  canvas.addEventListener('pointerdown', (e) => { drag = { x: e.clientX, y: e.clientY, cx: cam.x, cy: cam.y, moved: false }; canvas.setPointerCapture(e.pointerId); });
  canvas.addEventListener('pointermove', (e) => {
    const r = canvas.getBoundingClientRect();
    if (drag) {
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (Math.hypot(dx, dy) > 4) { drag.moved = true; canvas.classList.add('dragging'); }
      if (drag.moved) { cam.x = drag.cx + dx; cam.y = drag.cy + dy; }
    } else {
      hoverBot = botAt(e.clientX - r.left, e.clientY - r.top);
      canvas.classList.toggle('hovering', !!hoverBot);
    }
  });
  canvas.addEventListener('pointerup', (e) => {
    const r = canvas.getBoundingClientRect();
    if (drag && !drag.moved) select(botAt(e.clientX - r.left, e.clientY - r.top));
    drag = null; canvas.classList.remove('dragging');
  });
  function zoomAt(f, sx, sy) {
    const nz = Math.max(0.35, Math.min(3, cam.zoom * f)); f = nz / cam.zoom;
    cam.x = sx - (sx - cam.x) * f; cam.y = sy - (sy - cam.y) * f; cam.zoom = nz;
  }
  canvas.addEventListener('wheel', (e) => { e.preventDefault(); const r = canvas.getBoundingClientRect(); zoomAt(e.deltaY < 0 ? 1.12 : 1 / 1.12, e.clientX - r.left, e.clientY - r.top); }, { passive: false });
  const mid = () => { const r = canvas.getBoundingClientRect(); return [r.width / 2, r.height / 2]; };
  document.getElementById('zoomIn').onclick = () => zoomAt(1.2, ...mid());
  document.getElementById('zoomOut').onclick = () => zoomAt(1 / 1.2, ...mid());
  document.getElementById('zoomFit').onclick = fit;
  window.addEventListener('resize', () => { resize(); fit(); });

  // ───────────────────────── Drag & drop files ─────────────────────────
  const dropzone = document.getElementById('dropzone');
  const stage = document.getElementById('stage');
  const DOC = /\.(pdf|docx?|html?|txt|md|rtf)$/i, MEDIA = /\.(mp4|mov|m4v|webm|avi|mkv|png|jpe?g|gif|heic)$/i;
  function routeFile(file, target) {
    const name = file.name;
    // live mode: the server runs both teams for real; drop anywhere (or on the right team)
    const anyTarget = !target || target.id === 'mgr';
    if (live && DOC.test(name) && (anyTarget || target.team === 'compliance')) return uploadReal(file);
    if (live && MEDIA.test(name) && (anyTarget || target.team === 'content')) return uploadReal(file);
    if (target && target.id !== 'mgr') {
      const step = [...PIPELINES.compliance, ...PIPELINES.content].find((s) => s.bot === target.id);
      return assign(target.id, `${step ? step.verb : 'Handle'}: ${name}`, { secs: 8, file: name });
    }
    if (DOC.test(name)) return startPipeline('compliance', name);
    if (MEDIA.test(name)) return startPipeline('content', name);
    feed(botById.mgr, `hindi ko alam saan ilalagay ang ${name} — PDF/DOC or video/image lang po`);
  }
  let dragDepth = 0;
  stage.addEventListener('dragenter', (e) => { e.preventDefault(); dragDepth++; dropzone.classList.add('show'); });
  stage.addEventListener('dragleave', () => { if (--dragDepth <= 0) { dragDepth = 0; dropzone.classList.remove('show'); } });
  stage.addEventListener('dragover', (e) => {
    e.preventDefault(); const r = canvas.getBoundingClientRect(); hoverBot = botAt(e.clientX - r.left, e.clientY - r.top);
  });
  stage.addEventListener('drop', (e) => {
    e.preventDefault(); dragDepth = 0; dropzone.classList.remove('show');
    const r = canvas.getBoundingClientRect(); const target = botAt(e.clientX - r.left, e.clientY - r.top);
    for (const f of e.dataTransfer.files) routeFile(f, target);
  });
  const picker = document.getElementById('filePicker'); let pickerTarget = null;
  picker.addEventListener('change', () => { for (const f of picker.files) routeFile(f, pickerTarget); picker.value = ''; pickerTarget = null; });

  // ───────────────────────── Demo mode ─────────────────────────
  const SAMPLE = {
    compliance: ['Data_Privacy_Act_RA10173.pdf', 'Vendor_Contract_v3.docx', 'BSP_Circular_1140.pdf', 'Employee_Handbook.pdf', 'SEC_MC_2024-07.html', 'NDA_ClientX.docx'],
    content: ['vlog_day3.mp4', 'product_teaser.mov', 'behind_scenes.mp4', 'promo_poster.png', 'tutorial_part2.mp4', 'reel_hook_test.mp4'],
  };
  let demo = true, demoTimer = 2;
  document.getElementById('demoToggle').addEventListener('change', (e) => { demo = e.target.checked; });
  function demoTick(dt) {
    if (!demo) return;
    demoTimer -= dt;
    if (demoTimer > 0) return;
    demoTimer = 9 + Math.random() * 12;
    const busy = bots.reduce((n, b) => n + b.queue.length + (b.task ? 1 : 0), 0);
    if (busy > 6) return;
    const team = Math.random() < 0.5 ? 'content' : 'compliance';
    startPipeline(team, rand(SAMPLE[team]));
  }

  // ───────────────────────── Live backend (server.py) ─────────────────────────
  // When the page is served by server.py, compliance bots do real work: uploads go to
  // /api/upload and progress comes back from /api/bots/events.
  let live = false, cursor = 0;
  async function connectLive() {
    try {
      const h = await fetch('/api/health'); if (!h.ok) return;
      const info = await h.json();
      cursor = (await (await fetch('/api/bots/events?after=0')).json()).last; // skip old history
      live = true;
      document.getElementById('liveBadge').classList.remove('hidden');
      demo = false; document.getElementById('demoToggle').checked = false;
      feed(botById.mgr, `LIVE na tayo! PDF/DOCX → compliance ⚖️, video/image → content 🎬` +
        (info.claude ? ' · Claude is on ✨' : ' · (no Claude key: rule-based mode)') +
        (info.ffmpeg ? '' : ' · ffmpeg missing: videos kept as-is'));
      setInterval(pollLive, 1200);
    } catch (err) { /* opened as a plain file: stay in demo mode */ }
  }
  let polling = false;
  async function pollLive() {
    if (polling) return; polling = true;
    try {
      const r = await (await fetch(`/api/bots/events?after=${cursor}`)).json();
      r.events.forEach(applyEvent); cursor = r.last;
    } catch (err) { /* server restarting */ }
    polling = false;
  }
  async function uploadReal(file) {
    const fd = new FormData(); fd.append('files', file);
    feed(botById.mgr, `uploading ${file.name}… (${(file.size / 1048576).toFixed(1)} MB)`);
    try {
      const r = await (await fetch('/api/upload', { method: 'POST', body: fd })).json();
      r.skipped.forEach((n) => feed(botById.mgr, `hindi tinanggap: ${n} (type o size)`));
    } catch (err) { feed(botById.mgr, `upload failed: ${file.name}`); }
  }
  function findTask(b, id) { return [b.task, ...b.queue].find((t) => t && t.id === id); }
  function applyEvent(ev) {
    const b = botById[ev.bot]; if (!b) return;
    if (ev.type === 'task') return assign(b.id, ev.text, { secs: ev.secs || 6, external: true, id: ev.task });
    if (ev.type === 'done') {
      const t = findTask(b, ev.task);
      if (t) { t.finished = true; t.result = { text: ev.text, url: ev.url, ok: ev.ok, level: ev.level }; }
      else feed(b, ev.text, ev.url);
      return;
    }
    feed(b, ev.text); say(b, ev.text.slice(0, 28));
  }

  window.BotOffice = { bots: botById, assign, startPipeline, applyEvent, setDemo: (v) => { demo = v; document.getElementById('demoToggle').checked = v; } };

  resize(); fit(); makePortraits();
  document.querySelector('#managerBar .avatar').outerHTML = avatar(botById.mgr);
  feed(botById.mgr, 'Good morning team! Office is open 🌅');
  connectLive().then(() => {
    if (live) return;
    startPipeline('compliance', 'Data_Privacy_Act_RA10173.pdf');
    setTimeout(() => startPipeline('content', 'vlog_day3.mp4'), 1400);
  });
  requestAnimationFrame(frame);
})();
