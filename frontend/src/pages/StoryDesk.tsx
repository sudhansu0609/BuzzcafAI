import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Archive, ArchiveRestore, BookOpen, CalendarClock, ChevronDown, ChevronRight, Clapperboard, Copy, FolderOpen, Loader2, Maximize2, Minimize2, Play, Plus, RefreshCw, Save, Search, Trash2, Video, Volume2, Wand2 } from 'lucide-react';
import { useStudio } from '../state/studio';
import { getJson, postJson, deleteJson, describeError } from '../services/api';
import { CHANNEL_META } from '../lib/channels';
import { ART_STYLES } from '../lib/artStyles';
import type {
  AdaptJob, AdaptStatus, AutoStoryFormat, AutoStoryJob, AutoStoryRecord, AutoStorySettings,
  InstagramStatusResponse, NarrationJobStatus, StoryCandidate, StoryEntry, StoryJob, StoryPiece, StoryRights,
  VoiceMood, VoiceStyle,
} from '../lib/types';

// The Story Desk (AUTO_STORY_PLAN.md §3.6): videos made end to end by the
// tool in the creator's voice -- Instagram reels and audio stories that open
// on his face-intro clip. Script, narration, take, production, publish.

// Raat3Baje/SCP narrated reels are 1 minute (2026-10-23 night rules, VR7); a length is a
// target, not a cap (REELS_DESK_PLAN.md VR9 creator follow-up, 2026-10-24), so 90 seconds,
// 2 minutes and 3 minutes are offered too.
const REEL_LENGTHS = ['1 minute (60 seconds)', '90 seconds', '2 minutes', '3 minutes', '75 seconds (Short)'];
const LONG_STORY = 'long_story';
// A mood reel (REELS_DESK_PLAN.md §6): no face, no voice -- it has its own
// length/style pickers (from /api/auto_story/formats) and a visual theme.
const MOOD_REEL = 'mood_reel';
// 15-30s (2026-10-23 night rules, VR7: supersedes the earlier 15-45 range).
const MOOD_REEL_LENGTHS = ['15 seconds', '20 seconds', '26 seconds', '30 seconds'];
const MOOD_REEL_DEFAULT_LENGTH = '26 seconds';

const STATE_COLOURS: Record<string, string> = {
  running: '#38bdf8',
  ready: '#a78bfa',
  published: '#34d399',
  packaged: '#f59e0b',
  failed: '#f87171',
};

function usePoll() {
  const timer = useRef<number | null>(null);
  useEffect(() => () => { if (timer.current) window.clearInterval(timer.current); }, []);
  return useCallback((jobId: string, onUpdate: (j: AutoStoryJob) => void) => {
    if (timer.current) window.clearInterval(timer.current);
    timer.current = window.setInterval(async () => {
      try {
        const j = await getJson<AutoStoryJob>(`/api/auto_story/jobs/${jobId}`);
        onUpdate(j);
        if (j.state !== 'running' && timer.current) { window.clearInterval(timer.current); timer.current = null; }
      } catch { /* transient */ }
    }, 2000);
  }, []);
}

const copyText = async (text: string): Promise<boolean> => {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
};

// A posted entry is a URL, a note, a posted Instagram reel {permalink, media_id, at}
// (REELS_DESK_PLAN.md R7), or (since the reels skip YouTube) {skipped: why}: one
// record of that shape blanked the whole tab (2026-10-23).
function postedText(v: unknown): string {
  if (typeof v === 'string') return v;
  if (v && typeof v === 'object') {
    const o = v as Record<string, unknown>;
    return String(o.permalink ?? o.url ?? o.skipped ?? o.error ?? JSON.stringify(o));
  }
  return String(v ?? '');
}

// True once `posted.instagram` carries a permalink -- a packaging note
// ("packaged") or a failed posting attempt does not count.
function postedToInstagram(v: unknown): boolean {
  return Boolean(v && typeof v === 'object' && (v as Record<string, unknown>).permalink);
}

// The route Instagram posting resolves for this record: the "channel/format"
// route wins over the plain "channel" route (integrations/instagram_publish.py
// account_for) -- e.g. Life3Baje's mood reels route to a separate account
// from its ordinary reels.
function igRouteFor(status: InstagramStatusResponse | null, brand: string, format: string) {
  if (!status) return undefined;
  return status.routes[`${brand}/${format}`] || status.routes[brand];
}

