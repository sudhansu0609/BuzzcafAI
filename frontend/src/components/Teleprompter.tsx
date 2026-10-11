import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { ArrowDown, ArrowUp, Minus, Pause, Play, Plus, RotateCcw, X } from 'lucide-react';

/* Full-screen teleprompter for a BuzzEdit-annotated script (or a raw draft).
 *
 * Two views:
 *  - "dialogue": only the words the presenter speaks. Section headings,
 *    `[directive: ...]` cues, `**VISUAL:**`-style note lines, speaker labels
 *    and `(parenthetical)` stage notes are all dropped -- except pacing cues,
 *    which stay as small markers.
 *  - "full": everything, with the spoken lines bright and large and the rest
 *    dimmed and boxed so dialogue stands out at a glance.
 *
 * The text sits in a fixed-width column, so a bigger font re-wraps to fewer
 * words per line instead of growing sideways off screen.
 *
 * Speed is in words per minute, not pixels: each paragraph's height is
 * measured against its spoken word count, so the pace stays the same at any
 * font size and skims quickly past cue boxes that hold no words. Pacing cues
 * in the script drive the scroll:
 *  - `(pause)`, `[pause 2s]`, `(long pause)`, `(beat)`, `(breath)` hold it;
 *  - `(slow)`, `(softly)`, `(dramatic)`, `(emphasis)`... slow the rest of the
 *    paragraph, `(fast)` speeds it up, `(normal)` resets;
 *  - with natural pauses on, `...`, a dash, and each sentence end add a short
 *    breath.
 */

type SegKind = 'dialogue' | 'direction' | 'speaker';
type Seg = { kind: SegKind; text: string };
type Block = { kind: 'heading'; text: string } | { kind: 'para'; segs: Seg[] };
type Mode = 'dialogue' | 'full';

// Line labels that mark a non-spoken note (the whole line is a direction).
const NOTE_LABELS = /^(visual|visuals|text|text overlay|overlay|on[- ]screen|graphic|graphics|sfx|sound|music|audio|b[- ]?roll|broll|cut|cut to|transition|scene|shot|camera|angle|setting|note|notes|direction|action|title card|lower third|caption|fx|edit)s?$/i;

// `**LABEL:** rest` or `LABEL: rest` (label mostly upper-case, short).
const LABEL_RE = /^\s*(?:\*\*|__)?([A-Za-z][A-Za-z0-9 .'/()-]{0,30}?)(?:\*\*|__)?\s*:\s*(?:\*\*|__)?\s*(.*)$/;

function looksLikeLabel(label: string): boolean {
  const letters = label.replace(/\([^)]*\)/g, '').replace(/[^A-Za-z]/g, '');
  if (!letters) return false;
  // Upper-case labels (NARRATOR, V.O., HOST) or explicit note words.
  return letters === letters.toUpperCase() || NOTE_LABELS.test(label.trim());
}

// Split one line of text into dialogue and inline `[...]` / `(...)` cues.
function splitInline(text: string): Seg[] {
  const out: Seg[] = [];
  const re = /\[[^\]]*\]|\([^)]*\)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push({ kind: 'dialogue', text: text.slice(last, m.index) });
    out.push({ kind: 'direction', text: m[0] });
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ kind: 'dialogue', text: text.slice(last) });
  // Strip Markdown emphasis from spoken text; the presenter reads words, not stars.
  return out
    .map((s) => (s.kind === 'dialogue' ? { ...s, text: s.text.replace(/\*\*|__|(?<!\w)[*_](?=\S)|(?<=\S)[*_](?!\w)/g, '') } : s))
    .filter((s) => s.text.trim() !== '');
}

function parseLine(line: string): Seg[] {
  const m = LABEL_RE.exec(line);
  if (m && looksLikeLabel(m[1])) {
    const label = m[1].trim();
    const rest = m[2];
    if (NOTE_LABELS.test(label.replace(/\([^)]*\)/g, '').trim())) {
      return [{ kind: 'direction', text: line.replace(/\*\*|__/g, '').trim() }];
    }
    return [{ kind: 'speaker', text: `${label}:` }, ...splitInline(rest)];
  }
  return splitInline(line);
}

