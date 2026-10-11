import { useCallback, useEffect, useRef, useState } from 'react';
import { CheckCircle2, Copy, FileText, Layers, Loader2, Mic, PenLine, Plus, RefreshCw, Save, Sparkles, Trash2, Upload } from 'lucide-react';
import { useStudio } from '../state/studio';
import { deleteJson, describeError, getJson, postForm, postJson, putJson } from '../services/api';

/* The creator's own writing style, per channel (backend/app/services/writing_style.py).
 * Every agent that writes a script, story, edit or narration pass for the
 * channel gets it as "The Creator's Own Writing Style", and every script is
 * scored against it (one automatic rewrite below 75/100). It learns from his
 * own writing (pasted or uploaded here) and from what he actually said in
 * each produced video (kept automatically after every production).
 * A channel can keep several saved styles, each with its own samples, profile
 * and rules; the selected one is what the agents write in, and everything on
 * this page shows and edits that one. */

const CHANNELS = ['Raat3Baje', 'Beyond3Baje', 'Khayal3Baje', 'Life3Baje', 'Originals'];

type Sample = { id: string; kind: 'written' | 'spoken'; title: string; words: number; added: string };
type Fingerprint = Record<string, unknown> & { phrases?: string[]; source?: string; words?: number };
type SavedStyle = { id: string; name: string; active: boolean; written: number; spoken: number; built_at: string | null };
type Overview = {
  channel: string; samples: Sample[]; profile: string; notes: string; fingerprint: Fingerprint;
  rewrites: number; built_at: string | null; stale: boolean; mode?: 'mine' | 'agent'; skipped?: string[];
  harvest?: { projects_with_recordings: number; kept: string[] };
  style?: string; styles?: SavedStyle[];
};
type ChannelRow = {
  channel: string; mode?: 'mine' | 'agent'; written: number; spoken: number; built_at: string | null; stale: boolean;
  style_name?: string; styles?: number;
};
type CheckResult = { score: number; fixes: string[] };

const pct = (v: unknown) => (typeof v === 'number' ? `${Math.round(v * 100)}%` : '–');
const num = (v: unknown) => (typeof v === 'number' ? String(v) : '–');

