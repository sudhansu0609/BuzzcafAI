import React, { useEffect, useRef } from 'react';
import { AvatarConfig } from '../types/agent';

export const DEFAULT_AVATAR_CONFIG: AvatarConfig = {
  skinTone: '#e8b98a',
  hairStyle: 'short',
  hairColor: '#2d1b12',
  eyeColor: '#4a3120',
  shirtColor: '#6366f1',
  accessory: 'none',
  bgColor: '#1e1b4b',
};

// Swatch presets for the customizer UI.
export const SKIN_TONES = ['#f6d7b8', '#e8b98a', '#d29b6b', '#b07647', '#8d5a2b', '#5f3d1e'];
export const HAIR_COLORS = ['#1a1a1a', '#2d1b12', '#5b3a1a', '#8a5a2b', '#b8863b', '#9e9e9e', '#d9435f', '#7c3aed'];
export const EYE_COLORS = ['#4a3120', '#1f2937', '#2563eb', '#059669', '#7c3aed', '#b45309'];
export const SHIRT_COLORS = ['#6366f1', '#0ea5e9', '#10b981', '#f59e0b', '#ef4444', '#ec4899', '#64748b', '#111827'];
export const BG_COLORS = ['#1e1b4b', '#082f49', '#052e16', '#450a0a', '#3b0764', '#27272a'];
export const HAIR_STYLES: Array<{ id: AvatarConfig['hairStyle']; label: string }> = [
  { id: 'short', label: 'Short' },
  { id: 'long', label: 'Long' },
  { id: 'bun', label: 'Bun' },
  { id: 'curly', label: 'Curly' },
  { id: 'spiky', label: 'Spiky' },
  { id: 'bald', label: 'Bald' },
];
export const ACCESSORIES: Array<{ id: AvatarConfig['accessory']; label: string }> = [
  { id: 'none', label: 'None' },
  { id: 'glasses', label: 'Glasses' },
  { id: 'earrings', label: 'Earrings' },
  { id: 'both', label: 'Both' },
];

interface AnimatedAvatarProps {
  config?: Partial<AvatarConfig> | null;
  /** Rendered width/height in px (the SVG is square). */
  size?: number;
  /** Synthetic mouth movement when no live analyser signal is available. */
  talking?: boolean;
  /** Live audio analyser — drives real lip-sync when present. */
  analyser?: React.MutableRefObject<AnalyserNode | null>;
  style?: React.CSSProperties;
}

/**
 * A lifelike animated persona: breathing torso, swaying head, wandering eyes,
 * timed blinks, and a mouth driven by live speech amplitude. All motion is
 * applied by a single rAF loop writing SVG attributes through refs — no React
 * re-renders per frame.
 */