const META_HEADING_RE = /^[^A-Za-z]*(project|title|brand|brand focus|channel|language|tone|format|duration|target|genre|audience|version)\s*:/i;

export function parseScript(text: string): Block[] {
  const blocks: Block[] = [];
  let para: Seg[] = [];
  const flush = () => {
    if (para.length) blocks.push({ kind: 'para', segs: para });
    para = [];
  };
  for (const raw of text.replace(/\r\n?/g, '\n').split('\n')) {
    const line = raw.trim();
    if (!line) { flush(); continue; }
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(line)) { flush(); continue; }
    const h = /^#{1,6}\s+(.*)$/.exec(line);
    if (h) {
      flush();
      // Draft metadata written as headings ("script/draft.md", "🎬 Project: ...",
      // "Tone: ...") is not part of the performance; drop it.
      if (!META_HEADING_RE.test(h[1]) && !/\.(md|txt|json)\s*$/i.test(h[1])) {
        blocks.push({ kind: 'heading', text: h[1].trim() });
      }
      continue;
    }
    const segs = parseLine(line.replace(/^>\s?/, ''));
    if (para.length && segs.length) para.push({ kind: 'dialogue', text: ' ' });
    para.push(...segs);
  }
  flush();
  return blocks;
}

// --- pacing ----------------------------------------------------------------

type Cue = { pause: number } | { rate: number } | null;

const SLOW_RATE = 0.6;
const FAST_RATE = 1.35;

/** What a bracketed/parenthesised direction asks of the scroll, if anything. */
export function cueOf(direction: string): Cue {
  const t = direction.replace(/^[[(]\s*|\s*[\])]$/g, '').trim().toLowerCase();
  const secs = /(\d+(?:\.\d+)?)\s*(?:s|sec|secs|second|seconds)?\b/.exec(t);
  const n = secs ? Math.min(10, parseFloat(secs[1])) : null;
  if (/^(long\s+pause|long\s+beat)\b/.test(t)) return { pause: n ?? 2.5 };
  if (/^(pause|hold|stop|wait|silence|chup)\b/.test(t)) return { pause: n ?? 1.5 };
  if (/^(beat|breath|breathe|saans|thahro|ruko)\b/.test(t)) return { pause: n ?? 0.8 };
  if (/^(slow|slower|slowly|softly|soft|gently|dramatic|dramatically|emphasis|emphasi[sz]e|emotional|serious|whisper|dheere|aaram se)\b/.test(t)) return { rate: SLOW_RATE };
  if (/^(fast|faster|quick|quickly|excited|energetic|rapid|jaldi|tez)\b/.test(t)) return { rate: FAST_RATE };
  if (/^(normal|regular|normal pace|back to normal)\b/.test(t)) return { rate: 1 };
  return null;
}

type Tok =
  | { t: 'text'; kind: SegKind; text: string; rate: number; words: number }
  | { t: 'pause'; secs: number; auto: boolean; label: string };
type Para = { heading?: string; toks: Tok[] };

