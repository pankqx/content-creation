// Wireframe globe with halftone dot bands and knocked-out lettering. Drawn on a 2D canvas.
// Built by K S Pankaj for Clipzer.
(function () {
  const RAD = Math.PI / 180;

  function makeMask(text, cols, rows) {
    // Lettering rendered once into a small bitmap; dots are skipped where the bitmap is ink.
    const c = document.createElement("canvas");
    c.width = cols; c.height = rows;
    const g = c.getContext("2d");
    g.fillStyle = "#000"; g.fillRect(0, 0, cols, rows);
    g.fillStyle = "#fff";
    g.font = `900 ${Math.floor(rows * 0.78)}px Archivo, "Arial Black", sans-serif`;
    g.textBaseline = "middle";
    let x = 0;
    const unit = g.measureText(text).width || cols;
    while (x < cols) { g.fillText(text, x, rows / 2 + 1); x += unit; }
    const data = g.getImageData(0, 0, cols, rows).data;
    const mask = new Uint8Array(cols * rows);
    for (let i = 0; i < mask.length; i++) mask[i] = data[i * 4] > 110 ? 1 : 0;
    return mask;
  }

  function Globe(canvas, opts) {
    this.c = canvas;
    this.g = canvas.getContext("2d");
    this.o = Object.assign({
      bands: [{ lat0: 6, lat1: 30, text: "CLIPZER  ✦  FIND THE MOMENT  ✦  " },
              { lat0: -26, lat1: -8, text: "CUT  ✦  CAPTION  ✦  POST  ✦  " }],
      lats: 8, mers: 16, step: 1.05, speed: 9, tilt: -16, line: "#ffffff", dot: "#ffffff", interactive: true,
    }, opts || {});
    this.lon = 0; this.tilt = this.o.tilt; this.vel = this.o.speed; this.drag = null; this.reveal = 0;
    this.masks = this.o.bands.map((b) => {
      const cols = Math.round(360 / this.o.step), rows = Math.max(4, Math.round((b.lat1 - b.lat0) / this.o.step));
      return { cols, rows, bits: makeMask(b.text, cols, rows) };
    });
    this.resize();
    if (this.o.interactive) this.bind();
    this.last = performance.now();
    this.still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const loop = (t) => { this.frame(t); this.raf = requestAnimationFrame(loop); };
    this.raf = requestAnimationFrame(loop);
  }

  Globe.prototype.resize = function () {
    const r = this.c.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.max(80, r.width || this.c.width), h = Math.max(80, r.height || this.c.height);
    this.c.width = Math.round(w * dpr); this.c.height = Math.round(h * dpr);
    this.w = w; this.h = h; this.dpr = dpr;
  };

  Globe.prototype.bind = function () {
    const down = (e) => { const p = e.touches ? e.touches[0] : e; this.drag = { x: p.clientX, y: p.clientY, lon: this.lon, tilt: this.tilt }; };
    const move = (e) => {
      if (!this.drag) return;
      const p = e.touches ? e.touches[0] : e;
      const dx = p.clientX - this.drag.x, dy = p.clientY - this.drag.y;
      this.vel = (this.drag.lon + dx * 0.5 - this.lon) * 30 || this.vel;
      this.lon = this.drag.lon + dx * 0.5;
      this.tilt = Math.max(-60, Math.min(60, this.drag.tilt - dy * 0.3));
    };
    const up = () => { this.drag = null; };
    this.c.addEventListener("pointerdown", (e) => { this.c.setPointerCapture(e.pointerId); down(e); });
    this.c.addEventListener("pointermove", move);
    this.c.addEventListener("pointerup", up);
    this.c.addEventListener("pointercancel", up);
    window.addEventListener("resize", () => this.resize());
  };

  Globe.prototype.frame = function (t) {
    const dt = Math.min(0.05, (t - this.last) / 1000); this.last = t;
    if (!this.drag && !this.still) {
      this.vel += (this.o.speed - this.vel) * Math.min(1, dt * 1.5);
      this.lon += this.vel * dt;
    }
    this.reveal = Math.min(1, this.reveal + dt * 0.9);
    const g = this.g, w = this.w, h = this.h, dpr = this.dpr;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    const R = Math.min(w, h) * 0.44, cx = w / 2, cy = h / 2;
    const ct = Math.cos(this.tilt * RAD), st = Math.sin(this.tilt * RAD);
    const ease = 1 - Math.pow(1 - this.reveal, 3);
    const lon0 = this.lon;

    const project = (lat, lon) => {
      const la = lat * RAD, lo = (lon + lon0) * RAD;
      const x = Math.cos(la) * Math.sin(lo);
      const y0 = Math.sin(la);
      const z0 = Math.cos(la) * Math.cos(lo);
      const y = y0 * ct - z0 * st;
      const z = y0 * st + z0 * ct;
      return [cx + x * R, cy - y * R, z];
    };

    // Dot bands, back side faint, lettering knocked out.
    this.o.bands.forEach((band, bi) => {
      const m = this.masks[bi];
      for (let r = 0; r < m.rows; r++) {
        const lat = band.lat1 - (r + 0.5) * ((band.lat1 - band.lat0) / m.rows);
        for (let col = 0; col < m.cols; col++) {
          if (col / m.cols > ease) continue;
          const lon = col * this.o.step;
          const p = project(lat, lon);
          const ink = m.bits[r * m.cols + col];
          if (p[2] < -0.05) continue;
          if (ink) continue;
          const s = 0.8 + p[2] * 0.9;
          g.fillStyle = this.o.dot;
          g.globalAlpha = 0.25 + p[2] * 0.75;
          g.fillRect(p[0] - s / 2, p[1] - s / 2, s, s);
        }
      }
    });

    // Wireframe: latitudes and meridians, front lines bright, back lines faint.
    g.lineWidth = 1;
    const seg = (pts) => {
      for (let i = 1; i < pts.length; i++) {
        const a = pts[i - 1], b = pts[i];
        const z = (a[2] + b[2]) / 2;
        g.globalAlpha = z > 0 ? 0.9 * ease : 0.12 * ease;
        g.beginPath(); g.moveTo(a[0], a[1]); g.lineTo(b[0], b[1]); g.strokeStyle = this.o.line; g.stroke();
      }
    };
    for (let i = 1; i < this.o.lats; i++) {
      const lat = -90 + (180 / this.o.lats) * i, pts = [];
      for (let lo = 0; lo <= 360; lo += 6) pts.push(project(lat, lo));
      seg(pts);
    }
    for (let i = 0; i < this.o.mers; i++) {
      const lo = (360 / this.o.mers) * i, pts = [];
      for (let la = -90; la <= 90; la += 6) pts.push(project(la, lo));
      seg(pts);
    }
    g.globalAlpha = ease;
    g.beginPath(); g.arc(cx, cy, R, 0, Math.PI * 2); g.strokeStyle = this.o.line; g.lineWidth = 1.4; g.stroke();
    g.globalAlpha = 1;
  };

  Globe.prototype.stop = function () { cancelAnimationFrame(this.raf); };
  window.Globe = Globe;
})();
