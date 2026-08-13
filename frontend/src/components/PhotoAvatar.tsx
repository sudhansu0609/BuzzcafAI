import React, { useEffect, useRef } from 'react';
import { FaceLandmarks } from '../types/agent';

export const DEFAULT_LANDMARKS: FaceLandmarks = {
  leftEye: { x: 0.37, y: 0.42 },
  rightEye: { x: 0.63, y: 0.42 },
  mouth: { x: 0.5, y: 0.70 },
  mouthWidth: 0.20,
};

export interface PhotoMotion {
  mouth?: number;   // jaw/lip movement multiplier (1 = default, 0 = frozen)
  head?: number;    // sway/parallax multiplier
  expr?: number;    // brows + viseme spread multiplier
}

interface PhotoAvatarProps {
  photoUrl: string;
  landmarks?: FaceLandmarks | null;
  /** Rendered width/height in px (square). */
  size?: number;
  /** Synthetic mouth movement when no live analyser signal is available. */
  talking?: boolean;
  /** Live audio analyser — drives real lip-sync when present. */
  analyser?: React.MutableRefObject<AnalyserNode | null>;
  /** Per-agent animation intensity (from the studio sliders). */
  motion?: PhotoMotion | null;
  style?: React.CSSProperties;
}

// ─────────────────────────────────────────────────────────────────────────────
// Photo-realistic talking avatar, take 2: a WebGL deformation mesh.
//
// The first version translated a rectangular "jaw strip" and painted a dark
// ellipse over the lips — which reads as a ventriloquist puppet. This version
// warps the photo through a ~1200-vertex mesh with smooth per-vertex weights:
//
//   • the mesh is SPLIT along the lip line, so the lips genuinely separate and
//     reveal a mouth interior (cavity + teeth + tongue) rendered behind them
//   • jaw displacement grows toward the chin tip and fades at the neck, like a
//     hinged jaw under skin — nothing slides as a rigid block
//   • blinks pull the actual upper-lid skin down over the eye (texture warp),
//     not a painted oval
//   • the head moves with parallax INSIDE the photo (face shifts more than the
//     background) instead of rotating the whole picture like a card
//   • mouth SHAPE follows the audio spectrum: bright/high-frequency sounds
//     spread the lips wide, dark/loud vowels round them open
//
// Everything is computed per-frame on ~1200 vertices in JS (trivial) and the
// GPU interpolates the warp seamlessly. No models, no network, 60fps.
// ─────────────────────────────────────────────────────────────────────────────

const COLS = 33;                    // grid columns (vertices per row)
const ROWS = 41;                    // base grid rows before the lip-line insert

const VS_TEX = `
attribute vec2 aPos;
attribute vec2 aUV;
uniform vec4 uMap;  // clip = pos * uMap.xy + uMap.zw
varying vec2 vUV;
void main() {
  vUV = aUV;
  gl_Position = vec4(aPos * uMap.xy + uMap.zw, 0.0, 1.0);
}`;
const FS_TEX = `
precision mediump float;
varying vec2 vUV;
uniform sampler2D uTex;
void main() { gl_FragColor = texture2D(uTex, vUV); }`;

const VS_FLAT = `
attribute vec2 aUnit;
uniform vec2 uCenter;
uniform vec2 uRadii;
uniform vec4 uMap;
void main() {
  vec2 p = uCenter + aUnit * uRadii;
  gl_Position = vec4(p * uMap.xy + uMap.zw, 0.0, 1.0);
}`;
const FS_FLAT = `
precision mediump float;
uniform vec4 uColor;
void main() { gl_FragColor = uColor; }`;

function compile(gl: WebGLRenderingContext, type: number, src: string): WebGLShader {
  const sh = gl.createShader(type)!;
  gl.shaderSource(sh, src);
  gl.compileShader(sh);
  if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
    throw new Error(gl.getShaderInfoLog(sh) || 'shader compile failed');
  }
  return sh;
}