const countWords = (s: string) => s.trim().split(/\s+/).filter(Boolean).length;
const endsSentence = (s: string) => /[.!?।…"'”’]\s*$/.test(s);

// Natural breaths inside spoken text: ellipsis, spaced dash, sentence end.
const BREATH_RE = /(\.\.\.|…|\s[—–]\s|\s-{1,2}\s|[.?!।]+["'”’]?(?=\s|$))/g;
const breathFor = (mark: string) => (/\.\.\.|…/.test(mark) ? 0.7 : /[—–-]/.test(mark) ? 0.3 : 0.4);

function pushDialogue(toks: Tok[], text: string, rate: number, natural: boolean) {
  if (!natural) {
    toks.push({ t: 'text', kind: 'dialogue', text, rate, words: countWords(text) });
    return;
  }
  let last = 0;
  let m: RegExpExecArray | null;
  BREATH_RE.lastIndex = 0;
  while ((m = BREATH_RE.exec(text))) {
    const end = m.index + m[0].length;
    const piece = text.slice(last, end);
    toks.push({ t: 'text', kind: 'dialogue', text: piece, rate, words: countWords(piece) });
    toks.push({ t: 'pause', secs: breathFor(m[0]), auto: true, label: '' });
    last = end;
  }
  if (last < text.length) {
    const piece = text.slice(last);
    toks.push({ t: 'text', kind: 'dialogue', text: piece, rate, words: countWords(piece) });
  }
}

export function buildParas(blocks: Block[], mode: Mode, natural: boolean): Para[] {
  const out: Para[] = [];
  let carry: Tok[] | null = null; // dialogue mode: a paragraph still mid-sentence
  const lastSpoken = (toks: Tok[]) => {
    for (let i = toks.length - 1; i >= 0; i--) {
      const k = toks[i];
      if (k.t === 'text' && k.kind === 'dialogue' && k.text.trim()) return k.text;
    }
    return '';
  };
  for (const b of blocks) {
    if (b.kind === 'heading') {
      if (mode === 'full') out.push({ heading: b.text, toks: [] });
      continue;
    }
    const toks: Tok[] = [];
    let rate = 1;
    for (const s of b.segs) {
      if (s.kind === 'direction') {
        const cue = cueOf(s.text);
        if (cue && 'pause' in cue) {
          toks.push({ t: 'pause', secs: cue.pause, auto: false, label: s.text });
          continue;
        }
        if (cue && 'rate' in cue) rate = cue.rate;
        if (mode === 'full') toks.push({ t: 'text', kind: 'direction', text: s.text, rate: 1, words: 0 });
      } else if (s.kind === 'speaker') {
        if (mode === 'full') toks.push({ t: 'text', kind: 'speaker', text: s.text, rate: 1, words: 0 });
      } else {
        pushDialogue(toks, s.text, rate, natural);
      }
    }
    if (mode === 'full') {
      if (toks.length) out.push({ toks });
      continue;
    }
    // Dialogue only: take-split scripts break mid-sentence, so a paragraph
    // that doesn't end a sentence is joined to the next one.
    if (!toks.length) continue;
    if (carry) {
      carry.push({ t: 'text', kind: 'dialogue', text: ' ', rate: 1, words: 0 }, ...toks);
    } else {
      carry = toks;
    }
    if (endsSentence(lastSpoken(carry))) {
      out.push({ toks: carry });
      carry = null;
    }
  }
  if (carry && carry.length) out.push({ toks: carry });
  return out;
}

// --- layout metrics --------------------------------------------------------

type Band = { top: number; bottom: number };
type Metrics = {
  paras: (Band & { ppw: number })[]; // px of scroll per spoken word
  rates: (Band & { rate: number })[];
  pauses: { y: number; secs: number }[];
  avgPpw: number;
};
const EMPTY_METRICS: Metrics = { paras: [], rates: [], pauses: [], avgPpw: 20 };

function measure(scroller: HTMLElement, content: HTMLElement): Metrics {
  const origin = scroller.getBoundingClientRect().top - scroller.scrollTop;
  const band = (el: Element): Band => {
    const r = el.getBoundingClientRect();
    return { top: r.top - origin, bottom: r.bottom - origin };
  };
  const paras: Metrics['paras'] = [];
  let totalH = 0, totalW = 0;
  content.querySelectorAll<HTMLElement>('[data-para]').forEach((el) => {
    const words = Number(el.dataset.words || 0);
    const b = band(el);
    if (words > 0) { totalH += b.bottom - b.top; totalW += words; }
    paras.push({ ...b, ppw: words > 0 ? (b.bottom - b.top) / words : 0 });
  });
  const avgPpw = totalW > 0 ? totalH / totalW : 20;
  // Word-less blocks (headings, cue-only paragraphs) scroll past at twice
  // the normal pace: there is nothing to read aloud there.
  for (const p of paras) if (p.ppw === 0) p.ppw = avgPpw * 2;
  const rates: Metrics['rates'] = [];
  content.querySelectorAll<HTMLElement>('[data-rate]').forEach((el) => {
    const rate = Number(el.dataset.rate);
    if (rate && rate !== 1) rates.push({ ...band(el), rate });
  });
  const pauses: Metrics['pauses'] = [];
  content.querySelectorAll<HTMLElement>('[data-pause]').forEach((el) => {
    pauses.push({ y: band(el).bottom, secs: Number(el.dataset.pause) });
  });
  pauses.sort((a, b) => a.y - b.y);
  return { paras, rates, pauses, avgPpw };
}

// --- prefs -----------------------------------------------------------------

const STORE_KEY = 'buzzcaf.teleprompter.v2';
type Prefs = { wpm: number; fontSize: number; mode: Mode; natural: boolean };
const DEFAULT_PREFS: Prefs = { wpm: 140, fontSize: 44, mode: 'full', natural: true };

function loadPrefs(): Prefs {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (raw) return { ...DEFAULT_PREFS, ...JSON.parse(raw) };
  } catch { /* storage unavailable */ }
  return DEFAULT_PREFS;
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const WPM_MIN = 40, WPM_MAX = 300;
const FONT_MIN = 18, FONT_MAX = 110;
// Where the eye sits: this fraction down the scroll area.
const READ_FRAC = 0.33;
const LINE_HEIGHT = 1.5;
// The column: wide enough for comfortable lines, never wider than the screen.
const COLUMN_WIDTH = 'min(1100px, 100%)';

const ctrlBtn: CSSProperties = {
  color: '#e5e7eb',
  borderColor: 'rgba(255,255,255,0.3)',
  padding: '5px 10px',
  fontSize: '0.8rem',
  display: 'inline-flex',
  alignItems: 'center',
  gap: 6,
};

const fmtTime = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`;

export default function Teleprompter({
  title,
  text,
  busy,
  actions,
  onClose,
}: {
  title: string;
  text: string;
  busy: boolean;
  actions?: ReactNode;
  onClose: () => void;
}) {
  const [prefs, setPrefs] = useState<Prefs>(loadPrefs);
  const [playing, setPlaying] = useState(false);
  const [direction, setDirection] = useState<1 | -1>(1);
  const [holding, setHolding] = useState(0); // seconds of the cue being held, 0 = none
  const [viewH, setViewH] = useState(0);
  const scrollRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const metricsRef = useRef<Metrics>(EMPTY_METRICS);
  const wpmRef = useRef(prefs.wpm);
  const dirRef = useRef(direction);
  wpmRef.current = prefs.wpm;
  dirRef.current = direction;

  useEffect(() => {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(prefs)); } catch { /* ignore */ }
  }, [prefs]);

  const blocks = useMemo(() => parseScript(text), [text]);
  const paras = useMemo(() => buildParas(blocks, prefs.mode, prefs.natural), [blocks, prefs.mode, prefs.natural]);

  const estimate = useMemo(() => {
    let secs = 0;
    for (const p of paras) for (const k of p.toks) {
      if (k.t === 'text') secs += (k.words / prefs.wpm) * 60 / k.rate;
      else secs += k.secs;
    }
    return secs;
  }, [paras, prefs.wpm]);

  // Re-measure whenever the layout can change: text, mode, font, window size.
  const remeasure = useCallback(() => {
    const el = scrollRef.current, content = contentRef.current;
    if (!el) return;
    setViewH(el.clientHeight);
    if (content) metricsRef.current = measure(el, content);
  }, []);
  useLayoutEffect(() => { remeasure(); }, [remeasure, paras, prefs.fontSize, viewH, busy]);
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => remeasure());
    ro.observe(el);
    if (contentRef.current) ro.observe(contentRef.current);
    return () => ro.disconnect();
  }, [remeasure, busy, text]);

  // Keep the same passage under the reading line when the font changes.
  const anchorRef = useRef<number | null>(null);
  const changeFont = useCallback((v: number) => {
    const el = scrollRef.current;
    if (el && el.scrollHeight > 0) {
      anchorRef.current = (el.scrollTop + el.clientHeight * READ_FRAC) / el.scrollHeight;
    }
    setPrefs((p) => ({ ...p, fontSize: clamp(Math.round(v), FONT_MIN, FONT_MAX) }));
  }, []);
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (el && anchorRef.current !== null) {
      el.scrollTop = anchorRef.current * el.scrollHeight - el.clientHeight * READ_FRAC;
      anchorRef.current = null;
    }
  }, [prefs.fontSize]);

  // Auto-scroll loop. scrollTop rounds to whole pixels, so fractional
  // progress is kept in `pos` rather than read back each frame.
  useEffect(() => {
    if (!playing) return;
    const el = scrollRef.current;
    if (!el) return;
    let pos = el.scrollTop;
    let prev = performance.now();
    let holdUntil = 0;
    let raf = 0;
    const readY = (p: number) => p + el.clientHeight * READ_FRAC + (prefs.fontSize * LINE_HEIGHT) / 2;
    // Pauses already behind the reading line don't fire.
    let nextPause = metricsRef.current.pauses.findIndex((q) => q.y > readY(pos));
    if (nextPause < 0) nextPause = metricsRef.current.pauses.length;

    const tick = (now: number) => {
      const dt = Math.min(0.1, (now - prev) / 1000);
      prev = now;
      const m = metricsRef.current;
      // Respect manual scrolling (wheel/drag) while playing.
      if (Math.abs(el.scrollTop - pos) > 2) {
        pos = el.scrollTop;
        nextPause = m.pauses.findIndex((q) => q.y > readY(pos));
        if (nextPause < 0) nextPause = m.pauses.length;
      }
      if (now < holdUntil) { raf = requestAnimationFrame(tick); return; }
      if (holdUntil) { holdUntil = 0; setHolding(0); }

      const y = readY(pos);
      const para = m.paras.find((p) => y >= p.top && y < p.bottom);
      const ppw = para ? para.ppw : m.avgPpw * 2;
      const rateBand = m.rates.find((r) => y >= r.top && y < r.bottom);
      const rate = rateBand ? rateBand.rate : 1;
      const dir = dirRef.current;
      pos += (wpmRef.current / 60) * ppw * rate * dir * dt;

      const max = el.scrollHeight - el.clientHeight;
      if (pos <= 0 || pos >= max) {
        el.scrollTop = clamp(pos, 0, max);
        setPlaying(false);
        return;
      }
      el.scrollTop = pos;

      if (dir === 1) {
        // Hold on the longest cue the reading line just crossed.
        const ny = readY(pos);
        let hold = 0;
        while (nextPause < m.pauses.length && m.pauses[nextPause].y <= ny) {
          hold = Math.max(hold, m.pauses[nextPause].secs);
          nextPause++;
        }
        if (hold > 0) { holdUntil = now + hold * 1000; setHolding(hold); }
      } else {
        // Going back up: re-arm the cues we pass again.
        const ny = readY(pos);
        while (nextPause > 0 && m.pauses[nextPause - 1].y > ny) nextPause--;
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => { cancelAnimationFrame(raf); setHolding(0); };
  }, [playing, prefs.fontSize]);

  const setWpm = useCallback((v: number) => setPrefs((p) => ({ ...p, wpm: clamp(Math.round(v), WPM_MIN, WPM_MAX) })), []);
  const setMode = (mode: Mode) => setPrefs((p) => ({ ...p, mode }));

  const togglePlay = useCallback(() => {
    const el = scrollRef.current;
    if (!playing && el) {
      // Starting at an end in the direction of travel: rewind first.
      const max = el.scrollHeight - el.clientHeight;
      if (dirRef.current === 1 && el.scrollTop >= max - 1) el.scrollTop = 0;
      if (dirRef.current === -1 && el.scrollTop <= 1) el.scrollTop = max;
    }
    setPlaying((p) => !p);
  }, [playing]);

  const toTop = () => { if (scrollRef.current) scrollRef.current.scrollTop = 0; };

  // Keyboard: Space play/pause, ↑/↓ speed, +/- font, R reverse, Home top, Esc close.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') {
        if (e.key === 'Escape') onClose();
        return;
      }
      switch (e.key) {
        case ' ': e.preventDefault(); togglePlay(); break;
        case 'ArrowUp': e.preventDefault(); setWpm(wpmRef.current + 5); break;
        case 'ArrowDown': e.preventDefault(); setWpm(wpmRef.current - 5); break;
        case '+': case '=': changeFont(prefs.fontSize + 2); break;
        case '-': case '_': changeFont(prefs.fontSize - 2); break;
        case 'r': case 'R': setDirection((d) => (d === 1 ? -1 : 1)); break;
        case 'Home': toTop(); break;
        case 'Escape': onClose(); break;
        default: return;
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [togglePlay, setWpm, changeFont, prefs.fontSize, onClose]);

  const fs = prefs.fontSize;
  const hasText = !!text.trim();
  const full = prefs.mode === 'full';

  const renderTok = (k: Tok, j: number) => {
    if (k.t === 'pause') {
      if (k.auto) return <span key={j} data-pause={k.secs} />;
      return (
        <span
          key={j}
          data-pause={k.secs}
          style={{
            color: '#fbbf24', fontSize: '0.42em', fontFamily: 'ui-monospace, Consolas, monospace',
            background: 'rgba(251,191,36,0.1)', border: '1px solid rgba(251,191,36,0.4)',
            borderRadius: 4, padding: '1px 6px', margin: '0 0.3em', verticalAlign: 'middle', lineHeight: 1.4,
            whiteSpace: 'nowrap',
          }}
        >
          ⏸ {full ? k.label : 'pause'} · {k.secs}s
        </span>
      );
    }
    if (k.kind === 'dialogue') {
      const slow = k.rate < 1, fast = k.rate > 1;
      return (
        <span
          key={j}
          data-rate={k.rate !== 1 ? k.rate : undefined}
          style={{
            color: full ? '#fef08a' : '#ffffff',
            fontWeight: full ? 600 : 500,
            ...(slow ? { textDecoration: 'underline dotted rgba(96,165,250,0.8)', textUnderlineOffset: '0.2em' } : {}),
            ...(fast ? { textDecoration: 'underline dashed rgba(244,114,182,0.7)', textUnderlineOffset: '0.2em' } : {}),
          }}
        >
          {k.text}
        </span>
      );
    }
    if (k.kind === 'speaker') {
      return (
        <span key={j} style={{ color: '#f472b6', fontSize: '0.5em', fontWeight: 700, marginRight: '0.4em', letterSpacing: '0.05em' }}>
          {k.text}
        </span>
      );
    }
    const cue = cueOf(k.text);
    return (
      <span
        key={j}
        style={{
          color: cue ? '#93c5fd' : '#9ca3af', fontSize: '0.42em', fontFamily: 'ui-monospace, Consolas, monospace',
          background: 'rgba(255,255,255,0.06)', border: `1px solid ${cue ? 'rgba(147,197,253,0.45)' : 'rgba(255,255,255,0.12)'}`,
          borderRadius: 4, padding: '1px 6px', margin: '0 0.25em', verticalAlign: 'middle', lineHeight: 1.4,
        }}
      >
        {k.text}
      </span>
    );
  };

  // Portalled to <body> with a z-index above the app shell (the sidebar sits
  // at 1100-1500), so nothing in the page can overlap or clip it.
  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      style={{
        position: 'fixed',
        inset: 0,
        background: '#0a0a0e',
        zIndex: 5000,
        display: 'flex',
        flexDirection: 'column',
        padding: 24,
        boxSizing: 'border-box',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12, flexWrap: 'wrap', gap: 10 }}>
        <span style={{ color: '#e5e7eb', fontSize: '0.85rem', fontWeight: 600 }}>Teleprompter — {title}</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          {actions}
          <button type="button" className="btn btn-outline btn-sm" onClick={onClose} style={ctrlBtn}>
            <X size={14} />
            <span>Close</span>
          </button>
        </div>
      </div>

      {hasText && !busy && (
        <div
          style={{
            display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap',
            padding: '8px 12px', marginBottom: 12, borderRadius: 8,
            background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)',
            color: '#d1d5db', fontSize: '0.8rem',
          }}
        >
          <div style={{ display: 'inline-flex', borderRadius: 6, overflow: 'hidden', border: '1px solid rgba(255,255,255,0.25)' }}>
            {(['dialogue', 'full'] as Mode[]).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMode(m)}
                style={{
                  padding: '5px 12px', border: 'none', cursor: 'pointer', fontSize: '0.8rem',
                  background: prefs.mode === m ? '#facc15' : 'transparent',
                  color: prefs.mode === m ? '#111' : '#e5e7eb',
                  fontWeight: prefs.mode === m ? 700 : 500,
                }}
                title={m === 'dialogue' ? 'Show only the spoken lines' : 'Show everything, with spoken lines highlighted'}
              >
                {m === 'dialogue' ? 'Dialogue only' : 'Full script'}
              </button>
            ))}
          </div>

          <button type="button" className="btn btn-outline btn-sm" onClick={togglePlay} style={{ ...ctrlBtn, minWidth: 84 }} title="Play / pause (Space)">
            {playing ? <Pause size={14} /> : <Play size={14} />}
            <span>{playing ? 'Pause' : 'Scroll'}</span>
          </button>
          <button
            type="button"
            className="btn btn-outline btn-sm"
            onClick={() => setDirection((d) => (d === 1 ? -1 : 1))}
            style={ctrlBtn}
            title="Scroll direction (R)"
          >
            {direction === 1 ? <ArrowDown size={14} /> : <ArrowUp size={14} />}
            <span>{direction === 1 ? 'Down' : 'Up'}</span>
          </button>
          <button type="button" className="btn btn-outline btn-sm" onClick={toTop} style={ctrlBtn} title="Back to top (Home)">
            <RotateCcw size={14} />
            <span>Top</span>
          </button>

          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }} title="Reading pace in words per minute (↑ / ↓). Cues in the script slow, speed up or pause it.">
            <span>Pace</span>
            <button type="button" className="btn btn-outline btn-sm" style={{ ...ctrlBtn, padding: '3px 6px' }} onClick={() => setWpm(prefs.wpm - 5)}><Minus size={12} /></button>
            <input type="range" min={WPM_MIN} max={WPM_MAX} step={5} value={prefs.wpm} onChange={(e) => setWpm(Number(e.target.value))} style={{ width: 110 }} />
            <button type="button" className="btn btn-outline btn-sm" style={{ ...ctrlBtn, padding: '3px 6px' }} onClick={() => setWpm(prefs.wpm + 5)}><Plus size={12} /></button>
            <span style={{ minWidth: 64, fontVariantNumeric: 'tabular-nums' }}>{prefs.wpm} wpm</span>
          </label>

          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }} title="Text size (+ / -). Lines re-wrap; the column keeps its width.">
            <span>Size</span>
            <button type="button" className="btn btn-outline btn-sm" style={{ ...ctrlBtn, padding: '3px 6px' }} onClick={() => changeFont(fs - 2)}><Minus size={12} /></button>
            <input type="range" min={FONT_MIN} max={FONT_MAX} step={1} value={fs} onChange={(e) => changeFont(Number(e.target.value))} style={{ width: 110 }} />
            <button type="button" className="btn btn-outline btn-sm" style={{ ...ctrlBtn, padding: '3px 6px' }} onClick={() => changeFont(fs + 2)}><Plus size={12} /></button>
            <span style={{ minWidth: 40, fontVariantNumeric: 'tabular-nums' }}>{fs}px</span>
          </label>

          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'pointer' }} title="Add a short breath at each sentence end, dash and '...'">
            <input type="checkbox" checked={prefs.natural} onChange={(e) => setPrefs((p) => ({ ...p, natural: e.target.checked }))} />
            <span>Natural pauses</span>
          </label>

          <span style={{ marginLeft: 'auto', color: '#9ca3af', fontVariantNumeric: 'tabular-nums' }} title="Estimated read time at this pace, including pauses">
            ≈ {fmtTime(estimate)}
          </span>
        </div>
      )}

      <div style={{ position: 'relative', flex: 1, minHeight: 0 }}>
        {/* Reading line: where the presenter's eye should sit. */}
        {hasText && !busy && (
          <div
            aria-hidden="true"
            style={{
              position: 'absolute', left: 0, right: 0, top: `${READ_FRAC * 100}%`, height: fs * LINE_HEIGHT,
              borderTop: '1px solid rgba(250,204,21,0.35)', borderBottom: '1px solid rgba(250,204,21,0.35)',
              background: 'rgba(250,204,21,0.04)', pointerEvents: 'none', zIndex: 1,
            }}
          >
            {holding > 0 && (
              <span
                style={{
                  position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)',
                  color: '#111', background: '#fbbf24', borderRadius: 4, padding: '2px 8px',
                  fontSize: '0.8rem', fontWeight: 700,
                }}
              >
                ⏸ {holding}s
              </span>
            )}
          </div>
        )}
        <div ref={scrollRef} style={{ position: 'absolute', inset: 0, overflowY: 'auto', overflowX: 'hidden' }}>
          {busy ? (
            <div style={{ color: '#9ca3af', fontSize: '1rem', marginTop: 40, textAlign: 'center' }}>Loading…</div>
          ) : !hasText ? (
            <div style={{ color: '#9ca3af', fontSize: '1.2rem', marginTop: 40, textAlign: 'center' }}>No annotated script yet — produce a video first.</div>
          ) : (
            <div
              ref={contentRef}
              style={{
                width: COLUMN_WIDTH,
                margin: '0 auto',
                boxSizing: 'border-box',
                // Space above and below lets the first and last lines reach the reading line.
                paddingTop: viewH * READ_FRAC,
                paddingBottom: Math.max(0, viewH * (1 - READ_FRAC) - fs * LINE_HEIGHT),
                paddingLeft: 24,
                paddingRight: 24,
                fontSize: fs,
                lineHeight: LINE_HEIGHT,
                overflowWrap: 'anywhere',
              }}
            >
              {paras.map((p, i) =>
                p.heading !== undefined ? (
                  <div
                    key={i}
                    data-para=""
                    data-words={0}
                    style={{
                      color: '#60a5fa', fontSize: clamp(fs * 0.45, 14, 30), fontWeight: 700,
                      letterSpacing: '0.08em', textTransform: 'uppercase',
                      margin: `${fs * 0.8}px 0 ${fs * 0.4}px`, paddingBottom: 6,
                      borderBottom: '1px solid rgba(96,165,250,0.35)',
                    }}
                  >
                    {p.heading}
                  </div>
                ) : (
                  <p
                    key={i}
                    data-para=""
                    data-words={p.toks.reduce((n, k) => n + (k.t === 'text' ? k.words : 0), 0)}
                    style={{ margin: `0 0 ${fs * 0.9}px` }}
                  >
                    {p.toks.map(renderTok)}
                  </p>
                ),
              )}
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
