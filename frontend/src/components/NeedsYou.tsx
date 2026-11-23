import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { AlertTriangle, BellRing, Check, CheckCircle2, Clapperboard, Clock, Eye, EyeOff, Mic, ShieldCheck, X } from 'lucide-react';
import { useStudio } from '../state/studio';
import { getJson, postJson, describeError } from '../services/api';
import type { TabId } from '../lib/types';

// "Waiting for you" (2026-10-26): the creator found it confusing that work
// waiting on him (a script needing his voice, an approval, a review gate)
// looked like work in progress, scattered over the Dashboard, the Story Desk
// and the Projects page. GET /api/needs_you (backend app/services/needs_you.py)
// lists all of it with the buttons that settle each item; this pops it up,
// bright and in front, whenever something he has not put off is waiting.
//
// Seen it / Dismiss all (2026-10-27): an item he marks seen leaves the pop-up
// and never raises it again (POST /api/needs_you/seen, kept by the backend);
// "Show all pending" lists the seen ones too, until each is settled.

interface NeedsAction {
  label: string;
  method: 'POST';
  path: string;
  style: 'primary' | 'danger' | 'default';
  body: Record<string, unknown>;
  ask?: string;
  confirm?: string;
  background?: boolean;
}

interface NeedsItem {
  key: string;
  kind: 'publish' | 'step_approval' | 'review_gate' | 'director' | 'voice' | 'shorts_record';
  title: string;
  brand?: string;
  what: string;
  since?: string | null;
  project_id?: string | null;
  tab: TabId;
  count?: number;
  seen?: boolean;
  actions: NeedsAction[];
}

const POLL_MS = 30_000;
const LATER_MS = 2 * 60 * 60 * 1000;   // "Later" on one item
const CLOSE_MS = 60 * 60 * 1000;       // closing the pop-up puts everything shown off this long
const SNOOZE_KEY = 'buzzcaf.needsYou.snoozed';

const KIND_META: Record<NeedsItem['kind'], { label: string; icon: ReactNode; colour: string }> = {
  publish: { label: 'Approve to publish', icon: <Clapperboard size={18} />, colour: '#f97316' },
  step_approval: { label: 'Step waiting for your OK', icon: <CheckCircle2 size={18} />, colour: '#f59e0b' },
  review_gate: { label: 'Production waiting for your check', icon: <ShieldCheck size={18} />, colour: '#f59e0b' },
  director: { label: 'Studio Director asks', icon: <BellRing size={18} />, colour: '#a78bfa' },
  voice: { label: 'Needs your voice', icon: <Mic size={18} />, colour: '#fb7185' },
  shorts_record: { label: 'Shorts to record', icon: <Mic size={18} />, colour: '#94a3b8' },
};

function readSnoozed(): Record<string, number> {
  try {
    const raw = JSON.parse(localStorage.getItem(SNOOZE_KEY) || '{}') as Record<string, number>;
    const now = Date.now();
    return Object.fromEntries(Object.entries(raw).filter(([, until]) => until > now));
  } catch {
    return {};
  }
}

function writeSnoozed(map: Record<string, number>) {
  try { localStorage.setItem(SNOOZE_KEY, JSON.stringify(map)); } catch { /* private window: not remembered */ }
}

function ago(iso?: string | null): string {
  if (!iso) return '';
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return '';
  const mins = Math.max(0, Math.round((Date.now() - t) / 60_000));
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  return hours < 48 ? `${hours} h ago` : `${Math.round(hours / 24)} days ago`;
}