const AnimatedAvatar: React.FC<AnimatedAvatarProps> = ({ config, size = 120, talking = false, analyser, style }) => {
  const cfg: AvatarConfig = { ...DEFAULT_AVATAR_CONFIG, ...(config || {}) };

  const headRef = useRef<SVGGElement>(null);
  const torsoRef = useRef<SVGGElement>(null);
  const mouthRef = useRef<SVGPathElement>(null);
  const lidLRef = useRef<SVGEllipseElement>(null);
  const lidRRef = useRef<SVGEllipseElement>(null);
  const pupilsRef = useRef<SVGGElement>(null);
  const browLRef = useRef<SVGPathElement>(null);
  const browRRef = useRef<SVGPathElement>(null);

  const talkingRef = useRef(talking);
  talkingRef.current = talking;

  useEffect(() => {
    let raf = 0;
    let amp = 0;                       // smoothed mouth amplitude 0..1
    let nextBlinkAt = performance.now() + 1500;
    let blinkStart = -1;
    let pupilTarget = { x: 0, y: 0 };
    let pupil = { x: 0, y: 0 };
    let nextPupilMoveAt = 0;
    const timeData = new Uint8Array(512);

    const frame = (now: number) => {
      const t = now / 1000;

      // ── Mouth amplitude: live audio when available, synthetic otherwise ──
      let target = 0;
      const an = analyser?.current;
      let liveSignal = false;
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
          liveSignal = true;
        }
      }
      if (!liveSignal && talkingRef.current) {
        // Plausible syllable rhythm when we only know "it is speaking".
        target = Math.max(0, Math.sin(t * 9.5) * 0.5 + Math.sin(t * 4.1) * 0.3 + 0.15);
      }
      amp += (target - amp) * 0.35;

      // ── Head: idle sway + gentle nod while speaking ──
      if (headRef.current) {
        const sway = Math.sin(t * 0.55) * 2.0 + Math.sin(t * 1.31) * 0.7;
        const nod = amp * 1.6 * Math.sin(t * 6.0);
        const bob = Math.sin(t * 1.1) * 1.2 + amp * 1.2;
        headRef.current.setAttribute('transform', `rotate(${(sway + nod).toFixed(2)} 100 150) translate(0 ${bob.toFixed(2)})`);
      }

      // ── Torso breathing ──
      if (torsoRef.current) {
        const s = 1 + Math.sin(t * 1.4) * 0.012;
        torsoRef.current.setAttribute('transform', `translate(0 230) scale(1 ${s.toFixed(4)}) translate(0 -230)`);
      }

      // ── Blinks ──
      if (blinkStart < 0 && now >= nextBlinkAt) blinkStart = now;
      let lid = 0; // 0 open .. 1 closed
      if (blinkStart >= 0) {
        const p = (now - blinkStart) / 150;
        if (p >= 1) {
          blinkStart = -1;
          nextBlinkAt = now + 1800 + Math.random() * 3800;
        } else {
          lid = Math.sin(p * Math.PI);
        }
      }
      const lidRy = (7.5 * lid).toFixed(2);
      lidLRef.current?.setAttribute('ry', lidRy);
      lidRRef.current?.setAttribute('ry', lidRy);

      // ── Pupils wander between fixation points ──
      if (now >= nextPupilMoveAt) {
        pupilTarget = { x: (Math.random() - 0.5) * 5, y: (Math.random() - 0.5) * 2.5 };
        nextPupilMoveAt = now + 1400 + Math.random() * 2600;
      }
      pupil.x += (pupilTarget.x - pupil.x) * 0.12;
      pupil.y += (pupilTarget.y - pupil.y) * 0.12;
      pupilsRef.current?.setAttribute('transform', `translate(${pupil.x.toFixed(2)} ${pupil.y.toFixed(2)})`);

      // ── Mouth morph: relaxed smile ↔ open speech ──
      if (mouthRef.current) {
        const open = amp * 13;
        const y = 119;
        mouthRef.current.setAttribute(
          'd',
          `M 85 ${y} Q 100 ${(y + 4 + open * 0.35).toFixed(2)} 115 ${y} Q 100 ${(y + 5 + open).toFixed(2)} 85 ${y} Z`
        );
      }

      // ── Brows lift with speech energy ──
      const browLift = (-amp * 2.2).toFixed(2);
      browLRef.current?.setAttribute('transform', `translate(0 ${browLift})`);
      browRRef.current?.setAttribute('transform', `translate(0 ${browLift})`);

      raf = requestAnimationFrame(frame);
    };

    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, [analyser]);

  const skin = cfg.skinTone;
  const skinShade = shade(skin, -18);
  const hair = cfg.hairColor;
  const showGlasses = cfg.accessory === 'glasses' || cfg.accessory === 'both';
  const showEarrings = cfg.accessory === 'earrings' || cfg.accessory === 'both';

  return (
    <svg
      viewBox="0 0 200 230"
      width={size}
      height={size}
      style={{ display: 'block', borderRadius: '50%', background: `radial-gradient(circle at 50% 30%, ${shade(cfg.bgColor, 25)}, ${cfg.bgColor})`, ...style }}
    >
      {/* Torso */}
      <g ref={torsoRef}>
        <path
          d={'M 38 230 C 38 192 62 172 100 172 C 138 172 162 192 162 230 Z'}
          fill={cfg.shirtColor}
        />
        <path d={'M 88 172 L 112 172 L 108 186 L 92 186 Z'} fill={shade(cfg.shirtColor, -25)} />
      </g>

      {/* Neck */}
      <rect x="89" y="146" width="22" height="30" rx="8" fill={skinShade} />

      {/* Head group (sways/nods as one) */}
      <g ref={headRef}>
        {/* Back hair (behind the face) */}
        {cfg.hairStyle === 'long' && (
          <path d="M 52 90 C 48 150 56 168 66 172 L 134 172 C 144 168 152 150 148 90 C 148 55 128 38 100 38 C 72 38 52 55 52 90 Z" fill={hair} />
        )}
        {cfg.hairStyle === 'curly' && (
          <g fill={hair}>
            {[58, 74, 92, 110, 128, 142].map((x, i) => (
              <circle key={i} cx={x} cy={i % 2 ? 52 : 60} r="16" />
            ))}
            <circle cx="55" cy="82" r="12" />
            <circle cx="145" cy="82" r="12" />
          </g>
        )}

        {/* Ears */}
        <ellipse cx="54" cy="98" rx="8" ry="13" fill={skin} />
        <ellipse cx="146" cy="98" rx="8" ry="13" fill={skin} />
        {showEarrings && (
          <g fill="#fbbf24">
            <circle cx="54" cy="110" r="3" />
            <circle cx="146" cy="110" r="3" />
          </g>
        )}

        {/* Face */}
        <ellipse cx="100" cy="95" rx="46" ry="52" fill={skin} />

        {/* Front hair */}
        {cfg.hairStyle === 'short' && (
          <path d="M 54 88 C 52 48 74 34 100 34 C 126 34 148 48 146 88 C 140 66 126 58 100 58 C 74 58 60 66 54 88 Z" fill={hair} />
        )}
        {cfg.hairStyle === 'long' && (
          <path d="M 54 88 C 52 46 74 32 100 32 C 126 32 148 46 146 88 C 142 62 126 54 100 54 C 74 54 58 62 54 88 Z" fill={hair} />
        )}
        {cfg.hairStyle === 'bun' && (
          <>
            <circle cx="100" cy="30" r="16" fill={hair} />
            <path d="M 54 86 C 54 50 74 36 100 36 C 126 36 146 50 146 86 C 138 64 124 56 100 56 C 76 56 62 64 54 86 Z" fill={hair} />
          </>
        )}
        {cfg.hairStyle === 'curly' && (
          <path d="M 56 84 C 56 52 76 40 100 40 C 124 40 144 52 144 84 C 136 64 122 58 100 58 C 78 58 64 64 56 84 Z" fill={hair} />
        )}
        {cfg.hairStyle === 'spiky' && (
          <path d="M 54 88 L 58 52 L 68 66 L 76 40 L 86 60 L 100 34 L 114 60 L 124 40 L 132 66 L 142 52 L 146 88 C 138 66 126 58 100 58 C 74 58 62 66 54 88 Z" fill={hair} />
        )}

        {/* Brows */}
        <path ref={browLRef} d="M 70 74 Q 82 68 92 73" stroke={hair} strokeWidth="3.5" fill="none" strokeLinecap="round" />
        <path ref={browRRef} d="M 108 73 Q 118 68 130 74" stroke={hair} strokeWidth="3.5" fill="none" strokeLinecap="round" />

        {/* Eyes */}
        <ellipse cx="82" cy="88" rx="9.5" ry="7" fill="#ffffff" />
        <ellipse cx="118" cy="88" rx="9.5" ry="7" fill="#ffffff" />
        <g ref={pupilsRef}>
          <circle cx="82" cy="88" r="4.5" fill={cfg.eyeColor} />
          <circle cx="118" cy="88" r="4.5" fill={cfg.eyeColor} />
          <circle cx="82" cy="88" r="2" fill="#111" />
          <circle cx="118" cy="88" r="2" fill="#111" />
          <circle cx="83.5" cy="86.5" r="1" fill="#fff" />
          <circle cx="119.5" cy="86.5" r="1" fill="#fff" />
        </g>
        {/* Eyelids (ry animated 0 → closed) */}
        <ellipse ref={lidLRef} cx="82" cy="85" rx="10" ry="0" fill={skin} />
        <ellipse ref={lidRRef} cx="118" cy="85" rx="10" ry="0" fill={skin} />

        {showGlasses && (
          <g stroke="#1f2937" strokeWidth="2.5" fill="rgba(255,255,255,0.08)">
            <circle cx="82" cy="88" r="13" />
            <circle cx="118" cy="88" r="13" />
            <path d="M 95 88 L 105 88" fill="none" />
            <path d="M 69 86 L 56 82" fill="none" />
            <path d="M 131 86 L 144 82" fill="none" />
          </g>
        )}

        {/* Nose */}
        <path d="M 100 94 C 98 100 96 104 98 107 C 99.5 109 102 109 103 107" stroke={skinShade} strokeWidth="2.2" fill="none" strokeLinecap="round" />

        {/* Blush */}
        <ellipse cx="72" cy="106" rx="7" ry="4" fill="#f472b6" opacity="0.18" />
        <ellipse cx="128" cy="106" rx="7" ry="4" fill="#f472b6" opacity="0.18" />

        {/* Mouth (morphed every frame) */}
        <path ref={mouthRef} d="M 85 119 Q 100 123 115 119 Q 100 124 85 119 Z" fill="#7c2d3e" stroke="#5f1f2e" strokeWidth="1" />
      </g>
    </svg>
  );
};

/** Lighten (+) or darken (−) a #rrggbb color by `pct` percent. */
function shade(hex: string, pct: number): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return hex;
  const n = parseInt(m[1], 16);
  const adj = (c: number) => Math.max(0, Math.min(255, Math.round(c + (pct / 100) * (pct > 0 ? 255 - c : c))));
  const r = adj((n >> 16) & 255), g = adj((n >> 8) & 255), b = adj(n & 255);
  return `#${((r << 16) | (g << 8) | b).toString(16).padStart(6, '0')}`;
}

export default AnimatedAvatar;
