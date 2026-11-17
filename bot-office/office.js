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

  // ───────────────────────── Sound effects ─────────────────────────
  // Tiny synthesized sounds (Web Audio), so there are no audio files to ship.
  // Browsers only allow audio after the user interacts with the page, so the
  // AudioContext is created on the first click / key / drop.
  const Sound = (() => {
    let ac = null, master = null;
    let muted = localStorage.getItem('botOfficeMuted') === '1';
    const lastPlayed = {};
    let musicOn = localStorage.getItem('botOfficeMusic') === '1', musicGain = null, musicTimer = null, nextBeat = 0, beat = 0;
    function unlock() {
      if (ac) { if (ac.state === 'suspended') ac.resume(); return; }
      const AC = window.AudioContext || window.webkitAudioContext; if (!AC) return;
      ac = new AC(); master = ac.createGain(); master.gain.value = 0.35; master.connect(ac.destination);
      musicGain = ac.createGain(); musicGain.gain.value = muted ? 0 : 0.09; musicGain.connect(ac.destination);
      if (musicOn) startMusic();
    }
    // Chill lo-fi: Fmaj7 · Em7 · Dm7 · Cmaj7 at 76 BPM, soft keys + bass + brushed beat.
    const CHORDS = [[53, 57, 60, 64], [52, 55, 59, 62], [50, 53, 57, 60], [48, 52, 55, 59]];
    const hz = (m) => 440 * Math.pow(2, (m - 69) / 12);
    function tone(freq, t0, len, type, vol, filt) {
      const o = ac.createOscillator(), g = ac.createGain(), f = ac.createBiquadFilter();
      o.type = type; o.frequency.value = freq; f.type = 'lowpass'; f.frequency.value = filt;
      g.gain.setValueAtTime(0.0001, t0); g.gain.linearRampToValueAtTime(vol, t0 + 0.04); g.gain.exponentialRampToValueAtTime(0.0001, t0 + len);
      o.connect(f); f.connect(g); g.connect(musicGain); o.start(t0); o.stop(t0 + len + 0.1);
    }
    function noise(t0, len, vol, hp) {
      const buf = ac.createBuffer(1, ac.sampleRate * len, ac.sampleRate), d = buf.getChannelData(0);
      for (let i = 0; i < d.length; i++) d[i] = (Math.random() * 2 - 1) * (1 - i / d.length);
      const src = ac.createBufferSource(), f = ac.createBiquadFilter(), g = ac.createGain();
      src.buffer = buf; f.type = 'highpass'; f.frequency.value = hp; g.gain.value = vol;
      src.connect(f); f.connect(g); g.connect(musicGain); src.start(t0);
    }
    function scheduleBeat(t0) {
      const bar = Math.floor(beat / 4) % 4, pos = beat % 4, spb = 60 / 76;
      if (pos === 0) {
        CHORDS[bar].forEach((m, i) => tone(hz(m + 12), t0 + i * 0.03, spb * 3.6, 'triangle', 0.11, 1800));  // keys, lightly strummed
        tone(hz(CHORDS[bar][0] - 12), t0, spb * 1.8, 'sine', 0.35, 400);                                       // bass
      }
      if (pos === 2) tone(hz(CHORDS[bar][0] - 12 + 7), t0, spb * 1.6, 'sine', 0.25, 400);
      if (pos === 0 || pos === 2) { const o = ac.createOscillator(), g = ac.createGain();                     // soft kick
        o.frequency.setValueAtTime(110, t0); o.frequency.exponentialRampToValueAtTime(45, t0 + 0.18);
        g.gain.setValueAtTime(0.5, t0); g.gain.exponentialRampToValueAtTime(0.001, t0 + 0.25); o.connect(g); g.connect(musicGain); o.start(t0); o.stop(t0 + 0.3); }
      if (pos === 1 || pos === 3) noise(t0, 0.18, 0.12, 1500);                                              // brush snare
      noise(t0 + spb / 2, 0.05, 0.05, 7000);                                                                 // hat on the off-beat
      if (pos === 3 && Math.random() < 0.4) tone(hz(CHORDS[bar][1 + Math.floor(Math.random() * 3)] + 24), t0 + spb / 2, 0.5, 'sine', 0.06, 3000); // sparkle
      beat++;
    }
    function startMusic() {
      if (!ac || musicTimer) return;
      nextBeat = ac.currentTime + 0.1;
      musicTimer = setInterval(() => { while (nextBeat < ac.currentTime + 0.4) { scheduleBeat(nextBeat); nextBeat += 60 / 76; } }, 100);
    }
    function stopMusic() { clearInterval(musicTimer); musicTimer = null; }
    ['pointerdown', 'keydown', 'drop'].forEach((ev) => window.addEventListener(ev, unlock, { capture: true }));
    // one soft note: frequency (Hz), start offset (s), length (s), waveform, loudness
    function note(freq, at, len, type = 'sine', vol = 0.6, slideTo = null) {
      const t0 = ac.currentTime + at, o = ac.createOscillator(), g = ac.createGain();
      o.type = type; o.frequency.setValueAtTime(freq, t0);
      if (slideTo) o.frequency.exponentialRampToValueAtTime(slideTo, t0 + len);
      g.gain.setValueAtTime(0.0001, t0);
      g.gain.exponentialRampToValueAtTime(vol, t0 + 0.012);
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + len);
      o.connect(g); g.connect(master); o.start(t0); o.stop(t0 + len + 0.05);
    }
    const SFX = {
      task:  () => { note(660, 0, 0.09, 'triangle', 0.5); note(990, 0.08, 0.16, 'sine', 0.45); },             // pop-ding
      done:  () => { note(784, 0, 0.12, 'triangle'); note(988, 0.1, 0.12, 'triangle'); note(1319, 0.2, 0.28, 'sine', 0.55); }, // chime
      high:  () => { note(392, 0, 0.22, 'square', 0.22); note(311, 0.24, 0.34, 'square', 0.22); },           // uh-oh
      error: () => { note(220, 0, 0.25, 'sawtooth', 0.25, 110); },                                           // bonk
      blip:  () => { note(1200, 0, 0.06, 'sine', 0.35, 1600); },                                             // click a bot
      upload:() => { note(300, 0, 0.18, 'sine', 0.35, 900); },                                               // whoosh up
    };
    return {
      play(name) {
        if (muted || !ac || ac.state !== 'running' || !SFX[name]) return;
        const t = performance.now();
        if (t - (lastPlayed[name] || 0) < 150) return; // don't machine-gun when many events arrive at once
        lastPlayed[name] = t; SFX[name]();
      },
      get muted() { return muted; },
      toggle() { muted = !muted; localStorage.setItem('botOfficeMuted', muted ? '1' : '0'); unlock();
        if (musicGain) musicGain.gain.value = muted ? 0 : 0.09; if (!muted) SFX.blip(); return muted; },
      get music() { return musicOn; },
      toggleMusic() { musicOn = !musicOn; localStorage.setItem('botOfficeMusic', musicOn ? '1' : '0'); unlock();
        if (musicOn) startMusic(); else stopMusic(); return musicOn; },
    };
  })();

  // ───────────────────────── Map / zones ─────────────────────────
  // A beach resort: two open nipa huts at the back (Evercrestcorp Compliance Hub on the left,
  // Content Studio on the right) and the beach in front: coffee bar beside the Hub, dance floor,
  // volleyball court, loungers and palm trees, with the sea all around.
  const HUT_D = 8;                     // the huts cover y < 8
  const WALL_H = 74;
  const zoneOf = (x, y) => (y >= HUT_D ? 'beach' : x >= 10 ? 'content' : 'compliance');

  // Low bamboo railings you can't walk through (with doorways), and the volleyball net.
  const blockedEdges = new Set();
  const edgeKey = (a, b, c, d) => (a < c || (a === c && b < d) ? `${a},${b}|${c},${d}` : `${c},${d}|${a},${b}`);
  const railings = [];
  for (let x = 0; x < W; x++) if (![4, 5, 15, 16].includes(x)) { blockedEdges.add(edgeKey(x, 7, x, 8)); railings.push({ type: 'railH', x, y: 8 }); }
  for (let y = 0; y < 8; y++) if (![5, 6].includes(y)) { blockedEdges.add(edgeKey(9, y, 10, y)); railings.push({ type: 'railV', x: 10, y }); }
  for (let y = 10; y <= 14; y++) blockedEdges.add(edgeKey(15, y, 16, y));

  // Furniture. block:true marks the cells it covers as solid; flat:true is painted on the ground.
  const F = [];
  const add = (o) => (F.push(Object.assign({ block: true, z: 0 }, o)), o);
  // Compliance Hub
  add({ type: 'shelf', x: 0.1, y: 0.05, w: 2, d: 0.6, h: 70, books: true });
  add({ type: 'shelf', x: 2.2, y: 0.05, w: 2, d: 0.6, h: 70, books: true });
  add({ type: 'docTable', x: 5.4, y: 0.2, w: 2.6, d: 0.9, h: 22 });
  add({ type: 'cabinet', x: 0.05, y: 5.05, w: 0.7, d: 0.9, h: 40 });
  add({ type: 'cabinet', x: 0.05, y: 6.05, w: 0.7, d: 0.9, h: 40 });
  add({ type: 'plant', x: 9.0, y: 0.2, w: 0.7, d: 0.7, h: 14 });
  add({ type: 'plant', x: 3.1, y: 6.9, w: 0.7, d: 0.7, h: 14 });
  // Content Studio
  add({ type: 'reelShelf', x: 11.1, y: 0.05, w: 2.6, d: 0.6, h: 52 });
  add({ type: 'greenscreen', x: 19.6, y: 0.05, w: 4.2, d: 0.2, h: 80 });
  add({ type: 'camera', x: 21.25, y: 3.25, w: 0.5, d: 0.5, h: 40 });
  add({ type: 'ringlight', x: 22.3, y: 2.3, w: 0.4, d: 0.4, h: 52 });
  add({ type: 'plant', x: 23.1, y: 6.2, w: 0.7, d: 0.7, h: 14 });
  add({ type: 'plant', x: 18.1, y: 6.9, w: 0.7, d: 0.7, h: 14 });
  // Beach
  add({ type: 'danceFloor', x: 3.6, y: 10.4, w: 4.8, d: 4.4, flat: true, block: false });
  add({ type: 'court', x: 12, y: 9.6, w: 8, d: 5.8, flat: true, block: false });
  add({ type: 'coffeeBar', x: 0.05, y: 8.9, w: 0.9, d: 3.2, h: 30 });
  for (const sy of [9.3, 10.3, 11.3]) add({ type: 'stool', x: 1.25, y: sy, w: 0.4, d: 0.4, h: 16, block: false });
  add({ type: 'truss', x: 3.6, y: 10.15, w: 4.8, d: 0.2, h: 84, block: false });
  add({ type: 'speaker', x: 2.95, y: 10.0, w: 0.55, d: 0.55, h: 32 });
  add({ type: 'speaker', x: 8.55, y: 10.0, w: 0.55, d: 0.55, h: 32 });
  add({ type: 'net', x: 15.95, y: 9.7, w: 0.1, d: 5.6, h: 46, block: false });
  add({ type: 'lounger', x: 21.15, y: 11.2, w: 0.8, d: 1.8, h: 10 });
  add({ type: 'lounger', x: 22.55, y: 11.2, w: 0.8, d: 1.8, h: 10 });
  add({ type: 'umbrella', x: 21.95, y: 10.35, w: 0.6, d: 0.6, h: 70, col: '#ff6f61', block: false });
  add({ type: 'sandcastle', x: 18.9, y: 15.1, w: 0.8, d: 0.7, h: 12, block: false });
  for (const [px, py] of [[3.2, 8.2], [6.5, 8.2], [14.2, 8.2], [17.5, 8.2]]) add({ type: 'torch', x: px, y: py, w: 0.3, d: 0.3, h: 46 });
  for (const [px, py, s] of [[0.3, 14.6, 1.1], [23.4, 9.0, 1.05], [23.2, 15.0, 1.15], [10.4, 15.1, 0.95], [2.5, 15.3, 0.9], [20.6, 15.4, 0.85]])
    add({ type: 'palm', x: px, y: py, w: 0.6, d: 0.6, h: 110 * s, s });

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
  addDesk('mgr', 6, 5, { zone: 'manager' });
  addDesk('vid', 11, 3, { dual: true, zone: 'content' });
  addDesk('cap', 14, 3, { dual: true, zone: 'content' });
  addDesk('sched', 17, 3, { zone: 'content' });
  addDesk('post', 11, 6, { zone: 'content' });

  const solid = Array.from({ length: W }, () => new Array(H).fill(false));
  for (const f of F) if (f.block) {
    for (let cx = Math.floor(f.x); cx < Math.ceil(f.x + f.w - 0.01); cx++)
      for (let cy = Math.floor(f.y); cy < Math.ceil(f.y + f.d - 0.01); cy++)
        if (cx >= 0 && cy >= 0 && cx < W && cy < H) solid[cx][cy] = true;
  }

  // Places bots hang out when idle. z = how high they sit/stand.
  const spots = [
    { x: 1.45, y: 9.5, z: 0, n: 'coffee' }, { x: 1.45, y: 10.5, z: 0, n: 'coffee' }, { x: 1.45, y: 11.5, z: 0, n: 'coffee' },
    { x: 4.6, y: 11.5, z: 2, n: 'dance' }, { x: 6.0, y: 11.3, z: 2, n: 'dance' }, { x: 7.4, y: 11.7, z: 2, n: 'dance' },
    { x: 5.2, y: 13.1, z: 2, n: 'dance' }, { x: 6.8, y: 13.5, z: 2, n: 'dance' }, { x: 4.7, y: 14.3, z: 2, n: 'dance' },
    { x: 13.6, y: 11.3, z: 0, n: 'volley' }, { x: 13.4, y: 13.7, z: 0, n: 'volley' },
    { x: 18.4, y: 11.6, z: 0, n: 'volley' }, { x: 18.6, y: 13.8, z: 0, n: 'volley' },
    { x: 21.55, y: 12.4, z: 9, n: 'lounger' }, { x: 22.95, y: 12.4, z: 9, n: 'lounger' },
    { x: 11.5, y: 14.3, z: 0, n: 'wander' }, { x: 10.8, y: 9.3, z: 0, n: 'wander' }, { x: 21.5, y: 15.3, z: 0, n: 'wander' },
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
    { id: 'doc', name: 'Pablo', title: 'Doc Reader', team: 'compliance', color: '#3ddc84',
      role: 'First on every case. Takes your uploads (contracts, privacy policies) and the KYC/KYB forms, opens the merchant\'s Drive folder, reads every file, ticks the ✅/❌ checklist, and pulls out the business details, directors and shareholders.' },
    { id: 'reg', name: 'Bailey', title: 'Reg Checker', team: 'compliance', color: '#4da3ff',
      role: 'The checker. Sanctions screening (OFAC, UN, EU, UK), Data Privacy Act (RA 10173) and contract checks on the documents, and website checks: domain age, SSL, red flags and the privacy page.' },
    { id: 'risk', name: 'Charlie', title: 'Risk Scout', team: 'compliance', color: '#ff8a3d',
      role: 'The reporter. Gives the result (STOP, REJECT, ESCALATE, PENDING, EDD, INCOMPLETE or CLEAR*) and writes the HTML and Word report, saved to your Drive as dd.mm.yy_Merchant name.' },
    { id: 'vid', name: 'Video Editor', title: 'Content team', team: 'content', color: '#ff6fae', role: 'Cuts and edits the videos (9:16), affiliate drafts and finals.' },
    { id: 'cap', name: 'Caption Writer', title: 'Content team', team: 'content', color: '#ffd23d', role: 'Hooks, captions and hashtags, with the platform rules applied.' },
    { id: 'sched', name: 'Scheduler', title: 'Content team', team: 'content', color: '#a77bff', role: 'Plans the posting calendar.' },
    { id: 'post', name: 'Poster', title: 'Content team', team: 'content', color: '#2ee6c9', role: 'Packages and publishes the posts.' },
    { id: 'mgr', name: 'Hazel', title: 'Bot Manager', team: 'manager', color: '#ff5d8f',
      role: 'Helps everyone and sends the alerts, like "🛑 possible sanctions TRUE MATCH. Escalate to the MLRO now. No tip-off."' },
  ];
  BOT_DEFS.forEach((d) => (d.label = d.title && d.title !== 'Content team' ? `${d.name} · ${d.title}` : d.name));
  const LINES = {
    idle: ['Coffee first ☕', 'Sun\'s out, files out ☀️', 'Vitamin Sea 🌊', 'Sand in my keyboard again', 'Beach mode: ON 🏖️',
      'Who wants volleyball? 🏐', 'Tide\'s high, risk is low', 'Sunscreen? Applied ✅', 'Brb, chasing the sunset 🌅',
      'Need a coconut 🥥', 'Who\'s next?', 'Life\'s a beach, then you audit'],
    compliance: ['Reading the fine print 🔍', 'Sec. 12… hmm', 'Checking the DPA…', 'Red flag spotted 🚩', 'Citing Art. 7',
      'Compliant ✅', 'Who still writes "herein"?', 'Screening names…', 'Footnote of doom 😱', 'Need a clause ref',
      'GIS says 60%…', 'Checklist ✅❌✅'],
    content: ['Hook first!', 'Rendering…', 'Cut! That\'s a wrap 🎬', 'Caption on point', 'Color grade 🎨', '3… 2… 1… post!',
      'Make it pop ✨', 'Golden hour shot 🌅', '#fyp energy'],
    chat: [['You done yet?', 'Almost! You?'], ['Volleyball later?', 'You\'re on! 🏐'], ['New KYB just dropped', 'I got this'],
      ['This one\'s going viral', 'Said every video ever 😂'], ['Coffee?', 'Iced, please 🧊☕'], ['Nice edit!', 'Thanks! 🥹'],
      ['Did you read the T&Cs?', 'Nobody reads the T&Cs.'], ['Dance floor at 5?', 'Wouldn\'t miss it 💃']],
    eat: ['Kape muna ☕', 'Iced latte 🧊', 'One more cookie 🍪', 'Barista knows my order', 'Caffeine = compliance', 'Ensaymada break 🥐'],
    play: ['Spike! 🏐', 'Nice dig!', 'Mine! Mine!', 'Point for us!', 'Set it up!', 'Sand in my shoes 😂', 'Rematch?'],
    dance: ['Let\'s dance! 💃', 'Watch this move 🕺', 'This is my song! 🎶', 'Budots time 😂', 'Cha-cha slide!', 'Turn it up! 🔊'],
    relax: ['Ahh, sea breeze 😌', 'Five more minutes 😴', 'Coconut break 🥥', 'Sunset mode 🌅', 'Don\'t wake me 😎'],
    jokes: [['Why was the contract sad?', 'It lost its appeal 😢'], ['Lawyer\'s favorite drink?', 'Subpoena colada 🍹'],
      ['Why did the UBO hide?', 'Too many layers 🧅'], ['Why did the video go viral?', 'It had a great hook 🎣'],
      ['Why don\'t crabs share files?', 'They\'re shellfish 🦀'], ['What did the ocean say to the beach?', 'Nothing, it just waved 🌊'],
      ['Why was the PDF stressed?', 'Too many unresolved issues'], ['Why go to the beach to audit?', 'Better sea-curity 🏖️'],
      ['Why is the risk report so calm?', 'It manages expectations'], ['Knock knock', 'Who\'s there? …Compliance. Sign here.']],
  };

  const ACTIVITY = { coffee: 'eat', volley: 'play', dance: 'dance', lounger: 'relax' };
  const FOODS = { coffee: ['☕', '🧋', '🥤', '🍪', '🥐'] };

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
    if (!b.task && b.state !== 'break') say(b, rand(['On it! 🙋', 'Leave it to me!', 'Challenge accepted']), 2);
    Sound.play('task');
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
    Sound.play(failed ? 'error' : r.level === 'HIGH' ? 'high' : 'done');
    if (failed) say(b, 'Uh oh, problem 😵', 3);
    else if (r.level === 'HIGH') say(b, 'HIGH risk! 🚩', 3.5);
    else if (r.level === 'MEDIUM') say(b, 'Medium risk ⚠️', 3);
    else if (r.level === 'LOW') say(b, 'Low risk, nice! ✅', 3);
    else say(b, rand(['Done! ✅', 'Next!', 'Easy peasy 😎', 'Nailed it!']), 2);
    if (t.next) setTimeout(() => assign(t.next.bot, t.next.text, t.next), 600);
  }

  // ───────────────────────── Bot brain ─────────────────────────
  function updateBot(b, dt, t) {
    // a new task interrupts beach time: head back to the desk
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

    // idle life: coffee, volleyball, dancing or a lounger, sometimes chat
    if (b.state === 'working' || b.state === 'walking') b.state = 'idle';
    b.z = (b.spot ? b.spot.z : 0) + Math.sin(t * 2.2 + b.phase) * 1.2;
    if (b.spot && !b.path.length && b.activity !== b.spot) {  // arrived: eat, play or relax
      b.activity = b.spot;
      b.actKind = ACTIVITY[b.spot.n] || 'relax';
      b.food = rand(FOODS[b.spot.n] || ['🍪']);
      if (Math.random() < 0.8) setTimeout(() => !b.task && b.activity && say(b, rand(LINES[b.actKind])), 600);
    }
    b.idleTimer -= dt;
    if (b.idleTimer <= 0) {
      b.idleTimer = 6 + Math.random() * 9;
      const r = Math.random();
      const others = bots.filter((o) => o !== b && o.id !== 'mgr' && !o.task && !o.path.length);
      if (r < 0.25 && others.length) {
        const o = rand(others), [a, c] = rand(Math.random() < 0.5 ? LINES.jokes : LINES.chat);
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
        setTimeout(() => say(b, rand(['How\'s it going? 👀', 'Great job!', 'Keep going 💪'])), 3500);
        setTimeout(() => walkTo(b, desks.mgr.seat.x, desks.mgr.seat.y, 6), 8000);
      }
    } else if (!atDesk && !b.path.length) walkTo(b, desks.mgr.seat.x, desks.mgr.seat.y, 6);
    else say(b, rand(['All good 👍', 'Status check ✔', 'Bots never sleep!']));
  }

  // ───────────────────────── Drawing: furniture ─────────────────────────
  const T = { t: 0 };
  const BAMBOO = '#c99a55', BAMBOO_D = '#9c7036', WOOD = '#8a5a2b', THATCH = '#d2a957', THATCH_D = '#a27c38';
  function line(a, b, col, w = 1) { ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.strokeStyle = col; ctx.lineWidth = w; ctx.stroke(); }
  function pole(x, y, z0, z1, col = BAMBOO, w = 4) {
    const a = iso(x, y, z0), b = iso(x, y, z1);
    line(a, b, shade(col, -0.25), w + 1.5); line(a, b, col, w);
    for (let z = z0 + 14; z < z1; z += 14) { const p = iso(x, y, z); ctx.fillStyle = shade(col, -0.35); ctx.fillRect(p.x - w / 2 - .5, p.y, w + 1, 1.5); }
  }
  function leaf(px, py, ang, len, col) {   // one drooping palm frond
    ctx.save(); ctx.translate(px, py); ctx.rotate(ang);
    ctx.beginPath(); ctx.moveTo(0, 0);
    ctx.quadraticCurveTo(len * .5, -len * .28, len, len * .22);
    ctx.quadraticCurveTo(len * .5, -len * .02, 0, 0);
    ctx.fillStyle = col; ctx.fill();
    ctx.strokeStyle = shade(col, -0.3); ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(0, 0); ctx.quadraticCurveTo(len * .5, -len * .16, len, len * .22); ctx.stroke();
    ctx.restore();
  }
  function drawFurniture(f) {
    const { x, y, w, d, h } = f;
    switch (f.type) {
      case 'shelf':
        box(x, y, w, d, h, 0, WOOD);
        for (let r = 0; r < 4; r++) {
          const z1 = 6 + r * 16;
          quadY(y + d, x + .05, x + w - .05, z1, z1 + 2, '#5a3518');
          if (f.books) for (let i = 0; i < 9; i++) {
            const bx = x + .1 + i * (w - .2) / 9, col = ['#e84a5f', '#ffd23d', '#3ddc84', '#4da3ff', '#ff8a3d', '#a77bff'][(i * 7 + r * 3) % 6];
            quadY(y + d + 0.001, bx, bx + (w - .2) / 9 - .03, z1 + 2, z1 + 11 + ((i + r) % 3) * 1.5, col);
          }
        }
        break;
      case 'reelShelf':
        box(x, y, w, d, h, 0, WOOD);
        for (let r = 0; r < 2; r++) for (let i = 0; i < 4; i++) {
          const p = iso(x + .35 + i * .6, y + d, 14 + r * 22);
          ctx.beginPath(); ctx.arc(p.x, p.y, 7, 0, 7); ctx.fillStyle = '#d9d9e6'; ctx.fill();
          ctx.beginPath(); ctx.arc(p.x, p.y, 2.5, 0, 7); ctx.fillStyle = WOOD; ctx.fill();
        }
        break;
      case 'cabinet':
        box(x, y, w, d, h, 0, '#a87a48');
        for (let r = 0; r < 3; r++) quadX(x + w + .001, y + .15, y + d - .15, 6 + r * 12, 8 + r * 12, '#6b4a26');
        break;
      case 'docTable':
        box(x, y, w, d, h, 0, '#a8673a');
        for (let i = 0; i < 4; i++) box(x + .25 + i * .6, y + .2, .4, .45, 4 + (i % 3) * 3, h, '#f7f3ea');
        break;
      case 'desk': {
        box(x + .05, y + .05, .12, .12, h, 0, BAMBOO_D); box(x + w - .17, y + d - .17, .12, .12, h, 0, BAMBOO_D);
        box(x, y, w, d, 4, h - 4, BAMBOO, { top: '#e2b874' });
        const glow = f.owner && botById[f.owner] && (botById[f.owner].state === 'working' || f.owner === 'mgr');
        const screens = f.dual ? [x + .15, x + .9] : [x + .5];
        for (const sx of screens) {
          box(sx, y + .1, .65, .1, 18, h + 3, '#2b2b3a');
          box(sx + .28, y + .14, .08, .05, 3, h, '#2b2b3a');
          const sc = glow ? (f.zone === 'content' ? ['#ff9bd0', '#a68bff'][Math.floor(T.t * 2 + sx) % 2] : f.zone === 'manager' ? '#ffd6e3' : '#bfe8ff') : '#3a4560';
          quadY(y + .2 + .001, sx + .05, sx + .6, h + 5, h + 19, sc);
          if (glow) for (let l = 0; l < 3; l++) quadY(y + .2 + .002, sx + .1, sx + .1 + (.2 + ((l * 37 + Math.floor(T.t * 3)) % 5) * .06), h + 15 - l * 4, h + 16 - l * 4,
            f.zone === 'manager' && l === 0 ? '#e84a5f' : 'rgba(40,60,90,.55)');
        }
        box(x + .45, y + .45, .6, .2, 2, h, '#3a3a52');
        if (f.zone === 'compliance') box(x + 1.25, y + .4, .3, .35, 5, h, '#fffaf0');
        else if (f.zone === 'manager') { box(x + 1.2, y + .35, .35, .4, 7, h, '#ffd23d'); box(x + 1.22, y + .37, .3, .35, 3, h + 7, '#4da3ff'); }
        else { const p = iso(x + 1.45, y + .5, h + 4); ctx.beginPath(); ctx.arc(p.x, p.y, 5, 0, 7); ctx.fillStyle = '#ffd23d'; ctx.fill(); }
        break;
      }
      case 'chair':
        box(x, y, w, d, h, 0, '#9b6a3a');
        box(x, y + d - .12, w, .12, 14, h, '#b07a43');
        break;
      case 'greenscreen':
        pole(x + .05, y + .1, 0, h + 4, BAMBOO_D, 3); pole(x + w - .05, y + .1, 0, h + 4, BAMBOO_D, 3);
        quadY(y + .1, x + .1, x + w - .1, 6, h, '#2fb35c');
        break;
      case 'camera': {
        const c = iso(x + .25, y + .25, 0), top = iso(x + .25, y + .25, 34);
        for (const [ox, oy] of [[-8, 4], [8, 4], [0, -3]]) line({ x: c.x + ox, y: c.y + oy }, top, '#1c1c28', 2);
        box(x + .05, y + .05, .4, .45, 12, 32, '#1c1c28');
        const rec = Math.floor(T.t * 2) % 2; const p = iso(x + .1, y + .5, 40); ctx.beginPath(); ctx.arc(p.x, p.y, 2, 0, 7); ctx.fillStyle = rec ? '#ff3b3b' : '#5a1a1a'; ctx.fill();
        break;
      }
      case 'ringlight': {
        const c = iso(x + .2, y + .2, 0), top = iso(x + .2, y + .2, 46);
        line(c, top, '#2a2a38', 2);
        ctx.beginPath(); ctx.ellipse(top.x, top.y - 8, 9, 12, -0.5, 0, 7); ctx.strokeStyle = '#fff8d8'; ctx.lineWidth = 3;
        ctx.shadowColor = '#fff3b0'; ctx.shadowBlur = 12; ctx.stroke(); ctx.shadowBlur = 0;
        break;
      }
      case 'plant': {   // monstera in a clay pot
        box(x + .15, y + .15, .4, .4, h, 0, '#c2683a');
        const p = iso(x + .35, y + .35, h);
        for (let i = 0; i < 6; i++) {
          const a = -Math.PI / 2 + (i - 2.5) * 0.5 + Math.sin(T.t * 1.3 + x + i) * 0.05;
          ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(a);
          ctx.beginPath(); ctx.ellipse(13, 0, 12, 7, 0, 0, 7); ctx.fillStyle = i % 2 ? '#2f9e57' : '#3dbb69'; ctx.fill();
          ctx.strokeStyle = '#1f7a40'; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(2, 0); ctx.lineTo(24, 0); ctx.stroke();
          ctx.restore();
        }
        break;
      }
      case 'coffeeBar': {
        box(x, y, w, d, h, 0, BAMBOO, { top: '#f0dcb4' });
        for (let i = 0; i < 9; i++) quadX(x + w + .001, y + .1 + i * .34, y + .16 + i * .34, 2, h - 2, BAMBOO_D);  // bamboo front
        box(x + .15, y + .3, .55, .55, 20, h, '#c9ccd6', { top: '#e9ebf2' });                                       // espresso machine
        quadX(x + .7 + .001, y + .4, y + .75, h + 6, h + 16, '#30303e');
        const s = iso(x + .45, y + .6, h + 24 + Math.sin(T.t * 3) * 3); ctx.fillStyle = 'rgba(255,255,255,.45)'; ctx.beginPath(); ctx.arc(s.x, s.y, 3, 0, 7); ctx.fill();
        for (let i = 0; i < 3; i++) box(x + .35, y + 1.2 + i * .35, .2, .2, 6, h, ['#ffffff', '#ffd23d', '#ff9bd0'][i]);
        box(x + .25, y + 2.4, .45, .45, 12, h, 'rgba(220,240,255,.6)', { top: 'rgba(240,250,255,.6)' });           // cookie jar
        for (const [dx, dy] of [[.4, 2.6], [.5, 2.5]]) { const p = iso(x + dx, y + dy, h + 5); ctx.beginPath(); ctx.arc(p.x, p.y, 2.5, 0, 7); ctx.fillStyle = '#b8743f'; ctx.fill(); }
        // mini thatched roof on bamboo posts + sign
        for (const [px, py] of [[x + .05, y + .05], [x + w + .45, y + .05], [x + .05, y + d - .05], [x + w + .45, y + d - .05]]) pole(px, py, 0, 86, BAMBOO, 3);
        poly([iso(x - .3, y - .3, 92), iso(x + w + .8, y - .3, 80), iso(x + w + .8, y + d + .3, 80), iso(x - .3, y + d + .3, 92)], THATCH);
        poly([iso(x + w + .8, y - .3, 80), iso(x + w + .8, y + d + .3, 80), iso(x + w + .8, y + d + .3, 72), iso(x + w + .8, y - .3, 72)], THATCH_D);
        for (let i = 0; i < 16; i++) { const p = iso(x + w + .8, y - .25 + i * (d + .5) / 16, 72); line(p, { x: p.x + 1, y: p.y + 4 + (i % 3) }, THATCH_D, 2); }
        plank('☕ COFFEE BAR', 'x', x + w + .82, y + .2, y + d - .2, 74, 86, 11);
        break;
      }
      case 'stool': {
        const p = iso(x + .2, y + .2, 0), q = iso(x + .2, y + .2, h);
        line(p, q, '#6b4a26', 3);
        ctx.beginPath(); ctx.ellipse(q.x, q.y, 8, 4, 0, 0, 7); ctx.fillStyle = '#b07a43'; ctx.fill();
        break;
      }
      case 'danceFloor': {
        const n = 6, cw = w / n, cd = d / n, k = Math.floor(T.t * 3);
        const pal = ['#ff4fa3', '#ffd23d', '#2ee6c9', '#a77bff', '#4da3ff', '#ff8a3d'];
        poly([iso(x - .08, y - .08, 1), iso(x + w + .08, y - .08, 1), iso(x + w + .08, y + d + .08, 1), iso(x - .08, y + d + .08, 1)], '#2b2340');
        for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) {
          const on = (i * 3 + j * 5 + k) % 4 !== 0;
          const c = pal[(i + j + k) % pal.length];
          poly([iso(x + i * cw + .04, y + j * cd + .04, 2), iso(x + (i + 1) * cw - .04, y + j * cd + .04, 2),
            iso(x + (i + 1) * cw - .04, y + (j + 1) * cd - .04, 2), iso(x + i * cw + .04, y + (j + 1) * cd - .04, 2)], on ? c : shade(c, -0.55));
        }
        break;
      }
      case 'truss': {
        pole(x, y, 0, h, '#9aa0b4', 3); pole(x + w, y, 0, h, '#9aa0b4', 3);
        line(iso(x, y, h), iso(x + w, y, h), '#9aa0b4', 4);
        const pal = ['#ff4fa3', '#ffd23d', '#2ee6c9', '#a77bff', '#4da3ff'];
        for (let i = 0; i < 5; i++) {
          const lx = x + .5 + i * (w - 1) / 4, p = iso(lx, y, h - 4), c = pal[(i + Math.floor(T.t * 2)) % 5];
          ctx.globalAlpha = 0.16 + 0.1 * Math.sin(T.t * 5 + i);
          const sweep = Math.sin(T.t * 1.5 + i) * 1.2, f1 = iso(lx - .5 + sweep, y + 2.6, 2), f2 = iso(lx + .5 + sweep, y + 3.4, 2);
          ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(f1.x, f1.y); ctx.lineTo(f2.x, f2.y); ctx.closePath(); ctx.fillStyle = c; ctx.fill();
          ctx.globalAlpha = 1;
          ctx.beginPath(); ctx.arc(p.x, p.y, 4.5, 0, 7); ctx.fillStyle = c; ctx.shadowColor = c; ctx.shadowBlur = 12; ctx.fill(); ctx.shadowBlur = 0;
        }
        break;
      }
      case 'speaker': {
        box(x, y, w, d, h, 0, '#25212f');
        const beat = 1 + (Math.floor(T.t * 4) % 2) * 0.12;
        for (const z of [h * .3, h * .72]) { const p = iso(x + w / 2, y + d, z); ctx.beginPath(); ctx.ellipse(p.x - 4, p.y + 2, 5 * beat, 6 * beat, 0, 0, 7); ctx.fillStyle = '#4a4560'; ctx.fill(); }
        break;
      }
      case 'court': {
        poly([iso(x, y), iso(x + w, y), iso(x + w, y + d), iso(x, y + d)], 'rgba(255,240,205,.55)');
        ctx.lineWidth = 2; ctx.strokeStyle = '#3d8bff';
        poly([iso(x + .2, y + .2), iso(x + w - .2, y + .2), iso(x + w - .2, y + d - .2), iso(x + .2, y + d - .2)], null);
        ctx.beginPath(); [iso(x + .2, y + .2), iso(x + w - .2, y + .2), iso(x + w - .2, y + d - .2), iso(x + .2, y + d - .2)].forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y))); ctx.closePath(); ctx.stroke();
        break;
      }
      case 'net': {
        pole(x, y, 0, h + 4, '#e8e8f0', 3); pole(x, y + d, 0, h + 4, '#e8e8f0', 3);
        poly([iso(x, y, h - 14), iso(x, y + d, h - 14), iso(x, y + d, h), iso(x, y, h)], 'rgba(255,255,255,.16)');
        for (let i = 0; i <= 18; i++) line(iso(x, y + i * d / 18, h - 14), iso(x, y + i * d / 18, h), 'rgba(40,40,60,.45)', 1);
        for (const z of [h - 14, h - 7, h]) line(iso(x, y, z), iso(x, y + d, z), z === h ? '#ffffff' : 'rgba(40,40,60,.5)', z === h ? 2.5 : 1);
        break;
      }
      case 'lounger':
        box(x + .05, y + .1, .7, 1.6, 6, 0, '#f2f2f2');
        box(x + .08, y + .15, .64, 1.5, 3, 6, '#3fb7e0', { top: '#56c8ee' });
        box(x + .08, y + .12, .64, .35, 12, 6, '#3fb7e0', { top: '#56c8ee' });
        break;
      case 'umbrella': {
        pole(x + .3, y + .3, 0, h, '#f2f2f2', 2);
        const c = iso(x + .3, y + .3, h + 6);
        for (let i = 0; i < 8; i++) {
          const a1 = i / 8 * Math.PI * 2, a2 = (i + 1) / 8 * Math.PI * 2;
          ctx.beginPath(); ctx.moveTo(c.x, c.y - 8);
          ctx.lineTo(c.x + Math.cos(a1) * 40, c.y + Math.sin(a1) * 20 + 4); ctx.lineTo(c.x + Math.cos(a2) * 40, c.y + Math.sin(a2) * 20 + 4); ctx.closePath();
          ctx.fillStyle = i % 2 ? '#ffffff' : f.col; ctx.fill();
        }
        break;
      }
      case 'sandcastle': {
        box(x, y, w, d, 8, 0, '#e3c27f', { top: '#ecd093' });
        box(x + .1, y + .1, .3, .3, 10, 8, '#e3c27f', { top: '#ecd093' }); box(x + .45, y + .3, .25, .25, 7, 8, '#e3c27f', { top: '#ecd093' });
        const p = iso(x + .25, y + .25, 18); line(p, { x: p.x, y: p.y - 10 }, '#6b4a26', 1); ctx.fillStyle = '#e84a5f'; ctx.fillRect(p.x, p.y - 10, 6, 4);
        break;
      }
      case 'torch': {
        pole(x + .15, y + .15, 0, h, BAMBOO_D, 3);
        const p = iso(x + .15, y + .15, h + 4), fl = Math.sin(T.t * 12 + x) * 1.5;
        ctx.beginPath(); ctx.moveTo(p.x - 4, p.y + 2); ctx.quadraticCurveTo(p.x - 5, p.y - 8, p.x + fl, p.y - 14); ctx.quadraticCurveTo(p.x + 5, p.y - 8, p.x + 4, p.y + 2); ctx.closePath();
        ctx.fillStyle = '#ffb02e'; ctx.shadowColor = '#ff8a3d'; ctx.shadowBlur = 14; ctx.fill(); ctx.shadowBlur = 0;
        ctx.beginPath(); ctx.ellipse(p.x, p.y - 3, 1.8, 4, 0, 0, 7); ctx.fillStyle = '#fff3b0'; ctx.fill();
        break;
      }
      case 'palm': {
        const s = f.s || 1, sway = Math.sin(T.t * 0.9 + x * 1.7) * 3;
        const base = iso(x + .3, y + .3, 0);
        ctx.beginPath(); ctx.ellipse(base.x + 30 * s, base.y + 6, 34 * s, 12 * s, 0, 0, 7); ctx.fillStyle = 'rgba(40,90,40,.18)'; ctx.fill();
        let px = base.x, py = base.y;
        const segs = 9, top = { x: base.x + 16 * s + sway, y: base.y - h };
        for (let i = 0; i < segs; i++) {
          const u = (i + 1) / segs, nx = base.x + (16 * s + sway) * u * u, ny = base.y - h * u;
          ctx.beginPath(); ctx.ellipse((px + nx) / 2, (py + ny) / 2, 5.5 * s - u * 1.5, h / segs / 2 + 1, 0, 0, 7);
          ctx.fillStyle = i % 2 ? '#a5753f' : '#8c6132'; ctx.fill();
          px = nx; py = ny;
        }
        for (let i = 0; i < 8; i++) {
          const a = i / 8 * Math.PI * 2 + Math.sin(T.t * 1.1 + i) * 0.06;
          leaf(top.x, top.y, a, (44 + (i % 3) * 6) * s, i % 2 ? '#2f9e57' : '#3fbf6a');
        }
        for (const [cx, cy] of [[-3, 3], [3, 4], [0, 6]]) { ctx.beginPath(); ctx.arc(top.x + cx, top.y + cy, 3.6 * s, 0, 7); ctx.fillStyle = '#6b4a26'; ctx.fill(); }
        break;
      }
      case 'railH': case 'railV': {
        if (f.type === 'railH') { pole(x + .05, y, 0, 18, BAMBOO, 3); line(iso(x, y, 16), iso(x + 1, y, 16), BAMBOO_D, 5); line(iso(x, y, 16), iso(x + 1, y, 16), BAMBOO, 3.5); line(iso(x, y, 8), iso(x + 1, y, 8), BAMBOO, 2.5); }
        else { pole(x, y + .05, 0, 18, BAMBOO, 3); line(iso(x, y, 16), iso(x, y + 1, 16), BAMBOO_D, 5); line(iso(x, y, 16), iso(x, y + 1, 16), BAMBOO, 3.5); line(iso(x, y, 8), iso(x, y + 1, 8), BAMBOO, 2.5); }
        break;
      }
    }
  }

  // Volleyball: a ball flies between the players on each side of the net.
  function volleyBall(t) {
    const players = bots.filter((b) => b.spot && b.spot.n === 'volley' && b.activity === b.spot && !b.path.length && !b.task);
    if (!players.length) return null;
    const L = players.filter((b) => b.x < 16), R = players.filter((b) => b.x >= 16);
    if (L.length && R.length) {
      const P = 1.5, k = Math.floor(t / P), u = t / P - k;
      const from = k % 2 ? R[k % R.length] : L[k % L.length], to = k % 2 ? L[(k + 1) % L.length] : R[(k + 1) % R.length];
      return { x: from.x + (to.x - from.x) * u, y: from.y + (to.y - from.y) * u, z: 52 + 70 * 4 * u * (1 - u), hitter: u < 0.15 ? from : u > 0.85 ? to : null };
    }
    const b = players[0], u = (t * 0.9) % 1;
    return { x: b.x + .2, y: b.y, z: 50 + 44 * 4 * u * (1 - u), hitter: u < 0.15 || u > 0.85 ? b : null };
  }
  function drawBall(ball) {
    const g = iso(ball.x, ball.y, 0), p = iso(ball.x, ball.y, ball.z);
    ctx.beginPath(); ctx.ellipse(g.x, g.y, 5, 2.5, 0, 0, 7); ctx.fillStyle = 'rgba(0,0,0,.18)'; ctx.fill();
    ctx.beginPath(); ctx.arc(p.x, p.y, 5.5, 0, 7); ctx.fillStyle = '#fffdf5'; ctx.fill();
    ctx.strokeStyle = '#3d8bff'; ctx.lineWidth = 1.6; ctx.beginPath(); ctx.arc(p.x, p.y, 5.5, 0.3 + T.t * 4, 1.6 + T.t * 4); ctx.stroke();
    ctx.strokeStyle = '#ffd23d'; ctx.beginPath(); ctx.arc(p.x, p.y, 5.5, 2.4 + T.t * 4, 3.6 + T.t * 4); ctx.stroke();
  }

  // ───────────────────────── Drawing: sea, beach and huts ─────────────────────────
  const rect = (m, z = 0) => [iso(-m, -m, z), iso(W + m, -m, z), iso(W + m, H + m, z), iso(-m, H + m, z)];
  const SPECKS = Array.from({ length: 260 }, (_, i) => ({ x: ((i * 7919) % 1000) / 1000 * (W + 3) - 1.5, y: ((i * 104729) % 1000) / 1000 * (H + 3) - 1.5, c: i % 3 }));
  function drawGround(t) {
    // sky and sea (screen-wide, in world units)
    const hy = iso(-7, -7).y;
    const sky = ctx.createLinearGradient(0, hy - 520, 0, hy);
    sky.addColorStop(0, '#5ec2f2'); sky.addColorStop(1, '#c9efff');
    ctx.fillStyle = sky; ctx.fillRect(-6000, hy - 6000, 12000, 6000);
    const sea = ctx.createLinearGradient(0, hy, 0, hy + 900);
    sea.addColorStop(0, '#2fb6d8'); sea.addColorStop(0.5, '#1d9fca'); sea.addColorStop(1, '#147fae');
    ctx.fillStyle = sea; ctx.fillRect(-6000, hy, 12000, 6000);
    // far island with tiny nipa huts, and clouds
    const fx = iso(-7, -7).x - 420;
    ctx.fillStyle = '#4fae74'; ctx.beginPath(); ctx.ellipse(fx, hy, 150, 18, 0, Math.PI, 0); ctx.fill();
    for (const hx of [-50, -20, 15]) { ctx.fillStyle = '#a5753f'; ctx.fillRect(fx + hx, hy - 16, 14, 10); ctx.fillStyle = THATCH; ctx.beginPath(); ctx.moveTo(fx + hx - 4, hy - 16); ctx.lineTo(fx + hx + 7, hy - 26); ctx.lineTo(fx + hx + 18, hy - 16); ctx.closePath(); ctx.fill(); }
    for (let i = 0; i < 5; i++) {
      const cx = ((i * 380 + t * 6) % 2400) - 1200 + iso(W / 2, H / 2).x, cy = hy - 120 - (i % 3) * 70;
      ctx.fillStyle = 'rgba(255,255,255,.85)';
      for (const [ox, oy, r] of [[0, 0, 26], [24, -10, 30], [52, 0, 24], [26, 6, 26]]) { ctx.beginPath(); ctx.arc(cx + ox, cy + oy, r, 0, 7); ctx.fill(); }
    }
    // gentle wave rings around the island
    for (let i = 0; i < 5; i++) {
      const m = 3 + ((i * 1.6 + t * 0.35) % 8);
      ctx.globalAlpha = Math.max(0, 0.45 - m / 18);
      ctx.beginPath(); rect(m).forEach((p, j) => (j ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y))); ctx.closePath();
      ctx.strokeStyle = '#e8fbff'; ctx.lineWidth = 2; ctx.stroke();
    }
    ctx.globalAlpha = 1;
    // island: foam, wet sand, dry sand
    const foam = 2.5 + Math.sin(t * 1.2) * 0.12;
    poly(rect(foam), '#effcff'); poly(rect(2.15), '#e2c389'); poly(rect(1.8), '#f3dcaa');
    for (const s of SPECKS) { const p = iso(s.x, s.y); ctx.fillStyle = ['#e3c48c', '#fff1cf', '#d8b878'][s.c]; ctx.fillRect(p.x, p.y, 2, 1.5); }
    // bamboo floors of the huts
    for (let x = 0; x < W; x++) for (let y = 0; y < HUT_D; y++)
      poly([iso(x, y, 1), iso(x + 1, y, 1), iso(x + 1, y + 1, 1), iso(x, y + 1, 1)], (y % 2) ? '#d9ab6a' : '#cf9f5d');
    for (let y = 0; y < HUT_D; y += 0.5) line(iso(0, y, 1), iso(W, y, 1), 'rgba(120,80,30,.25)', 1);
    poly([iso(0, HUT_D, 1), iso(W, HUT_D, 1), iso(W, HUT_D, -4), iso(0, HUT_D, -4)], '#a77a3e');
    poly([iso(W, 0, 1), iso(W, HUT_D, 1), iso(W, HUT_D, -4), iso(W, 0, -4)], '#8f6631');
  }
  function plank(text, plane, p, a1, a2, z1, z2, size = 14) {
    // a wooden sign board on the x = p (plane 'x') or y = p (plane 'y') plane
    const pts = plane === 'y' ? [iso(a1, p, z1), iso(a2, p, z1), iso(a2, p, z2), iso(a1, p, z2)] : [iso(p, a1, z1), iso(p, a2, z1), iso(p, a2, z2), iso(p, a1, z2)];
    poly(pts, '#7a4a22'); ctx.lineWidth = 1.5; ctx.strokeStyle = '#4e2d12'; ctx.stroke();
    const o = plane === 'y' ? iso((a1 + a2) / 2, p, (z1 + z2) / 2) : iso(p, (a1 + a2) / 2, (z1 + z2) / 2);
    ctx.save(); ctx.translate(o.x, o.y); ctx.transform(1, plane === 'y' ? 0.5 : -0.5, 0, 1, 0, 0);
    ctx.font = `800 ${size}px ui-rounded, "Trebuchet MS", system-ui, sans-serif`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillStyle = '#ffe9b0'; ctx.shadowColor = 'rgba(0,0,0,.5)'; ctx.shadowBlur = 2; ctx.fillText(text, 0, 1); ctx.restore();
  }
  function drawHutWalls() {
    // woven bamboo back walls
    box(-0.25, -0.25, W + 0.25, 0.25, WALL_H, 0, '#b88446', { left: '#cf9f5d', top: '#8a5a2b' });
    box(-0.25, 0, 0.25, HUT_D, WALL_H, 0, '#b88446', { right: '#bf8d4e', top: '#8a5a2b' });
    for (let x = 0; x < W; x += 0.5) quadY(0.001, x, x + .05, 0, WALL_H, 'rgba(110,70,25,.35)');
    for (let y = 0; y < HUT_D; y += 0.5) quadX(0.001, y, y + .05, 0, WALL_H, 'rgba(110,70,25,.35)');
    for (const z of [22, 48]) { quadY(0.002, 0, W, z, z + 3, 'rgba(110,70,25,.35)'); quadX(0.002, 0, HUT_D, z, z + 3, 'rgba(110,70,25,.35)'); }
    // windows looking out to the sea
    for (const wx of [5.0, 7.3, 14.3, 16.6]) {
      quadY(0.003, wx, wx + 1.6, 28, 62, '#7a4a22');
      quadY(0.004, wx + .1, wx + 1.5, 31, 59, '#8fdcf2'); quadY(0.005, wx + .1, wx + 1.5, 31, 40, '#3fb3d6');
      quadY(0.006, wx + .77, wx + .83, 31, 59, '#7a4a22');
    }
    for (const wy of [1.4, 3.6]) { quadX(0.003, wy, wy + 1.5, 28, 62, '#7a4a22'); quadX(0.004, wy + .1, wy + 1.4, 31, 59, '#8fdcf2'); quadX(0.005, wy + .1, wy + 1.4, 31, 40, '#3fb3d6'); }
    // content calendar board
    quadY(0.003, 10.4, 13.4, 30, 66, '#fff6e6');
    for (let r = 0; r < 3; r++) for (let c = 0; c < 5; c++) {
      const cx = 10.55 + c * .56, z = 61 - r * 10;
      quadY(0.004, cx, cx + .46, z - 7, z, (r * 5 + c + Math.floor(stats.done / 2)) % 4 === 0 ? ['#ff6fae', '#ffd23d', '#2ee6c9', '#a77bff'][(r + c) % 4] : '#eadfca');
    }
  }
  function drawRoof() {
    // thatched nipa roof over the back of the huts (drawn last so it sits on top)
    const z0 = WALL_H - 4, z1 = WALL_H + 36;
    poly([iso(-0.7, -0.7, z1), iso(W + 0.5, -0.7, z1), iso(W + 0.5, 1.0, z0), iso(1.0, 1.0, z0)], THATCH);
    poly([iso(-0.7, -0.7, z1), iso(1.0, 1.0, z0), iso(1.0, HUT_D + 0.4, z0), iso(-0.7, HUT_D + 0.4, z1)], shade(THATCH, -0.08));
    for (let x = 1.1; x < W + 0.5; x += 0.22) line(iso(x - 1.6, -0.7, z1), iso(x, 1.0, z0), THATCH_D, 1);
    for (let y = 1.1; y < HUT_D + 0.4; y += 0.22) line(iso(-0.7, y - 1.6, z1), iso(1.0, y, z0), THATCH_D, 1);
    for (let x = 1.0; x < W + 0.5; x += 0.12) { const p = iso(x, 1.0, z0); line(p, { x: p.x, y: p.y + 4 + ((x * 31) % 4) }, THATCH_D, 2); }
    for (let y = 1.0; y < HUT_D + 0.4; y += 0.12) { const p = iso(1.0, y, z0); line(p, { x: p.x, y: p.y + 4 + ((y * 31) % 4) }, THATCH_D, 2); }
    line(iso(-0.7, -0.7, z1), iso(W + 0.5, -0.7, z1), '#8a6427', 4); line(iso(-0.7, -0.7, z1), iso(-0.7, HUT_D + 0.4, z1), '#8a6427', 4);
    plank('🌺 EVERCRESTCORP COMPLIANCE HUB', 'y', 0.2, 1.4, 9.4, z0 + 10, z0 + 30, 15);
    plank('🎬 CONTENT STUDIO', 'y', 0.2, 14.0, 19.0, z0 + 10, z0 + 30, 15);
  }

  // ───────────────────────── Drawing: the team (Pixar-style cartoon people) ─────────────────────────
  // Local coords: feet at (0,0), +x = the way the character faces (flipped with scale(-1,1)).
  const LOOKS = {
    doc:   { scale: 1.1, skin: '#e0ae84', hair: '#2b1d16', style: 'sidepart', eye: '#5a3a22', glasses: true, beard: false,
             top: 'floral', shirt: '#22a99a', flower: '#ffd6e0', pants: '#cdb48a', shoe: '#6b4a26', brows: 'thick' },
    reg:   { scale: 1.06, skin: '#f2c9a5', hair: '#5a3524', style: 'bob', eye: '#3f6b3a', headset: true, lashes: true,
             top: 'blazer', shirt: '#2f4f9e', inner: '#ffffff', pants: '#2b3556', long: true, shoe: '#2a2333', lips: true },
    risk:  { scale: 1.1, skin: '#d29a70', hair: '#3a2618', style: 'short', eye: '#4a2e1c', top: 'polo', shirt: '#4da3ff',
             pants: '#3b3d63', long: true, shoe: '#2a2333', brows: 'thick' },
    mgr:   { scale: 1.06, skin: '#e8b48e', hair: '#4a2a1a', style: 'longwave', eye: '#5a3a22', lashes: true, lips: true,
             top: 'floral', shirt: '#ff5d8f', flower: '#fff1a8', pants: '#f4efe6', shoe: '#c0392b', earrings: true },
    vid:   { scale: 0.88, skin: '#c98d62', hair: '#1f1410', style: 'curly', eye: '#3a2416', lashes: true,
             top: 'tee', shirt: '#a77bff', pants: '#3b5bdb', shoe: '#ffffff', clip: '#ffd23d' },
    cap:   { scale: 0.86, skin: '#f1c7a4', hair: '#7a4a22', style: 'boy', eye: '#3c6e9e', top: 'tee', shirt: '#ffd23d', stripe: '#ff8a3d',
             pants: '#3f7d4d', shoe: '#e84a5f' },
    sched: { scale: 0.88, skin: '#e3ad84', hair: '#2e1d16', style: 'pony', eye: '#4a2e1c', lashes: true, top: 'tee', shirt: '#ff7aa8',
             pants: '#ffffff', shoe: '#a77bff', clip: '#2ee6c9' },
    post:  { scale: 0.86, skin: '#8d5a3b', hair: '#1a110c', style: 'afro', eye: '#2a1a10', top: 'tee', shirt: '#2ee6c9',
             pants: '#30406b', shoe: '#ffd23d' },
  };
  Object.values(LOOKS).forEach((L) => (L.scale *= 1.3));  // bigger, friendlier characters
  let hoverBot = null, selected = null, filter = 'all';
  const HEAD_Y = -44, HR = 12.5;

  function rr(x, y, w, h, r) {
    ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
  }
  function circ(x, y, r, fill) { ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fillStyle = fill; ctx.fill(); }
  function grad(y1, y2, col) { const g = ctx.createLinearGradient(0, y1, 0, y2); g.addColorStop(0, shade(col, 0.16)); g.addColorStop(1, shade(col, -0.14)); return g; }
  function limb(px, py, ang, len, wid, col, end, endCol) {
    ctx.save(); ctx.translate(px, py); ctx.rotate(ang);
    rr(-wid / 2, 0, wid, len, wid / 2); ctx.fillStyle = col; ctx.fill();
    if (end) circ(0, len, end, endCol);
    ctx.restore();
  }

  function hairBack(L) {
    const h = L.hair, y = HEAD_Y;
    ctx.fillStyle = h;
    if (L.style === 'bob') {
      ctx.beginPath(); ctx.ellipse(-3, y - 1, 14.5, 14.5, 0, 0, Math.PI * 2); ctx.fill();
      ctx.beginPath(); ctx.moveTo(-15, y - 2); ctx.quadraticCurveTo(-17, y + 10, -10, y + 12); ctx.quadraticCurveTo(-5, y + 11, -4, y + 4); ctx.lineTo(-6, y - 6); ctx.closePath(); ctx.fill();
    }
    if (L.style === 'longwave') {
      ctx.beginPath(); ctx.moveTo(-14, y - 4); ctx.quadraticCurveTo(-20, y + 14, -14, y + 30); ctx.quadraticCurveTo(-6, y + 34, 2, y + 26);
      ctx.quadraticCurveTo(4, y + 14, 6, y + 4); ctx.lineTo(-2, y - 8); ctx.closePath(); ctx.fill();
      for (let i = 0; i < 4; i++) circ(-15 + i * 1.5, y + 6 + i * 7, 5, h);
    }
    if (L.style === 'curly') for (const [cx, cy, r] of [[-12, -8, 7], [-14, 2, 7], [-11, 10, 6], [-4, -14, 7], [5, -14, 6], [11, -9, 5], [-15, -3, 6], [-8, 14, 5]]) circ(cx, y + cy, r, h);
    if (L.style === 'afro') { ctx.beginPath(); ctx.arc(-1, y - 3, 17, 0, Math.PI * 2); ctx.fill(); }
    if (L.style === 'pony') { ctx.beginPath(); ctx.moveTo(-11, y - 6); ctx.quadraticCurveTo(-24, y + 2, -18, y + 18); ctx.quadraticCurveTo(-14, y + 8, -8, y - 2); ctx.closePath(); ctx.fill(); }
  }
  function hairFront(L) {
    const h = L.hair, y = HEAD_Y;
    ctx.fillStyle = h;
    if (L.style !== 'afro') {
      ctx.beginPath(); ctx.arc(0, y, HR + 1.3, Math.PI * 0.84, Math.PI * 2.0);
      if (L.style === 'sidepart') { ctx.quadraticCurveTo(10, y - 7, 4, y - 8); ctx.quadraticCurveTo(-2, y - 7, -8, y - 1); ctx.quadraticCurveTo(-11, y + 2, -12, y + 4); }
      else if (L.style === 'short' || L.style === 'boy') { ctx.quadraticCurveTo(9, y - 8, 6, y - 7); ctx.quadraticCurveTo(1, y - 10, -4, y - 5); ctx.quadraticCurveTo(-8, y - 2, -12, y + 3); }
      else { ctx.quadraticCurveTo(11, y - 4, 7, y - 4); ctx.quadraticCurveTo(1, y - 9, -5, y - 3); ctx.quadraticCurveTo(-9, y, -12, y + 5); }
      ctx.closePath(); ctx.fill();
    }
    if (L.style === 'sidepart') { ctx.beginPath(); ctx.moveTo(-6, y - 12); ctx.quadraticCurveTo(8, y - 20, 15, y - 7); ctx.quadraticCurveTo(7, y - 11, 0, y - 9); ctx.closePath(); ctx.fill(); }
    if (L.style === 'short') { ctx.beginPath(); ctx.moveTo(-4, y - 13); ctx.quadraticCurveTo(6, y - 19, 13, y - 9); ctx.quadraticCurveTo(5, y - 11, -2, y - 8); ctx.closePath(); ctx.fill(); }
    if (L.style === 'boy') { ctx.beginPath(); ctx.moveTo(2, y - 14); ctx.lineTo(8, y - 17); ctx.lineTo(7, y - 11); ctx.closePath(); ctx.fill(); }
    if (L.style === 'bob') { ctx.beginPath(); ctx.moveTo(-2, y - 13); ctx.quadraticCurveTo(12, y - 14, 15, y - 2); ctx.quadraticCurveTo(9, y - 8, 1, y - 7); ctx.closePath(); ctx.fill(); }
    if (L.style === 'longwave') { ctx.beginPath(); ctx.moveTo(-4, y - 13); ctx.quadraticCurveTo(13, y - 13, 15, y + 2); ctx.quadraticCurveTo(9, y - 7, 2, y - 7); ctx.closePath(); ctx.fill(); }
    if (L.style === 'curly') for (const [cx, cy, r] of [[-6, -13, 5], [1, -15, 5], [7, -12, 4.5], [-11, -6, 4.5]]) circ(cx, y + cy, r, h);
    if (L.style === 'afro') for (const [cx, cy, r] of [[-8, -14, 7], [1, -17, 7], [9, -12, 6], [-14, -5, 6]]) circ(cx, y + cy, r, h);
    if (L.style === 'pony') { circ(-10, y - 9, 4, L.clip); }
    // soft shine on the hair
    ctx.globalAlpha *= 0.28; ctx.strokeStyle = '#ffffff'; ctx.lineWidth = 2.2;
    ctx.beginPath(); ctx.arc(-1, y - 2, HR - 1, Math.PI * 1.2, Math.PI * 1.5); ctx.stroke(); ctx.globalAlpha /= 0.28;
    if (L.clip && L.style === 'curly') { ctx.fillStyle = L.clip; rr(3, y - 18, 6, 3, 1.5); ctx.fill(); }
  }
  function face(L, b, t) {
    const y = HEAD_Y;
    const blinking = ((t + b.blink) % 4.2) < 0.14;
    // eyes: big whites, coloured iris, pupil, two highlights (3/4 view: the far eye is smaller)
    for (const [ex, sc] of [[1.8, 0.86], [9.6, 1]]) {
      const rx = 3.3 * sc, ry = 4 * sc;
      if (blinking) {
        ctx.strokeStyle = '#3a2418'; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.arc(ex, y + 0.5, rx, 0.15 * Math.PI, 0.85 * Math.PI); ctx.stroke();
      } else {
        ctx.beginPath(); ctx.ellipse(ex, y + 0.5, rx, ry, 0, 0, 7); ctx.fillStyle = '#ffffff'; ctx.fill();
        circ(ex + 0.9 * sc, y + 0.9, 2.5 * sc, L.eye);
        circ(ex + 1.1 * sc, y + 1.1, 1.3 * sc, '#120a06');
        circ(ex + 0.1, y - 0.6, 0.95 * sc, '#ffffff'); circ(ex + 2 * sc, y + 2.1, 0.45 * sc, '#ffffff');
        ctx.strokeStyle = '#2a1a12'; ctx.lineWidth = L.lashes ? 1.6 : 1.1;
        ctx.beginPath(); ctx.ellipse(ex, y + 0.5, rx, ry, 0, 1.12 * Math.PI, 1.92 * Math.PI); ctx.stroke();
        if (L.lashes) { ctx.beginPath(); ctx.moveTo(ex + rx * .85, y - 1.6); ctx.lineTo(ex + rx + 1.4, y - 3); ctx.stroke(); }
      }
      // eyebrows
      ctx.strokeStyle = shade(L.hair, 0.05); ctx.lineWidth = L.brows === 'thick' ? 2.2 : 1.5; ctx.lineCap = 'round';
      const lift = b.bubble && b.bubble.until > t ? -1 : 0;
      ctx.beginPath(); ctx.moveTo(ex - rx, y - ry - 1.5 + lift); ctx.quadraticCurveTo(ex, y - ry - 3.5 + lift, ex + rx, y - ry - 2 + lift); ctx.stroke(); ctx.lineCap = 'butt';
    }
    // cheeks, nose, mouth
    ctx.globalAlpha *= 0.4; circ(-1.5, y + 7, 2.8, '#ff7d8c'); circ(12, y + 7, 2.4, '#ff7d8c'); ctx.globalAlpha /= 0.4;
    ctx.beginPath(); ctx.moveTo(12.4, y + 1.5); ctx.quadraticCurveTo(15, y + 5.2, 12.2, y + 5.6); ctx.strokeStyle = shade(L.skin, -0.28); ctx.lineWidth = 1.2; ctx.stroke();
    const talking = b.bubble && b.bubble.until > t && Math.floor(t * 8) % 2;
    if (talking) {
      ctx.beginPath(); ctx.ellipse(6.8, y + 9, 2.8, 2.3, 0, 0, 7); ctx.fillStyle = '#6b1f2a'; ctx.fill();
      ctx.fillStyle = '#ffffff'; ctx.fillRect(4.8, y + 7, 4, 1.1);
    } else {
      ctx.beginPath(); ctx.moveTo(3.6, y + 8); ctx.quadraticCurveTo(7, y + 11.6, 10.4, y + 7.8);
      ctx.strokeStyle = L.lips ? '#c0485a' : '#7a3328'; ctx.lineWidth = L.lips ? 1.8 : 1.4; ctx.stroke();
    }
    if (L.glasses) {
      ctx.strokeStyle = '#1e1e2a'; ctx.lineWidth = 1.4;
      ctx.beginPath(); rr(-2.4, y - 3.6, 8.2, 8, 2.5); ctx.stroke(); ctx.beginPath(); rr(5.6, y - 3.8, 8.6, 8.4, 2.5); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(-2.4, y - 1); ctx.lineTo(-9, y - 1); ctx.stroke();
    }
  }
  function torso(L, b, pose) {
    const top = -30, bot = -12;
    ctx.fillStyle = grad(top, bot, L.shirt); rr(-9.5, top, 19, bot - top + 2, 7); ctx.fill();
    if (L.top === 'floral') {
      for (const [fx, fy] of [[-5, -26], [3, -24], [-1, -18], [6, -16], [-7, -15]]) {
        for (let k = 0; k < 5; k++) circ(fx + Math.cos(k * 1.256) * 1.5, fy + Math.sin(k * 1.256) * 1.5, 1.2, L.flower);
        circ(fx, fy, 0.9, '#ffd23d');
      }
      ctx.fillStyle = shade(L.shirt, -0.2); ctx.beginPath(); ctx.moveTo(-3, top); ctx.lineTo(1.5, top + 6); ctx.lineTo(6, top); ctx.closePath(); ctx.fill();
    }
    if (L.top === 'blazer') {
      ctx.fillStyle = L.inner; ctx.beginPath(); ctx.moveTo(-1, top); ctx.lineTo(6, top); ctx.lineTo(4, bot); ctx.lineTo(1, bot); ctx.closePath(); ctx.fill();
      ctx.strokeStyle = shade(L.shirt, -0.35); ctx.lineWidth = 1.2; ctx.beginPath(); ctx.moveTo(-1, top); ctx.lineTo(2.5, top + 9); ctx.lineTo(6, top); ctx.stroke();
    }
    if (L.top === 'polo') {
      ctx.fillStyle = '#ffffff'; ctx.beginPath(); ctx.moveTo(-3, top); ctx.lineTo(2, top + 4); ctx.lineTo(7, top); ctx.lineTo(7, top + 2); ctx.lineTo(2, top + 6); ctx.lineTo(-3, top + 2); ctx.closePath(); ctx.fill();
      circ(2, top + 8, 0.8, '#ffffff'); circ(2, top + 11, 0.8, '#ffffff');
    }
    if (L.top === 'tee' && L.stripe) { ctx.fillStyle = L.stripe; for (let i = 0; i < 3; i++) ctx.fillRect(-9, top + 6 + i * 4.5, 18, 1.8); }
    if (L.earrings) circ(-9.5, HEAD_Y + 7, 1.4, '#ffd23d');
  }
  function legs(L, b, t, pose) {
    const sw = pose === 'walk' ? Math.sin(t * 14 + b.phase) : pose === 'dance' ? Math.sin(t * 7 + b.phase) * 0.6 : 0;
    if (pose === 'sit' || pose === 'lounge') {
      ctx.fillStyle = L.pants; rr(-6, -14, 17, 6.5, 3); ctx.fill();
      if (pose === 'lounge') { ctx.fillStyle = L.long ? L.pants : L.skin; rr(9, -14, 10, 5, 2.5); ctx.fill(); rr(18, -14, 4, 5, 2); ctx.fillStyle = L.shoe; ctx.fill(); return; }
      ctx.fillStyle = L.long ? L.pants : L.skin; rr(8, -12, 4.6, 10, 2.2); ctx.fill();
      ctx.beginPath(); ctx.ellipse(11.5, -2, 4, 2.5, 0, 0, 7); ctx.fillStyle = L.shoe; ctx.fill();
      return;
    }
    for (const [lx, ph] of [[-5, sw], [1.2, -sw]]) {
      const lift = Math.max(0, ph) * -2.5;
      ctx.fillStyle = L.pants; rr(lx, -14 + lift, 4.8, L.long ? 13 : 7, 2.2); ctx.fill();
      if (!L.long) { ctx.fillStyle = L.skin; rr(lx + 0.7, -8 + lift, 3.4, 7, 1.6); ctx.fill(); }
      ctx.beginPath(); ctx.ellipse(lx + 3 + ph * 1.5, -1 + lift, 3.8, 2.4, 0, 0, 7); ctx.fillStyle = L.shoe; ctx.fill();
    }
  }
  function arms(L, b, t, pose, front) {
    const sleeve = shade(L.shirt, front ? -0.02 : -0.2);
    const [px, py] = front ? [6.5, -27] : [-7, -27];
    let ang;
    if (pose === 'walk') ang = (front ? 1 : -1) * Math.sin(t * 14 + b.phase) * 0.55;
    else if (pose === 'sit') ang = front ? -1.25 + Math.sin(t * 22 + b.phase) * 0.06 : -0.6;
    else if (pose === 'dance') ang = Math.PI + (front ? 1 : -1) * (0.35 + Math.sin(t * 7 + b.phase + (front ? 0 : 1.6)) * 0.5);
    else if (pose === 'volley') ang = b._hit ? Math.PI - 0.15 : front ? -0.7 : -0.5;
    else if (pose === 'eat') ang = front ? -1.9 + (Math.sin(t * 3 + b.phase) + 1) * 0.35 : 0.1;
    else if (pose === 'lounge') ang = front ? -2.6 : -2.4;
    else if (pose === 'wave') ang = front ? Math.PI - 0.4 + Math.sin(t * 10) * 0.35 : 0.1;
    else ang = front ? 0.08 : -0.08;
    const longSleeve = L.top === 'blazer';
    limb(px, py, ang, 13, 5.2, longSleeve ? sleeve : L.skin, 2.7, L.skin);
    if (!longSleeve) limb(px, py, ang, 6.5, 6, sleeve);
  }
  function headset(L) {
    const y = HEAD_Y;
    ctx.strokeStyle = '#2a2a38'; ctx.lineWidth = 2.2; ctx.beginPath(); ctx.arc(-1, y, HR + 1.8, Math.PI * 1.05, Math.PI * 1.75); ctx.stroke();
    rr(-12, y - 1, 5, 7, 2); ctx.fillStyle = '#2a2a38'; ctx.fill();
    ctx.lineWidth = 1.3; ctx.beginPath(); ctx.moveTo(-9, y + 5); ctx.quadraticCurveTo(-3, y + 13, 4, y + 11); ctx.stroke(); circ(4.5, y + 11, 1.6, '#2a2a38');
  }
  function person(L, b, t, pose) {
    legs(L, b, t, pose);
    arms(L, b, t, pose, false);
    torso(L, b, pose);
    // neck + head
    ctx.fillStyle = shade(L.skin, -0.12); rr(-3, -34, 6, 6, 2); ctx.fill();
    const breathe = pose === 'walk' ? 0 : Math.sin(t * 2.4 + b.phase) * 0.6;
    ctx.save(); ctx.translate(0, breathe);
    hairBack(L);
    circ(-9.5, HEAD_Y + 2, 3.3, shade(L.skin, -0.06));
    const g = ctx.createRadialGradient(4, HEAD_Y - 5, 2, 1, HEAD_Y, HR + 3);
    g.addColorStop(0, shade(L.skin, 0.14)); g.addColorStop(1, shade(L.skin, -0.1));
    ctx.beginPath(); ctx.ellipse(1, HEAD_Y, HR, HR * 1.04, 0, 0, 7); ctx.fillStyle = g; ctx.fill();
    face(L, b, t);
    hairFront(L);
    if (L.headset) headset(L);
    ctx.restore();
    arms(L, b, t, pose, true);
  }
  function poseOf(b) {
    if (b.path.length) return 'walk';
    const s = desks[b.id] && desks[b.id].seat;
    if (b.state === 'working' || (s && Math.hypot(b.x - s.x, b.y - s.y) < 0.05)) return 'sit';
    if (b.activity && b.activity === b.spot && !b.task) return { eat: 'eat', play: 'volley', dance: 'dance', relax: 'lounge' }[b.actKind] || 'stand';
    if (b.bubble && b.bubble.until > now() && b.waveUntil > now()) return 'wave';
    return 'stand';
  }

  function drawBot(b, t) {
    const L = LOOKS[b.id];
    const g = iso(b.x, b.y, 0);
    const dim = filter !== 'all' && b.team !== filter && b.team !== 'manager';
    ctx.globalAlpha = dim ? 0.3 : 1;
    const pose = poseOf(b);
    let lift = 0;
    if (pose === 'dance') lift = Math.abs(Math.sin(t * 7 + b.phase)) * 4;
    if (pose === 'volley') { lift = b._hit ? 7 : 0; }
    const sh = Math.max(0.6, 1 - (b.z + lift) / 40);
    ctx.beginPath(); ctx.ellipse(g.x, g.y, 12 * sh * L.scale, 5.5 * sh * L.scale, 0, 0, 7); ctx.fillStyle = 'rgba(60,40,10,.25)'; ctx.fill();
    if (b === selected || b === hoverBot) {
      ctx.beginPath(); ctx.ellipse(g.x, g.y, 17, 8, 0, 0, 7); ctx.strokeStyle = b.color; ctx.lineWidth = 2.5;
      ctx.shadowColor = b.color; ctx.shadowBlur = 12; ctx.stroke(); ctx.shadowBlur = 0;
    }
    ctx.save();
    ctx.translate(g.x, g.y - b.z - lift);
    ctx.scale((b.face || 1) * L.scale, L.scale);
    if (pose === 'lounge') { ctx.rotate(-0.55); ctx.translate(-4, 6); }
    person(L, b, t, pose);
    ctx.restore();
    if (b.state === 'working' && Math.floor(t * 3 + b.phase) % 3 === 0) {
      const p = iso(b.x + .3, b.y - .3, b.z + 62); ctx.fillStyle = '#fff'; ctx.font = '10px sans-serif'; ctx.fillText('✦', p.x, p.y);
    }
    ctx.globalAlpha = 1;
  }

  function drawActivity(b, t) {
    if (!b.activity || b.activity !== b.spot || b.path.length || b.task) return;
    const L = LOOKS[b.id], f = b.face || 1, p = iso(b.x, b.y, b.z + 30 * L.scale);
    ctx.font = '14px "Apple Color Emoji","Segoe UI Emoji","Noto Color Emoji",sans-serif';
    ctx.textAlign = 'center';
    if (b.actKind === 'eat') {
      const bite = (Math.sin(t * 3 + b.phase) + 1) / 2;
      ctx.fillText(b.food, p.x + f * (15 - bite * 5) * L.scale, p.y - 2 - bite * 10);
      if (bite > 0.95) { const s = iso(b.x, b.y, b.z + 58 * L.scale); ctx.fillStyle = 'rgba(255,255,255,.7)'; ctx.font = '9px sans-serif'; ctx.fillText('~', s.x + f * 14, s.y); }
    } else if (b.actKind === 'dance') {
      for (let i = 0; i < 2; i++) {
        const u = ((t * 0.7 + i * 0.5 + b.phase) % 1);
        ctx.globalAlpha = 1 - u; ctx.fillStyle = ['#ff4fa3', '#2ee6c9'][i]; ctx.font = 'bold 13px sans-serif';
        ctx.fillText(i ? '♫' : '♪', p.x + (i ? 14 : -14) + Math.sin(u * 6) * 3, p.y - 30 - u * 22);
      }
      ctx.globalAlpha = 1;
    } else if (b.actKind === 'relax') {
      ctx.fillText(Math.floor(t / 6 + b.phase) % 2 ? '🍹' : '😎', p.x + f * 16, p.y - 10 + Math.sin(t * 1.5) * 2);
    }
    ctx.textAlign = 'left';
  }

  function drawOverlay(b, t) {
    drawActivity(b, t);
    const top = iso(b.x, b.y, b.z + 72 * LOOKS[b.id].scale);
    if (b.bubble && b.bubble.until > t) drawBubble(top.x, top.y - 6, b.bubble.text);
    else b.bubble = null;
    if (b === hoverBot || b === selected) {
      ctx.font = 'bold 11px ui-sans-serif, system-ui, sans-serif';
      const tw = ctx.measureText(b.label).width + 12, p = iso(b.x, b.y, 0);
      roundRect(p.x - tw / 2, p.y + 10, tw, 17, 8, 'rgba(15,12,30,.85)');
      ctx.fillStyle = b.color; ctx.textAlign = 'center'; ctx.fillText(b.label, p.x, p.y + 22); ctx.textAlign = 'left';
    }
    if (b.task && b.state === 'working') {
      const p = iso(b.x, b.y, b.z + 66 * LOOKS[b.id].scale);
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
    const worldW = (W + H + 3) * TW / 2, worldH = (W + H) * TH / 2 + 190;
    cam.zoom = Math.min(r.width / worldW, r.height / worldH) * 0.96;
    cam.x = r.width / 2 - ((W - H) * TW / 4) * cam.zoom;
    cam.y = (r.height - worldH * cam.zoom) / 2 + 175 * cam.zoom;
  }
  const toWorld = (sx, sy) => ({ x: (sx - cam.x) / cam.zoom, y: (sy - cam.y) / cam.zoom });

  let last = now();
  function frame() {
    const t = now(), dt = Math.min(0.05, t - last); last = t; T.t = t;
    for (const b of bots) updateBot(b, dt, t);
    demoTick(dt);

    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = '#5ec2f2'; ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.setTransform(cam.zoom * dpr, 0, 0, cam.zoom * dpr, cam.x * dpr, cam.y * dpr);

    drawGround(t);
    for (const f of F) if (f.flat) drawFurniture(f);
    drawHutWalls();
    const ball = volleyBall(t);
    for (const b of bots) b._hit = !!(ball && ball.hitter === b);
    const items = [];
    for (const f of F) if (!f.flat) items.push({ depth: f.x + f.w / 2 + f.y + f.d / 2, draw: () => drawFurniture(f) });
    for (const r of railings) items.push({ depth: r.type === 'railH' ? r.x + .5 + r.y : r.x + r.y + .5, draw: () => drawFurniture(Object.assign({ w: 1, d: 1 }, r)) });
    for (const b of bots) items.push({ depth: b.x + b.y + 0.01, draw: () => drawBot(b, t) });
    if (ball) items.push({ depth: ball.x + ball.y + 0.02, draw: () => drawBall(ball) });
    items.sort((a, b) => a.depth - b.depth).forEach((i) => i.draw());
    drawRoof();
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
      ctx.translate(46, 150); ctx.scale(1.6, 1.6);
      const fake = { ...b, path: [], state: 'idle', bubble: null, blink: 1, phase: 0 };
      ctx.translate(-2, 4); ctx.scale(1.25, 1.25);
      person(LOOKS[b.id], fake, 0, 'stand');
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
    li.querySelector('b').textContent = b.label; li.querySelector('.txt').textContent = text;
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
        <div><h2>${esc(b.name)}</h2><div class="role"><b>${esc(b.title)}</b><br>${esc(b.role)}</div></div>
        <button class="close" data-act="close">×</button></div>
      <span class="pill ${status}">${label}</span>
      <h4>Current task</h4>
      ${b.task ? `<div class="task">${esc(b.task.text)}<div class="bar"><i style="width:${pct}%"></i></div></div>` : '<div class="muted">Nothing to do, enjoying the beach 🏖️</div>'}
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
      else { b.state = 'break'; b.breakUntil = now() + 25; b.idleTimer = 0; feed(b, 'on a short break ☕'); say(b, 'Yay, break time! 🎉'); }
    }
    panelSig = '';
  });
  function select(b) {
    selected = b; panelSig = '';
    panel.classList.toggle('hidden', !b);
    if (b) { Sound.play('blip'); renderPanel(); if (!b.bubble) { say(b, rand(['Hi! 👋', 'Yes, boss?', 'How can I help?']), 1.6); b.waveUntil = now() + 1.6; } }
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
    feed(botById.mgr, `Not sure where ${name} goes. PDF/DOC or video/image only, please`);
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
      feed(botById.mgr, `We're LIVE! PDF/DOCX → compliance ⚖️, video/image → content 🎬` +
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
    Sound.play('upload');
    const fd = new FormData(); fd.append('files', file);
    feed(botById.mgr, `uploading ${file.name}… (${(file.size / 1048576).toFixed(1)} MB)`);
    try {
      const r = await (await fetch('/api/upload', { method: 'POST', body: fd })).json();
      r.skipped.forEach((n) => feed(botById.mgr, `Skipped ${n} (file type or size)`));
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

  // ───────────────────────── Affiliate Studio form ─────────────────────────
  const affModal = document.getElementById('affModal'), affForm = document.getElementById('affForm'), affMsg = document.getElementById('affMsg');
  document.getElementById('affBtn').onclick = () => { affModal.classList.remove('hidden'); affMsg.textContent = live ? '' :
    'Kailangang naka-run ang server (start-mac.command / start-windows.bat) para gumawa ng totoong videos.'; };
  document.getElementById('affClose').onclick = () => affModal.classList.add('hidden');
  affModal.addEventListener('click', (e) => { if (e.target === affModal) affModal.classList.add('hidden'); });
  affForm.onsubmit = async (e) => {
    e.preventDefault();
    if (!live) { affMsg.textContent = 'Offline: buksan muna ang server.'; return; }
    const btn = affForm.querySelector('.primary'); btn.disabled = true; affMsg.textContent = 'Sending…';
    try {
      const r = await fetch('/api/affiliate', { method: 'POST', body: new FormData(affForm) });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || 'error');
      Sound.play('upload');
      feed(botById.mgr, 'Affiliate job started! Watch the content team go 🎬');
      affForm.reset(); affModal.classList.add('hidden'); affMsg.textContent = '';
    } catch (err) { affMsg.textContent = 'Hindi nagsimula: ' + err.message; }
    btn.disabled = false;
  };

  // ───────────────────────── Settings (Google Veo) ─────────────────────────
  const setModal = document.getElementById('setModal'), setForm = document.getElementById('setForm'), setMsg = document.getElementById('setMsg');
  document.getElementById('setBtn').onclick = async () => {
    setModal.classList.remove('hidden');
    if (!live) { setMsg.textContent = 'Buksan muna ang server para ma-save ang settings.'; return; }
    const st = await (await fetch('/api/settings')).json();
    for (const [k, val] of Object.entries(st)) if (setForm.elements[k]) setForm.elements[k].value = val;
    setMsg.textContent = st.configured ? '✅ May naka-set na key.' : 'Wala pang key.';
  };
  document.getElementById('setClose').onclick = () => setModal.classList.add('hidden');
  const formJSON = () => Object.fromEntries(new FormData(setForm).entries());
  setForm.onsubmit = async (e) => {
    e.preventDefault();
    const r = await fetch('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(formJSON()) });
    setMsg.textContent = r.ok ? '💾 Saved!' : 'Hindi na-save.';
  };
  document.getElementById('setTest').onclick = async () => {
    await fetch('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(formJSON()) });
    setMsg.textContent = 'Testing…';
    const j = await (await fetch('/api/settings/test', { method: 'POST' })).json();
    if (!j.ok) { setMsg.textContent = '❌ ' + j.error; return; }
    const fill = (id, arr) => { document.getElementById(id).innerHTML = arr.map((m) => `<option value="${m}">`).join(''); };
    fill('imgModels', j.image_models); fill('vidModels', j.video_models);
    setForm.elements.backend.value = j.backend;
    if (j.video_models.length && !j.video_models.includes(setForm.elements.video_model.value)) setForm.elements.video_model.value = j.video_models[0];
    if (j.image_models.length && !j.image_models.includes(setForm.elements.image_model.value)) setForm.elements.image_model.value = j.image_models[0];
    const lines = Object.entries(j.results || {}).map(([b, r]) => r.ok
      ? `${b === 'gemini' ? 'Gemini API' : 'Vertex AI'}: video = ${r.video_models.join(', ') || 'wala'}; image = ${r.image_models.slice(0, 4).join(', ') || 'wala'}`
      : `${b === 'gemini' ? 'Gemini API' : 'Vertex AI'}: ❌ ${r.error}`);
    const all = Object.entries(j.results || {}).filter(([, r]) => r.ok).map(([b, r]) => `${b}: ${r.all_models.join(', ')}`).join('\n\n');
    setMsg.innerHTML = (j.video_models.length ? '✅ Handa ang video! Napili: <b>' + j.backend + '</b>. Pindutin ang 💾 Save.' : '⚠️ Gumagana ang key pero walang video model.')
      + '<br>' + lines.map((l) => l.replace(/[<>&]/g, '')).join('<br>')
      + '<details><summary>Lahat ng models (para kay Claude)</summary><pre style="white-space:pre-wrap;font-size:11px">' + all.replace(/[<>&]/g, '') + '</pre></details>';
  };

  // ───────────────────────── Phone access ─────────────────────────
  const phoneInfo = document.getElementById('phoneInfo');
  async function paintPhone() {
    if (!live) return;
    const st = await (await fetch('/api/phone')).json();
    phoneInfo.innerHTML = st.enabled
      ? `✅ Naka-on. Sa phone, i-scan ang QR o i-type: <br><b>${st.url}</b><img src="/api/phone/qr.png?t=${Date.now()}" alt="QR">` +
        'Kung may tanong ang Mac na "Allow incoming connections", pindutin ang Allow.'
      : (st.has_pin ? 'Naka-off.' : 'Wala pang PIN.');
  }
  async function setPhone(enabled) {
    const pin = document.getElementById('phonePin').value.trim();
    const r = await fetch('/api/phone', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled, pin }) });
    const j = await r.json().catch(() => ({ ok: false, error: 'Sa Mac lang puwedeng baguhin ito.' }));
    if (!j.ok) { phoneInfo.textContent = '❌ ' + (j.error || j.detail || 'error'); return; }
    document.getElementById('phonePin').value = '';
    paintPhone();
  }
  document.getElementById('phoneOn').onclick = () => setPhone(true);
  document.getElementById('phoneOff').onclick = () => setPhone(false);
  document.getElementById('phoneBox').addEventListener('toggle', paintPhone);

  // ───────────────────────── KYC / KYB / URL ─────────────────────────
  const kycModal = document.getElementById('kycModal'), kycForm = document.getElementById('kycForm'), kycMsg = document.getElementById('kycMsg');
  function kycTab(k) {
    kycForm.elements.kind.value = k;
    document.querySelectorAll('.ktabs button').forEach((b) => b.classList.toggle('on', b.dataset.k === k));
    kycForm.querySelectorAll('label[class]').forEach((l) => { l.style.display = l.classList.contains('k-' + k) ? '' : 'none'; });
    kycForm.querySelector('.lbl-name').textContent = { person: 'Buong pangalan', business: 'Pangalan ng negosyo (registered)', url: 'Pangalan ng negosyo (opsyonal)' }[k]
      + (k === 'business' ? ' (opsyonal kung may Drive link)' : '');
  }
  document.querySelectorAll('.ktabs button').forEach((b) => (b.onclick = () => kycTab(b.dataset.k)));
  document.getElementById('kycBtn').onclick = () => { kycModal.classList.remove('hidden'); kycTab(kycForm.elements.kind.value); kycMsg.textContent = live ? '' : 'Buksan muna ang server.'; };
  document.getElementById('kycClose').onclick = () => kycModal.classList.add('hidden');
  kycModal.addEventListener('click', (e) => { if (e.target === kycModal) kycModal.classList.add('hidden'); });
  kycForm.onsubmit = async (e) => {
    e.preventDefault();
    if (!live) { kycMsg.textContent = 'Offline: buksan muna ang server.'; return; }
    const btn = kycForm.querySelector('.primary'); btn.disabled = true; kycMsg.textContent = 'Sending…';
    try {
      const j = await (await fetch('/api/kyc', { method: 'POST', body: new FormData(kycForm) })).json();
      if (!j.ok) throw new Error(j.error || j.detail || 'error');
      Sound.play('upload'); feed(botById.mgr, 'Compliance check started 🛡️ (first run downloads the sanctions lists, about 1-2 minutes)');
      kycForm.reset(); kycModal.classList.add('hidden'); kycMsg.textContent = '';
    } catch (err) { kycMsg.textContent = 'Hindi nagsimula: ' + err.message; }
    btn.disabled = false;
  };
  document.getElementById('aiTest').onclick = async () => {
    const info = document.getElementById('aiInfo');
    await fetch('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(formJSON()) });
    info.textContent = 'Testing…';
    const j = await (await fetch('/api/ai/test', { method: 'POST' })).json();
    info.textContent = (j.ok ? '✅ ' : '❌ ') + j.message + (j.models && j.models.length ? ' · ' + j.models.slice(0, 8).join(', ') : '');
    if (j.models) document.getElementById('ollamaModels').innerHTML = j.models.map((m) => `<option value="${m}">`).join('');
  };
  document.getElementById('driveDetect').onclick = async () => {
    const j = await (await fetch('/api/drive/detect')).json();
    const list = document.getElementById('driveList');
    if (!j.folders.length) { list.textContent = 'Walang nakitang Google Drive for desktop. I-install sa drive.google.com/drive/download at mag-login.'; return; }
    list.innerHTML = 'Piliin ang folder (tapos 💾 Save):';
    j.folders.forEach((f) => { const b = document.createElement('button'); b.type = 'button'; b.textContent = f.split('/').slice(-2).join(' / ');
      b.title = f; b.onclick = () => { setForm.elements.drive_folder.value = f; list.textContent = '✔ ' + f + ' (pindutin ang 💾 Save)'; }; list.append(b); });
  };

  const muteBtn = document.getElementById('muteBtn');
  const paintMute = () => { muteBtn.textContent = Sound.muted ? '🔇' : '🔊'; muteBtn.title = Sound.muted ? 'Sound off (click to turn on)' : 'Sound on (click to mute)'; };
  muteBtn.addEventListener('click', () => { Sound.toggle(); paintMute(); });
  const musicBtn = document.getElementById('musicBtn');
  const paintMusic = () => { musicBtn.classList.toggle('on', Sound.music); musicBtn.title = Sound.music ? 'Background music on' : 'Background music off'; };
  musicBtn.addEventListener('click', () => { Sound.toggleMusic(); paintMusic(); });
  paintMusic();
  paintMute();

  window.BotOffice = { sound: Sound, bots: botById, assign, startPipeline, applyEvent, setDemo: (v) => { demo = v; document.getElementById('demoToggle').checked = v; } };

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
