import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ClipboardCopy, ClipboardPaste, FileUp, Loader2, Save, X } from 'lucide-react';

/* The teleprompter's script, out for rectifying and back in. Edit it here, or
 * copy it out (to fix it elsewhere) and paste or load the changed version
 * back. Saving replaces the project's script asset -- the backend keeps the
 * old text under history/ -- and the teleprompter reads the new one at once.
 *
 * Keys typed here never reach the teleprompter (whose Escape would close it
 * and drop the edit); Escape here asks before discarding changes. */

type Props = {
  title: string;
  text: string;
  onSave: (text: string) => Promise<void>;
  onClose: () => void;
  onToast: (text: string, kind?: 'success' | 'error' | 'info') => void;
};

const BTN = {
  color: '#e5e7eb', borderColor: 'rgba(255,255,255,0.3)', padding: '5px 12px', fontSize: '0.8rem',
  display: 'inline-flex', alignItems: 'center', gap: 6,
} as const;

const words = (s: string) => (s.match(/\S+/g) || []).length;

export default function ScriptEditor({ title, text, onSave, onClose, onToast }: Props) {
  const [draft, setDraft] = useState(text);
  const [saving, setSaving] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const areaRef = useRef<HTMLTextAreaElement>(null);
  const dirty = draft !== text;

  useEffect(() => { areaRef.current?.focus(); }, []);

  const close = () => {
    if (dirty && !window.confirm('Discard your changes to the script?')) return;
    onClose();
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(draft);
      onToast('Script copied. Fix it anywhere, then paste it back here.', 'success');
    } catch {
      areaRef.current?.select();
      onToast('Could not reach the clipboard; the text is selected, press Ctrl+C.', 'info');
    }
  };

  const replaceWith = (next: string, from: string) => {
    if (!next.trim()) { onToast(`${from} is empty.`, 'error'); return; }
    if (dirty && !window.confirm(`Replace your unsaved edits with the text from ${from.toLowerCase()}?`)) return;
    setDraft(next.replace(/\r\n/g, '\n'));
    onToast(`Replaced with the text from ${from.toLowerCase()}. Check it, then save it back.`, 'info');
  };

  const pasteAll = async () => {
    try {
      replaceWith(await navigator.clipboard.readText(), 'Clipboard');
    } catch {
      onToast('Could not read the clipboard; click in the text, Ctrl+A, then Ctrl+V.', 'info');
    }
  };

  const loadFile = async (files: FileList | null) => {
    const f = files?.[0];
    if (fileRef.current) fileRef.current.value = '';
    if (!f) return;
    replaceWith(await f.text(), f.name);
  };

  const save = async () => {
    if (!draft.trim()) { onToast('The script is empty; nothing was saved.', 'error'); return; }
    setSaving(true);
    try {
      await onSave(draft);
      onClose();
    } catch {
      // onSave reports its own error; stay open so nothing is lost.
    } finally {
      setSaving(false);
    }
  };

  return createPortal(
    <div
      role="dialog" aria-label="Edit script"
      onKeyDown={(e) => {
        e.stopPropagation();
        if (e.key === 'Escape') { e.preventDefault(); close(); }
        if (e.key === 's' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); save(); }
      }}
      style={{ position: 'fixed', inset: 0, zIndex: 5100, background: 'rgba(0,0,0,0.92)', display: 'flex', flexDirection: 'column', padding: 16, gap: 10 }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', color: '#e5e7eb' }}>
        <strong style={{ marginRight: 'auto' }}>Edit script — {title}</strong>
        <button type="button" className="btn btn-outline btn-sm" style={BTN} onClick={copy} title="Copy the whole script to fix it in another app">
          <ClipboardCopy size={14} /> Copy all
        </button>
        <button type="button" className="btn btn-outline btn-sm" style={BTN} onClick={pasteAll} title="Replace the script with your corrected version from the clipboard">
          <ClipboardPaste size={14} /> Paste to replace
        </button>
        <button type="button" className="btn btn-outline btn-sm" style={BTN} onClick={() => fileRef.current?.click()} title="Replace the script with a corrected .txt / .md file">
          <FileUp size={14} /> Load file…
        </button>
        <input ref={fileRef} type="file" accept=".txt,.md,text/plain,text/markdown" hidden onChange={(e) => loadFile(e.target.files)} />
        <button type="button" className="btn btn-primary btn-sm" style={{ ...BTN, color: undefined, borderColor: undefined }}
          onClick={save} disabled={saving || !dirty} title="Save back to the project (Ctrl+S); the teleprompter uses it at once. The old version is kept.">
          {saving ? <Loader2 size={14} className="spin" /> : <Save size={14} />} Save back
        </button>
        <button type="button" className="btn btn-outline btn-sm" style={BTN} onClick={close} title="Close (Esc)">
          <X size={14} /> Cancel
        </button>
      </div>
      <textarea
        ref={areaRef}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        spellCheck
        style={{
          flex: 1, width: '100%', resize: 'none', background: '#0b0b0f', color: '#f3f4f6',
          border: '1px solid rgba(255,255,255,0.2)', borderRadius: 8, padding: 16,
          fontSize: '1.05rem', lineHeight: 1.6, fontFamily: 'inherit',
        }}
      />
      <div style={{ color: '#9ca3af', fontSize: '0.78rem' }}>
        {words(draft)} words{dirty ? ` (was ${words(text)}) · unsaved changes` : ''} · cues like (pause), (slow), [pause 2s] still drive the scroll
      </div>
    </div>,
    document.body,
  );
}