export default function WritingStyle() {
  const { toast } = useStudio();
  const [channel, setChannel] = useState('Raat3Baje');
  const [rows, setRows] = useState<ChannelRow[]>([]);
  const [view, setView] = useState<Overview | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [sampleTitle, setSampleTitle] = useState('');
  const [sampleText, setSampleText] = useState('');
  const [profile, setProfile] = useState('');
  const [notes, setNotes] = useState('');
  const [checkText, setCheckText] = useState('');
  const [checkResult, setCheckResult] = useState<CheckResult | null>(null);
  const [styleName, setStyleName] = useState('');
  const fileRef = useRef<HTMLInputElement>(null);

  const show = useCallback((v: Overview) => {
    setView(v);
    setProfile(v.profile || '');
    setNotes(v.notes || '');
  }, []);

  const load = useCallback(async (ch: string) => {
    try {
      show(await getJson<Overview>(`/api/style/${ch}`));
      setRows((await getJson<{ channels: ChannelRow[] }>('/api/style')).channels);
    } catch (err) {
      toast(describeError(err), 'error');
    }
  }, [show, toast]);

  useEffect(() => { setCheckResult(null); load(channel); }, [channel, load]);

  const run = async (key: string, action: () => Promise<Overview | void>, done?: string) => {
    setBusy(key);
    try {
      const result = await action();
      if (result) show(result);
      setRows((await getJson<{ channels: ChannelRow[] }>('/api/style')).channels);
      if (done) toast(done, 'success');
    } catch (err) {
      toast(describeError(err), 'error');
    } finally {
      setBusy(null);
    }
  };

  const addSample = () => run('add', async () => {
    const v = await postJson<Overview>(`/api/style/${channel}/samples`, { title: sampleTitle, text: sampleText });
    setSampleTitle(''); setSampleText('');
    return v;
  }, 'Sample added. The profile is rebuilt before the next script (or rebuild it now).');

  const upload = (files: FileList | null) => {
    if (!files || !files.length) return;
    run('upload', async () => {
      const form = new FormData();
      Array.from(files).forEach((f) => form.append('files', f));
      const v = await postForm<Overview>(`/api/style/${channel}/upload`, form);
      if (v.skipped?.length) toast(`Skipped: ${v.skipped.join('; ')}`, 'info');
      return v;
    }, 'Uploaded. The profile is rebuilt before the next script (or rebuild it now).');
    if (fileRef.current) fileRef.current.value = '';
  };

  const harvest = () => run('harvest', async () => {
    const v = await postJson<Overview>(`/api/style/${channel}/harvest`, {});
    const h = v.harvest;
    toast(h && h.kept.length ? `Learned from ${h.kept.length} recording(s).` : 'No produced videos with a recording for this channel yet.',
      h && h.kept.length ? 'success' : 'info');
    return v;
  });

  const build = () => run('build', () => postJson<Overview>(`/api/style/${channel}/build`, {}), 'Style profile rebuilt.');
  const saveProfile = () => run('profile', () => putJson<Overview>(`/api/style/${channel}/profile`, { text: profile }), 'Profile saved.');
  const saveNotes = () => run('notes', () => putJson<Overview>(`/api/style/${channel}/notes`, { text: notes }), 'Your rules saved.');
  const remove = (s: Sample) => {
    if (!window.confirm(`Remove "${s.title}" from ${channel}'s style samples?`)) return;
    run('remove', () => deleteJson<Overview>(`/api/style/${channel}/samples/${s.id}`), 'Sample removed.');
  };
  const setMode = (mode: 'mine' | 'agent') => run('mode', () => putJson<Overview>(`/api/style/${channel}/mode`, { mode }),
    mode === 'mine' ? `${channel}: agents now write in your style.` : `${channel}: agents now write in their own style.`);
  const styles = view?.styles || [];
  const activeStyle = styles.find((s) => s.active);
  const pickStyle = (s: SavedStyle) => {
    if (s.active) return;
    setCheckResult(null);
    run('style', () => putJson<Overview>(`/api/style/${channel}/styles/active`, { id: s.id }),
      `${channel} now writes in "${s.name}".`);
  };
  const newStyle = (copyCurrent: boolean) => run('style', async () => {
    const v = await postJson<Overview>(`/api/style/${channel}/styles`, { name: styleName, copy_current: copyCurrent });
    setStyleName('');
    return v;
  }, copyCurrent ? 'Saved a copy as a new style and selected it.' : 'New empty style selected: add samples to it below.');
  const renameStyle = () => activeStyle && run('style', async () => {
    const v = await putJson<Overview>(`/api/style/${channel}/styles/${activeStyle.id}`, { name: styleName });
    setStyleName('');
    return v;
  }, 'Style renamed.');
  const deleteStyle = () => {
    if (!activeStyle || activeStyle.id === 'default') return;
    if (!window.confirm(`Delete the style "${activeStyle.name}" with its samples, profile and rules? This cannot be undone.`)) return;
    run('style', () => deleteJson<Overview>(`/api/style/${channel}/styles/${activeStyle.id}`), 'Style deleted.');
  };
  const check = () => run('check', async () => {
    setCheckResult(await postJson<CheckResult>(`/api/style/${channel}/check`, { text: checkText }));
  });

  const fp = view?.fingerprint || {};
  const written = view?.samples.filter((s) => s.kind === 'written') || [];
  const spoken = view?.samples.filter((s) => s.kind === 'spoken') || [];
  const spin = (key: string) => (busy === key ? <Loader2 size={14} className="spin" /> : null);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      <div className="panel-card">
        <h3 className="panel-title"><PenLine size={22} /> Writing style</h3>
        <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: 0 }}>
          How you write and talk, per channel. Every agent that writes a script, story, edit or narration for the
          channel gets this as <b>The Creator&apos;s Own Writing Style</b>, and every script is scored against it
          (below 75/100 it is rewritten once toward your style). It learns from your own writing, which you add
          here, and from what you actually said in every produced video, which is kept automatically.
          More of your own writing makes it more accurate.
        </p>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {CHANNELS.map((ch) => {
            const row = rows.find((r) => r.channel === ch);
            return (
              <button key={ch} type="button" className={`btn ${ch === channel ? '' : 'btn-outline'}`} onClick={() => setChannel(ch)}
                title={row ? `${row.style_name ? `Style: ${row.style_name}. ` : ''}${row.written} written, ${row.spoken} recorded sample(s)${row.built_at ? `; profile built ${row.built_at}` : '; no profile yet'}` : ch}>
                {ch}
                {row && (row.written + row.spoken > 0) && (
                  <span style={{ fontSize: '0.72rem', opacity: 0.8, marginLeft: 6 }}>
                    {row.written}✎ {row.spoken}🎙{row.built_at && !row.stale ? ' ✓' : ''}{row.mode === 'agent' ? ' · agent' : ''}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      <div className="panel-card">
        <h3 className="panel-title"><Layers size={20} /> Saved styles for {channel}</h3>
        <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: 0 }}>
          Keep several styles and pick the one to write in. Each has its own samples, profile and rules; everything
          below shows the selected one, and scripts for {channel} are written in it.
        </p>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }} role="radiogroup" aria-label={`Saved styles for ${channel}`}>
          {styles.map((s) => (
            <button key={s.id} type="button" role="radio" aria-checked={s.active} disabled={!!busy}
              className={`btn ${s.active ? '' : 'btn-outline'}`} onClick={() => pickStyle(s)}
              title={`${s.written} written, ${s.spoken} recorded sample(s)${s.built_at ? `; profile built ${s.built_at}` : '; no profile yet'}`}>
              {s.active ? <CheckCircle2 size={14} /> : null}
              <span>{s.name}</span>
              <span style={{ fontSize: '0.72rem', opacity: 0.8, marginLeft: 6 }}>{s.written}✎ {s.spoken}🎙</span>
            </button>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginTop: 10 }}>
          <input className="form-control" style={{ maxWidth: 260 }} placeholder="Style name, e.g. Podcast storyteller" maxLength={60}
            aria-label="Style name" value={styleName} onChange={(e) => setStyleName(e.target.value)} />
          <button type="button" className="btn btn-outline" disabled={!!busy || !styleName.trim()} onClick={() => newStyle(false)}
            title="Start a new, empty style with this name and select it">
            {spin('style') || <Plus size={14} />}<span>New empty style</span>
          </button>
          <button type="button" className="btn btn-outline" disabled={!!busy || !styleName.trim()} onClick={() => newStyle(true)}
            title="Save the selected style (samples, profile, rules) under this name, and select the copy">
            <Copy size={14} /><span>Save a copy of “{activeStyle?.name ?? 'Default'}”</span>
          </button>
          <button type="button" className="btn btn-outline" disabled={!!busy || !styleName.trim() || !activeStyle} onClick={renameStyle}
            title="Give the selected style this name">
            <PenLine size={14} /><span>Rename selected</span>
          </button>
          <button type="button" className="btn btn-outline" disabled={!!busy || !activeStyle || activeStyle.id === 'default'} onClick={deleteStyle}
            title={activeStyle?.id === 'default' ? 'The default style cannot be deleted; remove its samples instead' : 'Delete the selected style'}>
            <Trash2 size={14} /><span>Delete selected</span>
          </button>
        </div>
      </div>

      <div className="panel-card">
        <h3 className="panel-title"><Sparkles size={20} /> Who {channel} is written by</h3>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }} role="radiogroup" aria-label={`Writing style for ${channel}`}>
          {([['mine', 'My style', 'Agents match your own writing: the style section, the score and one rewrite below 75/100.'],
             ['agent', 'Agent style', 'Agents write in their own way, following only the channel guide. Nothing is scored or rewritten toward your style.']] as const)
            .map(([mode, label, hint]) => (
              <button key={mode} type="button" role="radio" aria-checked={(view?.mode ?? 'mine') === mode} title={hint}
                className={`btn ${(view?.mode ?? 'mine') === mode ? '' : 'btn-outline'}`} disabled={!!busy || !view}
                onClick={() => setMode(mode)}>
                {busy === 'mode' && (view?.mode ?? 'mine') !== mode ? <Loader2 size={14} className="spin" /> : null}
                <span>{label}</span>
              </button>
            ))}
          <span style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
            {(view?.mode ?? 'mine') === 'mine'
              ? (view?.samples.length ? 'Every script for this channel is written and checked in your style.' : 'My style is on, but there is nothing to learn from yet: add samples below.')
              : 'Agents use the channel guide only. Your samples and profile are kept for when you switch back.'}
            {' '}A project can override this on the Projects page.
          </span>
        </div>
      </div>

      <div className="panel-card">
        <h3 className="panel-title"><FileText size={20} /> Samples for {channel}{activeStyle ? ` · ${activeStyle.name}` : ''}</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 16 }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <b style={{ fontSize: '0.85rem' }}>Add your own writing</b>
            <input className="form-control" placeholder="Title (optional)" value={sampleTitle} onChange={(e) => setSampleTitle(e.target.value)} />
            <textarea className="form-control" rows={8} value={sampleText} onChange={(e) => setSampleText(e.target.value)}
              placeholder="Paste a story, script or post you wrote yourself, exactly as you would write it (at least 40 words). Several different pieces teach it best." />
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <button type="button" className="btn" disabled={!!busy || sampleText.trim().split(/\s+/).length < 40} onClick={addSample}>
                {spin('add')}<span>Add sample</span>
              </button>
              <button type="button" className="btn btn-outline" disabled={!!busy} onClick={() => fileRef.current?.click()}>
                {spin('upload') || <Upload size={14} />}<span>Upload .txt / .md</span>
              </button>
              <input ref={fileRef} type="file" accept=".txt,.md" multiple hidden onChange={(e) => upload(e.target.files)} />
              <button type="button" className="btn btn-outline" disabled={!!busy} onClick={harvest}
                title="Keep what you said in every produced video of this channel (new productions are kept automatically)">
                {spin('harvest') || <Mic size={14} />}<span>Learn from my recordings</span>
              </button>
            </div>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <b style={{ fontSize: '0.85rem' }}>{written.length} written · {spoken.length} recorded · {view?.rewrites ?? 0} rephrasings</b>
            {!view?.samples.length && (
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>No samples yet in this style.</div>
            )}
            {view?.samples.map((s) => (
              <div key={s.id} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.8rem', padding: '4px 8px', border: '1px solid var(--border-subtle, rgba(255,255,255,0.08))', borderRadius: 6 }}>
                {s.kind === 'written' ? <PenLine size={14} /> : <Mic size={14} />}
                <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={s.title}>{s.title}</span>
                <span style={{ color: 'var(--text-muted)' }}>{s.words} words</span>
                <button type="button" aria-label={`Remove ${s.title}`} disabled={!!busy} onClick={() => remove(s)}
                  style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', display: 'inline-flex' }}>
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
            {spoken.length > 0 && (
              <div style={{ fontSize: '0.74rem', color: 'var(--text-muted)' }}>
                Recordings are speech-to-text: they teach your phrasing, openings and habits, while sentence
                measurements come from your written samples.
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="panel-card">
        <h3 className="panel-title"><Sparkles size={20} /> Style profile</h3>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 8 }}>
          <button type="button" className="btn" disabled={!!busy || !view?.samples.length} onClick={build}
            title="StyleAnalyst studies every sample and writes the guide (uses Claude when it is available; about a minute)">
            {spin('build') || <RefreshCw size={14} />}<span>{view?.profile ? 'Rebuild profile' : 'Build profile'}</span>
          </button>
          <span style={{ fontSize: '0.78rem', color: view?.stale ? '#f59e0b' : 'var(--text-muted)' }}>
            {view?.built_at ? `Built ${view.built_at}` : 'Not built yet'}
            {view?.stale && view?.samples.length ? ' · new samples since — rebuilt automatically before the next script, or rebuild now' : ''}
          </span>
        </div>
        {fp.words ? (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 14, fontSize: '0.78rem', color: 'var(--text-secondary)', marginBottom: 10 }}>
            <span>Measured from {fp.source === 'written' ? 'your writing' : 'your recordings'} ({num(fp.words)} words):</span>
            {fp.sentence_avg !== undefined && <span>avg sentence {num(fp.sentence_avg)} words</span>}
            {fp.short_share !== undefined && <span>short sentences {pct(fp.short_share)}</span>}
            <span>English in the mix {pct(fp.english_share)}</span>
            <span>Devanagari {pct(fp.devanagari_share)}</span>
            <span>talks to viewer {num(fp.address_per_1000)}/1000 words</span>
            {fp.ellipsis_per_100 !== undefined && <span>“...” {num(fp.ellipsis_per_100)}/100 sentences</span>}
            {!!fp.phrases?.length && <span>phrases: {fp.phrases.slice(0, 6).map((p) => `“${p}”`).join(', ')}</span>}
          </div>
        ) : null}
        <textarea className="form-control" rows={16} value={profile} onChange={(e) => setProfile(e.target.value)}
          placeholder="Build the profile from your samples. You can then edit it; Rebuild replaces it (your own rules below are never replaced)."
          style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: '0.8rem' }} />
        <div style={{ marginTop: 8 }}>
          <button type="button" className="btn btn-outline" disabled={!!busy || profile === (view?.profile || '')} onClick={saveProfile}>
            {spin('profile') || <Save size={14} />}<span>Save profile edits</span>
          </button>
        </div>
      </div>

      <div className="panel-card">
        <h3 className="panel-title"><PenLine size={20} /> Your own rules for {channel}</h3>
        <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: 0 }}>
          Always included, above the profile, and never overwritten. A line <code>Never use: word, word</code> is
          also enforced by the style check, and a line <code>Greeting: ...</code> replaces the fixed greeting every
          full script opens with (your name and the channel&apos;s).
        </p>
        <textarea className="form-control" rows={6} value={notes} onChange={(e) => setNotes(e.target.value)}
          placeholder={'e.g.\n- Greeting: Hello doston, mera naam hai Sudhansu aur aap dekh rahe hain Raat 3 Baje.\n- Never use: bhayanak, khaufnak, rongte khade'} />
        <div style={{ marginTop: 8 }}>
          <button type="button" className="btn btn-outline" disabled={!!busy || notes === (view?.notes || '')} onClick={saveNotes}>
            {spin('notes') || <Save size={14} />}<span>Save my rules</span>
          </button>
        </div>
      </div>

      <div className="panel-card">
        <h3 className="panel-title"><CheckCircle2 size={20} /> Check a draft</h3>
        <textarea className="form-control" rows={6} value={checkText} onChange={(e) => setCheckText(e.target.value)}
          placeholder="Paste a script to see how close it is to your style (at least 60 words)." />
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginTop: 8, flexWrap: 'wrap' }}>
          <button type="button" className="btn btn-outline" disabled={!!busy || checkText.trim().split(/\s+/).length < 60} onClick={check}>
            {spin('check') || <CheckCircle2 size={14} />}<span>Check</span>
          </button>
          {checkResult && (
            <b style={{ color: checkResult.score >= 75 ? '#34d399' : checkResult.score >= 55 ? '#f59e0b' : '#f87171' }}>
              {checkResult.score}/100
            </b>
          )}
        </div>
        {checkResult && (
          <ul style={{ fontSize: '0.82rem', marginTop: 8 }}>
            {checkResult.fixes.length ? checkResult.fixes.map((f) => <li key={f}>{f}</li>) : <li>Close to your style.</li>}
          </ul>
        )}
      </div>
    </div>
  );
}