function link(gl: WebGLRenderingContext, vs: string, fs: string): WebGLProgram {
  const p = gl.createProgram()!;
  gl.attachShader(p, compile(gl, gl.VERTEX_SHADER, vs));
  gl.attachShader(p, compile(gl, gl.FRAGMENT_SHADER, fs));
  gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) {
    throw new Error(gl.getProgramInfoLog(p) || 'program link failed');
  }
  return p;
}

const smoothstep = (a: number, b: number, x: number): number => {
  const t = Math.max(0, Math.min(1, (x - a) / (b - a)));
  return t * t * (3 - 2 * t);
};
const gauss = (x: number, sigma: number): number => Math.exp(-(x * x) / (2 * sigma * sigma));

interface Geometry {
  rest: Float32Array;      // vertex rest positions (normalized image coords)
  uv: Float32Array;
  indices: Uint16Array;
  nVerts: number;
  // Per-vertex displacement weights, precomputed from rest positions:
  wJaw: Float32Array;      // jaw-open downward pull (0 above the lip line)
  wUp: Float32Array;       // upper-lip upward pull
  wWide: Float32Array;     // signed horizontal spread (viseme "ee")
  wFace: Float32Array;     // head parallax (face >> background)
  wLid: Float32Array;      // blink: upper-lid skin pulled down
  wBrow: Float32Array;     // eyebrow micro-raise
  d: number;               // eye distance (face scale), normalized
  pivot: { x: number; y: number };  // neck pivot for the micro-rotation
}