export function NeedsYou() {
  const { navigate, toast, confirm } = useStudio();
  const [items, setItems] = useState<NeedsItem[]>([]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [snoozed, setSnoozed] = useState<Record<string, number>>(readSnoozed);
  const [showAll, setShowAll] = useState(false);
  const openRef = useRef(open);
  openRef.current = open;

  const load = useCallback(async () => {
    try {
      const r = await getJson<{ items: NeedsItem[] }>('/api/needs_you');
      const list = r.items || [];
      setItems(list);
      // Pop up by itself for a decision he has neither put off nor marked
      // seen; the Shorts summary alone never interrupts.
      const now = readSnoozed();
      setSnoozed(now);
      if (!openRef.current && list.some((i) => i.kind !== 'shorts_record' && !i.seen && !now[i.key])) {
        setShowAll(false);
        setOpen(true);
      }
    } catch {
      // Backend busy or restarting: keep what we had; the next poll catches up.
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), POLL_MS);
    const onFocus = () => void load();
    window.addEventListener('focus', onFocus);
    return () => { window.clearInterval(timer); window.removeEventListener('focus', onFocus); };
  }, [load]);

  const snooze = (keys: string[], ms: number) => {
    const next = { ...readSnoozed() };
    for (const k of keys) next[k] = Date.now() + ms;
    writeSnoozed(next);
    setSnoozed(next);
  };

  const close = () => {
    snooze(items.filter((i) => i.kind !== 'shorts_record' && !i.seen).map((i) => i.key), CLOSE_MS);
    setOpen(false);
  };

  const markSeen = async (keys: string[], seen: boolean) => {
    if (!keys.length) return;
    // Right away on screen; the backend's answer is the truth a moment later.
    setItems((list) => list.map((i) => (keys.includes(i.key) ? { ...i, seen } : i)));
    try {
      const r = await postJson<{ items: NeedsItem[] }>(seen ? '/api/needs_you/seen' : '/api/needs_you/unseen', { keys });
      if (r?.items) setItems(r.items);
    } catch (err) {
      toast(describeError(err), 'error');
      void load();
    }
  };

  const dismissAll = () => {
    void markSeen(items.filter((i) => !i.seen).map((i) => i.key), true);
    if (!showAll) setOpen(false);
  };

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') close(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  const goTo = (item: NeedsItem) => {
    navigate(item.tab);
    if (item.project_id) {
      // Projects stays mounted once opened; give it a tick to be visible first.
      window.setTimeout(() => window.dispatchEvent(new CustomEvent('buzzcaf:open-project', { detail: item.project_id })), 50);
    }
    setOpen(false);
  };

  const run = async (item: NeedsItem, action: NeedsAction) => {
    if (busy[item.key]) return;
    if (action.confirm && !(await confirm({ title: action.label, body: action.confirm, confirmLabel: action.label }))) return;
    let body = action.body;
    if (action.ask) {
      const reason = window.prompt(action.ask, '');
      if (reason === null) return;
      body = { ...body, reason };
    }
    setBusy((b) => ({ ...b, [item.key]: true }));
    const settle = () => {
      setItems((list) => list.filter((i) => i.key !== item.key));
      window.setTimeout(() => void load(), 3000);
    };
    try {
      if (action.background) {
        // A whole workflow step can run for minutes behind this call.
        postJson(action.path, body).catch((err) => toast(`${item.title}: ${describeError(err)}`, 'error'));
        toast(`${action.label}: started for “${item.title}”.`, 'success');
      } else {
        await postJson(action.path, body);
        toast(`${action.label}: done for “${item.title}”.`, 'success');
      }
      settle();
    } catch (err) {
      toast(describeError(err), 'error');
    } finally {
      setBusy((b) => ({ ...b, [item.key]: false }));
    }
  };

  const unseen = items.filter((i) => !i.seen);
  const seenCount = items.length - unseen.length;
  const shown = showAll ? items : unseen;
  const decisions = unseen.filter((i) => i.kind !== 'shorts_record');
  const waitingCount = decisions.length + unseen.filter((i) => i.kind === 'shorts_record').reduce((n, i) => n + (i.count || 0), 0);

  const openPopup = () => {
    // Everything already seen: open straight onto the full list.
    setShowAll(unseen.length === 0);
    setOpen(true);
  };

  return (
    <>
      {items.length > 0 && (
        <button type="button" className={`needs-you-badge${unseen.length ? '' : ' needs-you-badge-quiet'}`} onClick={openPopup}
          title="Things waiting for you: approvals, reviews, scripts that need your voice">
          <AlertTriangle size={16} />
          <span>{decisions.length > 0 ? `${decisions.length} waiting for you`
            : unseen.length > 0 ? `${waitingCount} to record` : `${items.length} pending (seen)`}</span>
        </button>
      )}

      {open && items.length > 0 && createPortal(
        <div className="needs-you-overlay" role="dialog" aria-modal="true" aria-label="Waiting for you" onClick={close}>
          <div className="needs-you-card" onClick={(e) => e.stopPropagation()}>
            <div className="needs-you-head">
              <AlertTriangle size={30} />
              <div style={{ flex: 1 }}>
                <div className="needs-you-title">Waiting for you</div>
                <div className="needs-you-sub">
                  {decisions.length > 0
                    ? `${decisions.length} thing${decisions.length === 1 ? '' : 's'} can't go on until you decide.`
                    : unseen.length > 0 ? 'Nothing to decide; just recordings when you have time.'
                      : 'Everything here is marked seen; it stays until it is done.'}
                </div>
              </div>
              <button type="button" className="needs-you-close" onClick={close} aria-label="Close (reminds you again in an hour)"
                title="Close; reminds you again in an hour">
                <X size={22} />
              </button>
            </div>

            <div className="needs-you-toolbar">
              {unseen.length > 0 && (
                <button type="button" className="needs-you-btn needs-you-btn-default" onClick={dismissAll}
                  title="Mark everything seen: it stops popping up, and stays under Show all pending until it is done">
                  <EyeOff size={14} /> Dismiss all
                </button>
              )}
              <span className="needs-you-spacer" />
              {seenCount > 0 && (
                <button type="button" className="needs-you-btn needs-you-btn-ghost" onClick={() => setShowAll((v) => !v)}>
                  <Eye size={14} /> {showAll ? 'Hide the seen ones' : `Show all pending (${items.length})`}
                </button>
              )}
            </div>

            <div className="needs-you-list">
              {shown.length === 0 && <div className="needs-you-empty">Nothing new. {seenCount} seen, still pending.</div>}
              {shown.map((item) => {
                const meta = KIND_META[item.kind];
                const later = Boolean(snoozed[item.key]);
                return (
                  <div key={item.key} className="needs-you-item" style={{ borderLeftColor: meta.colour, opacity: item.seen || later ? 0.6 : 1 }}>
                    <div className="needs-you-kind" style={{ color: meta.colour }}>
                      {meta.icon} {meta.label}
                      {item.seen && <span className="needs-you-later"><Eye size={12} /> seen</span>}
                      {!item.seen && later && <span className="needs-you-later"><Clock size={12} /> put off</span>}
                    </div>
                    <div className="needs-you-name">{item.title}</div>
                    <div className="needs-you-meta">
                      {[item.brand, ago(item.since)].filter(Boolean).join(' · ')}
                    </div>
                    <div className="needs-you-what">{item.what}</div>
                    <div className="needs-you-actions">
                      {item.actions.map((a) => (
                        <button key={a.label} type="button" disabled={!!busy[item.key]}
                          className={`needs-you-btn needs-you-btn-${a.style}`} onClick={() => void run(item, a)}>
                          {a.label}
                        </button>
                      ))}
                      <button type="button" className="needs-you-btn needs-you-btn-default" onClick={() => goTo(item)}>
                        {item.kind === 'shorts_record' ? 'Open the Shorts' : 'Open'}
                      </button>
                      {item.kind !== 'shorts_record' && !item.seen && (
                        <button type="button" className="needs-you-btn needs-you-btn-ghost"
                          onClick={() => snooze([item.key], LATER_MS)} title="Hide this one for 2 hours">
                          Later
                        </button>
                      )}
                      {item.seen ? (
                        <button type="button" className="needs-you-btn needs-you-btn-ghost"
                          onClick={() => void markSeen([item.key], false)} title="Put it back in the pop-up">
                          Bring back
                        </button>
                      ) : (
                        <button type="button" className="needs-you-btn needs-you-btn-ghost"
                          onClick={() => void markSeen([item.key], true)}
                          title="I've seen it: stop popping up; it stays under Show all pending until it is done">
                          <Check size={14} /> Seen it
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>,
        document.body,
      )}
    </>
  );
}