export default function StoryDesk() {
  const { brands, selectedChannel, setSelectedChannel, toast } = useStudio();
  const [formats, setFormats] = useState<Record<string, AutoStoryFormat[]>>({});
  const [settings, setSettings] = useState<AutoStorySettings | null>(null);
  const [voices, setVoices] = useState<string[] | null>(null);
  const [moods, setMoods] = useState<VoiceMood[]>([]);
  const [records, setRecords] = useState<AutoStoryRecord[]>([]);
  const [fmt, setFmt] = useState('');
  const [reelLength, setReelLength] = useState(REEL_LENGTHS[0]);
  const [minutes, setMinutes] = useState(20);
  const [voice, setVoice] = useState('sudhansu');
  const [style, setStyle] = useState('real');
  const [theme, setTheme] = useState('');
  const [publish, setPublish] = useState(false);
  const [job, setJob] = useState<AutoStoryJob | null>(null);
  const [clipDrafts, setClipDrafts] = useState<Record<string, string>>({});
  const [noOpenRoute, setNoOpenRoute] = useState(false);
  const [igStatus, setIgStatus] = useState<InstagramStatusResponse | null>(null);
  const [posting, setPosting] = useState<Record<string, boolean>>({});
  const [retrying, setRetrying] = useState<Record<string, boolean>>({});
  const [reviewing, setReviewing] = useState<Record<string, boolean>>({});
  const [archivedFilter, setArchivedFilter] = useState<'active' | 'archived' | 'all'>('active');
  const [minimizedCards, setMinimizedCards] = useState<Record<string, boolean>>({});
  const [isPanelMinimized, setIsPanelMinimized] = useState<boolean>(false);
  const [deleting, setDeleting] = useState<Record<string, boolean>>({});
  const [archiving, setArchiving] = useState<Record<string, boolean>>({});
  const poll = usePoll();

  const channelOptions = useMemo(() => {
    const fromFormats = Object.keys(formats);
    if (fromFormats.length > 0) return fromFormats;
    return brands.length > 0 ? brands : CHANNEL_META.map((c) => c.id);
  }, [formats, brands]);
  const channelFormats = formats[selectedChannel] || [];
  const isLong = fmt === LONG_STORY;
  const isMoodReel = fmt === MOOD_REEL;
  const moodReelFormat = channelFormats.find((f) => f.key === MOOD_REEL);
  const moodReelLengths = moodReelFormat?.lengths?.length ? moodReelFormat.lengths : MOOD_REEL_LENGTHS;
  const moodReelStyles = ART_STYLES.filter((s) => (moodReelFormat?.styles || ['real', 'painterly', 'illustrated']).includes(s.id));
  const moodReelThemes = moodReelFormat?.themes || [];

  // A mood reel has its own length list and defaults to no theme (Auto, rotated).
  useEffect(() => {
    if (!isMoodReel) return;
    if (!moodReelLengths.includes(reelLength)) setReelLength(moodReelLengths.includes(MOOD_REEL_DEFAULT_LENGTH) ? MOOD_REEL_DEFAULT_LENGTH : moodReelLengths[0]);
    if (!moodReelStyles.some((s) => s.id === style)) setStyle(moodReelStyles[0]?.id || 'real');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isMoodReel]);

  const loadRecords = useCallback(async () => {
    try {
      const r = await getJson<{ records: AutoStoryRecord[] }>('/api/auto_story/records');
      setRecords(r.records || []);
    } catch { /* the list just stays as it was */ }
  }, []);

  useEffect(() => {
    getJson<{ channels: Record<string, AutoStoryFormat[]> }>('/api/auto_story/formats')
      .then((r) => setFormats(r.channels || {}))
      .catch((err) => toast(describeError(err), 'error'));
    getJson<AutoStorySettings>('/api/auto_story/settings')
      .then((s) => {
        setSettings(s);
        setClipDrafts(s.face_intro_clips || {});
        setPublish(!!s.publish);
        if (s.voice) setVoice(s.voice);
      })
      .catch(() => undefined);
    getJson<{ voices: string[] }>('/api/auto_story/voices')
      .then((r) => setVoices(r.voices && r.voices.length ? r.voices : null))
      .catch(() => setVoices(null));
    getJson<{ moods: VoiceMood[] }>('/api/auto_story/moods')
      .then((r) => setMoods(r.moods || []))
      .catch(() => setMoods([]));
    getJson<InstagramStatusResponse>('/api/instagram/status')
      .then(setIgStatus)
      .catch(() => setIgStatus(null));
    loadRecords();
  }, [toast, loadRecords]);

  // Keep the format valid for the channel.
  useEffect(() => {
    if (!channelFormats.some((f) => f.key === fmt)) setFmt(channelFormats[0]?.key || '');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedChannel, formats]);

  // Refresh the list every 20 s while anything is running.
  const anyRunning = records.some((r) => r.state === 'running');
  useEffect(() => {
    if (!anyRunning) return undefined;
    const t = window.setInterval(loadRecords, 20000);
    return () => window.clearInterval(t);
  }, [anyRunning, loadRecords]);

  const patchSettings = async (patch: Partial<AutoStorySettings>) => {
    try {
      const next = await postJson<AutoStorySettings>('/api/auto_story/settings', patch);
      setSettings(next);
      return next;
    } catch (err) {
      toast(describeError(err), 'error');
      return null;
    }
  };

  const make = async () => {
    if (job?.state === 'running' || !fmt) return;
    try {
      const j = await postJson<AutoStoryJob>('/api/auto_story/make', {
        channel: selectedChannel,
        format: fmt,
        length: isLong ? minutes : reelLength,
        voice,
        publish,
        style,
        theme: isMoodReel ? (theme || undefined) : undefined,
      });
      setJob(j);
      loadRecords();
      poll(j.job_id, (next) => {
        setJob(next);
        if (next.state === 'done') {
          toast('Auto story made.', 'success');
          loadRecords();
        } else if (next.state === 'failed') {
          toast(next.error || 'Auto story failed', 'error');
          loadRecords();
        }
      });
    } catch (err) {
      toast(describeError(err), 'error');
    }
  };

  const saveClip = async (brand: string) => {
    const path = (clipDrafts[brand] || '').trim();
    const next = await patchSettings({ face_intro_clips: { [brand]: path } });
    if (next) toast(`Face intro clip saved for ${brand}.`, 'success');
  };

  const copyPath = async (path: string) => {
    toast((await copyText(path)) ? 'Path copied.' : path, 'info');
  };

  const openPackage = async (rec: AutoStoryRecord) => {
    try {
      await postJson(`/api/auto_story/${encodeURIComponent(rec.project_id)}/open_package`, {});
    } catch {
      setNoOpenRoute(true);
      if (rec.package_dir) await copyPath(rec.package_dir);
    }
  };

  const postInstagram = async (rec: AutoStoryRecord) => {
    if (posting[rec.project_id]) return;
    setPosting((p) => ({ ...p, [rec.project_id]: true }));
    try {
      const result = await postJson<{ permalink?: string; error?: string }>(
        `/api/auto_story/${encodeURIComponent(rec.project_id)}/post_instagram`, {},
      );
      if (result.permalink) toast('Posted to Instagram.', 'success');
      else toast(result.error || 'Instagram refused the post.', 'error');
      loadRecords();
    } catch (err) {
      toast(describeError(err), 'error');
    } finally {
      setPosting((p) => ({ ...p, [rec.project_id]: false }));
    }
  };

  // Ask before publishing (STUDIO_DIRECTOR_PLAN.md; Fable review #10 /
  // enhancement 3): Approve / Reject here, same as the Dashboard's "Needs you".
  const approveRecord = async (rec: AutoStoryRecord) => {
    if (reviewing[rec.project_id]) return;
    setReviewing((r) => ({ ...r, [rec.project_id]: true }));
    try {
      await postJson(`/api/auto_story/${encodeURIComponent(rec.project_id)}/approve`, {});
      toast('Approved.', 'success');
      loadRecords();
    } catch (err) {
      toast(describeError(err), 'error');
    } finally {
      setReviewing((r) => ({ ...r, [rec.project_id]: false }));
    }
  };

  const rejectRecord = async (rec: AutoStoryRecord) => {
    if (reviewing[rec.project_id]) return;
    const reason = window.prompt('Reason for rejecting this?', '');
    if (reason === null) return;
    setReviewing((r) => ({ ...r, [rec.project_id]: true }));
    try {
      await postJson(`/api/auto_story/${encodeURIComponent(rec.project_id)}/reject`, { reason });
      toast('Rejected.', 'success');
      loadRecords();
    } catch (err) {
      toast(describeError(err), 'error');
    } finally {
      setReviewing((r) => ({ ...r, [rec.project_id]: false }));
    }
  };

  // A record a Studio restart left stuck (STUDIO_DIRECTOR_PLAN.md enhancement 2:
  // the startup sweep marks it failed "Studio restarted -- press Retry" when no
  // BuzzEdit job was still rendering it) -- `/run` on the same project id, so a
  // vibe reel resumes from the shots/narration already made rather than starting over.
  const retryRecord = async (rec: AutoStoryRecord) => {
    if (retrying[rec.project_id]) return;
    setRetrying((p) => ({ ...p, [rec.project_id]: true }));
    try {
      const j = await postJson<AutoStoryJob>(`/api/auto_story/${encodeURIComponent(rec.project_id)}/run`, {});
      poll(j.job_id, (next) => {
        if (next.state === 'done') { toast('Auto story made.', 'success'); loadRecords(); }
        else if (next.state === 'failed') { toast(next.error || 'Auto story failed', 'error'); loadRecords(); }
      });
      loadRecords();
    } catch (err) {
      toast(describeError(err), 'error');
    } finally {
      setRetrying((p) => ({ ...p, [rec.project_id]: false }));
    }
  };

  const deleteAutoStory = async (rec: AutoStoryRecord) => {
    if (deleting[rec.project_id]) return;
    const title = rec.name || rec.project_id;
    if (!window.confirm(`Permanently delete auto story "${title}"?\nThis removes all project files, narration, and renders.`)) return;
    setDeleting((d) => ({ ...d, [rec.project_id]: true }));
    try {
      try {
        await deleteJson(`/api/auto_story/${encodeURIComponent(rec.project_id)}`);
      } catch {
        await deleteJson(`/api/projects/${encodeURIComponent(rec.project_id)}`);
      }
      toast(`Deleted "${title}".`, 'success');
      loadRecords();
    } catch (err) {
      toast(describeError(err), 'error');
    } finally {
      setDeleting((d) => ({ ...d, [rec.project_id]: false }));
    }
  };

  const toggleArchiveAutoStory = async (rec: AutoStoryRecord) => {
    if (archiving[rec.project_id]) return;
    const nextArchived = !rec.archived;
    setArchiving((a) => ({ ...a, [rec.project_id]: true }));
    try {
      try {
        await postJson(`/api/auto_story/${encodeURIComponent(rec.project_id)}/archive`, { archived: nextArchived });
      } catch {
        await postJson(`/api/projects/${encodeURIComponent(rec.project_id)}/archive`, { archived: nextArchived });
      }
      toast(nextArchived ? 'Auto story archived.' : 'Auto story unarchived.', 'success');
      loadRecords();
    } catch (err) {
      toast(describeError(err), 'error');
    } finally {
      setArchiving((a) => ({ ...a, [rec.project_id]: false }));
    }
  };

  const toggleMinimizeCard = (projectId: string) => {
    setMinimizedCards((m) => ({ ...m, [projectId]: !m[projectId] }));
  };

  const running = job?.state === 'running';
  const sorted = [...records].sort((a, b) => (b.started_at || '').localeCompare(a.started_at || ''));
  const activeCount = records.filter((r) => !r.archived).length;
  const archivedCount = records.filter((r) => !!r.archived).length;
  const totalCount = records.length;

  const filteredRecords = sorted.filter((r) => {
    if (archivedFilter === 'active') return !r.archived;
    if (archivedFilter === 'archived') return !!r.archived;
    return true; // 'all'
  });

  const allVisibleMinimized = filteredRecords.length > 0 && filteredRecords.every((r) => !!minimizedCards[r.project_id]);

  const toggleMinimizeAll = () => {
    const nextState: Record<string, boolean> = { ...minimizedCards };
    for (const r of filteredRecords) {
      nextState[r.project_id] = !allVisibleMinimized;
    }
    setMinimizedCards(nextState);
  };

  const last = settings?.last as { ran_at?: string; made?: unknown[]; failed?: unknown[]; summary?: string } | null | undefined;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div className="panel-card" style={{ padding: '16px 20px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
          <div style={{ width: 40, height: 40, borderRadius: '50%', backgroundColor: 'var(--bg-pill)', border: '1px solid #fb7185', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fb7185' }}>
            <Clapperboard size={22} />
          </div>
          <div>
            <div style={{ fontSize: '1.05rem', fontWeight: 700, color: 'var(--text-primary)' }}>Story Desk</div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
              Videos made end to end in your voice: the agents find and write the story, the narration is converted to your voice, your face-intro clip opens it, and production and publishing run by themselves.
            </div>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.78rem', color: 'var(--text-muted)' }}>
            Channel
            <select className="form-control" style={{ width: 'auto', fontWeight: 700 }} value={selectedChannel} onChange={(e) => setSelectedChannel(e.target.value)} aria-label="Channel">
              {channelOptions.map((b) => <option key={b} value={b}>{b}</option>)}
            </select>
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.78rem', color: 'var(--text-muted)' }}>
            Format
            <select className="form-control" style={{ width: 'auto' }} value={fmt} onChange={(e) => setFmt(e.target.value)} aria-label="Format" disabled={channelFormats.length === 0}>
              {channelFormats.length === 0 && <option value="">No formats for this channel</option>}
              {channelFormats.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
            </select>
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.78rem', color: 'var(--text-muted)' }}>
            Length
            {isLong ? (
              <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <input type="number" className="form-control" aria-label="Minutes" min={3} max={120} value={minutes}
                  onChange={(e) => setMinutes(Math.max(3, Math.min(120, Number(e.target.value) || 3)))} style={{ width: 80 }} /> min
              </span>
            ) : (
              <select className="form-control" style={{ width: 'auto' }} value={reelLength} onChange={(e) => setReelLength(e.target.value)} aria-label="Length">
                {(isMoodReel ? moodReelLengths : REEL_LENGTHS).map((l) => <option key={l} value={l}>{l}</option>)}
              </select>
            )}
          </label>
          {isMoodReel && (
            <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.78rem', color: 'var(--text-muted)' }}>
              Theme
              <select className="form-control" style={{ width: 'auto' }} value={theme} onChange={(e) => setTheme(e.target.value)} aria-label="Theme">
                <option value="">Auto (rotates)</option>
                {moodReelThemes.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
              </select>
            </label>
          )}
          {!isMoodReel && (
            <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.78rem', color: 'var(--text-muted)' }}>
              Voice
              {voices ? (
                <select className="form-control" style={{ width: 'auto' }} value={voice} onChange={(e) => setVoice(e.target.value)} aria-label="Voice">
                  {(voices.includes(voice) ? voices : [voice, ...voices]).map((v) => <option key={v} value={v}>{v}</option>)}
                </select>
              ) : (
                <input className="form-control" aria-label="Voice" value={voice} onChange={(e) => setVoice(e.target.value)} style={{ width: 140 }} />
              )}
            </label>
          )}
          <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.78rem', color: 'var(--text-muted)' }}>
            Art style
            <select className="form-control" style={{ width: 'auto' }} value={style} onChange={(e) => setStyle(e.target.value)} aria-label="Art style">
              {(isMoodReel ? moodReelStyles : ART_STYLES).map((s) => <option key={s.id} value={s.id} title={s.hint}>{s.label}</option>)}
            </select>
          </label>
          <button type="button" className="btn" onClick={make} disabled={running || !fmt} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            {running ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> : <Play size={14} />}
            {running ? 'Making…' : 'Make one now'}
          </button>
        </div>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', marginTop: 10, fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
          <input type="checkbox" checked={publish} onChange={(e) => setPublish(e.target.checked)} />
          Upload to YouTube when done (Instagram always gets a package)
        </label>
        {job && (
          <div style={{ marginTop: 10, fontSize: '0.82rem', display: 'flex', alignItems: 'center', gap: 8, color: job.state === 'failed' ? '#f87171' : job.state === 'done' ? '#34d399' : 'var(--accent-primary)' }}>
            {running && <Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} />}
            {job.state === 'failed' ? job.error || job.message : job.message}
          </div>
        )}
      </div>

      <VoiceDeliveryPanel key={selectedChannel} channel={selectedChannel} moods={moods} settings={settings} patchSettings={patchSettings} toast={toast} />

      <div className="panel-card" style={{ padding: '16px 20px' }}>
        <h3 className="panel-title"><Video size={20} /> Face intro clip</h3>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.84rem', marginTop: 0 }}>
          The clip of you that opens every auto story on that channel; the rest is your voice over pictures.
        </p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {channelOptions.map((b) => (
            <div key={b} style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <span style={{ width: 110, fontWeight: 600, fontSize: '0.85rem' }}>{b}</span>
              <input className="form-control" aria-label={`Face intro clip for ${b}`} value={clipDrafts[b] || ''} placeholder={'D:\\Recordings\\intro.mp4'}
                onChange={(e) => setClipDrafts((d) => ({ ...d, [b]: e.target.value }))} style={{ flex: 1, minWidth: 260 }} />
              <button type="button" className="btn btn-outline" style={{ padding: '4px 10px', fontSize: '0.78rem' }}
                disabled={(clipDrafts[b] || '') === (settings?.face_intro_clips?.[b] || '')} onClick={() => saveClip(b)}>
                <Save size={13} style={{ marginRight: 4 }} /> Save
              </button>
            </div>
          ))}
        </div>
      </div>

      <div className="panel-card" style={{ padding: '16px 20px' }}>
        <h3 className="panel-title"><CalendarClock size={20} /> Nightly auto stories</h3>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.86rem', marginTop: 0 }}>
          Every night the nightly run makes this many auto stories per channel, rotating the formats, and puts them in the morning report.
        </p>
        {settings ? (
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center' }}>
            <label style={{ display: 'flex', gap: 8, alignItems: 'center', cursor: 'pointer' }}>
              <input type="checkbox" aria-label="Nightly auto stories enabled" checked={settings.enabled} onChange={(e) => patchSettings({ enabled: e.target.checked })} style={{ width: 18, height: 18 }} />
              <strong>{settings.enabled ? 'On' : 'Off'}</strong>
            </label>
            {channelOptions.map((b) => (
              <label key={b} style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: '0.85rem' }}>
                {b}
                <input type="number" className="form-control" aria-label={`Per night for ${b}`} min={0} max={5} value={settings.per_channel?.[b] ?? 0}
                  onChange={(e) => patchSettings({ per_channel: { ...(settings.per_channel || {}), [b]: Math.max(0, Math.min(5, Number(e.target.value) || 0)) } })} style={{ width: 70 }} />
              </label>
            ))}
            <label style={{ display: 'flex', gap: 6, alignItems: 'center', cursor: 'pointer', fontSize: '0.85rem' }}>
              <input type="checkbox" aria-label="Nightly upload to YouTube" checked={settings.publish} onChange={(e) => patchSettings({ publish: e.target.checked })} />
              Upload to YouTube
            </label>
          </div>
        ) : (
          <div style={{ fontSize: '0.84rem', color: 'var(--text-muted)' }}>Settings not loaded.</div>
        )}
        {settings?.last_run && (
          <div style={{ marginTop: 12, fontSize: '0.84rem', color: 'var(--text-secondary)' }}>
            Last run {settings.last_run}
            {last?.summary ? `: ${last.summary}` : ''}
            {Array.isArray(last?.made) ? ` · ${last!.made!.length} made` : ''}
            {Array.isArray(last?.failed) && last!.failed!.length > 0 ? ` · ${last!.failed!.length} failed` : ''}
          </div>
        )}
      </div>

      <div className="panel-card" style={{ padding: '16px 20px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 12, flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <button
              type="button"
              onClick={() => setIsPanelMinimized((p) => !p)}
              style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center' }}
              title={isPanelMinimized ? 'Expand panel' : 'Minimise panel'}
            >
              {isPanelMinimized ? <ChevronRight size={18} /> : <ChevronDown size={18} />}
            </button>
            <h3 className="panel-title" style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
              <Clapperboard size={20} /> Auto stories
              <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)', fontWeight: 500 }}>
                ({totalCount})
              </span>
            </h3>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            {/* Filter pills: Active / Archived / All */}
            <div style={{ display: 'inline-flex', padding: 2, borderRadius: 6, background: 'var(--bg-app)', border: '1px solid var(--border-subtle)' }}>
              <button
                type="button"
                onClick={() => setArchivedFilter('active')}
                style={{
                  padding: '2px 9px',
                  fontSize: '0.74rem',
                  fontWeight: 600,
                  border: 'none',
                  borderRadius: 4,
                  cursor: 'pointer',
                  background: archivedFilter === 'active' ? 'var(--bg-pill)' : 'transparent',
                  color: archivedFilter === 'active' ? 'var(--text-primary)' : 'var(--text-muted)',
                }}
              >
                Active ({activeCount})
              </button>
              <button
                type="button"
                onClick={() => setArchivedFilter('archived')}
                style={{
                  padding: '2px 9px',
                  fontSize: '0.74rem',
                  fontWeight: 600,
                  border: 'none',
                  borderRadius: 4,
                  cursor: 'pointer',
                  background: archivedFilter === 'archived' ? 'var(--bg-pill)' : 'transparent',
                  color: archivedFilter === 'archived' ? 'var(--text-primary)' : 'var(--text-muted)',
                }}
              >
                Archived ({archivedCount})
              </button>
              <button
                type="button"
                onClick={() => setArchivedFilter('all')}
                style={{
                  padding: '2px 9px',
                  fontSize: '0.74rem',
                  fontWeight: 600,
                  border: 'none',
                  borderRadius: 4,
                  cursor: 'pointer',
                  background: archivedFilter === 'all' ? 'var(--bg-pill)' : 'transparent',
                  color: archivedFilter === 'all' ? 'var(--text-primary)' : 'var(--text-muted)',
                }}
              >
                All ({totalCount})
              </button>
            </div>

            {/* Minimise / Expand all button */}
            {filteredRecords.length > 0 && !isPanelMinimized && (
              <button
                type="button"
                className="btn btn-outline"
                style={{ padding: '3px 8px', fontSize: '0.74rem', display: 'inline-flex', alignItems: 'center', gap: 5 }}
                onClick={toggleMinimizeAll}
                title={allVisibleMinimized ? 'Expand all stories' : 'Minimise all stories'}
              >
                {allVisibleMinimized ? <Maximize2 size={12} /> : <Minimize2 size={12} />}
                {allVisibleMinimized ? 'Expand all' : 'Minimise all'}
              </button>
            )}

            <button type="button" className="btn btn-outline" style={{ padding: '3px 8px', fontSize: '0.74rem' }} onClick={loadRecords} title="Reload"><RefreshCw size={12} /></button>
          </div>
        </div>

        {!isPanelMinimized && (
          <>
            {filteredRecords.length === 0 ? (
              <div style={{ fontSize: '0.84rem', color: 'var(--text-secondary)' }}>
                {archivedFilter === 'archived'
                  ? 'No archived stories.'
                  : 'None made yet. Press “Make one now”, or switch the nightly run on.'}
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {filteredRecords.map((r) => {
                  const colour = STATE_COLOURS[r.state] || 'var(--text-secondary)';
                  const formatLabel = (formats[r.brand] || []).find((f) => f.key === r.format)?.label || r.format;
                  const isMinimized = !!minimizedCards[r.project_id];
                  const isDeleting = !!deleting[r.project_id];
                  const isArchiving = !!archiving[r.project_id];

                  return (
                    <div
                      key={r.project_id}
                      style={{
                        padding: isMinimized ? '8px 12px' : '10px 14px',
                        borderRadius: 8,
                        border: '1px solid var(--border-card)',
                        borderLeft: `3px solid ${colour}`,
                        background: r.archived ? 'var(--bg-card-muted, rgba(255,255,255,0.02))' : 'var(--bg-card)',
                        opacity: r.archived ? 0.8 : 1,
                        transition: 'all 0.2s ease',
                      }}
                    >
                      {/* Card Header Row */}
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', flex: 1, minWidth: 260 }}>
                          <button
                            type="button"
                            onClick={() => toggleMinimizeCard(r.project_id)}
                            style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center' }}
                            title={isMinimized ? 'Expand story details' : 'Minimise story'}
                          >
                            {isMinimized ? <ChevronRight size={16} /> : <ChevronDown size={16} />}
                          </button>

                          <span style={{ fontSize: '0.72rem', fontWeight: 700, color: colour, backgroundColor: 'var(--bg-pill)', padding: '2px 8px', borderRadius: 4, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                            {r.state === 'running' && <Loader2 size={11} style={{ animation: 'spin 1s linear infinite' }} />}
                            {r.state}
                          </span>

                          {r.archived && (
                            <span style={{ fontSize: '0.72rem', fontWeight: 600, color: 'var(--text-muted)', background: 'rgba(255,255,255,0.06)', border: '1px solid var(--border-subtle)', padding: '1px 6px', borderRadius: 4 }}>
                              Archived
                            </span>
                          )}

                          <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{r.name || r.project_id}</span>
                          <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{r.brand} · {formatLabel}</span>
                          {r.started_at && <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{new Date(r.started_at).toLocaleString()}</span>}
                        </div>

                        {/* Action buttons on card header: Archive/Unarchive, Delete */}
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          {/* Archive / Unarchive Button */}
                          <button
                            type="button"
                            className="btn btn-outline"
                            style={{ padding: '2px 8px', fontSize: '0.73rem', display: 'inline-flex', alignItems: 'center', gap: 4, color: r.archived ? '#38bdf8' : 'var(--text-secondary)' }}
                            disabled={isArchiving}
                            onClick={() => toggleArchiveAutoStory(r)}
                            title={r.archived ? 'Unarchive auto story (restore to active)' : 'Archive auto story'}
                          >
                            {isArchiving ? <Loader2 size={11} style={{ animation: 'spin 1s linear infinite' }} /> : r.archived ? <ArchiveRestore size={11} /> : <Archive size={11} />}
                            {r.archived ? 'Unarchive' : 'Archive'}
                          </button>

                          {/* Delete Button */}
                          <button
                            type="button"
                            className="btn btn-outline"
                            style={{ padding: '2px 8px', fontSize: '0.73rem', display: 'inline-flex', alignItems: 'center', gap: 4, color: '#f87171' }}
                            disabled={isDeleting}
                            onClick={() => deleteAutoStory(r)}
                            title="Permanently delete auto story"
                          >
                            {isDeleting ? <Loader2 size={11} style={{ animation: 'spin 1s linear infinite' }} /> : <Trash2 size={11} />}
                            Delete
                          </button>
                        </div>
                      </div>

                      {/* Body only shown when NOT minimized */}
                      {!isMinimized && (
                        <div style={{ marginTop: 8 }}>
                          {r.final && (
                            <div style={{ marginTop: 6, fontSize: '0.8rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                              Final: <code style={{ fontSize: '0.78rem' }}>{r.final}</code>
                              <button type="button" className="btn btn-outline" style={{ padding: '1px 6px', fontSize: '0.72rem' }} onClick={() => copyPath(r.final!)} title="Copy the path"><Copy size={11} /></button>
                            </div>
                          )}
                          {(r.posted?.youtube || r.posted?.instagram) && (
                            <div style={{ marginTop: 4, fontSize: '0.8rem', color: 'var(--text-secondary)', display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                              {r.posted.youtube && (
                                postedText(r.posted.youtube).startsWith('http')
                                  ? <a href={postedText(r.posted.youtube)} target="_blank" rel="noreferrer" style={{ color: '#38bdf8', textDecoration: 'none' }}>YouTube</a>
                                  : <span>YouTube: {postedText(r.posted.youtube)}</span>
                              )}
                              {r.posted.instagram && (
                                postedToInstagram(r.posted.instagram)
                                  ? <a href={postedText(r.posted.instagram)} target="_blank" rel="noreferrer" style={{ color: '#f472b6', textDecoration: 'none' }}>Instagram</a>
                                  : <span>Instagram: {postedText(r.posted.instagram)}</span>
                              )}
                            </div>
                          )}
                          {r.review && (
                            <div style={{ marginTop: 6, fontSize: '0.8rem', display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                              <span style={{
                                fontSize: '0.72rem', fontWeight: 700, borderRadius: 999, padding: '1px 8px',
                                color: r.review.state === 'approved' ? '#34d399' : r.review.state === 'rejected' ? '#f87171' : '#f59e0b',
                                border: `1px solid ${r.review.state === 'approved' ? '#34d399' : r.review.state === 'rejected' ? '#f87171' : '#f59e0b'}`,
                              }}>
                                {r.review.state === 'approved' ? 'Approved' : r.review.state === 'rejected' ? 'Rejected' : 'Needs you'}
                              </span>
                              {r.review.state === 'rejected' && r.review.reason && <span style={{ color: 'var(--text-secondary)' }}>{r.review.reason}</span>}
                              {r.review.state !== 'approved' && (
                                <button type="button" className="btn btn-outline" style={{ padding: '2px 10px', fontSize: '0.76rem' }}
                                  disabled={!!reviewing[r.project_id]} onClick={() => approveRecord(r)}>Approve</button>
                              )}
                              {r.review.state !== 'rejected' && (
                                <button type="button" className="btn btn-outline" style={{ padding: '2px 10px', fontSize: '0.76rem' }}
                                  disabled={!!reviewing[r.project_id]} onClick={() => rejectRecord(r)}>Reject</button>
                              )}
                            </div>
                          )}
                          {r.package_dir && !postedToInstagram(r.posted?.instagram) && (() => {
                            const route = igRouteFor(igStatus, r.brand, r.format);
                            const notApproved = r.review?.state !== 'approved';
                            return (
                            <div style={{ marginTop: 6, fontSize: '0.8rem' }}>
                              <button
                                type="button"
                                className="btn btn-outline"
                                style={{ padding: '3px 10px', fontSize: '0.76rem' }}
                                disabled={!!posting[r.project_id] || !route?.connected || notApproved}
                                title={notApproved ? 'Approve this first (above) before it can post.'
                                  : route?.connected ? undefined
                                  : route
                                  ? `Connect ${route.account}'s Instagram account under Settings -> Instagram first.`
                                  : `No Instagram account is routed for ${r.brand}/${r.format} -- add one under Settings -> Instagram.`}
                                onClick={() => postInstagram(r)}
                              >
                                {posting[r.project_id] ? <Loader2 size={13} style={{ marginRight: 4, animation: 'spin 1s linear infinite' }} />
                                  : null}
                                {posting[r.project_id] ? 'Posting…' : 'Post to Instagram'}
                              </button>
                            </div>
                            );
                          })()}
                          {r.package_dir && (
                            <div style={{ marginTop: 6, fontSize: '0.8rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                              {!noOpenRoute && (
                                <button type="button" className="btn btn-outline" style={{ padding: '3px 10px', fontSize: '0.76rem' }} onClick={() => openPackage(r)}>
                                  <FolderOpen size={13} style={{ marginRight: 4 }} /> Open package
                                </button>
                              )}
                              <code style={{ fontSize: '0.78rem' }}>{r.package_dir}</code>
                              <button type="button" className="btn btn-outline" style={{ padding: '1px 6px', fontSize: '0.72rem' }} onClick={() => copyPath(r.package_dir!)} title="Copy the path"><Copy size={11} /></button>
                            </div>
                          )}
                          {r.state === 'failed' && (
                            <div style={{ marginTop: 6, fontSize: '0.8rem', color: '#f87171', display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                              {r.error && <span>{r.error}</span>}
                              <button
                                type="button"
                                className="btn btn-outline"
                                style={{ padding: '2px 10px', fontSize: '0.76rem' }}
                                disabled={!!retrying[r.project_id]}
                                onClick={() => retryRecord(r)}
                              >
                                {retrying[r.project_id] ? <Loader2 size={12} style={{ marginRight: 4, animation: 'spin 1s linear infinite' }} /> : null}
                                {retrying[r.project_id] ? 'Retrying…' : 'Retry'}
                              </button>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </>
        )}
      </div>

      <StoryLibraryPanel />
    </div>
  );
}

// ──────────────────────────── Story Library (AUTO_STORY_PLAN.md §7, L3) ────────────────────────────
// Find a story (Gutenberg, Wikisource, Archive, the web), add it to the
// library with its rights verdict, and adapt it into the creator's style.

const STORY_LANGUAGES: { id: string; label: string }[] = [
  { id: 'any', label: 'Any language' },
  { id: 'en', label: 'English' },
  { id: 'hi', label: 'Hindi' },
  { id: 'mr', label: 'Marathi' },
  { id: 'bn', label: 'Bengali' },
  { id: 'ur', label: 'Urdu' },
];
const STORY_SOURCES: { id: string; label: string }[] = [
  { id: 'any', label: 'Any source' },
  { id: 'gutenberg', label: 'Gutenberg' },
  { id: 'wikisource', label: 'Wikisource' },
  { id: 'archive', label: 'Internet Archive' },
  { id: 'web', label: 'Web' },
];

const labelStyle = { display: 'flex', flexDirection: 'column' as const, gap: 4, fontSize: '0.78rem', color: 'var(--text-muted)' };
const spinStyle = { animation: 'spin 1s linear infinite' };

// A poller for one job at a time; stops on any state but "running".
function useJobPoll<T extends { state: string }>() {
  const timer = useRef<number | null>(null);
  useEffect(() => () => { if (timer.current) window.clearInterval(timer.current); }, []);
  return useCallback((url: string, onUpdate: (j: T) => void) => {
    if (timer.current) window.clearInterval(timer.current);
    timer.current = window.setInterval(async () => {
      try {
        const j = await getJson<T>(url);
        onUpdate(j);
        if (j.state !== 'running' && timer.current) { window.clearInterval(timer.current); timer.current = null; }
      } catch { /* transient */ }
    }, 2000);
  }, []);
}

// ──────────────────────────── Voice and delivery (VOICE_DELIVERY_PLAN.md S2) ────────────────────────────
// Per-channel mood, pacing and dramatic-moments settings, sent as `style`
// with every auto-story narration (S1); Preview plays a sample line (or the
// creator's own text) through BuzzEdit so he can hear a setting before saving it.

const DRAMATIC_LEVELS: { id: 'off' | 'subtle' | 'strong'; label: string }[] = [
  { id: 'off', label: 'Off' },
  { id: 'subtle', label: 'Subtle' },
  { id: 'strong', label: 'Strong' },
];
const DEFAULT_VOICE_STYLE: VoiceStyle = { mood: 'steady', dramatic: 'subtle' };

function SliderRow({ label, value, min, max, step, onChange }: {
  label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void;
}) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.78rem', color: 'var(--text-muted)' }}>
      <span>{label}: <strong style={{ color: 'var(--text-primary)' }}>{value}</strong></span>
      <input type="range" aria-label={label} min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(Number(e.target.value))} style={{ width: '100%', maxWidth: 420 }} />
    </label>
  );
}

function VoiceDeliveryPanel({ channel, moods, settings, patchSettings, toast }: {
  channel: string;
  moods: VoiceMood[];
  settings: AutoStorySettings | null;
  patchSettings: (patch: Partial<AutoStorySettings>) => Promise<AutoStorySettings | null>;
  toast: (msg: string, kind?: 'info' | 'success' | 'error') => void;
}) {
  const saved = settings?.voice_style?.[channel];
  const [open, setOpen] = useState(false);
  const [style, setStyleState] = useState<VoiceStyle>(
    saved && Object.keys(saved).length > 0 ? { ...DEFAULT_VOICE_STYLE, ...saved } : { ...DEFAULT_VOICE_STYLE },
  );
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const [previewText, setPreviewText] = useState('');
  const [previewJob, setPreviewJob] = useState<NarrationJobStatus | null>(null);
  const [previewAudioUrl, setPreviewAudioUrl] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const poll = useJobPoll<NarrationJobStatus>();

  const preset = useMemo(() => moods.find((m) => m.id === style.mood)?.style || {}, [moods, style.mood]);
  const valueOf = (key: keyof VoiceStyle, fallback: number): number =>
    (style[key] as number | undefined) ?? (preset[key as string] as number | undefined) ?? fallback;

  const setMood = (mood: string) => {
    setStyleState({ mood, dramatic: style.dramatic || 'subtle' });
    setTouched({});
  };
  const setSlider = (key: keyof VoiceStyle, value: number) => {
    setStyleState((s) => ({ ...s, [key]: value }));
    setTouched((t) => ({ ...t, [key]: true }));
  };
  const setDramatic = (dramatic: 'off' | 'subtle' | 'strong') => setStyleState((s) => ({ ...s, dramatic }));

  // Only the keys the user set, plus mood and dramatic (VOICE_DELIVERY_PLAN.md S1).
  const styleForSend = (): VoiceStyle => {
    const out: VoiceStyle = { mood: style.mood || 'steady', dramatic: style.dramatic || 'subtle' };
    (Object.keys(touched) as (keyof VoiceStyle)[]).forEach((key) => {
      if (touched[key] && style[key] != null) (out as Record<string, unknown>)[key] = style[key];
    });
    return out;
  };

  const save = async () => {
    setSaving(true);
    try {
      const next = await patchSettings({ voice_style: { [channel]: styleForSend() } });
      if (next) toast(`Voice and delivery saved for ${channel}.`, 'success');
    } finally {
      setSaving(false);
    }
  };

  const previewing = previewJob?.state === 'running';
  const preview = async () => {
    setPreviewAudioUrl(null);
    try {
      const started = await postJson<{ job_id: string }>('/api/auto_story/voice_preview', {
        channel, text: previewText.trim() || undefined, style: styleForSend(),
      });
      setPreviewJob({ job_id: started.job_id, state: 'running' });
      poll(`/api/auto_story/voice_preview/${started.job_id}`, (next) => {
        setPreviewJob(next);
        if (next.state === 'done') setPreviewAudioUrl(`/api/auto_story/voice_preview/${started.job_id}/audio`);
        else if (next.state === 'failed') toast(next.message || 'Preview failed.', 'error');
      });
    } catch (err) {
      toast(describeError(err), 'error');
    }
  };

  // Steadiness is shown and dragged the other way round from temperature:
  // higher steadiness = lower temperature (VOICE_DELIVERY_PLAN.md S2).
  const steadiness = Math.round((1.4 - valueOf('temperature', 0.8)) * 100) / 100;
  const setSteadiness = (v: number) => setSlider('temperature', Math.round((1.4 - v) * 100) / 100);

  return (
    <div className="panel-card" style={{ padding: '16px 20px' }}>
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
        style={{ display: 'flex', alignItems: 'center', gap: 8, background: 'none', border: 'none', cursor: 'pointer', padding: 0, width: '100%', textAlign: 'left' }}>
        {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        <h3 className="panel-title" style={{ margin: 0 }}><Volume2 size={20} /> Voice and delivery</h3>
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>{channel}</span>
      </button>
      {open && (
        <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
            <label style={labelStyle}>
              Mood
              <select className="form-control" style={{ width: 'auto' }} value={style.mood || 'steady'} onChange={(e) => setMood(e.target.value)} aria-label="Mood">
                {moods.length === 0 && <option value={style.mood || 'steady'}>{style.mood || 'steady'}</option>}
                {moods.map((m) => <option key={m.id} value={m.id} title={m.description}>{m.label}</option>)}
              </select>
            </label>
            <label style={labelStyle}>
              Dramatic moments
              <select className="form-control" style={{ width: 'auto' }} value={style.dramatic || 'subtle'}
                onChange={(e) => setDramatic(e.target.value as 'off' | 'subtle' | 'strong')} aria-label="Dramatic moments">
                {DRAMATIC_LEVELS.map((d) => <option key={d.id} value={d.id}>{d.label}</option>)}
              </select>
            </label>
          </div>

          <SliderRow label="Tempo" value={valueOf('pace', 1.0)} min={0.7} max={1.3} step={0.01} onChange={(v) => setSlider('pace', v)} />
          <SliderRow label="Word spacing (ms)" value={valueOf('word_gap_ms', 40)} min={0} max={200} step={5} onChange={(v) => setSlider('word_gap_ms', v)} />
          <SliderRow label="Comma pause (s)" value={valueOf('phrase_pause_s', 0.25)} min={0} max={1.0} step={0.05} onChange={(v) => setSlider('phrase_pause_s', v)} />
          <SliderRow label="Sentence pause (s)" value={valueOf('sentence_pause_s', 0.45)} min={0} max={1.5} step={0.05} onChange={(v) => setSlider('sentence_pause_s', v)} />
          <SliderRow label="Expressiveness" value={valueOf('exaggeration', 0.5)} min={0.2} max={1.2} step={0.05} onChange={(v) => setSlider('exaggeration', v)} />
          <SliderRow label="Steadiness (higher = steadier, lower temperature)" value={steadiness} min={0.4} max={1.0} step={0.05} onChange={setSteadiness} />

          <label style={labelStyle}>
            Preview text (optional)
            <textarea className="form-control" aria-label="Preview text" rows={2} placeholder="Leave empty for a sample horror line..."
              value={previewText} onChange={(e) => setPreviewText(e.target.value)} style={{ minWidth: 280, maxWidth: 480, resize: 'vertical' }} />
          </label>

          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <button type="button" className="btn btn-outline" onClick={preview} disabled={previewing} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              {previewing ? <Loader2 size={14} style={spinStyle} /> : <Play size={14} />}
              {previewing ? 'Previewing…' : 'Preview'}
            </button>
            <button type="button" className="btn" onClick={save} disabled={saving} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <Save size={14} /> {saving ? 'Saving…' : `Save for ${channel}`}
            </button>
            {previewJob?.state === 'failed' && (
              <span style={{ fontSize: '0.8rem', color: '#f87171' }}>{previewJob.message || 'Preview failed.'}</span>
            )}
          </div>
          {previewAudioUrl && <audio controls src={previewAudioUrl} style={{ width: '100%', maxWidth: 420 }} />}
        </div>
      )}
    </div>
  );
}

const rightsOf = (r: StoryRights | string | null | undefined, deathYear?: number | null): StoryRights => {
  if (!r) return { status: 'unknown', death_year: deathYear ?? null };
  if (typeof r === 'string') return { status: r, death_year: deathYear ?? null };
  return { ...r, death_year: r.death_year ?? deathYear ?? null };
};

const isPublicDomain = (r: StoryRights) => r.status === 'public_domain';

function RightsBadge({ rights }: { rights: StoryRights }) {
  let colour = '#94a3b8';
  let text = 'Rights unknown: treated as protected';
  if (rights.status === 'public_domain') {
    colour = '#34d399';
    text = rights.death_year ? `Public domain, died ${rights.death_year}` : 'Public domain';
  } else if (rights.status === 'protected') {
    colour = '#f59e0b';
    text = 'Protected: inspired-by only';
  }
  return (
    <span title={rights.note || undefined} style={{ fontSize: '0.72rem', fontWeight: 700, color: colour, border: `1px solid ${colour}`, backgroundColor: 'var(--bg-pill)', padding: '2px 8px', borderRadius: 4 }}>
      {text}
    </span>
  );
}

function StoryLibraryPanel() {
  const { toast } = useStudio();
  const [query, setQuery] = useState('');
  const [language, setLanguage] = useState('any');
  const [author, setAuthor] = useState('');
  const [source, setSource] = useState('any');
  const [searchJob, setSearchJob] = useState<StoryJob<StoryCandidate[]> | null>(null);
  const [candidates, setCandidates] = useState<StoryCandidate[]>([]);
  const [adding, setAdding] = useState<Record<string, boolean>>({});
  const [added, setAdded] = useState<Record<string, number>>({});
  const [entries, setEntries] = useState<StoryEntry[]>([]);
  const poll = useJobPoll<StoryJob<StoryCandidate[]>>();

  const loadLibrary = useCallback(async () => {
    try {
      const r = await getJson<{ entries: StoryEntry[] }>('/api/stories/library');
      setEntries(r.entries || []);
    } catch (err) {
      toast(describeError(err), 'error');
    }
  }, [toast]);

  useEffect(() => { loadLibrary(); }, [loadLibrary]);

  const searching = searchJob?.state === 'running';

  const search = async () => {
    if (searching) return;
    if (!query.trim() && !author.trim()) {
      toast('Type a query or an author.', 'info');
      return;
    }
    try {
      const j = await postJson<StoryJob<StoryCandidate[]>>('/api/stories/search', {
        query: query.trim(), language, author: author.trim(), source, limit: 12,
      });
      setSearchJob(j);
      setCandidates([]);
      const finish = (next: StoryJob<StoryCandidate[]>) => {
        setSearchJob(next);
        if (next.state === 'done') {
          const rows = Array.isArray(next.result) ? next.result : [];
          setCandidates(rows);
          if (rows.length === 0) toast('No stories found.', 'info');
        } else if (next.state === 'failed') {
          toast(next.error || 'Search failed', 'error');
        }
      };
      if (j.state === 'running') poll(`/api/stories/jobs/${j.job_id}`, finish);
      else finish(j);
    } catch (err) {
      toast(describeError(err), 'error');
    }
  };

  const addToLibrary = async (c: StoryCandidate) => {
    const key = c.url || `${c.title}|${c.author}`;
    if (adding[key]) return;
    setAdding((a) => ({ ...a, [key]: true }));
    try {
      const entry = await postJson<StoryEntry>('/api/stories/fetch', { candidate: c });
      setAdded((a) => ({ ...a, [key]: entry.words || 0 }));
      toast(`Added "${entry.title || c.title}" (${(entry.words || 0).toLocaleString()} words).`, 'success');
      loadLibrary();
    } catch (err) {
      toast(describeError(err), 'error');
    } finally {
      setAdding((a) => ({ ...a, [key]: false }));
    }
  };

  const sortedEntries = [...entries].sort((a, b) => (b.fetched_at || '').localeCompare(a.fetched_at || ''));

  return (
    <div className="panel-card" style={{ padding: '16px 20px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
        <h3 className="panel-title" style={{ margin: 0 }}><BookOpen size={20} /> Story Library</h3>
        <button type="button" className="btn btn-outline" style={{ padding: '2px 8px', fontSize: '0.74rem' }} onClick={loadLibrary} title="Reload"><RefreshCw size={12} /></button>
      </div>
      <p style={{ color: 'var(--text-secondary)', fontSize: '0.84rem', marginTop: 6 }}>
        Public-domain authors (died before 1966, for India) are translated and adapted; protected writers are inspiration only (an original story), and the mode is recorded on the project.
      </p>

      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <label style={{ ...labelStyle, flex: 1, minWidth: 220 }}>
          Query
          <input className="form-control" aria-label="Story query" value={query} placeholder="ghost story, haunted house, chudail..."
            onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') search(); }} />
        </label>
        <label style={labelStyle}>
          Language
          <select className="form-control" style={{ width: 'auto' }} value={language} onChange={(e) => setLanguage(e.target.value)} aria-label="Story language">
            {STORY_LANGUAGES.map((l) => <option key={l.id} value={l.id}>{l.label}</option>)}
          </select>
        </label>
        <label style={labelStyle}>
          Author
          <input className="form-control" aria-label="Story author" value={author} placeholder="Premchand"
            onChange={(e) => setAuthor(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') search(); }} style={{ width: 180 }} />
        </label>
        <label style={labelStyle}>
          Source
          <select className="form-control" style={{ width: 'auto' }} value={source} onChange={(e) => setSource(e.target.value)} aria-label="Story source">
            {STORY_SOURCES.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
          </select>
        </label>
        <button type="button" className="btn" onClick={search} disabled={searching} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          {searching ? <Loader2 size={14} style={spinStyle} /> : <Search size={14} />}
          {searching ? 'Searching...' : 'Search'}
        </button>
      </div>
      {searchJob && searchJob.state !== 'done' && (
        <div style={{ marginTop: 8, fontSize: '0.82rem', display: 'flex', alignItems: 'center', gap: 8, color: searchJob.state === 'failed' ? '#f87171' : 'var(--accent-primary)' }}>
          {searching && <Loader2 size={13} style={spinStyle} />}
          {searchJob.state === 'failed' ? searchJob.error || searchJob.message : searchJob.message}
        </div>
      )}

      {candidates.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 12 }}>
          {candidates.map((c, i) => {
            const key = c.url || `${c.title}|${c.author}`;
            const rights = rightsOf(c.rights, c.death_year);
            const words = added[key];
            return (
              <div key={`${key}-${i}`} style={{ padding: '10px 14px', borderRadius: 8, border: '1px solid var(--border-card)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{c.title || 'Untitled'}</span>
                  <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                    {c.author || 'Unknown author'} · {c.language || '?'} · {c.source}
                    {c.words_estimate ? ` · ~${c.words_estimate.toLocaleString()} words` : ''}
                  </span>
                  <RightsBadge rights={rights} />
                  {c.url && <a href={c.url} target="_blank" rel="noreferrer" style={{ fontSize: '0.78rem', color: '#38bdf8', textDecoration: 'none' }}>source</a>}
                </div>
                {c.snippet && <div style={{ marginTop: 6, fontSize: '0.82rem', color: 'var(--text-secondary)' }}>{c.snippet}</div>}
                <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 8 }}>
                  <button type="button" className="btn btn-outline" style={{ padding: '3px 10px', fontSize: '0.76rem', display: 'inline-flex', alignItems: 'center', gap: 4 }}
                    disabled={!!adding[key] || words !== undefined} onClick={() => addToLibrary(c)}>
                    {adding[key] ? <Loader2 size={13} style={spinStyle} /> : <Plus size={13} />}
                    {adding[key] ? 'Adding...' : words !== undefined ? 'In library' : 'Add to library'}
                  </button>
                  {words !== undefined && <span style={{ fontSize: '0.8rem', color: '#34d399' }}>{words.toLocaleString()} words</span>}
                </div>
              </div>
            );
          })}
        </div>
      )}

      <h4 style={{ margin: '18px 0 8px', fontSize: '0.92rem', color: 'var(--text-primary)' }}>Library</h4>
      {sortedEntries.length === 0 ? (
        <div style={{ fontSize: '0.84rem', color: 'var(--text-secondary)' }}>No stories yet. Search above and add one.</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {sortedEntries.map((e) => <LibraryEntryRow key={e.id} entry={e} onDeleted={loadLibrary} />)}
        </div>
      )}
    </div>
  );
}

function LibraryEntryRow({ entry, onDeleted }: { entry: StoryEntry; onDeleted: () => void }) {
  const { toast, confirm, navigate } = useStudio();
  const rights = rightsOf(entry.rights);
  const publicDomain = isPublicDomain(rights);
  const [open, setOpen] = useState(false);
  const [parts, setParts] = useState(1);
  const [minutesPerPart, setMinutesPerPart] = useState(20);
  const [inspiredChoice, setInspiredChoice] = useState(false);
  const [pieces, setPieces] = useState<StoryPiece[]>([]);
  const [piece, setPiece] = useState(0);
  const [job, setJob] = useState<AdaptJob | null>(null);
  const [status, setStatus] = useState<AdaptStatus | null>(null);
  const poll = useJobPoll<AdaptJob>();
  const inspired = publicDomain ? inspiredChoice : true;

  useEffect(() => {
    getJson<{ pieces: StoryPiece[] }>(`/api/stories/adapt/pieces/${encodeURIComponent(entry.id)}`)
      .then((r) => {
        const list = r.pieces || [];
        setPieces(list);
        if (list.length > 0) setPiece(list[0].index);
      })
      .catch(() => setPieces([]));
  }, [entry.id]);

  const projectIdOf = (j: AdaptJob | null) => j?.project_id || j?.result?.project_id || '';

  const loadStatus = useCallback(async (projectId: string) => {
    if (!projectId) return;
    try {
      setStatus(await getJson<AdaptStatus>(`/api/stories/adapt/${encodeURIComponent(projectId)}`));
    } catch { /* the steps just stay as they were */ }
  }, []);

  const running = job?.state === 'running';

  const adapt = async () => {
    if (running) return;
    try {
      const body: Record<string, unknown> = {
        entry_id: entry.id, parts, minutes_per_part: minutesPerPart, inspired, run: true,
      };
      if (pieces.length > 1) body.story_index = piece;
      const j = await postJson<AdaptJob>('/api/stories/adapt', body);
      setJob(j);
      setStatus(null);
      const pid = projectIdOf(j);
      if (pid) loadStatus(pid);
      if (j.job_id && j.state === 'running') {
        poll(`/api/stories/adapt/jobs/${j.job_id}`, (next) => {
          setJob(next);
          loadStatus(projectIdOf(next) || pid);
          if (next.state === 'done') toast('Adaptation ready.', 'success');
          else if (next.state === 'failed') toast(next.error || 'Adaptation failed', 'error');
        });
      }
    } catch (err) {
      toast(describeError(err), 'error');
    }
  };

  const remove = async () => {
    const yes = await confirm({
      title: `Delete "${entry.title}"?`,
      body: 'The story and its text are removed from the library. Projects made from it stay.',
      confirmLabel: 'Delete',
      danger: true,
    });
    if (!yes) return;
    try {
      await deleteJson(`/api/stories/library/${encodeURIComponent(entry.id)}`);
      toast('Story deleted.', 'success');
      onDeleted();
    } catch (err) {
      toast(describeError(err), 'error');
    }
  };

  const projectId = projectIdOf(job) || status?.project_id || '';
  const firstLines = Array.isArray(entry.first_lines) ? entry.first_lines.join('\n') : entry.first_lines || '';
  const steps = status?.steps || [];

  return (
    <div style={{ padding: '10px 14px', borderRadius: 8, border: '1px solid var(--border-card)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <button type="button" className="btn btn-outline" style={{ padding: '1px 6px', fontSize: '0.72rem' }} onClick={() => setOpen((o) => !o)} aria-label={open ? 'Hide first lines' : 'Show first lines'}>
          {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        </button>
        <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{entry.title || entry.id}</span>
        <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
          {entry.author || 'Unknown author'} · {entry.language || '?'} · {entry.source} · {(entry.words || 0).toLocaleString()} words
        </span>
        <RightsBadge rights={rights} />
        {entry.fetched_at && <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{new Date(entry.fetched_at).toLocaleString()}</span>}
        <span style={{ flex: 1 }} />
        <button type="button" className="btn btn-outline" style={{ padding: '2px 8px', fontSize: '0.74rem' }} onClick={remove} title="Delete from the library"><Trash2 size={12} /></button>
      </div>
      {entry.summary && <div style={{ marginTop: 6, fontSize: '0.82rem', color: 'var(--text-secondary)' }}>{entry.summary}</div>}
      {open && (
        <div style={{ marginTop: 6, fontSize: '0.82rem', color: 'var(--text-secondary)', whiteSpace: 'pre-wrap', borderLeft: '2px solid var(--border-card)', paddingLeft: 10 }}>
          {firstLines || 'No preview.'}
          {entry.source_url && (
            <div style={{ marginTop: 4 }}><a href={entry.source_url} target="_blank" rel="noreferrer" style={{ color: '#38bdf8', textDecoration: 'none' }}>source</a></div>
          )}
        </div>
      )}

      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end', marginTop: 10 }}>
        <label style={labelStyle}>
          Parts
          <input type="number" className="form-control" aria-label="Parts" min={1} max={6} value={parts}
            onChange={(e) => setParts(Math.max(1, Math.min(6, Number(e.target.value) || 1)))} style={{ width: 70 }} />
        </label>
        <label style={labelStyle}>
          Minutes per part
          <input type="number" className="form-control" aria-label="Minutes per part" min={10} max={40} value={minutesPerPart}
            onChange={(e) => setMinutesPerPart(Math.max(10, Math.min(40, Number(e.target.value) || 10)))} style={{ width: 80 }} />
        </label>
        {pieces.length > 1 && (
          <label style={labelStyle}>
            Story
            <select className="form-control" style={{ width: 'auto', maxWidth: 280 }} value={piece} onChange={(e) => setPiece(Number(e.target.value))} aria-label="Story in this book">
              {pieces.map((p) => <option key={p.index} value={p.index}>{p.title} ({(p.words || 0).toLocaleString()} words)</option>)}
            </select>
          </label>
        )}
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: publicDomain ? 'pointer' : 'not-allowed', fontSize: '0.82rem', color: 'var(--text-secondary)', paddingBottom: 6 }}
          title={publicDomain ? undefined : 'Not public domain: only an original story inspired by it'}>
          <input type="checkbox" checked={inspired} disabled={!publicDomain} onChange={(e) => setInspiredChoice(e.target.checked)} />
          Inspired-by (original story)
        </label>
        <button type="button" className="btn" onClick={adapt} disabled={running} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          {running ? <Loader2 size={14} style={spinStyle} /> : <Wand2 size={14} />}
          {running ? 'Adapting...' : 'Adapt into my style'}
        </button>
      </div>

      {job && (
        <div style={{ marginTop: 8, fontSize: '0.82rem', display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', color: job.state === 'failed' ? '#f87171' : job.state === 'done' ? '#34d399' : 'var(--accent-primary)' }}>
          {running && <Loader2 size={13} style={spinStyle} />}
          {job.state === 'failed' ? job.error || job.message : job.message}
          {status?.mode && <span style={{ color: 'var(--text-muted)' }}>· mode: {status.mode}</span>}
          {status?.human_score != null && <span style={{ color: 'var(--text-muted)' }}>· human score {status.human_score}</span>}
        </div>
      )}
      {steps.length > 0 && (
        <div style={{ marginTop: 6, display: 'flex', flexDirection: 'column', gap: 2, fontSize: '0.78rem' }}>
          {steps.map((s, i) => (
            <div key={`${s.name}-${i}`} style={{ color: s.status === 'failed' ? '#f87171' : s.status === 'completed' ? '#34d399' : 'var(--text-secondary)' }}>
              {s.name}{s.agent ? ` (${s.agent})` : ''}: {s.status}
            </div>
          ))}
        </div>
      )}
      {job && job.state !== 'running' && job.state !== 'failed' && projectId && (
        <div style={{ marginTop: 8, fontSize: '0.82rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          Project: <code style={{ fontSize: '0.78rem' }}>{projectId}</code>
          <button type="button" className="btn btn-outline" style={{ padding: '3px 10px', fontSize: '0.76rem' }} onClick={() => navigate('projects')}>
            <FolderOpen size={13} style={{ marginRight: 4 }} /> Open Projects
          </button>
        </div>
      )}
    </div>
  );
}