export function buildGeometry(lm: FaceLandmarks, ar: number): Geometry {
  const ex = (lm.leftEye.x + lm.rightEye.x) / 2;
  const ey = (lm.leftEye.y + lm.rightEye.y) / 2;
  const d = Math.max(0.08, Math.hypot(lm.rightEye.x - lm.leftEye.x, (lm.rightEye.y - lm.leftEye.y) / ar));
  const Mx = lm.mouth.x, My = lm.mouth.y;
  const w = lm.mouthWidth;
  const faceCx = (ex + Mx) / 2, faceCy = (ey + My) / 2;
  const lipHalf = w * 0.55;        // mouth-corner half-span: lips split inside this

  // Row Y coordinates: uniform grid with one row snapped exactly onto the lip
  // line — that row is duplicated (up/down copies) inside the corner span so
  // the mesh can open along it.
  const ys: number[] = [];
  for (let r = 0; r < ROWS; r++) ys.push(r / (ROWS - 1));
  let lipRow = 0;
  for (let r = 1; r < ROWS; r++) if (Math.abs(ys[r] - My) < Math.abs(ys[lipRow] - My)) lipRow = r;
  ys[lipRow] = My;

  // Vertex table. For the lip row, columns within the corner span get TWO
  // vertices (idUp / idDown); everywhere else one shared vertex.
  const rest: number[] = [];
  const idUp: number[][] = [];   // [row][col] -> vertex id used by quads ABOVE
  const idDn: number[][] = [];   // [row][col] -> vertex id used by quads BELOW
  let n = 0;
  for (let r = 0; r < ROWS; r++) {
    idUp.push([]); idDn.push([]);
    for (let c = 0; c < COLS; c++) {
      const x = c / (COLS - 1);
      const split = r === lipRow && Math.abs(x - Mx) <= lipHalf;
      rest.push(x, ys[r]);
      idUp[r][c] = n;
      idDn[r][c] = n;
      n++;
      if (split) {
        rest.push(x, ys[r]);
        idDn[r][c] = n;      // lower-lip copy
        n++;
      }
    }
  }

  const indices: number[] = [];
  for (let r = 0; r < ROWS - 1; r++) {
    for (let c = 0; c < COLS - 1; c++) {
      // Quad between rows r and r+1: its TOP edge uses the "below" copies of
      // row r, its BOTTOM edge the "above" copies of row r+1.
      const a = idDn[r][c], b = idDn[r][c + 1];
      const cc = idUp[r + 1][c], dd = idUp[r + 1][c + 1];
      indices.push(a, cc, b, b, cc, dd);
    }
  }

  const nVerts = n;
  const restF = new Float32Array(rest);
  const uv = new Float32Array(restF);   // texture coords == rest positions
  const wJaw = new Float32Array(nVerts);
  const wUp = new Float32Array(nVerts);
  const wWide = new Float32Array(nVerts);
  const wFace = new Float32Array(nVerts);
  const wLid = new Float32Array(nVerts);
  const wBrow = new Float32Array(nVerts);

  // Which vertices sit on the lower-lip copy of the split row?
  const isLower = new Uint8Array(nVerts);
  for (let r = 0; r < ROWS; r++) {
    for (let c = 0; c < COLS; c++) {
      if (idDn[r][c] !== idUp[r][c]) isLower[idDn[r][c]] = 1;
    }
  }

  for (let i = 0; i < nVerts; i++) {
    const x = restF[i * 2], y = restF[i * 2 + 1];
    const lat = gauss(x - Mx, w * 0.85);              // lateral falloff around mouth

    // Jaw: starts right at the lip line (the lower-lip copy included), grows
    // toward the chin tip like a hinged jaw, fades out by the neck.
    const below = y > My + 1e-6 || isLower[i] === 1;
    if (below) {
      const hinge = 0.45 + 0.55 * smoothstep(My, My + d * 0.55, y);      // more at chin tip
      const neckFade = 1 - smoothstep(My + d * 0.95, My + d * 1.45, y);  // skin, not shirt
      wJaw[i] = lat * hinge * neckFade;
    }

    // Upper lip: narrow band just above the lip line lifts slightly.
    if (!below && y > My - d * 0.14) {
      wUp[i] = lat * smoothstep(My - d * 0.14, My, y);
    }

    // Viseme spread: signed horizontal pull near the mouth band.
    const fx = Math.max(-1, Math.min(1, (x - Mx) / (w * 0.6)));
    wWide[i] = fx * gauss(y - My, d * 0.28) * gauss(x - Mx, w * 1.2);

    // Head parallax: strong on the face, weak on the background — the head
    // moves inside the photo instead of the photo moving. Sigma tuned so the
    // photo corners get <30% of the face's motion (wider and the whole photo
    // sways as one, which is exactly the puppet-on-a-stick look).
    wFace[i] = 0.15 + 0.85 * gauss(Math.hypot((x - faceCx) / 1.15, (y - faceCy) / 1.55), d * 1.15);

    // Blink: skin above each eye slides down to cover it.
    const eyeH = d * 0.30;
    for (const eye of [lm.leftEye, lm.rightEye]) {
      const gx = gauss(x - eye.x, d * 0.36);
      if (y < eye.y + eyeH * 0.5 && y > eye.y - eyeH * 2.2) {
        const cover = Math.max(0, Math.min(1, (eye.y + eyeH * 0.45 - y) / (eyeH * 1.5)));
        const band = smoothstep(eye.y - eyeH * 2.2, eye.y - eyeH * 0.9, y);
        wLid[i] = Math.max(wLid[i], gx * cover * band);
      }
    }

    // Brows: subtle lift with speech energy.
    wBrow[i] = gauss(y - (ey - d * 0.5), d * 0.28) * gauss(x - ex, d * 1.1);
  }

  return {
    rest: restF, uv, indices: new Uint16Array(indices), nVerts,
    wJaw, wUp, wWide, wFace, wLid, wBrow, d,
    pivot: { x: faceCx, y: My + d * 1.4 },
  };
}

const PhotoAvatar: React.FC<PhotoAvatarProps> = ({ photoUrl, landmarks, size = 120, talking = false, analyser, motion, style }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const talkingRef = useRef(talking);
  talkingRef.current = talking;
  // Ref, not effect dep: slider changes tune the live loop without rebuilding
  // the GL state.
  const motionRef = useRef<PhotoMotion | null | undefined>(motion);
  motionRef.current = motion;
  const lm: FaceLandmarks = { ...DEFAULT_LANDMARKS, ...(landmarks || {}) };
  const lmKey = JSON.stringify(lm);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = size * dpr;
    canvas.height = size * dpr;

    const gl = canvas.getContext('webgl', { premultipliedAlpha: false });
    if (!gl) return;

    let raf = 0;
    let disposed = false;
    let geo: Geometry | null = null;
    let img: HTMLImageElement | null = null;

    const texProg = link(gl, VS_TEX, FS_TEX);
    const flatProg = link(gl, VS_FLAT, FS_FLAT);
    const aPos = gl.getAttribLocation(texProg, 'aPos');
    const aUV = gl.getAttribLocation(texProg, 'aUV');
    const uMapT = gl.getUniformLocation(texProg, 'uMap');
    const uTex = gl.getUniformLocation(texProg, 'uTex');
    const aUnit = gl.getAttribLocation(flatProg, 'aUnit');
    const uMapF = gl.getUniformLocation(flatProg, 'uMap');
    const uCenter = gl.getUniformLocation(flatProg, 'uCenter');
    const uRadii = gl.getUniformLocation(flatProg, 'uRadii');
    const uColor = gl.getUniformLocation(flatProg, 'uColor');

    const posBuf = gl.createBuffer();
    const uvBuf = gl.createBuffer();
    const idxBuf = gl.createBuffer();
    // Unit disc fan for the mouth interior shapes.
    const FAN = 26;
    const fan: number[] = [0, 0];
    for (let i = 0; i <= FAN; i++) {
      const a = (i / FAN) * Math.PI * 2;
      fan.push(Math.cos(a), Math.sin(a));
    }
    const fanBuf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, fanBuf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(fan), gl.STATIC_DRAW);

    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);

    const image = new Image();
    image.onload = () => {
      if (disposed) return;
      img = image;
      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);
      const ar = image.naturalWidth / image.naturalHeight;
      geo = buildGeometry(lm, ar);
      gl.bindBuffer(gl.ARRAY_BUFFER, uvBuf);
      gl.bufferData(gl.ARRAY_BUFFER, geo.uv, gl.STATIC_DRAW);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, idxBuf);
      gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, geo.indices, gl.STATIC_DRAW);
      gl.bindBuffer(gl.ARRAY_BUFFER, posBuf);
      gl.bufferData(gl.ARRAY_BUFFER, geo.rest.byteLength, gl.DYNAMIC_DRAW);
    };
    image.src = photoUrl;

    const pos = { arr: null as Float32Array | null };
    const timeData = new Uint8Array(512);
    const freqData = new Uint8Array(256);
    let amp = 0, bright = 0.4;
    let nextBlinkAt = performance.now() + 1600;
    let blinkStart = -1;
    let doubleBlink = false;

    const frame = (now: number) => {
      raf = requestAnimationFrame(frame);
      if (!img || !geo) return;
      const g = geo;
      const t = now / 1000;

      // ── Speech signal: amplitude envelope + spectral brightness (viseme) ──
      let target = 0;
      let live = false;
      const an = analyser?.current;
      if (an) {
        an.getByteTimeDomainData(timeData);
        let sum = 0;
        for (let i = 0; i < timeData.length; i++) {
          const v = (timeData[i] - 128) / 128;
          sum += v * v;
        }
        const rms = Math.sqrt(sum / timeData.length);
        if (rms > 0.01) {
          target = Math.min(1, rms * 5.5);
          live = true;
          an.getByteFrequencyData(freqData);
          let e = 0, we = 0;
          for (let i = 0; i < freqData.length; i++) { e += freqData[i]; we += freqData[i] * i; }
          if (e > 0) {
            const centroid = we / e / freqData.length;   // 0..1, higher = brighter
            bright += (Math.min(1, centroid * 3.2) - bright) * 0.25;
          }
        }
      }
      if (!live && talkingRef.current) {
        target = Math.max(0, Math.sin(t * 9.5) * 0.5 + Math.sin(t * 4.1) * 0.3 + 0.15);
        bright = 0.4 + Math.sin(t * 2.7) * 0.25;
      }
      // Fast attack, slower release — consonants snap, vowels linger.
      amp += (target - amp) * (target > amp ? 0.55 : 0.18);

      // ── Blink scheduling (with occasional double-blink) ──
      if (blinkStart < 0 && now >= nextBlinkAt) blinkStart = now;
      let blink = 0;
      if (blinkStart >= 0) {
        const p = (now - blinkStart) / 160;
        if (p >= 1) {
          blinkStart = -1;
          if (!doubleBlink && Math.random() < 0.2) { doubleBlink = true; nextBlinkAt = now + 220; }
          else { doubleBlink = false; nextBlinkAt = now + 1900 + Math.random() * 3900; }
        } else blink = Math.sin(p * Math.PI);
      }

      const iw = img.naturalWidth, ih = img.naturalHeight;
      const ar = iw / ih;
      const d = g.d;
      const w = lm.mouthWidth;

      // Per-agent intensity multipliers from the studio sliders.
      const mMouth = motionRef.current?.mouth ?? 1;
      const mHead = motionRef.current?.head ?? 1;
      const mExpr = motionRef.current?.expr ?? 1;

      // Mouth: openness vs spread trade off like real visemes.
      const open = amp * (1 - bright * 0.35);
      const wide = amp * bright;
      const jawAmt = open * w * ar * 0.30 * mMouth;   // in image-height fraction
      const upAmt = jawAmt * 0.14;
      const wideAmt = wide * w * 0.07 * mExpr;
      const lidAmt = blink * d * 0.30;
      const browAmt = (amp * d * 0.028 + Math.sin(t * 0.9) * d * 0.005) * mExpr;

      // Head life: yaw/pitch parallax + micro-roll around the neck.
      const yaw = ((Math.sin(t * 0.45) * 0.55 + Math.sin(t * 1.13) * 0.25) * d * 0.038 + amp * Math.sin(t * 5.7) * d * 0.008) * mHead;
      const pitch = ((Math.sin(t * 0.71) * 0.4 + amp * Math.sin(t * 6.3) * 0.3) * d * 0.024) * mHead;
      const roll = ((Math.sin(t * 0.31) * 0.5 + Math.sin(t * 0.97) * 0.2) * 0.008 + amp * Math.sin(t * 5.1) * 0.003) * mHead;
      const cosR = Math.cos(roll), sinR = Math.sin(roll);

      // ── Vertex update ──
      if (!pos.arr || pos.arr.length !== g.rest.length) pos.arr = new Float32Array(g.rest.length);
      const P = pos.arr;
      for (let i = 0; i < g.nVerts; i++) {
        let x = g.rest[i * 2];
        let y = g.rest[i * 2 + 1];
        y += jawAmt * g.wJaw[i];
        y -= upAmt * g.wUp[i];
        y += lidAmt * g.wLid[i];
        y -= browAmt * g.wBrow[i];
        x += wideAmt * g.wWide[i];
        const f = g.wFace[i];
        x += yaw * f;
        y += pitch * f;
        // Micro-roll around the neck pivot, blended by the face weight so the
        // background stays put while the head tilts (aspect-corrected: the
        // rotation is done in pixel space, coords are normalized).
        const rx = x - g.pivot.x, ry = y - g.pivot.y;
        const rotX = g.pivot.x + rx * cosR - (ry * sinR) / ar;
        const rotY = g.pivot.y + rx * sinR * ar + ry * cosR;
        P[i * 2] = x + (rotX - x) * f;
        P[i * 2 + 1] = y + (rotY - y) * f;
      }

      // ── Square cover-crop centered on the face, with breath drift ──
      const side = Math.min(iw, ih);
      const faceX = ((lm.leftEye.x + lm.rightEye.x) / 2) * iw;
      const faceY = (((lm.leftEye.y + lm.rightEye.y) / 2) * 0.5 + lm.mouth.y * 0.5) * ih;
      const sx = Math.max(0, Math.min(iw - side, faceX - side / 2));
      const sy = Math.max(0, Math.min(ih - side, faceY - side / 2));
      const zoom = 1.06 + (Math.sin(t * 1.35) * 0.005 + Math.sin(t * 0.13) * 0.006 + amp * 0.005) * mHead;
      // clip = pos * scale + offset  (y flipped), zoom around crop center
      const scaleX = (2 * iw / side) * zoom;
      const scaleY = (-2 * ih / side) * zoom;
      const cx0 = (sx + side / 2) / iw, cy0 = (sy + side / 2) / ih;
      const offX = -cx0 * scaleX;
      const offY = -cy0 * scaleY;

      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.clearColor(0.05, 0.08, 0.15, 1);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.disable(gl.DEPTH_TEST);

      // ── Mouth interior, drawn BEHIND the split lips ──
      if (jawAmt > 0.002) {
        const Mx = lm.mouth.x + yaw * 0.9;
        const My = lm.mouth.y + pitch * 0.9;
        gl.useProgram(flatProg);
        gl.uniform4f(uMapF, scaleX, scaleY, offX, offY);
        gl.bindBuffer(gl.ARRAY_BUFFER, fanBuf);
        gl.enableVertexAttribArray(aUnit);
        gl.vertexAttribPointer(aUnit, 2, gl.FLOAT, false, 0, 0);
        const draw = (cxx: number, cyy: number, rx: number, ry: number, r: number, gg: number, b: number) => {
          gl.uniform2f(uCenter, cxx, cyy);
          gl.uniform2f(uRadii, rx, ry);
          gl.uniform4f(uColor, r, gg, b, 1);
          gl.drawArrays(gl.TRIANGLE_FAN, 0, FAN + 2);
        };
        // Cavity only — a dark interior reads naturally at every opening size;
        // painted teeth flashed white and looked fake, so they're gone.
        draw(Mx, My + jawAmt * 0.42, w * 0.52, jawAmt * 0.75 + 0.004, 0.09, 0.03, 0.045);
        // Tongue hint on wide-open vowels (dark pink, no highlights)
        if (open > 0.45) {
          draw(Mx, My + jawAmt * 0.74, w * 0.28, jawAmt * 0.24, 0.45, 0.20, 0.22);
        }
      }

      // ── The warped photo itself ──
      gl.useProgram(texProg);
      gl.uniform4f(uMapT, scaleX, scaleY, offX, offY);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.uniform1i(uTex, 0);
      gl.bindBuffer(gl.ARRAY_BUFFER, posBuf);
      gl.bufferSubData(gl.ARRAY_BUFFER, 0, P);
      gl.enableVertexAttribArray(aPos);
      gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 0, 0);
      gl.bindBuffer(gl.ARRAY_BUFFER, uvBuf);
      gl.enableVertexAttribArray(aUV);
      gl.vertexAttribPointer(aUV, 2, gl.FLOAT, false, 0, 0);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, idxBuf);
      gl.drawElements(gl.TRIANGLES, g.indices.length, gl.UNSIGNED_SHORT, 0);
    };

    raf = requestAnimationFrame(frame);
    return () => {
      disposed = true;
      cancelAnimationFrame(raf);
      gl.deleteTexture(tex);
      gl.deleteBuffer(posBuf); gl.deleteBuffer(uvBuf); gl.deleteBuffer(idxBuf); gl.deleteBuffer(fanBuf);
      gl.deleteProgram(texProg); gl.deleteProgram(flatProg);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [photoUrl, size, analyser, lmKey]);

  return (
    <canvas
      ref={canvasRef}
      style={{ width: size, height: size, display: 'block', borderRadius: '50%', background: '#0f172a', ...style }}
    />
  );
};

export default PhotoAvatar;
