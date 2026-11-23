import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import {
  AlertCircle,
  Archive,
  ArchiveRestore,
  Check,
  CheckCheck,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Circle,
  Clock,
  Copy,
  Download,
  ExternalLink,
  FastForward,
  FileText,
  Film,
  Filter,
  FolderOpen,
  Layers,
  Maximize2,
  Mic,
  PenLine,
  Play,
  Printer,
  RotateCw,
  Search,
  ShieldAlert,
  Smartphone,
  Trash2,
  UploadCloud,
  Video,
  X,
} from 'lucide-react';
import { useStudio } from '../state/studio';
import AnimateProduce from '../components/AnimateProduce';
import { getJson, postJson, putJson, deleteJson, describeError, ApiError } from '../services/api';
import Markdown from '../components/Markdown';
import ArchiveCleanup from '../components/ArchiveCleanup';
import EyeContactSettings from '../components/EyeContactSettings';
import MusicSettings, { type PickedTrack } from '../components/MusicSettings';
import ProductionQueue from '../components/ProductionQueue';
import Teleprompter from '../components/Teleprompter';
import YouTubePublish from '../components/YouTubePublish';
import ProductionEstimate from '../components/ProductionEstimate';
import OwnFootage from '../components/OwnFootage';
import ScriptEditor from '../components/ScriptEditor';
import NewFromOwnScript from '../components/NewFromOwnScript';
import type {
  ChannelFormatsState,
  Project,
  SessionParent,
  SessionSplit,
  StepRecord,
  WorkflowStepInfo,
  ProduceQueue,
  ProduceQueueItem,
  ProduceVideoStatus,
  VideoSettingsResponse,
  VisualPlanBeat,
  VisualPlanTake,
} from '../lib/types';
import { GENRES, DENSITIES, VOICE_PRESETS } from '../lib/types';
import { ART_STYLES } from '../lib/artStyles';

// The story's characters and their voices (GET /api/projects/{id}/cast and
// GET /api/produce/voices, app/api/produce_api.py; BuzzEdit
// VOICE_CHANGER_PLAN.md brief S3): BuzzEdit converts each character's
// labelled lines to their voice before the render; the narration stays his.
interface CastVoiceEntry {
  voice?: string | null;
  preset?: string | null;
  match_pitch?: boolean;
  pitch_shift?: number;
  steps?: number;
}
interface CastCharacter {
  name: string;
  gender?: string | null;
  look?: string | null;
  voice?: CastVoiceEntry | null;
  voice_set?: boolean;
}
interface CastView {
  characters: CastCharacter[];
  voices_decided?: boolean;
  proposed?: Record<string, CastVoiceEntry | null>;
}
interface VoiceLibrary {
  available: boolean;
  voices: { name: string; kind?: string | null }[];
  presets: Record<string, { name?: string; voice?: string; voice_in_library?: boolean }>;
}
interface VoiceConversion {
  speaker: string;
  voice: string;
  spans?: unknown[];
  seconds?: number;
}
interface VoiceReport {
  note?: string | null;
  warnings?: string[];
  failed_spans?: unknown[];
}

function isShort(p: Project): boolean {
  return p.workflow_name === 'shorts_ready';
}

function history(p: Project): StepRecord[] {
  return (p.history || p.steps_history || []) as StepRecord[];
}

function lastStep(p: Project): StepRecord | null {
  const h = history(p);
  return h.length ? h[h.length - 1] : null;
}

// Where each workflow step stands: the newest history record for that step
// wins, and anything the run has not reached yet is pending (roadmap v9, C2).
function stepState(p: Project, step: WorkflowStepInfo): 'done' | 'current' | 'failed' | 'waiting' | 'pending' {
  const records = history(p).filter((h) => h.step_name === step.name);
  const record = records.length ? records[records.length - 1] : null;
  if (record?.status === 'failed') return 'failed';
  if (record?.status === 'paused_for_approval') return 'waiting';
  if (record?.status === 'completed') return 'done';
  // Voice Recording is his own step: it only blinks while the cloned voice is
  // actually being made (Auto Story's "narration"); otherwise it waits for him.
  if (/voice recording/i.test(step.name) && p.current_step === step.name) {
    return (p.metadata as { auto_story?: { state?: string } } | undefined)?.auto_story?.state === 'narration'
      ? 'current' : 'waiting';
  }
  if (p.current_step === step.name) return 'current';
  return record ? 'current' : 'pending';
}

const STATE_COLOR: Record<string, string> = {
  done: '#34d399',
  current: '#f59e0b',
  failed: '#ef4444',
  waiting: '#a78bfa',
  pending: '#64748b',
};

function formatProjectId(id: string): string {
  if (id.length <= 26) return id;
  const parts = id.split('_');
  if (parts.length >= 3) {
    const date = parts[0];
    const brand = parts[1];
    const rest = parts.slice(2).join('_');
    const shortRest = rest.length > 14 ? `${rest.slice(0, 6)}…${rest.slice(-6)}` : rest;
    return `${date}_${brand}_${shortRest}`;
  }
  return `${id.slice(0, 12)}…${id.slice(-10)}`;
}

type SeoPlain = { titles: string[]; description: string; tags: string[] };

/** The SEO package as normal text: the title (and the other title options), the
 *  description with its hashtags and the tags comma-separated, each with its own
 *  Copy button, so they can be pasted into YouTube Studio by hand. */
function SeoPlainText({ seo }: { seo: SeoPlain }) {
  const title = seo.titles[0] || '';
  const tags = seo.tags.map((t) => t.trim()).filter(Boolean).join(', ');
  const everything = [title, seo.description, tags].filter(Boolean).join('\n\n');
  const label = { fontSize: '0.78rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 } as const;
  const box = {
    width: '100%', boxSizing: 'border-box', padding: '8px 10px', fontSize: '0.85rem', lineHeight: 1.5,
    color: 'var(--text-primary)', background: 'var(--bg-pill)', border: '1px solid var(--border-card)', borderRadius: 8,
    whiteSpace: 'pre-wrap', wordBreak: 'break-word', userSelect: 'text', margin: 0,
  } as const;
  return (
    <div style={{ marginBottom: 16, display: 'grid', gap: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
        <b style={{ fontSize: '0.86rem' }}>Plain text for copy-paste</b>
        <CopyButton text={everything} label="Copy all three" />
      </div>
      <div>
        <div style={label}>Title ({title.length}/100) <CopyButton text={title} label="Copy title" /></div>
        <pre style={box}>{title}</pre>
        {seo.titles.length > 1 && (
          <div style={{ marginTop: 6, display: 'grid', gap: 4 }}>
            {seo.titles.slice(1).map((t) => (
              <div key={t} style={{ ...label, marginBottom: 0 }}>
                <span style={{ color: 'var(--text-muted)' }}>option:</span> <span style={{ color: 'var(--text-primary)', userSelect: 'text' }}>{t}</span>
                <CopyButton text={t} label="Copy this title" />
              </div>
            ))}
          </div>
        )}
      </div>
      <div>
        <div style={label}>Description <CopyButton text={seo.description} label="Copy description" /></div>
        <pre style={box}>{seo.description || '(none)'}</pre>
      </div>
      <div>
        <div style={label}>Tags ({tags.length}/500, comma separated) <CopyButton text={tags} label="Copy tags" /></div>
        <pre style={box}>{tags || '(none)'}</pre>
      </div>
    </div>
  );
}

function CopyButton({ text, label = 'Copy project ID' }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  const copy = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <button
      type="button"
      onClick={copy}
      title={copied ? 'Copied to clipboard!' : label}
      aria-label={copied ? 'Copied to clipboard!' : label}
      style={{
        background: 'none',
        border: 'none',
        padding: '2px 4px',
        color: copied ? '#34d399' : 'var(--text-muted)',
        cursor: 'pointer',
        display: 'inline-flex',
        alignItems: 'center',
        gap: 3,
        borderRadius: 4,
      }}
    >
      {copied ? <Check size={12} style={{ color: '#34d399' }} /> : <Copy size={12} />}
      <span style={{ fontSize: '0.72rem' }}>{copied ? 'Copied' : ''}</span>
    </button>
  );
}

// Scripts the teleprompter can read, best first: the written script to record
// from (it carries the writer's (pause) / (slow) cues), then the annotated
// one BuzzEdit rebuilds from what was actually said after production.
const TELEPROMPTER_SOURCES: [string, string][] = [
  // A Shorts-first session: the Shorts, then the long video, in recording order.
  ['recording_script', 'Recording session (Shorts first, then the long video)'],
  ['script_final', 'Final script'],
  ['narration_optimized', 'Narration (optimised)'],
  ['script', 'Script draft'],
  ['buzzedit_script', 'As recorded (annotated)'],
];

function teleprompterSourcesFor(project: Project): [string, string][] {
  return TELEPROMPTER_SOURCES.filter(([k]) => project.assets?.[k]);
}

/** The Writing Style channel a project's brand belongs to (backend: writing_style.canonical_channel). */
function styleChannel(brand: string): string {
  const b = (brand || '').toLowerCase();
  if (b.includes('raat') || b.includes('after dark') || b.includes('afterdark')) return 'Raat3Baje';
  if (b.includes('khayal')) return 'Khayal3Baje';
  if (b.includes('life')) return 'Life3Baje';
  if (b.includes('originals') || b.includes('spilled')) return 'Originals';
  if (b.includes('beyond')) return 'Beyond3Baje';
  return (brand || '').replace(/[^A-Za-z0-9]/g, '');
}

export default function Projects() {
  const { projects: allProjects, workflows, refreshProjects, toast, confirm, health, channelFilter } = useStudio();
  // The header's channel picker narrows everything on this page ('' = all).
  const projects = useMemo(
    () => (channelFilter ? allProjects.filter((p) => (p.brand || '').toLowerCase() === channelFilter.toLowerCase()) : allProjects),
    [allProjects, channelFilter],
  );
  const [runningId, setRunningId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [log, setLog] = useState<string[]>([]);
  const [feedback, setFeedback] = useState<Record<string, string>>({});
  // "Use my own script": the project whose box is open, and the pasted text.
  const [ownScriptFor, setOwnScriptFor] = useState<string | null>(null);
  const [ownScriptText, setOwnScriptText] = useState('');
  const [ownScriptBusy, setOwnScriptBusy] = useState(false);
  // "New from my script": a project created straight from his own script.
  const [showOwnScriptNew, setShowOwnScriptNew] = useState(false);
  const submitOwnScript = async (projectId: string) => {
    if (!ownScriptText.trim() || ownScriptBusy) return;
    setOwnScriptBusy(true);
    try {
      await postJson(`/api/projects/${encodeURIComponent(projectId)}/own_script`, { text: ownScriptText });
      toast('Your script is in. Research and writing are skipped.', 'success');
      setOwnScriptFor(null);
      setOwnScriptText('');
      await refreshProjects();
    } catch (err) {
      toast(`Could not use your script: ${describeError(err)}`, 'error');
    } finally {
      setOwnScriptBusy(false);
    }
  };
  // Per project: the step "Regenerate" restarts from ('' = everything).
  const [regenFrom, setRegenFrom] = useState<Record<string, string>>({});
  // The Scheduler Desk leaves a project id here when a task there is clicked.
  const [openId, setOpenId] = useState<string | null>(() => {
    try {
      const id = sessionStorage.getItem('projects.openOnLoad');
      sessionStorage.removeItem('projects.openOnLoad');
      return id;
    } catch {
      return null;
    }
  });
  const [sideTab, setSideTab] = useState<'steps' | 'assets'>('steps');
  const [assetName, setAssetName] = useState<string | null>(null);
  const [assetBody, setAssetBody] = useState<string>('');
  const [rawAssetBody, setRawAssetBody] = useState<string>('');
  // The SEO package as plain text (title, description, tags) for copy-paste,
  // parsed by the backend the same way the YouTube publish panel reads it.
  const [seoPlain, setSeoPlain] = useState<SeoPlain | null>(null);
  const [assetBusy, setAssetBusy] = useState(false);
  const [printable, setPrintable] = useState<{
    title: string;
    projectName: string;
    brand: string;
    filename: string;
    date: string;
    content: string;
  } | null>(null);
  const [kindTab, setKindTab] = useState<'long' | 'shorts'>(() => {
    try {
      return localStorage.getItem('projects.kindTab') === 'shorts' ? 'shorts' : 'long';
    } catch {
      return 'long';
    }
  });
  const chooseKind = (kind: 'long' | 'shorts') => {
    setKindTab(kind);
    try {
      localStorage.setItem('projects.kindTab', kind);
    } catch {
      // Private window: the tab just isn't remembered.
    }
  };
  const [filterTab, setFilterTab] = useState<'all' | 'active' | 'waiting' | 'completed' | 'archived'>('all');
  // The "Waiting for you" pop-up's Open button (components/NeedsYou.tsx): this
  // page stays mounted, so the sessionStorage hand-off above only works once.
  useEffect(() => {
    const onOpen = (e: Event) => {
      const id = (e as CustomEvent<string>).detail;
      const p = allProjects.find((x) => x.id === id);
      if (!id || !p) return;
      chooseKind(isShort(p) ? 'shorts' : 'long');
      setFilterTab('all');
      setOpenId(id);
      window.setTimeout(() => {
        document.querySelector(`[data-project-id="${CSS.escape(id)}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }, 150);
    };
    window.addEventListener('buzzcaf:open-project', onOpen);
    return () => window.removeEventListener('buzzcaf:open-project', onOpen);
  }, [allProjects]);
  const [cleanupOpen, setCleanupOpen] = useState(false);
  const [archivingId, setArchivingId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  // Collapse the project list to just the open project (or nothing), so the
  // queue and the open project's panel are not pushed down by every card.
  // Remembered per browser; storage may be unavailable, which only loses that.
  const [listCollapsed, setListCollapsed] = useState<boolean>(() => {
    try {
      return window.localStorage.getItem('projects.listCollapsed') === '1';
    } catch {
      return false;
    }
  });
  // A card's own arrow overrides the Collapse all / Expand all default for that
  // card (true = full, false = compact). The global toggle resets them.
  const [cardExpanded, setCardExpanded] = useState<Record<string, boolean>>({});
  const toggleListCollapsed = () => {
    setCardExpanded({});
    setListCollapsed((prev) => {
      const next = !prev;
      try {
        window.localStorage.setItem('projects.listCollapsed', next ? '1' : '0');
      } catch {
        // per-browser convenience only
      }
      return next;
    });
  };
  const [wrapStagesMap, setWrapStagesMap] = useState<Record<string, boolean>>({});
  const [durationDraft, setDurationDraft] = useState<Record<string, number>>({});
  const [savingDuration, setSavingDuration] = useState<string | null>(null);
  // Video / images while a slider is being dragged: shown at once, saved on release.
  const [mixDraft, setMixDraft] = useState<Record<string, { video: number; images: number }>>({});
  // Who writes each channel's scripts by default (Writing Style page): "mine" or "agent".
  const [styleModes, setStyleModes] = useState<Record<string, 'mine' | 'agent'>>({});
  useEffect(() => {
    getJson<{ channels: { channel: string; mode?: 'mine' | 'agent' }[] }>('/api/style')
      .then((r) => setStyleModes(Object.fromEntries(r.channels.map((c) => [c.channel, c.mode ?? 'mine']))))
      .catch(() => undefined);
  }, []);
  // Each session channel's defaults (Shorts first, how many, the face layout)
  // and its episode formats -- set on the Scheduler Desk's Long form tab.
  const [channelFormats, setChannelFormats] = useState<ChannelFormatsState | null>(null);
  useEffect(() => {
    getJson<ChannelFormatsState>('/api/channel_formats').then(setChannelFormats).catch(() => undefined);
  }, []);
  const [splitDraft, setSplitDraft] = useState<Record<string, string>>({});
  // How BuzzEdit generates clips (Studio setting `clip_generation_mode`, sent to
  // BuzzEdit before every production): "classic" or "hq".
  const [clipGenMode, setClipGenMode] = useState<'classic' | 'hq'>('classic');
  useEffect(() => {
    getJson<{ clip_generation_mode?: string }>('/api/settings')
      .then((s) => setClipGenMode(s.clip_generation_mode === 'hq' ? 'hq' : 'classic'))
      .catch(() => undefined);
  }, []);
  const saveClipGenMode = async (mode: 'classic' | 'hq') => {
    setClipGenMode(mode);
    try {
      await postJson('/api/settings', { clip_generation_mode: mode });
    } catch (err) {
      toast(`Could not save the clip generation setting: ${describeError(err)}`, 'error');
    }
  };
  // The BuzzEdit audio rack preset per channel (Studio setting `audio_rack_preset`,
  // {channel: preset}), put on the edit's A1 (voice) rack before every render.
  // `audioRackPresets` is null while BuzzEdit has not listed its presets.
  const [audioRackTable, setAudioRackTable] = useState<Record<string, string>>({});
  const [audioRackPresets, setAudioRackPresets] = useState<string[] | null>(null);
  useEffect(() => {
    getJson<{ available: boolean; presets?: Record<string, unknown>; channels?: Record<string, string> }>(
      '/api/produce/audio_rack_presets')
      .then((r) => {
        setAudioRackTable(r.channels || {});
        setAudioRackPresets(r.available ? Object.keys(r.presets || {}) : null);
      })
      .catch(() => undefined);
  }, []);
  const channelKey = (name: string) => name.toLowerCase().replace(/[^a-z0-9]/g, '');
  const audioRackFor = (channel: string) =>
    Object.entries(audioRackTable).find(([c]) => channelKey(c) === channelKey(channel))?.[1] || '';
  const saveAudioRack = async (channel: string, preset: string) => {
    const next = Object.fromEntries(Object.entries(audioRackTable).filter(([c]) => channelKey(c) !== channelKey(channel)));
    if (preset) next[channel] = preset;
    setAudioRackTable(next);
    try {
      await postJson('/api/settings', { audio_rack_preset: next });
    } catch (err) {
      toast(`Could not save the audio rack setting: ${describeError(err)}`, 'error');
    }
  };
  // The cast block per project (opened on demand): each story character's
  // voice, from BuzzEdit's library (`voiceLibrary`, null until read).
  const [castOpen, setCastOpen] = useState<Record<string, boolean>>({});
  const [castViews, setCastViews] = useState<Record<string, CastView | null>>({});
  const [castBusy, setCastBusy] = useState<Record<string, boolean>>({});
  const [voiceLibrary, setVoiceLibrary] = useState<VoiceLibrary | null>(null);
  const loadCast = async (projectId: string) => {
    try {
      const [cast, library] = await Promise.all([
        getJson<CastView>(`/api/projects/${encodeURIComponent(projectId)}/cast`),
        getJson<VoiceLibrary>('/api/produce/voices'),
      ]);
      setCastViews((prev) => ({ ...prev, [projectId]: cast }));
      setVoiceLibrary(library);
    } catch (err) {
      setCastViews((prev) => ({ ...prev, [projectId]: null }));
      toast(`Could not read the cast: ${describeError(err)}`, 'error');
    }
  };
  const toggleCast = (projectId: string) => {
    const open = !castOpen[projectId];
    setCastOpen((prev) => ({ ...prev, [projectId]: open }));
    if (open) void loadCast(projectId);
  };
  const setCharacterVoice = async (projectId: string, character: string, choice: string) => {
    if (choice.startsWith('entry:')) return; // the voice it already has
    const sep = choice.indexOf(':');
    const kind = sep > 0 ? choice.slice(0, sep) : '';
    const value = sep > 0 ? choice.slice(sep + 1) : '';
    setCastBusy((prev) => ({ ...prev, [projectId]: true }));
    try {
      const cast = await putJson<CastView>(`/api/projects/${encodeURIComponent(projectId)}/cast/voice`, {
        character,
        voice: kind === 'voice' ? value : null,
        preset: kind === 'preset' ? value : null,
      });
      setCastViews((prev) => ({ ...prev, [projectId]: cast }));
    } catch (err) {
      toast(`Could not set ${character}'s voice: ${describeError(err)}`, 'error');
    } finally {
      setCastBusy((prev) => ({ ...prev, [projectId]: false }));
    }
  };
  const proposeVoices = async (projectId: string) => {
    setCastBusy((prev) => ({ ...prev, [projectId]: true }));
    try {
      const cast = await postJson<CastView>(`/api/projects/${encodeURIComponent(projectId)}/cast/propose_voices`, {});
      setCastViews((prev) => ({ ...prev, [projectId]: cast }));
      const found = Object.values(cast.proposed || {}).filter(Boolean).length;
      toast(found ? `Voices proposed for ${found} character${found === 1 ? '' : 's'}.`
        : 'No voice in the library fits these characters.', found ? 'success' : 'info');
    } catch (err) {
      toast(`Could not propose voices: ${describeError(err)}`, 'error');
    } finally {
      setCastBusy((prev) => ({ ...prev, [projectId]: false }));
    }
  };
  const poll = useRef<number | null>(null);

  // Produce Video (BuzzcafAI -> BuzzEdit bridge, app/api/produce_api.py).
  const [recordingPath, setRecordingPath] = useState<Record<string, string>>({});
  // Style settings persisted server-side (project.metadata.video_settings) --
  // GET/PUT /api/projects/{id}/video_settings. `video_settings` is this
  // project's saved overrides, `effective` the fully resolved values (base ->
  // density -> channel profile -> project) the dropdowns actually display.
  const [videoSettings, setVideoSettings] = useState<Record<string, VideoSettingsResponse>>({});
  const [advancedOpen, setAdvancedOpen] = useState<Record<string, boolean>>({});
  // The eye-contact panel is tall; minimised or not is remembered per browser.
  const [eyeContactOpen, setEyeContactOpen] = useState<boolean>(() => {
    try { return localStorage.getItem('studio.eyeContactOpen') !== '0'; } catch { return true; }
  });
  const toggleEyeContact = () => setEyeContactOpen((open) => {
    try { localStorage.setItem('studio.eyeContactOpen', open ? '0' : '1'); } catch { /* private mode */ }
    return !open;
  });
  const videoSettingsSaveTimers = useRef<Record<string, number>>({});
  const videoSettingsPending = useRef<Record<string, Record<string, unknown>>>({});
  const [produceStatus, setProduceStatus] = useState<Record<string, ProduceVideoStatus>>({});
  const [producingId, setProducingId] = useState<string | null>(null);
  const producePoll = useRef<number | null>(null);
  // The cross-channel production queue (components/ProductionQueue.tsx):
  // its last snapshot, and a key bumped to make it refetch right away.
  const [queueState, setQueueState] = useState<ProduceQueue | null>(null);
  const [queueKey, setQueueKey] = useState(0);
  const [queueBusy, setQueueBusy] = useState<Record<string, boolean>>({});
  // Review gates (awaiting_cut_review / awaiting_plan_review): the editable
  // beats list loaded from production/visual_plan_take.json, and a busy flag
  // for the Continue/Cancel buttons.
  const [planDraft, setPlanDraft] = useState<Record<string, VisualPlanBeat[]>>({});
  const [planLoading, setPlanLoading] = useState<Record<string, boolean>>({});
  const [gateBusy, setGateBusy] = useState<Record<string, boolean>>({});
  const [teleprompterId, setTeleprompterId] = useState<string | null>(null);
  const [teleprompterText, setTeleprompterText] = useState('');
  const [teleprompterBusy, setTeleprompterBusy] = useState(false);
  const [teleprompterSource, setTeleprompterSource] = useState('');
  // The teleprompter's script taken out for rectifying (ScriptEditor), then put back.
  const [scriptEditing, setScriptEditing] = useState(false);
  const [buzzEditStatus, setBuzzEditStatus] = useState<{ online: boolean; comfyui_online: boolean; url: string | null } | null>(null);
  const [startingBuzzEdit, setStartingBuzzEdit] = useState(false);
  const [browsingId, setBrowsingId] = useState<string | null>(null);
  const [dragOverId, setDragOverId] = useState<string | null>(null);

  useEffect(() => {
    checkBuzzEditStatus();
    const statusInterval = window.setInterval(checkBuzzEditStatus, 10000);
    return () => {
      window.clearInterval(statusInterval);
      if (poll.current) window.clearInterval(poll.current);
      if (producePoll.current) window.clearInterval(producePoll.current);
      Object.values(videoSettingsSaveTimers.current).forEach((t) => window.clearTimeout(t));
    };
  }, []);

  const fetchVideoSettings = async (projectId: string) => {
    try {
      const data = await getJson<VideoSettingsResponse>(`/api/projects/${encodeURIComponent(projectId)}/video_settings`);
      setVideoSettings((prev) => ({ ...prev, [projectId]: data }));
    } catch {
      // Best-effort: the panel just falls back to the channel profile's defaults.
    }
  };

  useEffect(() => {
    if (openId) void fetchVideoSettings(openId);
  }, [openId]);

  // Restart-safety: a review gate pausing produce_video lives in
  // `project.metadata`, not this component's state, so it survives a Studio
  // restart -- fetch it once when the panel opens rather than only after the
  // user clicks "Produce Video" this session (`GET .../produce_video/status`
  // falls back to the persisted gate when in-memory state is idle).
  useEffect(() => {
    if (!openId) return;
    let cancelled = false;
    (async () => {
      try {
        const status = await getJson<ProduceVideoStatus>(
          `/api/projects/${encodeURIComponent(openId)}/produce_video/status`,
        );
        if (cancelled) return;
        setProduceStatus((prev) => ({ ...prev, [openId]: status }));
        const proj = allProjects.find((p) => p.id === openId);
        if (!proj) return;
        if (status.state === 'awaiting_plan_review') void loadPlanDraft(proj);
        if (status.state === 'starting' || status.state === 'running') {
          setProducingId(openId);
          pollProduceStatus(proj);
        } else if (status.state === 'queued') {
          pollProduceStatus(proj);
        }
      } catch {
        // best-effort: the panel just shows no produce status yet
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openId]);

  // Patches this project's saved style overrides, updating the panel
  // immediately and saving to the backend after a short debounce so a fast
  // typist (or a slider drag) does not fire a PUT per keystroke.
  const patchVideoSettings = (projectId: string, patch: Record<string, unknown>) => {
    setVideoSettings((prev) => {
      const current = prev[projectId];
      // The sliders read `mix`: dropping it here made them flick to a fallback
      // on every move and jump back on the server's reply (the jitter).
      let mix = current?.mix;
      if (typeof patch.video_broll_share === 'number' || typeof patch.image_broll_share === 'number') {
        const video = typeof patch.video_broll_share === 'number' ? patch.video_broll_share : (mix?.video ?? 0.7);
        const images = Math.min(typeof patch.image_broll_share === 'number' ? patch.image_broll_share : (mix?.images ?? 0.2), 1 - video);
        mix = { video, images, face: Math.max(0, 1 - video - images), mode: 'runtime' };
      }
      return {
        ...prev,
        [projectId]: {
          video_settings: { ...(current?.video_settings || {}), ...patch },
          effective: { ...(current?.effective || {}), ...patch },
          sources: current?.sources || {},
          mix,
        },
      };
    });
    if (videoSettingsSaveTimers.current[projectId]) {
      window.clearTimeout(videoSettingsSaveTimers.current[projectId]);
    }
    // Accumulate every change made inside the debounce window: sending only
    // the last patch dropped earlier ones (change genre, then density within
    // 500ms, and the genre snapped back on the server's reply).
    const pending = { ...(videoSettingsPending.current[projectId] || {}), ...patch };
    videoSettingsPending.current[projectId] = pending;
    videoSettingsSaveTimers.current[projectId] = window.setTimeout(async () => {
      delete videoSettingsPending.current[projectId];
      try {
        const data = await putJson<VideoSettingsResponse>(
          `/api/projects/${encodeURIComponent(projectId)}/video_settings`,
          pending,
        );
        setVideoSettings((prev) => ({ ...prev, [projectId]: data }));
        if (data.live_applied && data.mix) {
          toast(
            `Applied to the running render: video ${Math.round(data.mix.video * 100)}%, images ${Math.round(data.mix.images * 100)}%, face ${Math.round(data.mix.face * 100)}%.`,
            'success',
          );
        }
      } catch (err) {
        toast(`Could not save video style settings: ${describeError(err)}`, 'error');
      }
    }, 500);
  };

  const open = useMemo(() => allProjects.find((p) => p.id === openId) || null, [allProjects, openId]);

  // The details panel scrolls with the page and starts level with the card it
  // belongs to, instead of floating at the top of the list on its own scrollbar.
  const layoutRef = useRef<HTMLDivElement | null>(null);
  const [drawerTop, setDrawerTop] = useState(0);
  useLayoutEffect(() => {
    const layout = layoutRef.current;
    if (!openId || !layout) {
      setDrawerTop(0);
      return;
    }
    const card = layout.querySelector<HTMLElement>(`[data-project-id="${CSS.escape(openId)}"]`);
    const top = card ? card.getBoundingClientRect().top - layout.getBoundingClientRect().top : 0;
    setDrawerTop(Math.max(0, Math.round(top)));
  }, [openId, listCollapsed, allProjects]);
  const openWorkflow = useMemo(
    () => (open ? workflows.find((w) => (w.id || w.name) === open.workflow_name) || null : null),
    [open, workflows],
  );

  const toggleSelect = (projectId: string) => {
    if (openId === projectId) {
      setOpenId(null);
    } else {
      setOpenId(projectId);
      setAssetName(null);
      setAssetBody('');
      setRawAssetBody('');
    }
  };

  const showAsset = async (project: Project, name: string) => {
    setAssetName(name);
    setAssetBusy(true);
    setAssetBody('');
    setRawAssetBody('');
    setSeoPlain(null);
    try {
      const data = await getJson<Record<string, unknown>>(
        `/api/projects/${encodeURIComponent(project.id)}/asset/${encodeURIComponent(name)}`,
      );
      // Text assets come back as {content}; a .json asset comes back parsed.
      const isText = typeof data?.content === 'string';
      const raw = isText ? (data.content as string) : JSON.stringify(data, null, 2);
      const content = isText ? (data.content as string) : `\`\`\`json\n${raw}\n\`\`\``;
      setRawAssetBody(raw);
      setAssetBody(content);
      const assetPath = String((project.assets as Record<string, string> | undefined)?.[name] || '');
      if (name === 'seo_package' || assetPath.endsWith('publish.json')) {
        try {
          const yt = await getJson<{ draft?: { seo_found?: boolean; titles?: string[]; description?: string; tags?: string[] } }>(
            `/api/projects/${encodeURIComponent(project.id)}/youtube`,
          );
          const d = yt?.draft;
          if (d?.seo_found) setSeoPlain({ titles: d.titles || [], description: d.description || '', tags: d.tags || [] });
        } catch {
          // The JSON view below still shows the package.
        }
      }
    } catch (err) {
      setAssetBody('');
      setRawAssetBody('');
      toast(describeError(err), 'error');
    } finally {
      setAssetBusy(false);
    }
  };

  const saveArtifact = (filename: string, content: string, project?: Project | null) => {
    if (!content) {
      toast('No content to save.', 'info');
      return;
    }
    try {
      const cleanProj = (project?.name || project?.id || 'buzzcaf_project')
        .toLowerCase()
        .replace(/[^a-z0-9_-]/g, '_')
        .replace(/_+/g, '_');
      const baseFilename = filename || 'artifact.txt';
      const downloadName = baseFilename.toLowerCase().includes(cleanProj)
        ? baseFilename
        : `${cleanProj}_${baseFilename}`;
      const isJson = downloadName.endsWith('.json');
      const mimeType = isJson ? 'application/json;charset=utf-8' : 'text/markdown;charset=utf-8';
      const blob = new Blob([content], { type: mimeType });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = downloadName;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      toast(`Saved "${downloadName}"`, 'success');
    } catch (err) {
      toast(`Could not save file: ${describeError(err)}`, 'error');
    }
  };

  const printArtifact = (title: string, filename: string, content: string, project?: Project | null) => {
    if (!content) {
      toast('No content to print.', 'info');
      return;
    }
    try {
      setPrintable({
        title,
        projectName: project?.name || 'Buzzcaf Project',
        brand: project?.brand || 'Buzzcaf Media',
        filename,
        date: new Date().toLocaleString(),
        content,
      });
      toast('Opening print preview… (Tip: press Ctrl+Shift+P for Windows system printers)', 'info');
      // Allow state update to populate #buzzcaf-printable-artifact on document.body
      setTimeout(() => {
        window.print();
      }, 150);
    } catch (err) {
      toast(`Could not start print: ${describeError(err)}`, 'error');
    }
  };

  const openBrowserPrint = async (projectId: string, name: string) => {
    try {
      await postJson(`/api/projects/${encodeURIComponent(projectId)}/asset/${encodeURIComponent(name)}/open_browser_print`, {});
      toast('Opened in default browser with full printer detection.', 'success');
    } catch {
      window.open(`/api/projects/${encodeURIComponent(projectId)}/asset/${encodeURIComponent(name)}/print?auto=1`, '_blank');
      toast('Opened in default browser with full printer detection.', 'success');
    }
  };

  const toggleAllowAll = async (project: Project) => {
    try {
      const updated = await postJson<Project>(`/api/projects/${encodeURIComponent(project.id)}/toggle_allow_all`, {});
      const isNow = Boolean(updated.metadata?.allow_all);
      toast(`Allow All ${isNow ? 'enabled' : 'disabled'} for "${project.name}".`, 'info');
      await refreshProjects();
    } catch (err) {
      toast(`Failed to toggle Allow All: ${describeError(err)}`, 'error');
    }
  };

  const saveWritingStyle = async (proj: Project, mode: string) => {
    try {
      await putJson(`/api/style/projects/${encodeURIComponent(proj.id)}/mode`, { mode: mode || null });
      toast(mode === 'mine' ? `"${proj.name}" is written in your style.` : mode === 'agent'
        ? `"${proj.name}" is written in the agents' own style.` : `"${proj.name}" follows the channel's writing style.`, 'success');
      await refreshProjects();
    } catch (err) {
      toast(`Could not change the writing style: ${describeError(err)}`, 'error');
    }
  };

  // The project's recording session, Shorts count, split point or episode format.
  const saveSession = async (proj: Project, patch: Record<string, unknown>, done?: string) => {
    try {
      await putJson(`/api/projects/${encodeURIComponent(proj.id)}/session`, patch);
      if (done) toast(done, 'success');
      await refreshProjects();
    } catch (err) {
      toast(`Could not save the session settings: ${describeError(err)}`, 'error');
    }
  };

  const saveDuration = async (proj: Project) => {
    const raw = durationDraft[proj.id];
    const minutes = raw == null || Number.isNaN(raw) || raw <= 0 ? null : raw;
    setSavingDuration(proj.id);
    try {
      await postJson(`/api/projects/${encodeURIComponent(proj.id)}/duration`, { minutes });
      toast(`Target length updated for "${proj.name}".`, 'success');
      await refreshProjects();
    } catch (err) {
      toast(`Could not update target length: ${describeError(err)}`, 'error');
    } finally {
      setSavingDuration(null);
    }
  };

  // Archive / bring back (2026-10-22): the project keeps its files and moves
  // to the Archived tab; the nightly sweep does the same to anything
  // untouched for two weeks that is not in the queue.
  const handleArchiveProject = async (proj: Project, archived: boolean, e?: React.MouseEvent) => {
    e?.stopPropagation();
    if (archivingId || runningId === proj.id) return;
    setArchivingId(proj.id);
    try {
      await postJson(`/api/projects/${encodeURIComponent(proj.id)}/archive`, { archived });
      toast(archived ? `"${proj.name}" archived.` : `"${proj.name}" is back.`, 'success');
      if (archived && openId === proj.id) setOpenId(null);
      await refreshProjects();
    } catch (err) {
      toast(describeError(err), 'error');
    } finally {
      setArchivingId(null);
    }
  };

  const handleDeleteProject = async (proj: Project, e?: React.MouseEvent) => {
    e?.stopPropagation();
    if (deletingId || runningId === proj.id) return;
    const ok = await confirm({
      title: `Delete "${proj.name}"?`,
      body: `This permanently deletes the project directory, scripts, and research assets for "${proj.name}". This cannot be undone.`,
      confirmLabel: 'Delete Project',
      danger: true,
    });
    if (!ok) return;

    setDeletingId(proj.id);
    try {
      await deleteJson(`/api/projects/${encodeURIComponent(proj.id)}`);
      toast(`Project "${proj.name}" deleted.`, 'success');
      if (openId === proj.id) {
        setOpenId(null);
        setAssetName(null);
        setAssetBody('');
        setRawAssetBody('');
      }
      await refreshProjects();
    } catch (err) {
      toast(`Could not delete project: ${describeError(err)}`, 'error');
    } finally {
      setDeletingId(null);
    }
  };

  const run = async (
    project: Project,
    mode: 'execute' | 'approve' | 'allow_all' | 'run_all' | 'regenerate',
    notes?: string,
    allowAll?: boolean,
    fromStep?: string,
  ) => {
    if (runningId) return;
    setRunningId(project.id);
    let startMsg = 'Starting the next workflow step…';
    if (mode === 'approve') startMsg = allowAll ? 'Allowing all steps and continuing…' : 'Approving the step that is waiting…';
    else if (mode === 'allow_all') startMsg = 'Enabling Allow All and continuing…';
    else if (mode === 'run_all') startMsg = 'Running all remaining workflow steps…';
    else if (mode === 'regenerate') startMsg = fromStep ? `Regenerating from "${fromStep}"…` : 'Regenerating everything from the first step…';
    setLog([startMsg]);
    // The stage pills follow the run while it is going, not only once the
    // whole request returns (a long video is an hour): a regenerate first
    // clears the stages it will run again, then each one fills in as it
    // starts and finishes.
    let ticks = 0;
    poll.current = window.setInterval(async () => {
      ticks += 1;
      if (ticks === 2 || ticks % 5 === 0) refreshProjects().catch(() => undefined);
      try {
        const lines = await getJson<string[]>(`/api/projects/${encodeURIComponent(project.id)}/logs`);
        if (Array.isArray(lines) && lines.length) setLog(lines);
      } catch {
        // keep the last log we had
      }
    }, 700);
    try {
      const endpoint = `/api/projects/${encodeURIComponent(project.id)}/${mode === 'allow_all' ? 'allow_all' : mode === 'run_all' ? 'run_all' : mode}`;
      const payload: Record<string, unknown> = {};
      if (notes) payload.feedback = notes;
      if (allowAll) payload.allow_all = true;
      if (mode === 'regenerate' && fromStep) payload.from_step = fromStep;

      const updated = await postJson<Project>(
        endpoint,
        payload,
        // A whole-workflow run (every step of a long video) can outlast 10 min.
        { signal: AbortSignal.timeout(mode === 'run_all' || mode === 'regenerate' ? 3_600_000 : 600_000) },
      );
      const step = lastStep(updated);
      if (step?.status === 'paused_for_approval') toast(`${step.step_name || 'The step'} is waiting for your approval.`, 'info');
      else if (updated.status === 'completed') toast(`${project.name} is complete.`, 'success');
      else if (allowAll || mode === 'allow_all') toast(`Allow All enabled: ran ${step?.step_name || 'the next step'}.`, 'success');
      else toast(`Ran ${step?.step_name || 'the next step'}.`, 'success');
      setFeedback((prev) => ({ ...prev, [project.id]: '' }));
    } catch (err) {
      const detail = err instanceof ApiError && err.status === 409
        ? `${describeError(err)} Refreshing the list.`
        : describeError(err);
      setLog((prev) => [...prev, `[ERROR] ${detail}`]);
      toast(detail, 'error');
    } finally {
      if (poll.current) window.clearInterval(poll.current);
      poll.current = null;
      try {
        const lines = await getJson<string[]>(`/api/projects/${encodeURIComponent(project.id)}/logs`);
        if (Array.isArray(lines) && lines.length) setLog(lines);
      } catch {
        // ignore
      }
      await refreshProjects();
      setRunningId(null);
    }
  };

  // The editable beats list for an `awaiting_plan_review` gate -- read from
  // `production/visual_plan_take.json` (registered as the `visual_plan_take`
  // asset by `_plan_and_render` in produce_api.py) via the generic asset
  // route, which returns a `.json` asset parsed rather than wrapped.
  const loadPlanDraft = async (project: Project) => {
    setPlanLoading((prev) => ({ ...prev, [project.id]: true }));
    try {
      const data = await getJson<VisualPlanTake>(
        `/api/projects/${encodeURIComponent(project.id)}/asset/visual_plan_take`,
      );
      setPlanDraft((prev) => ({
        ...prev,
        [project.id]: (data.beats || []).map((b) => ({ ...b, deleted: !!b.deleted })),
      }));
    } catch (err) {
      toast(`Could not load the visual plan: ${describeError(err)}`, 'error');
    } finally {
      setPlanLoading((prev) => ({ ...prev, [project.id]: false }));
    }
  };

  const updatePlanBeat = (projectId: string, index: number, patch: Partial<VisualPlanBeat>) => {
    setPlanDraft((prev) => {
      const beats = prev[projectId] ? [...prev[projectId]] : [];
      if (!beats[index]) return prev;
      beats[index] = { ...beats[index], ...patch };
      return { ...prev, [projectId]: beats };
    });
  };

  const pollProduceStatus = (project: Project) => {
    if (producePoll.current) window.clearInterval(producePoll.current);
    producePoll.current = window.setInterval(async () => {
      try {
        const status = await getJson<ProduceVideoStatus>(
          `/api/projects/${encodeURIComponent(project.id)}/produce_video/status`,
        );
        setProduceStatus((prev) => ({ ...prev, [project.id]: status }));
        const gated = (status.state === 'awaiting_cut_review' || status.state === 'awaiting_plan_review'
          || status.state === 'awaiting_effects_review') && !status.sample_running;
        if (status.state === 'ready' || status.state === 'failed' || gated || status.state === 'cancelled'
            || status.state === 'paused') {
          if (producePoll.current) window.clearInterval(producePoll.current);
          producePoll.current = null;
          setProducingId(null);
          if (status.state === 'ready') toast(`${project.name}: video ready.`, 'success');
          else if (status.state === 'failed') toast(`${project.name}: ${status.error || 'video production failed.'}`, 'error');
          else if (status.state === 'paused') toast(`${project.name}: production paused.`, 'info');
          else if (status.state === 'awaiting_effects_review') {
            toast(status.sample_error ? `${project.name}: ${status.sample_error}` : `${project.name}: effects sample ready to review.`,
              status.sample_error ? 'error' : 'info');
          }
          else if (status.state === 'awaiting_cut_review') toast(`${project.name}: review the cut in BuzzEdit, then continue.`, 'info');
          else if (status.state === 'awaiting_plan_review') {
            toast(`${project.name}: visual plan ready for review.`, 'info');
            void loadPlanDraft(project);
          }
          if (status.state === 'ready' || status.state === 'failed') await refreshProjects();
          setQueueKey((k) => k + 1);
        }
      } catch {
        // keep the last status we had; the next tick tries again
      }
    }, 3000);
  };

  const retestEffects = async (project: Project) => {
    setGateBusy((prev) => ({ ...prev, [project.id]: true }));
    try {
      await postJson(`/api/projects/${encodeURIComponent(project.id)}/produce_video/effects_sample`, {});
      setProduceStatus((prev) => ({
        ...prev,
        [project.id]: { ...(prev[project.id] || { state: 'awaiting_effects_review' }), sample_running: true,
          message: 'Re-rendering the effects sample with your current settings...' },
      }));
      pollProduceStatus(project);
    } catch (err) {
      toast(`Could not re-test the effects: ${describeError(err)}`, 'error');
    } finally {
      setGateBusy((prev) => ({ ...prev, [project.id]: false }));
    }
  };

  const continueProduce = async (project: Project, stage: 'cut_review' | 'plan_review' | 'effects_review') => {
    setGateBusy((prev) => ({ ...prev, [project.id]: true }));
    try {
      const body: Record<string, unknown> = { stage };
      if (stage === 'plan_review') body.plan = planDraft[project.id] || [];
      await postJson(`/api/projects/${encodeURIComponent(project.id)}/produce_video/continue`, body);
      setProduceStatus((prev) => ({ ...prev, [project.id]: { state: 'queued', message: 'Continuing -- waiting in the production queue...' } }));
      toast('Continuing: back in the production queue.', 'info');
      setQueueKey((k) => k + 1);
      pollProduceStatus(project);
    } catch (err) {
      toast(`Could not continue: ${describeError(err)}`, 'error');
    } finally {
      setGateBusy((prev) => ({ ...prev, [project.id]: false }));
    }
  };

  const cancelProduce = async (project: Project) => {
    setGateBusy((prev) => ({ ...prev, [project.id]: true }));
    try {
      const res = await postJson<{ status: string }>(`/api/projects/${encodeURIComponent(project.id)}/produce_video/cancel`, {});
      setProduceStatus((prev) => ({ ...prev, [project.id]: { state: 'cancelled', message: 'Cancelled by user.' } }));
      setProducingId(null);
      setQueueKey((k) => k + 1);
      toast(res?.status === 'cancelled' ? 'Video production cancelled.' : 'Cancelled.', 'info');
    } catch (err) {
      toast(`Could not cancel: ${describeError(err)}`, 'error');
    } finally {
      setGateBusy((prev) => ({ ...prev, [project.id]: false }));
    }
  };

  const checkBuzzEditStatus = async () => {
    try {
      const data = await getJson<{ online: boolean; comfyui_online: boolean; url: string | null }>('/api/produce/buzzedit/status');
      setBuzzEditStatus(data);
    } catch {
      setBuzzEditStatus({ online: false, comfyui_online: false, url: null });
    }
  };

  const startBuzzEdit = async () => {
    setStartingBuzzEdit(true);
    toast('Starting BuzzEdit service and ComfyUI...', 'info');
    try {
      const res = await postJson<{ status: string; message: string }>('/api/produce/buzzedit/start', {});
      toast(res.message || 'BuzzEdit started successfully!', 'success');
      await checkBuzzEditStatus();
    } catch (err) {
      toast(`Could not start BuzzEdit: ${describeError(err)}`, 'error');
    } finally {
      setStartingBuzzEdit(false);
    }
  };

  const browseRecording = async (project: Project) => {
    const projectId = project.id;
    setBrowsingId(projectId);
    try {
      const res = await postJson<{ path: string | null }>('/api/produce/browse_recording', {});
      if (res?.path) {
        const filePath = res.path;
        setRecordingPath((prev) => ({ ...prev, [projectId]: filePath }));
        // Picking a file only fills the path: production starts on the
        // "Start video production" button, after the style is set.
        toast(`Selected recording: ${filePath.split(/[/\\]/).pop()} — press Start video production when ready`, 'success');
      }
    } catch (err) {
      toast(`Browse failed: ${describeError(err)}`, 'error');
    } finally {
      setBrowsingId(null);
    }
  };

  const handleDragOver = (e: React.DragEvent, projectId: string) => {
    e.preventDefault();
    e.stopPropagation();
    if (dragOverId !== projectId) {
      setDragOverId(projectId);
    }
  };

  const handleDragLeave = (e: React.DragEvent, projectId: string) => {
    e.preventDefault();
    e.stopPropagation();
    if (dragOverId === projectId) {
      setDragOverId(null);
    }
  };

  const handleDrop = (e: React.DragEvent, project: Project) => {
    const projectId = project.id;
    e.preventDefault();
    e.stopPropagation();
    setDragOverId(null);
    const files = e.dataTransfer.files;
    if (!files || files.length === 0) return;
    const file = files[0];
    const fullPath = (file as any).path || file.name;
    if (fullPath) {
      setRecordingPath((prev) => ({ ...prev, [projectId]: fullPath }));
      // Dropping only fills the path; production starts on the button.
      toast(`Added recording: ${fullPath.split(/[/\\]/).pop()} — press Start video production when ready`, 'success');
    }
  };

  const produceVideo = async (project: Project, pathOverride?: string) => {
    const path = (pathOverride ?? recordingPath[project.id] ?? '').trim();
    if (!path) {
      toast('Enter or select the absolute path to your recording first.', 'error');
      return;
    }
    if (producingId === project.id) return;
    setProducingId(project.id);
    try {
      // Style (genre, density, voice preset, auto-cut, ...) is already saved
      // server-side via PUT /video_settings as the panel's controls change;
      // produce_video resolves it from there when the request omits it.
      const othersActive = !!queueState?.items.some((i) => i.project_id !== project.id
        && (i.status === 'running' || i.status === 'queued'));
      await postJson(`/api/projects/${encodeURIComponent(project.id)}/produce_video`, {
        recording_path: path,
      });
      setProduceStatus((prev) => ({ ...prev, [project.id]: { state: 'queued', message: 'Waiting in the production queue...' } }));
      toast(othersActive || queueState?.paused
        ? `"${project.name}" added to the production queue.`
        : `Producing video for "${project.name}"...`, 'info');
      setQueueKey((k) => k + 1);
      pollProduceStatus(project);
    } catch (err) {
      toast(`Could not start video production: ${describeError(err)}`, 'error');
    } finally {
      setProducingId(null);
    }
  };

  // The project's own queue item: the unfinished one if any, else its newest.
  const queueItemFor = (projectId: string): ProduceQueueItem | null => {
    const mine = (queueState?.items || []).filter((i) => i.project_id === projectId);
    const active = mine.find((i) => ['queued', 'running', 'paused', 'awaiting_review'].includes(i.status));
    if (active) return active;
    return [...mine].sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1))[0] || null;
  };

  const queueAction = async (project: Project, item: ProduceQueueItem, action: 'pause' | 'resume' | 'cancel' | 'retry' | 'restart' | 'recut') => {
    if (action === 'cancel' || action === 'restart' || action === 'recut') {
      const ok = await confirm({
        title: action === 'cancel' ? `Cancel "${project.name}"?`
          : action === 'recut' ? `Re-cut "${project.name}"?`
          : `Restart "${project.name}" from scratch?`,
        body: action === 'cancel'
          ? item.status === 'running'
            ? 'The run stops at its next safe point. You can retry it later from there.'
            : 'It leaves the production queue. You can retry it later.'
          : action === 'recut'
            ? 'The cut is planned again from the existing transcription under the current rules (no new transcription). Eye contact is redone if its setup changed, visuals are re-planned, and the video is rendered again.'
            : 'The recording is imported and transcribed again, and visuals are re-planned.',
        confirmLabel: action === 'cancel' ? 'Cancel video' : action === 'recut' ? 'Re-cut' : 'Restart',
        danger: action !== 'recut',
      });
      if (!ok) return;
    }
    setQueueBusy((prev) => ({ ...prev, [project.id]: true }));
    try {
      const q = await postJson<ProduceQueue>(`/api/produce/queue/${encodeURIComponent(item.id)}/${action}`, {});
      setQueueState(q);
      setQueueKey((k) => k + 1);
      const status = await getJson<ProduceVideoStatus>(`/api/projects/${encodeURIComponent(project.id)}/produce_video/status`);
      setProduceStatus((prev) => ({ ...prev, [project.id]: status }));
      if (['queued', 'running', 'starting'].includes(status.state)) pollProduceStatus(project);
      if (action === 'pause' && item.status === 'running') toast('Pausing after the current stage...', 'info');
    } catch (err) {
      toast(describeError(err), 'error');
    } finally {
      setQueueBusy((prev) => ({ ...prev, [project.id]: false }));
    }
  };

  const handleQueueChange = (q: ProduceQueue) => {
    setQueueState(q);
    if (!openId) return;
    const mine = q.items.filter((i) => i.project_id === openId);
    if (!mine.length) return;
    const proj = allProjects.find((p) => p.id === openId);
    if (!proj) return;
    const moving = mine.some((i) => i.status === 'queued' || i.status === 'running');
    if (moving) {
      if (!producePoll.current) pollProduceStatus(proj);
      return;
    }
    // Nothing moving, but the queue may have changed this run's state (a retry
    // that failed again, a pause, a resume from the queue panel) after the
    // status poll stopped. Fetch it once so the panel below says what the
    // queue says instead of the last thing it saw.
    void getJson<ProduceVideoStatus>(`/api/projects/${encodeURIComponent(openId)}/produce_video/status`)
      .then((status) => setProduceStatus((prev) => ({ ...prev, [openId]: status })))
      .catch(() => { /* keep what we had */ });
  };

  const resumeProduce = async (project: Project) => {
    try {
      await postJson(`/api/projects/${encodeURIComponent(project.id)}/produce_video/resume`, {});
      setProduceStatus((prev) => ({ ...prev, [project.id]: { state: 'queued', message: 'Waiting in the production queue to re-attach...' } }));
      toast('Queued to re-attach to the BuzzEdit render.', 'info');
      setQueueKey((k) => k + 1);
      pollProduceStatus(project);
    } catch (err) {
      toast(`Could not resume: ${describeError(err)}`, 'error');
    }
  };

  const openTeleprompter = async (project: Project, source?: string) => {
    const available = teleprompterSourcesFor(project);
    const key = source && available.some(([k]) => k === source) ? source : available[0]?.[0];
    if (!key) return;
    setTeleprompterId(project.id);
    setTeleprompterSource(key);
    setTeleprompterBusy(true);
    setTeleprompterText('');
    try {
      const data = await getJson<Record<string, unknown>>(
        `/api/projects/${encodeURIComponent(project.id)}/asset/${encodeURIComponent(key)}`,
      );
      setTeleprompterText(typeof data?.content === 'string' ? data.content : '');
    } catch (err) {
      toast(describeError(err), 'error');
    } finally {
      setTeleprompterBusy(false);
    }
  };

  // Shorts Desk projects (workflow shorts_ready) get their own tab; everything
  // else is long-form.
  const kindCounts = useMemo(() => {
    const shorts = projects.filter(isShort).length;
    return { long: projects.length - shorts, shorts };
  }, [projects]);
  const kindProjects = useMemo(
    () => projects.filter((p) => isShort(p) === (kindTab === 'shorts')),
    [projects, kindTab],
  );

  // Filtered and searched projects
  const counts = useMemo(() => {
    let waiting = 0;
    let completed = 0;
    let active = 0;
    let archived = 0;
    for (const p of kindProjects) {
      const step = lastStep(p);
      if (p.status === 'archived') {
        archived++;
      } else if (step?.status === 'paused_for_approval') {
        waiting++;
      } else if (p.status === 'completed') {
        completed++;
      } else {
        active++;
      }
    }
    return { all: kindProjects.length - archived, active, waiting, completed, archived };
  }, [kindProjects]);

  const filteredProjects = useMemo(() => {
    return kindProjects.filter((p) => {
      const step = lastStep(p);
      const isWaiting = step?.status === 'paused_for_approval';
      const isCompleted = p.status === 'completed';
      const isArchived = p.status === 'archived';

      // Archived projects live only on their own tab (2026-10-22).
      if (filterTab === 'archived') return isArchived;
      if (isArchived) return false;
      if (filterTab === 'active' && (isCompleted || isWaiting)) return false;
      if (filterTab === 'waiting' && !isWaiting) return false;
      if (filterTab === 'completed' && !isCompleted) return false;

      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase().trim();
        const matchName = p.name?.toLowerCase().includes(q);
        const matchBrand = p.brand?.toLowerCase().includes(q);
        const matchWf = p.workflow_name?.toLowerCase().includes(q);
        const matchId = p.id?.toLowerCase().includes(q);
        if (!matchName && !matchBrand && !matchWf && !matchId) return false;
      }
      return true;
    });
  }, [kindProjects, filterTab, searchQuery]);

  return (
    <div>
      {/* Top Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20, flexWrap: 'wrap', gap: 16 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: '1.5rem', color: 'var(--text-primary)' }}>Projects</h2>
          <div style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginTop: 4 }}>
            Monitor pipelines, review stage progressions, and control autonomous execution
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <button type="button" className="btn" onClick={() => setShowOwnScriptNew((v) => !v)}>
            <PenLine size={15} />
            <span>New from my script</span>
          </button>
          <button type="button" className="btn btn-outline" onClick={() => refreshProjects()}>
            <RotateCw size={15} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {showOwnScriptNew && <NewFromOwnScript onClose={() => setShowOwnScriptNew(false)} />}

      <ProductionQueue
        refreshKey={queueKey}
        onChange={handleQueueChange}
        onOpenProject={(id) => setOpenId(id)}
      />

      {/* Long-form / Shorts */}
      <div className="project-filter-tabs" style={{ marginBottom: 12 }}>
        <button
          type="button"
          className={`project-filter-tab ${kindTab === 'long' ? 'active' : ''}`}
          onClick={() => chooseKind('long')}
        >
          <Film size={14} />
          <span>Long-form</span>
          <span className="tab-count">{kindCounts.long}</span>
        </button>
        <button
          type="button"
          className={`project-filter-tab ${kindTab === 'shorts' ? 'active' : ''}`}
          onClick={() => chooseKind('shorts')}
        >
          <Smartphone size={14} />
          <span>Shorts</span>
          <span className="tab-count">{kindCounts.shorts}</span>
        </button>
      </div>

      {/* Filter Tabs & Search Bar */}
      <div className="project-filter-tabs">
        <button
          type="button"
          className={`project-filter-tab ${filterTab === 'all' ? 'active' : ''}`}
          onClick={() => setFilterTab('all')}
        >
          <Layers size={14} />
          <span>All Projects</span>
          <span className="tab-count">{counts.all}</span>
        </button>
        <button
          type="button"
          className={`project-filter-tab ${filterTab === 'active' ? 'active' : ''}`}
          onClick={() => setFilterTab('active')}
        >
          <Play size={14} />
          <span>Active / In Progress</span>
          <span className="tab-count">{counts.active}</span>
        </button>
        <button
          type="button"
          className={`project-filter-tab ${filterTab === 'waiting' ? 'active' : ''}`}
          onClick={() => setFilterTab('waiting')}
        >
          <Clock size={14} />
          <span>Needs Approval</span>
          <span className="tab-count">{counts.waiting}</span>
        </button>
        <button
          type="button"
          className={`project-filter-tab ${filterTab === 'completed' ? 'active' : ''}`}
          onClick={() => setFilterTab('completed')}
        >
          <CheckCircle2 size={14} />
          <span>Completed</span>
          <span className="tab-count">{counts.completed}</span>
        </button>
        <button
          type="button"
          className={`project-filter-tab ${filterTab === 'archived' ? 'active' : ''}`}
          onClick={() => setFilterTab('archived')}
          title="Projects put away by hand or by the nightly archive rules. Nothing is deleted; one click brings one back."
        >
          <Archive size={14} />
          <span>Archived</span>
          <span className="tab-count">{counts.archived}</span>
        </button>
        <button type="button" className="btn btn-outline btn-compact" onClick={() => setCleanupOpen(true)}
          title="Archive what the rules say is finished with: stale, failed, duplicates, old ready scripts">
          Clean up
        </button>
        <ArchiveCleanup open={cleanupOpen} onClose={() => setCleanupOpen(false)} />

        {/* Search input */}
        <div className="project-search-container">
          <Search size={14} style={{ position: 'absolute', left: 10, color: 'var(--text-muted)' }} />
          <input
            type="text"
            className="form-control project-search-input"
            placeholder="Search projects, channels..."
            aria-label="Search projects, channels"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            style={{
              paddingLeft: 32,
              paddingRight: 10,
              paddingTop: 6,
              paddingBottom: 6,
              fontSize: '0.82rem',
              borderRadius: 8,
              height: 34,
            }}
          />
          {searchQuery && (
            <button
              type="button"
              onClick={() => setSearchQuery('')}
              aria-label="Clear search"
              style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', display: 'flex', marginLeft: -26, zIndex: 2 }}
            >
              <X size={13} />
            </button>
          )}
        </div>
      </div>

      {/* Empty State */}
      {projects.length === 0 && (
        <div className="panel-card" style={{ textAlign: 'center', color: 'var(--text-secondary)', padding: 40 }}>
          <p style={{ margin: 0, fontSize: '1rem' }}>
            {health === 'offline' ? 'The Studio backend is offline.' : channelFilter && allProjects.length > 0 ? `No ${channelFilter} projects yet.` : 'No projects yet.'}
          </p>
          {channelFilter && allProjects.length > 0 ? (
            <p style={{ fontSize: '0.85rem', marginTop: 6 }}>Pick "All channels" in the channel picker at the top to see the other {allProjects.length}.</p>
          ) : (
            <p style={{ fontSize: '0.85rem', marginTop: 6 }}>Create one from the Dashboard, send a topic from the Vault, or ask Dexter to start one.</p>
          )}
        </div>
      )}

      {projects.length > 0 && filteredProjects.length === 0 && (
        <div className="panel-card" style={{ textAlign: 'center', color: 'var(--text-secondary)', padding: 32 }}>
          <Filter size={24} style={{ color: 'var(--text-muted)', marginBottom: 8 }} />
          <p style={{ margin: 0, fontSize: '0.95rem' }}>No projects match the selected tab or search filter.</p>
          <button type="button" className="btn btn-outline btn-sm" onClick={() => { setFilterTab('all'); setSearchQuery(''); }} style={{ marginTop: 12 }}>
            Reset Filters
          </button>
        </div>
      )}

      {/* Main Workspace Layout: Cards List + Optional Side Drawer */}
      {filteredProjects.length > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '4px 0 8px' }}>
          <button
            type="button"
            className="btn btn-outline btn-sm"
            onClick={toggleListCollapsed}
            aria-expanded={!listCollapsed}
            title={listCollapsed ? 'Show every project as a full card' : 'Shrink every project to one line (the open project stays full)'}
            style={{ padding: '3px 10px', fontSize: '0.76rem', display: 'inline-flex', alignItems: 'center', gap: 6 }}
          >
            {listCollapsed ? <ChevronRight size={13} /> : <ChevronDown size={13} />}
            <span>{listCollapsed ? 'Expand all' : 'Collapse all'}</span>
          </button>
          {listCollapsed && (
            <span style={{ fontSize: '0.74rem', color: 'var(--text-muted)' }}>
              {filteredProjects.length} project{filteredProjects.length === 1 ? '' : 's'} — click a name to open it.
            </span>
          )}
        </div>
      )}

      <div className="projects-layout" ref={layoutRef}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="project-list">
            {filteredProjects.map((proj) => {
              const step = lastStep(proj);
              const waiting = step?.status === 'paused_for_approval';
              const busy = runningId === proj.id;
              const isAllowAll = Boolean(proj.metadata?.allow_all);
              const isOpen = openId === proj.id;
              const compact = !(cardExpanded[proj.id] ?? (isOpen || !listCollapsed));
              const isWrapStages = Boolean(wrapStagesMap[proj.id]);

              // Workflow & Stages Pipeline computation
              const wf = workflows.find((w) => (w.id || w.name) === proj.workflow_name);
              const steps = wf?.steps || [];
              const stepsWithState = steps.map((s, idx) => ({
                step: s,
                index: idx + 1,
                state: stepState(proj, s),
              }));
              const completedCount = stepsWithState.filter((s) => s.state === 'done').length;
              const totalCount = steps.length;
              const currentStepItem = stepsWithState.find((s) => s.state === 'current' || s.state === 'waiting');
              const progressPercent = totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : (proj.status === 'completed' ? 100 : 0);

              return (
                <div
                  key={proj.id}
                  data-project-id={proj.id}
                  className="project-item"
                  style={{
                    borderColor: isOpen ? 'var(--accent-primary)' : undefined,
                    boxShadow: isOpen ? '0 0 0 1px var(--accent-primary), var(--card-shadow)' : undefined,
                  }}
                >
                  {/* Top Card Row: Title, Badges & Quick Action Controls */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 14, flexWrap: 'wrap' }}>
                    <div style={{ flex: 1, minWidth: 260 }}>
                      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 2 }}>
                        <button
                          type="button"
                          onClick={() => setCardExpanded((prev) => ({ ...prev, [proj.id]: compact }))}
                          aria-expanded={!compact}
                          title={compact ? 'Expand this project' : 'Collapse this project to its steps'}
                          aria-label={compact ? 'Expand this project' : 'Collapse this project to its steps'}
                          style={{ background: 'none', border: 'none', padding: '2px 4px 0 0', flexShrink: 0, cursor: 'pointer', color: 'var(--accent-primary)', display: 'inline-flex', alignItems: 'center', verticalAlign: 'middle' }}
                        >
                          {compact ? <ChevronRight size={16} /> : <ChevronDown size={16} />}
                        </button>
                        <div
                          className="project-name"
                          onClick={() => toggleSelect(proj.id)}
                          role="button"
                          tabIndex={0}
                          onKeyDown={(e) => e.key === 'Enter' && toggleSelect(proj.id)}
                          style={{ cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 8 }}
                        >
                          <span>{proj.name}</span>
                        </div>
                      </div>

                      {/* Header Badges Row */}
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6, flexWrap: 'wrap' }}>
                        {/* Status Badge */}
                        <span className={`status-badge-inline status-${waiting ? 'waiting' : proj.status}`}>
                          {waiting ? (
                            <>
                              <Clock size={11} />
                              <span>Awaiting Approval</span>
                            </>
                          ) : proj.status === 'completed' ? (
                            <>
                              <CheckCircle2 size={11} />
                              <span>Completed</span>
                            </>
                          ) : (
                            <>
                              <Play size={10} />
                              <span>{String(proj.status || 'active').toUpperCase()}</span>
                            </>
                          )}
                        </span>

                        {/* Brand Badge */}
                        <span className="brand-badge">{proj.brand}</span>

                        {/* Genre / episode format badge */}
                        {(() => {
                          const key = (proj.metadata?.episode_format as string | undefined) || '';
                          if (!key) return null;
                          const all = channelFormats?.episode_formats ?? {};
                          const label = all[styleChannel(proj.brand)]?.find((f) => f.key === key)?.label
                            ?? Object.values(all).flat().find((f) => f.key === key)?.label
                            ?? ({ horror_tale: 'Horror', classic_retold: 'Classic retold' } as Record<string, string>)[key]
                            ?? key;
                          return (
                            <span className="brand-badge" title="Episode format (genre)"
                              style={{ backgroundColor: 'var(--bg-pill)', color: 'var(--accent-primary)' }}>{label}</span>
                          );
                        })()}

                        {/* Allow All Toggle Badge */}
                        <button
                          type="button"
                          className="btn btn-outline"
                          onClick={(e) => { e.stopPropagation(); toggleAllowAll(proj); }}
                          title={isAllowAll ? 'Allow All is ON: steps run automatically without pausing. Click to turn off.' : 'Click to enable Allow All: steps advance without pausing for approval.'}
                          style={{
                            padding: '3px 8px',
                            fontSize: '0.74rem',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: 4,
                            borderRadius: 6,
                            borderColor: isAllowAll ? '#10b981' : 'var(--border-card)',
                            background: isAllowAll ? 'rgba(16, 185, 129, 0.15)' : 'var(--bg-pill)',
                            color: isAllowAll ? '#34d399' : 'var(--text-secondary)',
                          }}
                        >
                          {isAllowAll ? <CheckCircle2 size={12} style={{ color: '#10b981' }} /> : <ShieldAlert size={12} />}
                          <span>{isAllowAll ? 'Allow All: ON' : 'Allow All: OFF'}</span>
                        </button>
                      </div>
                    </div>

                    {/* Actions Group on Top Right */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginLeft: 'auto' }}>
                      {/* Always reachable once a script exists: recording comes
                          before the visual plan, so it cannot wait for that panel. */}
                      {teleprompterSourcesFor(proj).length > 0 && (
                        <button
                          type="button"
                          className="btn btn-outline btn-sm"
                          onClick={(e) => { e.stopPropagation(); openTeleprompter(proj); }}
                          style={{ padding: '3px 10px', fontSize: '0.74rem' }}
                          title="Read the script full screen, paced by its (pause) / (slow) cues"
                        >
                          <Maximize2 size={12} />
                          <span>Teleprompter</span>
                        </button>
                      )}
                      {waiting ? (
                        <>
                          <button
                            type="button"
                            className="btn btn-outline"
                            disabled={!!runningId}
                            onClick={() => run(proj, 'approve')}
                            style={{ padding: '6px 12px', fontSize: '0.8rem' }}
                            title="Approve this step and pause again at the next approval step"
                          >
                            <CheckCircle2 size={13} />
                            <span>Approve</span>
                          </button>
                          <button
                            type="button"
                            className="btn"
                            disabled={!!runningId}
                            onClick={() => run(proj, 'approve', undefined, true)}
                            style={{
                              padding: '6px 14px',
                              fontSize: '0.8rem',
                              background: 'linear-gradient(135deg, #10b981, #059669)',
                              borderColor: '#059669',
                              color: '#ffffff',
                              fontWeight: 600,
                            }}
                            title="Approve this step and enable Allow All so future steps run continuously"
                          >
                            <CheckCheck size={14} />
                            <span>Allow all & continue</span>
                          </button>
                        </>
                      ) : (
                        proj.status !== 'completed' && (
                          <>
                            <button
                              type="button"
                              className="btn"
                              disabled={!!runningId}
                              onClick={() => run(proj, 'execute')}
                              style={{ padding: '6px 14px', fontSize: '0.8rem' }}
                            >
                              <Play size={13} />
                              <span>{busy ? 'Running…' : 'Run next step'}</span>
                            </button>
                            {isAllowAll && (
                              <button
                                type="button"
                                className="btn btn-outline"
                                disabled={!!runningId}
                                onClick={() => run(proj, 'run_all')}
                                style={{ padding: '6px 12px', fontSize: '0.8rem', borderColor: '#10b981', color: '#34d399' }}
                                title="Run automatically through all remaining steps to completion"
                              >
                                <FastForward size={13} />
                                <span>Run all</span>
                              </button>
                            )}
                          </>
                        )
                      )}

                      {/* Regenerate: run again from a chosen step (or everything),
                          keeping the title, brief and creator instructions. */}
                      {history(proj).length > 0 && (() => {
                        const stepNames = Array.from(new Set(history(proj).map((h) => h.step_name).filter((n): n is string => !!n)));
                        const from = regenFrom[proj.id] || '';
                        return (
                          <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
                            <select
                              value={from}
                              disabled={!!runningId}
                              onChange={(e) => setRegenFrom((prev) => ({ ...prev, [proj.id]: e.target.value }))}
                              title="Where to start regenerating from"
                              aria-label={`Regenerate from step for ${proj.name}`}
                              style={{ padding: '5px 6px', fontSize: '0.78rem', maxWidth: 170 }}
                            >
                              <option value="">Everything</option>
                              {stepNames.map((n) => <option key={n} value={n}>From: {n}</option>)}
                            </select>
                            <button
                              type="button"
                              className="btn btn-outline"
                              disabled={!!runningId}
                              onClick={() => {
                                const what = from ? `"${from}" and every step after it` : 'every step';
                                if (window.confirm(`Regenerate ${what} for "${proj.name}"? The title, brief and instructions are kept; those steps' files are overwritten.`)) {
                                  run(proj, 'regenerate', undefined, undefined, from || undefined);
                                }
                              }}
                              style={{ padding: '6px 12px', fontSize: '0.8rem' }}
                              title="Run the workflow again from the chosen step, keeping the title and brief"
                            >
                              <RotateCw size={13} />
                              <span>Regenerate</span>
                            </button>
                          </span>
                        );
                      })()}

                      {/* Inspect / Drawer Toggle Button */}
                      <button
                        type="button"
                        className={`btn btn-sm ${isOpen ? '' : 'btn-outline'}`}
                        onClick={() => toggleSelect(proj.id)}
                        style={{
                          padding: '6px 11px',
                          fontSize: '0.78rem',
                          background: isOpen ? 'var(--accent-gradient)' : 'transparent',
                          color: isOpen ? 'var(--text-on-accent)' : 'var(--text-secondary)',
                          borderColor: isOpen ? 'transparent' : 'var(--border-card)',
                        }}
                        title={isOpen ? 'Collapse details panel' : 'Inspect project details, full timeline & assets'}
                      >
                        <span>{isOpen ? 'Close' : 'Details'}</span>
                        {isOpen ? <X size={12} /> : <ChevronRight size={12} />}
                      </button>

                      {/* Archive / bring back */}
                      <button
                        type="button"
                        className="btn btn-outline btn-sm"
                        onClick={(e) => handleArchiveProject(proj, proj.status !== 'archived', e)}
                        disabled={archivingId === proj.id || runningId === proj.id}
                        title={proj.status === 'archived' ? `Bring "${proj.name}" back` : `Archive "${proj.name}" (keeps its files)`}
                        aria-label={proj.status === 'archived' ? `Bring back "${proj.name}"` : `Archive "${proj.name}"`}
                        style={{ padding: '6px 9px', fontSize: '0.78rem', background: 'transparent', color: 'var(--text-secondary)' }}
                      >
                        {proj.status === 'archived' ? <ArchiveRestore size={13} /> : <Archive size={13} />}
                      </button>

                      {/* Delete Project Button */}
                      <button
                        type="button"
                        className="btn btn-outline btn-sm"
                        onClick={(e) => handleDeleteProject(proj, e)}
                        disabled={deletingId === proj.id || runningId === proj.id}
                        title={`Delete project "${proj.name}"`}
                        aria-label={`Delete project "${proj.name}"`}
                        style={{
                          padding: '6px 9px',
                          fontSize: '0.78rem',
                          borderColor: 'rgba(239, 68, 68, 0.35)',
                          color: '#f87171',
                          background: 'transparent',
                        }}
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </div>

                  {/* Metadata Row: Workflow, Stage, ID */}
                  <div className="project-meta">
                    <span>
                      Workflow: <code style={{ color: 'var(--text-primary)', whiteSpace: 'nowrap' }}>{proj.workflow_name}</code>
                    </span>
                    <span>
                      Stage:{' '}
                      <strong
                        style={{
                          color: currentStepItem?.state === 'waiting' ? '#c4b5fd' : currentStepItem?.state === 'current' ? '#fbbf24' : 'var(--text-primary)',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {proj.current_step ? proj.current_step : proj.status === 'completed' ? 'All stages complete' : 'Ready'}
                      </strong>
                    </span>
                    <span title={proj.id}>
                      ID: <code style={{ color: 'var(--text-muted)' }}>{formatProjectId(proj.id)}</code>
                      <CopyButton text={proj.id} />
                    </span>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }} title="Target script runtime; change it, save, then re-run the Script step to resize">
                      Target length:
                      <input
                        type="number"
                        className="form-control"
                        min={0.5}
                        max={180}
                        step={0.5}
                        placeholder="min"
                        value={durationDraft[proj.id] ?? (typeof proj.metadata?.target_duration_minutes === 'number' ? proj.metadata.target_duration_minutes : '')}
                        onChange={(e) => setDurationDraft((prev) => ({ ...prev, [proj.id]: Number(e.target.value) }))}
                        aria-label={`Target length for ${proj.name}`}
                        style={{ width: 64, padding: '2px 6px', fontSize: '0.78rem', height: 26 }}
                      />
                      <button
                        type="button"
                        className="btn btn-outline btn-sm"
                        disabled={savingDuration === proj.id}
                        onClick={() => saveDuration(proj)}
                        style={{ padding: '3px 8px', fontSize: '0.74rem' }}
                      >
                        {savingDuration === proj.id ? 'Saving…' : 'Save'}
                      </button>
                    </span>
                    {(() => {
                      const channel = styleChannel(proj.brand);
                      const channelMode = styleModes[channel] ?? 'mine';
                      const own = proj.metadata?.writing_style;
                      const label = (m: string) => (m === 'agent' ? 'Agent style' : 'My style');
                      return (
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
                          title="Who the scripts sound like. My style: agents match your own writing (Writing Style page), scored and rewritten once below 75/100. Agent style: the agents' own voice, channel guide only. Applies to the next script/edit/narration step you run.">
                          Writing:
                          <select className="form-control" value={own === 'mine' || own === 'agent' ? own : ''}
                            onChange={(e) => saveWritingStyle(proj, e.target.value)}
                            aria-label={`Writing style for ${proj.name}`}
                            style={{ width: 'auto', padding: '2px 6px', fontSize: '0.78rem', height: 26 }}>
                            <option value="">Channel default ({label(channelMode)})</option>
                            <option value="mine">My style</option>
                            <option value="agent">Agent style</option>
                          </select>
                        </span>
                      );
                    })()}
                    {(() => {
                      // A Short cut out of a session recording: where it came from.
                      const parent = proj.metadata?.session_parent as SessionParent | undefined;
                      if (!parent) return null;
                      return (
                        <span title="This Short was recorded at the start of a long video's session and cut out of that recording.">
                          Short {parent.index} of {parent.count} from{' '}
                          <button type="button" onClick={() => setOpenId(parent.project_id)}
                            style={{ background: 'none', border: 'none', padding: 0, color: 'var(--accent-primary)', textDecoration: 'underline', cursor: 'pointer', font: 'inherit' }}>
                            {parent.name}
                          </button>
                        </span>
                      );
                    })()}
                    {(() => {
                      // The recording session: the Shorts first, then the long video.
                      const channel = styleChannel(proj.brand);
                      const defaults = channelFormats?.channels[channel];
                      if (!defaults || proj.workflow_name === 'shorts_ready' || proj.metadata?.session_parent) return null;
                      const own = proj.metadata?.session_format as string | undefined;
                      const count = proj.metadata?.session_shorts_count as number | undefined;
                      const value = own === 'long_only' ? 'long_only' : own === 'shorts_first' ? `shorts_${count ?? defaults.shorts_count}` : '';
                      const channelDefault = defaults.shorts_first ? `${defaults.shorts_count} Shorts first` : 'long video only';
                      return (
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
                          title="Shorts first: you record 3-4 Shorts at the start of the session, then the long video. The Shorts Scripts step writes them, the teleprompter shows them first, and production splits the recording at your greeting -- each Short becomes its own project.">
                          Session:
                          <select className="form-control" value={value}
                            aria-label={`Session format for ${proj.name}`}
                            onChange={(e) => {
                              const v = e.target.value;
                              saveSession(proj, v === '' ? { session_format: null, shorts_count: null }
                                : v === 'long_only' ? { session_format: 'long_only' }
                                : { session_format: 'shorts_first', shorts_count: Number(v.split('_')[1]) },
                              v === 'long_only' ? `"${proj.name}" is recorded as the long video only.`
                                : `"${proj.name}": session settings saved.`);
                            }}
                            style={{ width: 'auto', padding: '2px 6px', fontSize: '0.78rem', height: 26 }}>
                            <option value="">Channel default ({channelDefault})</option>
                            <option value="shorts_3">3 Shorts first, then the long video</option>
                            <option value="shorts_4">4 Shorts first, then the long video</option>
                            <option value="long_only">Long video only</option>
                          </select>
                        </span>
                      );
                    })()}
                    {(() => {
                      // Raat3Baje's episode formats (rules, real encounter, story, black magic, tantra).
                      const formats = channelFormats?.episode_formats[styleChannel(proj.brand)];
                      if (!formats?.length || proj.workflow_name === 'shorts_ready' || proj.metadata?.session_parent) return null;
                      const own = (proj.metadata?.episode_format as string | undefined) || '';
                      return (
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
                          title="The episode's story format. The researcher and the writer follow its section of the channel guide. Applies to the next step you run.">
                          Format:
                          <select className="form-control" value={own}
                            aria-label={`Episode format for ${proj.name}`}
                            onChange={(e) => saveSession(proj, { episode_format: e.target.value || null },
                              e.target.value ? `Format set: ${formats.find((f) => f.key === e.target.value)?.label}.` : 'Format cleared.')}
                            style={{ width: 'auto', padding: '2px 6px', fontSize: '0.78rem', height: 26 }}>
                            <option value="">Not set (channel rules)</option>
                            {formats.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
                          </select>
                        </span>
                      );
                    })()}
                  </div>

                  {/* =========================================================
                      THE STAGES GLIMPSE: Complete Visual Pipeline Overview
                      ========================================================= */}
                  <div className="stages-glimpse-container">
                    <div className="stages-glimpse-header">
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                        <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
                          Stages Pipeline:
                        </span>
                        <span>
                          {totalCount > 0 ? (
                            <>
                              <strong style={{ color: progressPercent === 100 ? '#34d399' : 'var(--accent-primary)' }}>
                                {completedCount} of {totalCount} completed
                              </strong>{' '}
                              ({progressPercent}%)
                            </>
                          ) : (
                            <span>{proj.status === 'completed' ? 'Completed' : 'Active'}</span>
                          )}
                        </span>
                        {currentStepItem && (
                          <span style={{ color: currentStepItem.state === 'waiting' ? '#c4b5fd' : '#fbbf24', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                            {currentStepItem.state === 'waiting'
                              ? <Clock size={12} style={{ color: '#c4b5fd' }} />
                              : <span className="stage-pulse-beacon" />}
                            <span>
                              Active: <strong>{currentStepItem.index}. {currentStepItem.step.name}</strong> ({currentStepItem.step.agent_role})
                            </span>
                          </span>
                        )}
                      </div>

                      {totalCount > 6 && (
                        <button
                          type="button"
                          onClick={() => setWrapStagesMap((prev) => ({ ...prev, [proj.id]: !prev[proj.id] }))}
                          style={{
                            background: 'none',
                            border: 'none',
                            color: 'var(--accent-primary)',
                            fontSize: '0.74rem',
                            cursor: 'pointer',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: 3,
                            padding: '2px 6px',
                            borderRadius: 4,
                          }}
                        >
                          <span>{isWrapStages ? 'Single Row' : `View All (${totalCount})`}</span>
                        </button>
                      )}
                    </div>

                    {/* Progress Bar */}
                    <div className="stages-progress-bar-bg">
                      <div
                        className="stages-progress-bar-fill"
                        style={{
                          width: `${progressPercent}%`,
                          background:
                            progressPercent === 100
                              ? '#10b981'
                              : 'linear-gradient(90deg, #10b981, #3b82f6, #a78bfa)',
                        }}
                      />
                    </div>

                    {/* Glimpse of all stages (Interactive nodes) */}
                    {stepsWithState.length > 0 ? (
                      <div className={`stages-track ${isWrapStages ? 'wrap-mode' : ''}`}>
                        {stepsWithState.map((s) => {
                          const isAutoApproved = Boolean(proj.metadata?.allow_all) && s.step.requires_approval;
                          return (
                            <div
                              key={s.step.name}
                              className={`stage-pill stage-${s.state}`}
                              onClick={() => {
                                setOpenId(proj.id);
                                setSideTab('steps');
                              }}
                              title={`Stage ${s.index}: ${s.step.name}\nAgent: ${s.step.agent_role}\nStatus: ${s.state.toUpperCase()}${
                                s.step.requires_approval ? (isAutoApproved ? ' (Auto-approved via Allow All)' : ' (Needs Approval)') : ''
                              }${s.step.description ? `\n\n${s.step.description}` : ''}\n\nClick to inspect in detail.`}
                            >
                              {s.state === 'done' ? (
                                <CheckCircle2 size={12} style={{ color: '#34d399' }} />
                              ) : s.state === 'current' ? (
                                <span className="stage-pulse-beacon" />
                              ) : s.state === 'waiting' ? (
                                <Clock size={12} style={{ color: '#c4b5fd' }} />
                              ) : s.state === 'failed' ? (
                                <AlertCircle size={12} style={{ color: '#f87171' }} />
                              ) : (
                                <Circle size={8} style={{ color: 'var(--text-muted)' }} />
                              )}
                              <span>
                                {s.index}. {s.step.name}
                              </span>
                              {s.step.requires_approval && s.state !== 'done' && (
                                <span
                                  style={{
                                    fontSize: '0.65rem',
                                    color: isAutoApproved ? '#34d399' : 'var(--accent-primary)',
                                    opacity: 0.9,
                                  }}
                                  title={isAutoApproved ? 'Auto-approved' : 'Approval Gate'}
                                >
                                  {isAutoApproved ? '⚡' : '🔒'}
                                </span>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
                        Workflow definition <code>{proj.workflow_name}</code> loaded with custom steps.
                      </div>
                    )}
                  </div>

                  {/* Collapsed view stops here, after the steps breadcrumb; click the name for the rest. */}
                  {!compact && (<>
                  {/* Waiting for approval notes input */}
                  {waiting && (
                    <div style={{ width: '100%', display: 'flex', gap: 10, alignItems: 'center', marginTop: 4 }}>
                      <input
                        type="text"
                        className="form-control"
                        placeholder={`Revision notes for ${step?.step_name || 'this step'} (optional)`}
                        aria-label={`Revision notes for ${proj.name}`}
                        value={feedback[proj.id] || ''}
                        onChange={(e) => setFeedback((prev) => ({ ...prev, [proj.id]: e.target.value }))}
                      />
                      <button
                        type="button"
                        className="btn btn-outline"
                        disabled={!!runningId || !(feedback[proj.id] || '').trim()}
                        onClick={() => run(proj, 'execute', feedback[proj.id])}
                        style={{ whiteSpace: 'nowrap' }}
                      >
                        <span>Revise with notes</span>
                      </button>
                    </div>
                  )}

                  {/* His own script (or a recorded video): research and writing are skipped. */}
                  {(proj.metadata?.script_source === 'creator' || proj.metadata?.script_source === 'recording') && (
                    <span className="badge" style={{ fontSize: '0.75rem' }}>
                      {proj.metadata?.script_source === 'creator' ? 'Your script' : 'Recorded video'}
                    </span>
                  )}
                  {!busy && !proj.assets?.script && !proj.assets?.script_final && proj.status !== 'completed' && (
                    <div style={{ width: '100%' }}>
                      {ownScriptFor === proj.id ? (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                          <textarea
                            className="form-control"
                            rows={8}
                            aria-label={`Own script for ${proj.name}`}
                            placeholder="Paste your script here"
                            value={ownScriptText}
                            onChange={(e) => setOwnScriptText(e.target.value)}
                          />
                          <div style={{ display: 'flex', gap: 8 }}>
                            <button type="button" className="btn" disabled={ownScriptBusy || !ownScriptText.trim()}
                              onClick={() => submitOwnScript(proj.id)}>
                              <span>{ownScriptBusy ? 'Saving…' : 'Use this script'}</span>
                            </button>
                            <button type="button" className="btn btn-outline" onClick={() => { setOwnScriptFor(null); setOwnScriptText(''); }}>
                              <span>Cancel</span>
                            </button>
                          </div>
                        </div>
                      ) : (
                        <button type="button" className="btn btn-outline" onClick={() => { setOwnScriptFor(proj.id); setOwnScriptText(''); }}>
                          <span>Use my own script</span>
                        </button>
                      )}
                    </div>
                  )}

                  {/* Busy live log viewer */}
                  {busy && (
                    <div style={{ width: '100%' }}>
                      <div className="logs-panel">
                        {log.map((line, i) => <div key={i}>{line}</div>)}
                      </div>
                    </div>
                  )}

                  {proj.assets?.screenplay && ['khayal3baje', 'originals'].includes(String(proj.brand || '').toLowerCase()) && (
                    <AnimateProduce projectId={proj.id} />
                  )}

                  {/* ===================================================
                      PRODUCE VIDEO: the BuzzcafAI -> BuzzEdit bridge.
                      Script-first needs a finished script AND the visual plan;
                      a project with no script yet is produced record-first
                      from a video he already has (visuals planned from it).
                      =================================================== */}
                  {(!proj.assets?.script || Boolean(proj.metadata?.recording_path)
                    || Boolean(proj.assets?.visual_plan) || Boolean(proj.metadata?.short_format)) && (() => {
                    const status = produceStatus[proj.id];
                    // A render BuzzEdit may still be working on: the run failed
                    // (often just BuzzEdit too busy to answer) or the Studio
                    // restarted mid-render, and no finished video is recorded.
                    const canResume = !!proj.metadata?.buzzedit_project_id && !proj.metadata?.output_path
                      && (!status || status.state === 'idle' || status.state === 'failed');
                    const producing = producingId === proj.id || status?.state === 'starting' || status?.state === 'running';
                    // Paused at a review gate: still not safe to start a new
                    // run (the backend 409s), but the recording-path/style
                    // controls stay usable since nothing is running.
                    const gated = status?.state === 'awaiting_cut_review' || status?.state === 'awaiting_plan_review'
                      || status?.state === 'awaiting_effects_review';
                    const inQueue = status?.state === 'queued' || status?.state === 'paused';
                    const qItem = queueItemFor(proj.id);
                    const queueRunningElsewhere = !!queueState?.items.some((i) => i.project_id !== proj.id
                      && (i.status === 'running' || i.status === 'queued'));
                    const isDragging = dragOverId === proj.id;
                    return (
                      <div className="stages-glimpse-container" style={{ marginTop: 4 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
                          <Video size={14} style={{ color: 'var(--accent-primary)' }} />
                          <span style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: '0.85rem' }}>
                            Produce Video (BuzzEdit)
                          </span>

                          {/* BuzzEdit online status pill & manual start button */}
                          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginLeft: 4 }}>
                            {buzzEditStatus?.online ? (
                              <span
                                style={{
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                  gap: 5,
                                  fontSize: '0.72rem',
                                  padding: '2px 8px',
                                  borderRadius: 12,
                                  background: 'rgba(16, 185, 129, 0.12)',
                                  color: '#10b981',
                                  border: '1px solid rgba(16, 185, 129, 0.25)',
                                }}
                                title={`BuzzEdit is active at ${buzzEditStatus.url || 'localhost'}${buzzEditStatus.comfyui_online ? ' with ComfyUI' : ''}`}
                              >
                                <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#10b981', display: 'inline-block' }} />
                                {buzzEditStatus.comfyui_online ? 'BuzzEdit & ComfyUI Ready' : 'BuzzEdit Online'}
                              </span>
                            ) : (
                              <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                                <span
                                  style={{
                                    display: 'inline-flex',
                                    alignItems: 'center',
                                    gap: 5,
                                    fontSize: '0.72rem',
                                    padding: '2px 8px',
                                    borderRadius: 12,
                                    background: 'rgba(245, 158, 11, 0.12)',
                                    color: '#f59e0b',
                                    border: '1px solid rgba(245, 158, 11, 0.25)',
                                  }}
                                  title="BuzzEdit is currently offline. Clicking Produce Video will start it automatically, or click Start BuzzEdit to launch now."
                                >
                                  <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#f59e0b', display: 'inline-block' }} />
                                  BuzzEdit Offline
                                </span>
                                <button
                                  type="button"
                                  className="btn btn-outline btn-sm"
                                  onClick={startBuzzEdit}
                                  disabled={startingBuzzEdit}
                                  style={{ padding: '2px 8px', fontSize: '0.72rem', height: 22 }}
                                  title="Start BuzzEdit process in background"
                                >
                                  <RotateCw size={11} className={startingBuzzEdit ? 'animate-spin' : ''} />
                                  <span>{startingBuzzEdit ? 'Starting…' : 'Start BuzzEdit'}</span>
                                </button>
                              </div>
                            )}
                          </div>

                        </div>

                        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
                          {/* Drag & Drop Recording Area + Browse Button */}
                          <div
                            onDragOver={(e) => handleDragOver(e, proj.id)}
                            onDragLeave={(e) => handleDragLeave(e, proj.id)}
                            onDrop={(e) => handleDrop(e, proj)}
                            style={{
                              position: 'relative',
                              flex: '1 1 340px',
                              minWidth: 260,
                              display: 'flex',
                              alignItems: 'center',
                              border: isDragging ? '1px dashed var(--accent-primary, #6366f1)' : '1px solid var(--border-color, rgba(255,255,255,0.12))',
                              background: isDragging ? 'rgba(99, 102, 241, 0.1)' : 'var(--bg-card, rgba(255,255,255,0.02))',
                              borderRadius: 6,
                              transition: 'all 0.15s ease',
                              padding: '2px',
                            }}
                          >
                            <div style={{ position: 'relative', flex: 1, display: 'flex', alignItems: 'center' }}>
                              {isDragging ? (
                                <UploadCloud size={14} style={{ position: 'absolute', left: 9, color: 'var(--accent-primary, #6366f1)' }} />
                              ) : (
                                <Mic size={13} style={{ position: 'absolute', left: 9, color: 'var(--text-muted)' }} />
                              )}
                              <input
                                type="text"
                                className="form-control"
                                placeholder={isDragging ? 'Drop video file here…' : 'Drag video here or click Browse (e.g. C:\\Recordings\\take1.mp4)'}
                                aria-label={`Recording path for ${proj.name}`}
                                value={recordingPath[proj.id] || ''}
                                onChange={(e) => setRecordingPath((prev) => ({ ...prev, [proj.id]: e.target.value }))}
                                disabled={producing}
                                style={{
                                  paddingLeft: 28,
                                  paddingRight: 6,
                                  fontSize: '0.8rem',
                                  height: 30,
                                  border: 'none',
                                  background: 'transparent',
                                  boxShadow: 'none',
                                }}
                              />
                            </div>
                            <button
                              type="button"
                              className="btn btn-outline btn-sm"
                              onClick={() => browseRecording(proj)}
                              disabled={producing || browsingId === proj.id}
                              style={{
                                marginRight: 2,
                                padding: '3px 10px',
                                fontSize: '0.74rem',
                                height: 26,
                                whiteSpace: 'nowrap',
                                display: 'flex',
                                alignItems: 'center',
                                gap: 4,
                              }}
                              title="Browse computer for recording file"
                            >
                              <FolderOpen size={12} />
                              <span>{browsingId === proj.id ? 'Browsing…' : 'Browse'}</span>
                            </button>
                          </div>

                          {(() => {
                            const vs = videoSettings[proj.id];
                            const overridesFor = vs?.video_settings || {};
                            const effective = vs?.effective || {};
                            const genreVal = (overridesFor.genre ?? effective.genre ?? 'general') as string;
                            const genreSecondaryVal = (overridesFor.genre_secondary ?? effective.genre_secondary ?? '') as string;
                            const densityVal = (overridesFor.density ?? effective.density ?? 'balanced') as string;
                            const voicePresetVal = (overridesFor.voice_preset ?? effective.voice_preset ?? 'studio_mic') as string;
                            const reviewModeVal = (overridesFor.review_mode ?? effective.review_mode ?? 'plan') as string;
                            const autoCutChecked = overridesFor.precut !== true;
                            const allowFreeStockChecked = Boolean(overridesFor.allow_free_stock);
                            const isAdvancedOpen = Boolean(advancedOpen[proj.id]);
                            const autoProceed = reviewModeVal === 'none';
                            const reviewCuts = reviewModeVal === 'cuts_and_plan';
                            const pretty = (v: string) => v.replace(/_/g, ' ');
                            const hasRecording = Boolean((recordingPath[proj.id] || '').trim());
                            // Each control gets a heading so it says what it does;
                            // the select itself shows the saved value.
                            const field = (heading: string, hint: string, control: ReactNode) => (
                              <div className="vs-field" title={hint}>
                                <span className="vs-field-label">{heading}</span>
                                {control}
                              </div>
                            );
                            return (
                              <>
                                {field('Genre', 'Main style of the video: drives B-roll, grade, transitions and effects', (
                                  <select
                                    className="form-control vs-select"
                                    value={genreVal}
                                    onChange={(e) => patchVideoSettings(proj.id, { genre: e.target.value })}
                                    aria-label={`Genre for ${proj.name}`}
                                    disabled={producing}
                                    style={{ width: 150 }}
                                  >
                                    {GENRES.map((g) => (
                                      <option key={g} value={g}>{pretty(g)}</option>
                                    ))}
                                  </select>
                                ))}
                                {field('Secondary genre', 'Optional second style blended in (e.g. vlog + motivational)', (
                                  <select
                                    className="form-control vs-select"
                                    value={genreSecondaryVal}
                                    onChange={(e) => patchVideoSettings(proj.id, { genre_secondary: e.target.value || null })}
                                    aria-label={`Secondary genre for ${proj.name}`}
                                    disabled={producing}
                                    style={{ width: 150 }}
                                  >
                                    <option value="">none</option>
                                    {GENRES.map((g) => (
                                      <option key={g} value={g}>{pretty(g)}</option>
                                    ))}
                                  </select>
                                ))}
                                {field('Visual density', 'How much B-roll, zooms and text effects the video gets', (
                                  <select
                                    className="form-control vs-select"
                                    value={densityVal}
                                    onChange={(e) => patchVideoSettings(proj.id, { density: e.target.value })}
                                    aria-label={`Visual density for ${proj.name}`}
                                    disabled={producing}
                                    style={{ width: 120 }}
                                  >
                                    {DENSITIES.map((d) => (
                                      <option key={d} value={d}>{pretty(d)}</option>
                                    ))}
                                  </select>
                                ))}
                                {field('Face', 'How your face is used. Mixed: your face comes back between the pictures all through (the Video / Images sliders). Face first: only your face for the opening, then pictures and clips only, to the end.', (() => {
                                  const layout = (overridesFor.face_layout ?? effective.face_layout ?? 'mixed') as string;
                                  const secs = Number(overridesFor.face_intro_seconds ?? effective.face_intro_seconds ?? 90);
                                  const own = Boolean(overridesFor.face_layout);
                                  const pick = (value: 'mixed' | 'face_intro') => (
                                    <button type="button" className={`btn btn-sm${layout === value ? '' : ' btn-outline'}`}
                                      onClick={() => patchVideoSettings(proj.id, { face_layout: value })}
                                      disabled={producing}
                                      style={{ padding: '2px 8px', fontSize: '0.74rem', height: 26, borderRadius: 0 }}>
                                      {value === 'mixed' ? 'Mixed' : 'Face first'}
                                    </button>
                                  );
                                  return (
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                                      <span style={{ display: 'inline-flex', borderRadius: 6, overflow: 'hidden' }}>
                                        {pick('mixed')}{pick('face_intro')}
                                      </span>
                                      {layout === 'face_intro' && (
                                        <span style={{ fontSize: '0.74rem', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                                          first
                                          <select className="form-control vs-select" value={secs}
                                            onChange={(e) => patchVideoSettings(proj.id, { face_intro_seconds: Number(e.target.value) })}
                                            aria-label={`Face intro seconds for ${proj.name}`}
                                            disabled={producing}
                                            style={{ width: 'auto', padding: '2px 6px', fontSize: '0.76rem', height: 24 }}>
                                            {[30, 45, 60, 75, 90, 105, 120, 150, 180].map((s) => (
                                              <option key={s} value={s}>{s < 60 ? `${s} s` : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')} min`}</option>
                                            ))}
                                          </select>
                                          then pictures only
                                        </span>
                                      )}
                                      {own ? (
                                        <button type="button" onClick={() => patchVideoSettings(proj.id, { face_layout: null, face_intro_seconds: null })}
                                          disabled={producing}
                                          style={{ background: 'none', border: 'none', padding: 0, color: 'var(--accent-primary)', textDecoration: 'underline', cursor: 'pointer', fontSize: '0.72rem' }}>
                                          channel default
                                        </button>
                                      ) : (
                                        <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>(channel default)</span>
                                      )}
                                    </div>
                                  );
                                })())}
                                {field('Voice sound', 'How your voice is cleaned and EQ-ed in the final mix', (
                                  <select
                                    className="form-control vs-select"
                                    value={voicePresetVal}
                                    onChange={(e) => patchVideoSettings(proj.id, { voice_preset: e.target.value })}
                                    aria-label={`Voice sound for ${proj.name}`}
                                    disabled={producing}
                                    style={{ width: 140 }}
                                  >
                                    {VOICE_PRESETS.map((v) => (
                                      <option key={v} value={v}>{pretty(v)}</option>
                                    ))}
                                  </select>
                                ))}
                                {field('Review', 'Whether to pause for you before the long render', (
                                  <div className="vs-checks">
                                    <label className="vs-check" title="On: plan the visuals and render straight away. Off: pause so you can review and edit the visual plan first.">
                                      <input
                                        type="checkbox"
                                        checked={autoProceed}
                                        onChange={(e) => patchVideoSettings(proj.id, {
                                          review_mode: e.target.checked ? 'none' : (reviewCuts ? 'cuts_and_plan' : 'plan'),
                                        })}
                                        aria-label={`Auto-proceed (no plan review) for ${proj.name}`}
                                        disabled={producing}
                                      />
                                      Auto-proceed (no plan review)
                                    </label>
                                    <label className="vs-check" title="Also pause after the auto-cut so you can check the cuts in BuzzEdit first.">
                                      <input
                                        type="checkbox"
                                        checked={reviewCuts}
                                        onChange={(e) => patchVideoSettings(proj.id, {
                                          review_mode: e.target.checked ? 'cuts_and_plan' : 'plan',
                                        })}
                                        aria-label={`Review cuts first for ${proj.name}`}
                                        disabled={producing || autoProceed}
                                      />
                                      Review cuts first
                                    </label>
                                    <label className="vs-check" title="Before the long render, BuzzEdit renders ~20 seconds of your cut with the captions, text effects, a zoom, sound effects and music, so you can check the look and re-test after changing settings.">
                                      <input
                                        type="checkbox"
                                        checked={Boolean(overridesFor.effects_review)}
                                        onChange={(e) => patchVideoSettings(proj.id, { effects_review: e.target.checked })}
                                        aria-label={`Review effects first for ${proj.name}`}
                                        disabled={producing}
                                      />
                                      Review effects first (20 s sample)
                                    </label>
                                    <label className="vs-check" title="Animated maps, charts, kinetic text, stick figures, collages, flow diagrams, callouts and shape transitions. Off: each is drawn as its still card instead.">
                                      <input
                                        type="checkbox"
                                        checked={(overridesFor.motion_graphics ?? effective.motion_graphics) !== false}
                                        onChange={(e) => patchVideoSettings(proj.id, { motion_graphics: e.target.checked ? null : false })}
                                        aria-label={`Motion graphics for ${proj.name}`}
                                        disabled={producing}
                                      />
                                      Motion graphics
                                    </label>
                                    <label className="vs-check" title="About 3 in 10 stills with real depth get a slow 2.5D camera move (parallax) instead of a flat zoom. Every channel, story channels included.">
                                      <input
                                        type="checkbox"
                                        checked={Number(overridesFor.parallax_share ?? effective.parallax_share ?? 0.3) > 0}
                                        onChange={(e) => patchVideoSettings(proj.id, { parallax_share: e.target.checked ? null : 0 })}
                                        aria-label={`2.5D depth on stills for ${proj.name}`}
                                        disabled={producing}
                                      />
                                      2.5D depth on stills
                                    </label>
                                    <label className="vs-check" title="Pictures and videos only: no captions, headings, cards, newspaper cutaways, text effects, zoom punches, whooshes or flash/shake hits. Same characters in every shot. On by default for Raat3Baje, Khayal3Baje and Beyond3Baje.">
                                      <input
                                        type="checkbox"
                                        checked={(overridesFor.visual_style ?? effective.visual_style) === 'story'}
                                        onChange={(e) => patchVideoSettings(proj.id, { visual_style: e.target.checked ? 'story' : 'full' })}
                                        aria-label={`Story visuals only for ${proj.name}`}
                                        disabled={producing}
                                      />
                                      Story visuals only (pictures + videos)
                                    </label>
                                  </div>
                                ))}
                                {field('Art style', 'The medium every picture, clip, thumbnail scene and text card is made in. Explainer and stick figure put short text (numbers, names) back on a story channel; cartoon is pictures only.', (
                                  <select
                                    className="form-control vs-select"
                                    value={(overridesFor.art_style ?? effective.art_style ?? 'real') as string}
                                    onChange={(e) => patchVideoSettings(proj.id, { art_style: e.target.value })}
                                    aria-label={`Art style for ${proj.name}`}
                                    disabled={producing}
                                  >
                                    {ART_STYLES.map((s) => (
                                      <option key={s.id} value={s.id} title={s.hint}>{s.label}</option>
                                    ))}
                                  </select>
                                ))}
                                {field('Editing', 'What BuzzEdit does with the raw take', (
                                  <div className="vs-checks">
                                    <label className="vs-check" title="On: BuzzEdit also removes fumbles and long pauses. Off: the recording is already cut, so BuzzEdit keeps every frame and only dresses it.">
                                      <input
                                        type="checkbox"
                                        checked={autoCutChecked}
                                        onChange={(e) => patchVideoSettings(proj.id, { precut: !e.target.checked })}
                                        aria-label={`Auto-cut fumbles for ${proj.name}`}
                                        disabled={producing}
                                      />
                                      Auto-cut fumbles
                                    </label>
                                    <label className="vs-check" title="On: BuzzEdit may fall back to free Pixabay footage when ComfyUI cannot make a visual (key and default in Settings -> Stock footage).">
                                      <input
                                        type="checkbox"
                                        checked={allowFreeStockChecked}
                                        onChange={(e) => patchVideoSettings(proj.id, { allow_free_stock: e.target.checked })}
                                        aria-label={`Free stock fallback for ${proj.name}`}
                                        disabled={producing}
                                      />
                                      Free stock fallback (Pixabay)
                                    </label>
                                  </div>
                                ))}
                                {field('Music', 'Background music: on/off, script cues, engine, a brief for the whole video -- or your own picked tracks at fixed levels', (
                                  <MusicSettings
                                    music={(overridesFor.music ?? effective.music ?? true) !== false}
                                    musicCues={(overridesFor.music_cues ?? effective.music_cues ?? true) !== false}
                                    engine={String(overridesFor.music_engine ?? effective.music_engine ?? 'ace_step')}
                                    brief={String(overridesFor.music_brief ?? effective.music_brief ?? '')}
                                    tracks={(overridesFor.music_tracks ?? effective.music_tracks ?? []) as PickedTrack[]}
                                    tracksMode={String(overridesFor.music_tracks_mode ?? effective.music_tracks_mode ?? 'together')}
                                    disabled={producing}
                                    onPatch={(patch) => patchVideoSettings(proj.id, patch)}
                                    onToast={toast}
                                  />
                                ))}
                                {field('Eye contact', 'Teleprompter gaze correction, done in BuzzEdit: prompter side, angle, aim and steadiness', (
                                  <div>
                                    <button
                                      type="button"
                                      className="btn btn-outline btn-sm"
                                      onClick={toggleEyeContact}
                                      aria-expanded={eyeContactOpen}
                                      style={{ display: 'inline-flex', alignItems: 'center', gap: 4, padding: '2px 8px', fontSize: '0.72rem', marginBottom: eyeContactOpen ? 6 : 0 }}
                                    >
                                      {eyeContactOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                                      {eyeContactOpen ? 'Minimise' : 'Show eye contact settings'}
                                    </button>
                                    {eyeContactOpen && (
                                      <EyeContactSettings
                                        projectId={proj.id}
                                        hasRecording={Boolean(proj.metadata?.buzzedit_project_id)}
                                        disabled={producing}
                                        onToast={toast}
                                      />
                                    )}
                                  </div>
                                ))}
                                <button
                                  type="button"
                                  className="btn btn-outline btn-sm"
                                  onClick={() => setAdvancedOpen((prev) => ({ ...prev, [proj.id]: !prev[proj.id] }))}
                                  style={{ padding: '3px 10px', fontSize: '0.74rem', alignSelf: 'flex-end' }}
                                >
                                  <span>{isAdvancedOpen ? 'Hide advanced ▲' : 'Advanced ▼'}</span>
                                </button>
                                <button
                                  type="button"
                                  className="btn btn-outline btn-sm"
                                  onClick={() => toggleCast(proj.id)}
                                  style={{ padding: '3px 10px', fontSize: '0.74rem', alignSelf: 'flex-end' }}
                                  title="The story's characters and the voice BuzzEdit gives each one's lines before the render."
                                >
                                  <span>{castOpen[proj.id] ? 'Hide cast voices ▲' : 'Cast voices ▼'}</span>
                                </button>
                                <button
                                  type="button"
                                  className="btn"
                                  disabled={producing || gated || inQueue || !!runningId || !hasRecording}
                                  onClick={() => produceVideo(proj)}
                                  style={{ padding: '6px 14px', fontSize: '0.8rem', whiteSpace: 'nowrap', alignSelf: 'flex-end' }}
                                  title={gated ? 'Awaiting your review below: continue or cancel it first.'
                                    : inQueue ? 'Already in the production queue.'
                                    : !hasRecording ? 'Pick or drop your recording first.'
                                    : queueRunningElsewhere || queueState?.paused
                                      ? 'Add this video to the production queue; it starts when the videos ahead of it finish.'
                                      : 'Start producing the video with the settings above.'}
                                >
                                  <Video size={13} />
                                  <span>{producing ? 'Producing…' : gated ? 'Awaiting review'
                                    : status?.state === 'queued' ? 'Queued' : status?.state === 'paused' ? 'Paused'
                                    : queueRunningElsewhere || queueState?.paused ? 'Add to production queue' : 'Start video production'}</span>
                                </button>
                              </>
                            );
                          })()}
                        </div>

                        {(() => {
                          // A Shorts-first session: where the long video starts, and the Shorts cut out of it.
                          const defaults = channelFormats?.channels[styleChannel(proj.brand)];
                          const own = proj.metadata?.session_format as string | undefined;
                          // A session is split only when it was planned as one: its Shorts were
                          // written, or it was set to Shorts first (or given a split point) by hand.
                          const planned = own === 'shorts_first' || Boolean(proj.assets?.shorts_json)
                            || typeof proj.metadata?.session_split_s === 'number';
                          const isSession = proj.workflow_name !== 'shorts_ready' && !proj.metadata?.session_parent
                            && (own ? own === 'shorts_first' : Boolean(defaults?.shorts_first)) && planned;
                          if (!isSession) return null;
                          const split = proj.metadata?.session_split as SessionSplit | undefined;
                          const savedAt = proj.metadata?.session_split_s as number | undefined;
                          const draft = splitDraft[proj.id] ?? (typeof savedAt === 'number' ? String(savedAt) : '');
                          const commitSplit = () => {
                            const raw = (splitDraft[proj.id] ?? '').trim();
                            if (splitDraft[proj.id] === undefined) return;
                            const value = raw === '' ? null : Number(raw);
                            if (value !== null && (Number.isNaN(value) || value < 0)) {
                              toast('Enter the seconds into the recording where your greeting starts, or leave it empty.', 'error');
                              return;
                            }
                            saveSession(proj, { split_at_s: value },
                              value === null ? 'The long video will start at your greeting (found automatically).'
                                : `The long video starts ${value} s into the recording.`);
                            setSplitDraft((prev) => { const next = { ...prev }; delete next[proj.id]; return next; });
                          };
                          const fmt = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`;
                          return (
                            <div style={{ marginTop: 10, padding: '8px 10px', border: '1px solid var(--border-color, rgba(255,255,255,0.1))', borderRadius: 6, fontSize: '0.78rem', display: 'grid', gap: 6 }}>
                              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
                                <strong>Recording session</strong>
                                <span style={{ color: 'var(--text-secondary)' }}>
                                  Record the Shorts first (the teleprompter's "Recording session" shows them in order), then your greeting and the long video, in one recording. Production splits it at your greeting.
                                </span>
                                <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
                                  title="Only if the greeting was not found (or you changed it): the seconds into the recording where the long video starts. Empty = find your greeting automatically.">
                                  Long video starts at
                                  <input type="number" className="form-control" min={0} step={0.5} placeholder="auto"
                                    aria-label={`Long video start time for ${proj.name}`}
                                    value={draft}
                                    onChange={(e) => setSplitDraft((prev) => ({ ...prev, [proj.id]: e.target.value }))}
                                    onBlur={commitSplit}
                                    onKeyDown={(e) => { if (e.key === 'Enter') commitSplit(); }}
                                    style={{ width: 76, padding: '2px 6px', fontSize: '0.76rem', height: 24 }} />
                                  s
                                </label>
                              </div>
                              {split && (
                                <div style={{ display: 'grid', gap: 4 }}>
                                  <span>
                                    The long video starts at <b>{fmt(split.boundary_s)}</b> ({split.how === 'manual' ? 'set by you' : 'your greeting'})
                                    {split.programme_cut_s ? ` -- ${split.programme_cut_s.toFixed(0)} s of Shorts cut off it.` : '.'}
                                  </span>
                                  {split.shorts.map((s) => (
                                    <span key={s.index} style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                                      <span style={{ color: 'var(--text-muted)' }}>Short {s.index}</span>
                                      {s.project_id ? (
                                        <button type="button" onClick={() => setOpenId(s.project_id as string)}
                                          style={{ background: 'none', border: 'none', padding: 0, color: 'var(--accent-primary)', textDecoration: 'underline', cursor: 'pointer', font: 'inherit' }}>
                                          {s.title}
                                        </button>
                                      ) : <span>{s.title}</span>}
                                      <span style={{ color: 'var(--text-secondary)' }}>{fmt(s.from_s)}-{fmt(s.to_s)}{s.queued ? ' · queued' : ''}</span>
                                      {s.error && <span style={{ color: '#f87171' }}>{s.error}</span>}
                                    </span>
                                  ))}
                                  {split.warning && <span style={{ color: '#fbbf24' }}>{split.warning}</span>}
                                </div>
                              )}
                            </div>
                          );
                        })()}

                        {Boolean(advancedOpen[proj.id]) && (() => {
                          const vs = videoSettings[proj.id];
                          const overridesFor = vs?.video_settings || {};
                          const effective = vs?.effective || {};
                          const num = (key: string, fallback: number) => {
                            const v = (overridesFor as Record<string, unknown>)[key];
                            return typeof v === 'number' ? v : (typeof effective[key] === 'number' ? (effective[key] as number) : fallback);
                          };
                          const field = (label: string, key: string, fallback: number, min: number, max: number, step: number, toPct = false, hint?: string) => (
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }} key={key} title={hint}>
                              <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>{label}</span>
                              <input
                                type="range"
                                min={toPct ? min * 100 : min}
                                max={toPct ? max * 100 : max}
                                step={toPct ? step * 100 : step}
                                value={toPct ? Math.round(num(key, fallback) * 100) : num(key, fallback)}
                                onChange={(e) => patchVideoSettings(proj.id, { [key]: toPct ? Number(e.target.value) / 100 : Number(e.target.value) })}
                                aria-label={`${label} for ${proj.name}`}
                                disabled={producing}
                                style={{ width: 90 }}
                              />
                              <span style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', minWidth: 40, whiteSpace: 'nowrap' }}>
                                {toPct ? `${Math.round(num(key, fallback) * 100)}%` : num(key, fallback)}
                              </span>
                            </div>
                          );
                          return (
                            <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', alignItems: 'center', marginTop: 10, padding: '8px 10px', border: '1px solid var(--border-color, rgba(255,255,255,0.1))', borderRadius: 6 }}>
                              {(() => {
                                // Video / images / face as shares of the whole running time, each up to
                                // 100%, filled in that order: video first, then images, the face gets the rest.
                                const saved = vs?.mix ?? { video: 0.7, images: 0.2, face: 0.1, mode: 'runtime' as const };
                                const draft = mixDraft[proj.id];
                                const mix = draft
                                  ? { video: draft.video, images: draft.images, face: Math.max(0, 1 - draft.video - draft.images) }
                                  : saved;
                                // Dragging only moves the slider (no request per pixel); the value is
                                // saved once when it is let go.
                                const setMix = (video: number, images: number) =>
                                  setMixDraft((prev) => ({ ...prev, [proj.id]: { video, images: Math.min(images, 1 - video) } }));
                                const commitMix = () => {
                                  const d = mixDraft[proj.id];
                                  if (!d) return;
                                  patchVideoSettings(proj.id, { video_broll_share: d.video, image_broll_share: d.images });
                                  setMixDraft((prev) => { const next = { ...prev }; delete next[proj.id]; return next; });
                                };
                                const slider = (label: string, value: number, onChange: (v: number) => void, hint: string, color: string) => (
                                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }} title={hint}>
                                    <span style={{ fontSize: '0.72rem', color, whiteSpace: 'nowrap', fontWeight: 600 }}>{label}</span>
                                    <input type="range" min={0} max={100} step={2} value={Math.round(value * 100)}
                                      aria-label={`${label} for ${proj.name}`}
                                      onChange={(e) => onChange(Number(e.target.value) / 100)}
                                      onPointerUp={commitMix} onKeyUp={commitMix} onBlur={commitMix}
                                      style={{ width: 120 }} />
                                    <span style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', minWidth: 38, whiteSpace: 'nowrap' }}>{Math.round(value * 100)}%</span>
                                  </div>
                                );
                                return (
                                  <>
                                    {slider('Video', mix.video, (v) => setMix(v, mix.images),
                                      'Share of the whole running time that is generated video clips (up to 100%). It comes first: images and your face share what is left.', '#a78bfa')}
                                    {slider('Images', mix.images, (i) => setMix(mix.video, i),
                                      'Share of the whole running time that is still images, after the video (up to whatever video leaves).', '#38bdf8')}
                                    {((overridesFor.face_layout ?? effective.face_layout) === 'face_intro') ? (
                                      <span style={{ fontSize: '0.72rem', whiteSpace: 'nowrap' }}
                                        title="Face first: only your face for the opening, then pictures only. Video and Images here only split those pictures between clips and stills, in this proportion.">
                                        <b style={{ color: '#34d399' }}>Face</b>{' '}
                                        <span style={{ color: 'var(--text-secondary)' }}>
                                          first {Number(overridesFor.face_intro_seconds ?? effective.face_intro_seconds ?? 90)} s only
                                          {mix.video + mix.images > 0 ? ` · clips ${Math.round((100 * mix.video) / (mix.video + mix.images))}% of the pictures` : ''}
                                        </span>
                                      </span>
                                    ) : (
                                      <span style={{ fontSize: '0.72rem', whiteSpace: 'nowrap' }}
                                        title="Your face gets whatever video and images leave. Set video + images to 100% for no face at all.">
                                        <b style={{ color: '#34d399' }}>Face</b> <span style={{ color: 'var(--text-secondary)' }}>{Math.round(mix.face * 100)}%</span>
                                      </span>
                                    )}
                                    <ProductionEstimate projectId={proj.id} video={mix.video} images={mix.images} />
                                    <OwnFootage projectId={proj.id} onToast={toast}
                                      planned={Array.isArray((status as { planning?: { unused_clips?: string[] } } | undefined)?.planning?.unused_clips)}
                                      unusedClips={(status as { planning?: { unused_clips?: string[] } } | undefined)?.planning?.unused_clips} />
                                    {producing && (
                                      <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}
                                        title="A change made while BuzzEdit is generating reaches the running render: it stops making clips once the new video share is met and trims the pictures to the new coverage before placing them. Nothing restarts.">
                                        · applies to the running render
                                      </span>
                                    )}
                                  </>
                                );
                              })()}
                              {field('Punch/min', 'punch_rate_per_minute', 1.5, 0, 6, 0.5)}
                              {field('Text FX/min', 'text_fx_per_minute', 2.0, 0, 6, 0.5)}
                              {field('Zoom depth', 'zoom_depth', 0.1, 0, 0.3, 0.01, true)}
                              {field('Base zoom', 'base_zoom', 1.0, 1.0, 1.5, 0.01, false,
                                'The recording\'s resting frame for the whole video: 1.00 is the full frame, 1.15 starts 15% tighter. Every push-in and punch-in moves from there; B-roll keeps its full frame.')}
                              <label style={{ display: 'flex', alignItems: 'center', gap: 6 }} key="clip_generation"
                                title="How BuzzEdit generates the video clips, for every production (sent to BuzzEdit when a production starts). HQ is sharper and takes longer.">
                                <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>Clip generation</span>
                                <select className="form-control" value={clipGenMode}
                                  onChange={(e) => void saveClipGenMode(e.target.value === 'hq' ? 'hq' : 'classic')}
                                  aria-label="Clip generation"
                                  style={{ width: 'auto', padding: '2px 6px', fontSize: '0.72rem', height: 24 }}>
                                  <option value="classic">Classic (832×480, fast)</option>
                                  <option value="hq">HQ (1024×576 → 1080p, slower)</option>
                                </select>
                              </label>
                              {(() => {
                                // The channel's BuzzEdit audio rack preset (Studio setting `audio_rack_preset`).
                                const current = audioRackFor(proj.brand);
                                const names = audioRackPresets || [];
                                const options = current && !names.includes(current) ? [current, ...names] : names;
                                return (
                                  <label style={{ display: 'flex', alignItems: 'center', gap: 6 }} key="audio_rack"
                                    title={`The BuzzEdit audio rack preset put on the voice (A1) before every render, for every ${proj.brand} project. Rack presets are saved in BuzzEdit's Audio panel.${audioRackPresets === null ? ' BuzzEdit did not list its presets (not running?).' : ''}`}>
                                    <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>Audio rack</span>
                                    <select className="form-control" value={current}
                                      onChange={(e) => void saveAudioRack(proj.brand, e.target.value)}
                                      aria-label={`Audio rack for ${proj.brand}`}
                                      style={{ width: 'auto', padding: '2px 6px', fontSize: '0.72rem', height: 24 }}>
                                      <option value="">None (the edit's own rack)</option>
                                      {options.map((n) => <option key={n} value={n}>{n}</option>)}
                                    </select>
                                  </label>
                                );
                              })()}
                              {/* Clip length: how long each B-roll cutaway (and generated video clip) holds. */}
                              {(() => {
                                const lo = num('broll_seconds_min', 3);
                                const hi = num('broll_seconds_max', 5);
                                const slider = (value: number, onChange: (v: number) => void, title: string) => (
                                  <input
                                    type="range" min={1} max={8} step={0.5} value={value}
                                    onChange={(e) => onChange(Number(e.target.value))}
                                    aria-label={`${title} for ${proj.name}`}
                                    disabled={producing} style={{ width: 80 }} title={title}
                                  />
                                );
                                return (
                                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }} key="broll_seconds"
                                    title="How long each B-roll clip stays on screen (1–8 s). Longer AI video clips take longer to generate.">
                                    <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>Clip length</span>
                                    {slider(lo, (v) => patchVideoSettings(proj.id, v > hi ? { broll_seconds_min: v, broll_seconds_max: v } : { broll_seconds_min: v }), 'Shortest clip (s)')}
                                    {slider(hi, (v) => patchVideoSettings(proj.id, v < lo ? { broll_seconds_min: v, broll_seconds_max: v } : { broll_seconds_max: v }), 'Longest clip (s)')}
                                    <span style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>{lo}–{hi} s</span>
                                  </div>
                                );
                              })()}
                            </div>
                          );
                        })()}

                        {Boolean(castOpen[proj.id]) && (() => {
                          // Each story character's voice: the next production sends BuzzEdit
                          // a voice map and it converts the character's labelled lines
                          // before the render. The narration stays the creator's own.
                          const cast = castViews[proj.id];
                          const busy = !!castBusy[proj.id];
                          const voices = voiceLibrary?.voices || [];
                          const presets = Object.entries(voiceLibrary?.presets || {});
                          const libraryName = (name?: string | null) =>
                            voices.find((v) => v.name.toLowerCase() === String(name || '').toLowerCase())?.name;
                          const valueOf = (v?: CastVoiceEntry | null) => {
                            if (!v || (!v.voice && !v.preset)) return '';
                            if (v.preset) {
                              const stem = voiceLibrary?.presets?.[v.preset]?.voice;
                              return !v.voice || String(stem || '').toLowerCase() === v.voice.toLowerCase()
                                ? `preset:${v.preset}` : `entry:${v.preset}|${v.voice}`;
                            }
                            const name = libraryName(v.voice);
                            return name ? `voice:${name}` : `entry:|${v.voice}`;
                          };
                          const small = { padding: '3px 10px', fontSize: '0.74rem' };
                          return (
                            <div style={{ marginTop: 10, padding: '8px 10px', border: '1px solid var(--border-color)', borderRadius: 8 }}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 6 }}>
                                <Mic size={13} style={{ color: 'var(--accent-primary)' }} />
                                <span style={{ fontWeight: 600, fontSize: '0.8rem', color: 'var(--text-primary)' }}>Cast voices</span>
                                <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                                  {voiceLibrary === null ? 'Reading BuzzEdit\'s voices…'
                                    : !voiceLibrary.available ? 'BuzzEdit did not list its voices (not running?).'
                                    : voices.length ? `${voices.length} voice${voices.length === 1 ? '' : 's'} in BuzzEdit's library`
                                    : 'No voices in the library: add or record them in BuzzEdit.'}
                                </span>
                                <button type="button" className="btn btn-outline btn-sm" style={{ ...small, marginLeft: 'auto' }}
                                  disabled={busy || producing || !cast?.characters?.length || !voices.length}
                                  onClick={() => void proposeVoices(proj.id)}
                                  title="Pick every character's voice from their description (woman, child, creature, the dead, man), with the voices BuzzEdit's library has. Replaces the voices below.">
                                  <span>Propose voices</span>
                                </button>
                              </div>
                              {cast === undefined ? (
                                <div style={{ fontSize: '0.74rem', color: 'var(--text-muted)' }}>Reading the cast…</div>
                              ) : !cast?.characters?.length ? (
                                <div style={{ fontSize: '0.74rem', color: 'var(--text-muted)' }}>
                                  No cast sheet yet: a story production writes it from the script.
                                </div>
                              ) : (
                                <div style={{ display: 'grid', gap: 4 }}>
                                  {cast.characters.map((c) => {
                                    const current = valueOf(c.voice);
                                    return (
                                      <div key={c.name} style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                                        <span style={{ fontSize: '0.76rem', fontWeight: 600, minWidth: 110, color: 'var(--text-primary)' }}>
                                          {c.name}
                                        </span>
                                        <span title={c.look || ''}
                                          style={{ fontSize: '0.7rem', color: 'var(--text-muted)', flex: 1, minWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                          {c.look || ''}
                                        </span>
                                        <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}
                                          title={`The voice ${c.name}'s labelled lines (${c.name.toUpperCase()}: or ${c.name.toUpperCase()} (V.O.)) are converted to before the render.`}>
                                          <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Voice</span>
                                          <select className="form-control" value={current}
                                            aria-label={`Voice for ${c.name}`}
                                            disabled={busy || producing || !voiceLibrary?.available}
                                            onChange={(e) => void setCharacterVoice(proj.id, c.name, e.target.value)}
                                            style={{ width: 'auto', padding: '2px 6px', fontSize: '0.72rem', height: 24 }}>
                                            <option value="">{c.voice_set ? 'None (your own voice)' : 'None yet (proposed at production)'}</option>
                                            {current.startsWith('entry:') && (
                                              <option value={current}>
                                                {[c.voice?.preset, c.voice?.voice].filter(Boolean).join(' · ')}
                                              </option>
                                            )}
                                            {voices.length > 0 && (
                                              <optgroup label="Library voices">
                                                {voices.map((v) => (
                                                  <option key={`v-${v.name}`} value={`voice:${v.name}`}>
                                                    {v.name}{v.kind ? ` (${v.kind})` : ''}
                                                  </option>
                                                ))}
                                              </optgroup>
                                            )}
                                            {presets.length > 0 && (
                                              <optgroup label="Presets">
                                                {presets.map(([name, p]) => (
                                                  <option key={`p-${name}`} value={`preset:${name}`} disabled={!p.voice_in_library}>
                                                    {name}{p.voice_in_library ? ` (${p.voice})` : ` (needs a "${p.voice}" voice)`}
                                                  </option>
                                                ))}
                                              </optgroup>
                                            )}
                                          </select>
                                        </label>
                                      </div>
                                    );
                                  })}
                                  <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: 2 }}>
                                    Only lines the script labels with a character's name are converted; your narration stays yours.
                                  </div>
                                </div>
                              )}
                            </div>
                          );
                        })()}

                        {canResume && (
                          <button
                            type="button"
                            className="btn btn-outline btn-sm"
                            onClick={() => resumeProduce(proj)}
                            style={{ marginTop: 6, padding: '3px 10px', fontSize: '0.74rem' }}
                            title="BuzzEdit may still be rendering: re-attach to its job without re-importing or re-transcribing"
                          >
                            <RotateCw size={11} />
                            <span>Resume render</span>
                          </button>
                        )}
                        {qItem && (() => {
                          const busyQ = !!queueBusy[proj.id];
                          const qRunning = qItem.status === 'running';
                          const rendering = qRunning && qItem.checkpoint === 'render';
                          const small = { padding: '3px 10px', fontSize: '0.74rem' };
                          return (
                            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', marginTop: 8 }}>
                              <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Queue:</span>
                              {(qItem.status === 'queued' || (qRunning && !rendering && !qItem.pause_requested)) && (
                                <button type="button" className="btn btn-outline btn-sm" disabled={busyQ} style={small}
                                  onClick={() => queueAction(proj, qItem, 'pause')}
                                  title={qRunning ? 'Pause after the current stage; resume picks up from there.' : 'Hold this video in the queue.'}>
                                  <span>Pause</span>
                                </button>
                              )}
                              {rendering && (
                                <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}
                                  title="BuzzEdit cannot suspend a render; pause the queue to hold the next video.">
                                  rendering in BuzzEdit (cannot pause mid-render)
                                </span>
                              )}
                              {(qItem.status === 'paused' || (qRunning && qItem.pause_requested)) && (
                                <button type="button" className="btn btn-sm" disabled={busyQ} style={small}
                                  onClick={() => queueAction(proj, qItem, 'resume')}>
                                  <span>Resume</span>
                                </button>
                              )}
                              {(qItem.status === 'failed' || qItem.status === 'cancelled') && (
                                <button type="button" className="btn btn-sm" disabled={busyQ} style={small}
                                  onClick={() => queueAction(proj, qItem, 'retry')}
                                  title="Retry from the last safe point, without redoing finished stages.">
                                  <RotateCw size={11} />
                                  <span>Retry</span>
                                </button>
                              )}
                              {['failed', 'cancelled', 'paused'].includes(qItem.status) && qItem.recording_path && (
                                <button type="button" className="btn btn-outline btn-sm" disabled={busyQ} style={small}
                                  onClick={() => queueAction(proj, qItem, 'restart')}
                                  title="Start over: re-import and re-transcribe the recording.">
                                  <span>Restart from scratch</span>
                                </button>
                              )}
                              {['done', 'failed', 'cancelled', 'paused'].includes(qItem.status) && !qItem.precut && (
                                <button type="button" className="btn btn-outline btn-sm" disabled={busyQ} style={small}
                                  onClick={() => queueAction(proj, qItem, 'recut')}
                                  title="Plan the cut again under the current rules from the existing transcription, then re-plan visuals and render.">
                                  <span>Re-cut</span>
                                </button>
                              )}
                              {['queued', 'running', 'paused'].includes(qItem.status) && !qItem.cancel_requested && (
                                <button type="button" className="btn btn-outline btn-sm" disabled={busyQ} style={small}
                                  onClick={() => queueAction(proj, qItem, 'cancel')}>
                                  <X size={11} />
                                  <span>Cancel</span>
                                </button>
                              )}
                              {qRunning && qItem.pause_requested && (
                                <span style={{ fontSize: '0.72rem', color: '#a78bfa' }}>Pausing after the current stage…</span>
                              )}
                              {qRunning && qItem.cancel_requested && (
                                <span style={{ fontSize: '0.72rem', color: '#f87171' }}>Cancelling after the current stage…</span>
                              )}
                            </div>
                          );
                        })()}
                        {status && status.state !== 'idle' && (
                          <div style={{ marginTop: 10 }}>
                            <div className="stages-progress-bar-bg">
                              <div
                                className="stages-progress-bar-fill"
                                style={{
                                  width: `${Math.round((status.progress || 0) * 100)}%`,
                                  background: status.state === 'failed'
                                    ? '#ef4444'
                                    : status.state === 'ready'
                                      ? '#10b981'
                                      : 'linear-gradient(90deg, #10b981, #3b82f6, #a78bfa)',
                                }}
                              />
                            </div>
                            <div style={{ fontSize: '0.76rem', color: status.state === 'failed' ? '#f87171' : 'var(--text-secondary)', marginTop: 6 }}>
                              {status.state === 'failed'
                                ? `Failed: ${status.error || 'unknown error'}`
                                : status.message || status.state}
                            </div>
                            {status.deviation && (
                              <div style={{ fontSize: '0.74rem', color: 'var(--text-muted)', marginTop: 4 }}>
                                Followed {Math.round(status.deviation.script_spoken_share * 100)}% of the script
                                {' · '}{Math.round(status.deviation.adlib_share * 100)}% ad-libbed
                                {' · '}{status.deviation.beats_placed} visuals placed
                                {status.deviation.beats_dropped > 0 && ` · ${status.deviation.beats_dropped} skipped (lines not spoken)`}
                              </div>
                            )}
                            {status.planning && (
                              <div style={{ fontSize: '0.74rem', color: 'var(--text-muted)', marginTop: 4 }}>
                                Visual planning: {status.planning.ok}/{status.planning.windows} window(s) planned
                                {status.planning.failed.length > 0 && ` · ${status.planning.failed.length} failed`}
                              </div>
                            )}
                            {status.warning && (
                              <div style={{ fontSize: '0.76rem', color: '#f59e0b', marginTop: 4 }}>
                                Warning: {status.warning}
                              </div>
                            )}
                            {status.resumed_after_restart && (
                              <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 4 }}>
                                (Studio restarted while this was pending -- picked back up from where it paused.)
                              </div>
                            )}

                            {status.state === 'awaiting_cut_review' && (
                              <div
                                style={{
                                  marginTop: 8, padding: '10px 12px', borderRadius: 6,
                                  border: '1px solid rgba(245, 158, 11, 0.35)', background: 'rgba(245, 158, 11, 0.08)',
                                }}
                              >
                                <div style={{ fontSize: '0.78rem', color: 'var(--text-primary)', marginBottom: 8 }}>
                                  Review the auto-cut in BuzzEdit's Cuts view -- toggling a word there changes what
                                  visuals get planned next, since planning re-reads the kept words after you continue.
                                </div>
                                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                                  <button
                                    type="button"
                                    className="btn btn-outline btn-sm"
                                    disabled={!buzzEditStatus?.url}
                                    onClick={() => buzzEditStatus?.url && window.open(buzzEditStatus.url, '_blank')}
                                    style={{ padding: '3px 10px', fontSize: '0.74rem' }}
                                  >
                                    <ExternalLink size={12} />
                                    <span>Open BuzzEdit to review cuts</span>
                                  </button>
                                  <button
                                    type="button"
                                    className="btn btn-sm"
                                    disabled={!!gateBusy[proj.id]}
                                    onClick={() => continueProduce(proj, 'cut_review')}
                                    style={{ padding: '3px 10px', fontSize: '0.74rem' }}
                                  >
                                    <span>{gateBusy[proj.id] ? 'Continuing…' : 'Continue'}</span>
                                  </button>
                                  <button
                                    type="button"
                                    className="btn btn-outline btn-sm"
                                    disabled={!!gateBusy[proj.id]}
                                    onClick={() => cancelProduce(proj)}
                                    style={{ padding: '3px 10px', fontSize: '0.74rem' }}
                                  >
                                    <span>Cancel</span>
                                  </button>
                                </div>
                              </div>
                            )}

                            {status.state === 'awaiting_effects_review' && (() => {
                              const sample = status.effects_sample;
                              const placed = sample?.result?.text_fx || {};
                              const busy = !!gateBusy[proj.id] || !!status.sample_running;
                              return (
                                <div
                                  style={{
                                    marginTop: 8, padding: '10px 12px', borderRadius: 6,
                                    border: '1px solid rgba(16, 185, 129, 0.35)', background: 'rgba(16, 185, 129, 0.06)',
                                  }}
                                >
                                  <div style={{ fontSize: '0.78rem', color: 'var(--text-primary)', marginBottom: 8 }}>
                                    Effects sample: about 20 seconds of your cut with the captions, text effects, a punch-in,
                                    sound effects and music. Change the style settings above and re-test as often as you like,
                                    then continue to the full render.
                                  </div>
                                  {status.sample_running ? (
                                    <div style={{ fontSize: '0.76rem', color: 'var(--text-muted)', marginBottom: 8 }}>
                                      Rendering the sample{typeof status.sample_progress === 'number'
                                        ? ` (${Math.round(status.sample_progress * 100)}%)` : ''}…
                                    </div>
                                  ) : sample?.url ? (
                                    <video
                                      key={`${sample.url}-${sample.rendered_at || 0}`}
                                      src={`${sample.url}?t=${sample.rendered_at || 0}`}
                                      controls
                                      style={{ width: '100%', maxWidth: 640, borderRadius: 6, background: '#000', display: 'block', marginBottom: 8 }}
                                    />
                                  ) : (
                                    <div style={{ fontSize: '0.76rem', color: 'var(--text-muted)', marginBottom: 8 }}>
                                      No sample to show (is BuzzEdit running?). Re-test to render one.
                                    </div>
                                  )}
                                  {status.sample_error && (
                                    <div style={{ fontSize: '0.76rem', color: '#f87171', marginBottom: 8 }}>{status.sample_error}</div>
                                  )}
                                  {sample?.result && !status.sample_running && (
                                    <div style={{ fontSize: '0.74rem', color: 'var(--text-muted)', marginBottom: 8 }}>
                                      In this sample: {Object.entries(placed).map(([k, v]) => `${v} ${k.replace(/_/g, ' ')}`).join(', ') || 'no text effects'}
                                      {' · '}{sample.result.zooms || 0} punch-in
                                      {' · '}{sample.result.sfx || 0} sound effects
                                      {sample.result.music ? ' · music' : ''}
                                    </div>
                                  )}
                                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                                    <button
                                      type="button"
                                      className="btn btn-outline btn-sm"
                                      disabled={busy}
                                      onClick={() => retestEffects(proj)}
                                      style={{ padding: '3px 10px', fontSize: '0.74rem' }}
                                      title="Render the sample again with the current style settings."
                                    >
                                      <RotateCw size={11} />
                                      <span>{status.sample_running ? 'Rendering…' : 'Re-test effects'}</span>
                                    </button>
                                    <button
                                      type="button"
                                      className="btn btn-sm"
                                      disabled={busy}
                                      onClick={() => continueProduce(proj, 'effects_review')}
                                      style={{ padding: '3px 10px', fontSize: '0.74rem' }}
                                    >
                                      <span>{gateBusy[proj.id] ? 'Continuing…' : 'Looks good: full render'}</span>
                                    </button>
                                    <button
                                      type="button"
                                      className="btn btn-outline btn-sm"
                                      disabled={busy}
                                      onClick={() => cancelProduce(proj)}
                                      style={{ padding: '3px 10px', fontSize: '0.74rem' }}
                                    >
                                      <span>Cancel</span>
                                    </button>
                                  </div>
                                </div>
                              );
                            })()}

                            {status.state === 'awaiting_plan_review' && (
                              <div
                                style={{
                                  marginTop: 8, padding: '10px 12px', borderRadius: 6,
                                  border: '1px solid rgba(99, 102, 241, 0.35)', background: 'rgba(99, 102, 241, 0.06)',
                                }}
                              >
                                <div style={{ fontSize: '0.78rem', color: 'var(--text-primary)', marginBottom: 8 }}>
                                  Visual plan for this take -- edit a prompt, drop a beat, then continue to render.
                                </div>
                                {planLoading[proj.id] ? (
                                  <div style={{ fontSize: '0.76rem', color: 'var(--text-muted)' }}>Loading plan…</div>
                                ) : (
                                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 280, overflowY: 'auto' }}>
                                    {(planDraft[proj.id] || []).map((beat, idx) => {
                                      const mins = typeof beat.start === 'number' ? Math.floor(beat.start / 60) : 0;
                                      const secs = typeof beat.start === 'number' ? Math.floor(beat.start % 60) : 0;
                                      const timeLabel = typeof beat.start === 'number' ? `${mins}:${String(secs).padStart(2, '0')}` : '--:--';
                                      return (
                                        <div
                                          key={idx}
                                          style={{ display: 'flex', gap: 8, alignItems: 'center', opacity: beat.deleted ? 0.45 : 1 }}
                                        >
                                          <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', width: 40, flexShrink: 0 }}>
                                            {timeLabel}
                                          </span>
                                          <span
                                            style={{
                                              fontSize: '0.68rem', color: 'var(--accent-primary)', width: 88, flexShrink: 0,
                                              whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                                            }}
                                            title={beat.kind}
                                          >
                                            {beat.kind}
                                          </span>
                                          <input
                                            type="text"
                                            className="form-control"
                                            value={beat.prompt || ''}
                                            aria-label={`Prompt for the ${beat.kind} beat`}
                                            disabled={!!beat.deleted}
                                            onChange={(e) => updatePlanBeat(proj.id, idx, { prompt: e.target.value })}
                                            style={{ flex: 1, fontSize: '0.76rem', height: 26 }}
                                          />
                                          <button
                                            type="button"
                                            className="btn btn-outline btn-sm"
                                            onClick={() => updatePlanBeat(proj.id, idx, { deleted: !beat.deleted })}
                                            title={beat.deleted ? 'Restore this beat' : 'Drop this beat'}
                                            style={{ padding: '2px 8px', fontSize: '0.7rem', flexShrink: 0 }}
                                          >
                                            <span>{beat.deleted ? 'Restore' : 'Drop'}</span>
                                          </button>
                                        </div>
                                      );
                                    })}
                                    {(planDraft[proj.id] || []).length === 0 && (
                                      <div style={{ fontSize: '0.76rem', color: 'var(--text-muted)' }}>
                                        No new beats were planned for this take.
                                      </div>
                                    )}
                                  </div>
                                )}
                                <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                                  <button
                                    type="button"
                                    className="btn btn-sm"
                                    disabled={!!gateBusy[proj.id] || !!planLoading[proj.id]}
                                    onClick={() => continueProduce(proj, 'plan_review')}
                                    style={{ padding: '3px 10px', fontSize: '0.74rem' }}
                                  >
                                    <span>{gateBusy[proj.id] ? 'Continuing…' : 'Continue to render'}</span>
                                  </button>
                                  <button
                                    type="button"
                                    className="btn btn-outline btn-sm"
                                    disabled={!!gateBusy[proj.id]}
                                    onClick={() => cancelProduce(proj)}
                                    style={{ padding: '3px 10px', fontSize: '0.74rem' }}
                                  >
                                    <span>Cancel</span>
                                  </button>
                                </div>
                              </div>
                            )}

                            {(() => {
                              // The live run's file, else the one the last run saved on the
                              // project -- so the final video stays listed after a restart.
                              const live = status.state === 'ready' ? (status.final_output_path || status.output_path) : null;
                              const finalPath = String(live || proj.metadata?.final_output_path || '');
                              if (!finalPath || status.state === 'running') return null;
                              return (
                                <div style={{ fontSize: '0.76rem', color: 'var(--text-primary)', marginTop: 6, wordBreak: 'break-all' }}>
                                  <div>
                                    Final video: <strong>{finalPath.split(/[\\/]/).pop()}</strong>{' '}
                                    <code style={{ color: 'var(--text-muted)' }}>{finalPath}</code>
                                    <CopyButton text={finalPath} label="Copy path" />
                                    <button
                                      type="button"
                                      className="btn btn-sm"
                                      style={{ marginLeft: 8 }}
                                      onClick={() => postJson(`/api/projects/${proj.id}/produce_video/reveal`, {})
                                        .then(() => toast('Opened the folder with the final video.'))
                                        .catch((err) => toast(describeError(err), 'error'))}
                                    >
                                      Open in Explorer
                                    </button>
                                  </div>
                                  {live && status.final_output_path && status.output_path && status.final_output_path !== status.output_path && (
                                    <div style={{ color: 'var(--text-muted)', marginTop: 2 }}>
                                      BuzzEdit's render: <code>{status.output_path}</code>
                                    </div>
                                  )}
                                </div>
                              );
                            })()}
                            {(() => {
                              // Which music the edit used, from BuzzEdit's report.
                              const report = (status.report || proj.metadata?.buzzedit_report) as
                                { music_used?: string; music_source_used?: string } | null | undefined;
                              if (!report || status.state !== 'ready') return null;
                              const used = String(report.music_used || '');
                              const source = String(report.music_source_used || '');
                              const label: Record<string, string> = {
                                cue: 'generated for this video', library: 'from the music library',
                                generated: 'generated loop', synth: 'synthesised bed', off: 'none',
                              };
                              return (
                                <div style={{ fontSize: '0.76rem', color: 'var(--text-secondary)', marginTop: 4, wordBreak: 'break-all' }}>
                                  Music used: {used ? <><code>{used}</code> ({label[source] || source || 'library'})</> : 'none'}
                                </div>
                              );
                            })()}
                            {(() => {
                              // The audio rack preset the production put on the voice (A1) before its render.
                              const rack = ((status as ProduceVideoStatus & { audio_rack_used?: unknown }).audio_rack_used
                                ?? proj.metadata?.audio_rack_used) as
                                { audio_rack_preset?: string; effects?: string[] } | null | undefined;
                              if (!rack?.audio_rack_preset || status.state !== 'ready') return null;
                              const effects = Array.isArray(rack.effects) ? rack.effects : [];
                              return (
                                <div style={{ fontSize: '0.76rem', color: 'var(--text-secondary)', marginTop: 4, wordBreak: 'break-all' }}>
                                  Audio rack used: <code>{rack.audio_rack_preset}</code>
                                  {effects.length ? ` (${effects.join(', ')})` : ''}
                                </div>
                              );
                            })()}
                            {(() => {
                              // The character lines BuzzEdit converted to their cast voices before the render.
                              const extra = status as ProduceVideoStatus & { voice_conversions?: unknown; voice_report?: unknown };
                              const conversions = (extra.voice_conversions ?? proj.metadata?.voice_conversions) as
                                VoiceConversion[] | null | undefined;
                              const report = (extra.voice_report ?? proj.metadata?.voice_report) as VoiceReport | null | undefined;
                              const list = Array.isArray(conversions) ? conversions : [];
                              if (status.state !== 'ready' || (!list.length && !report)) return null;
                              const warnings = Array.isArray(report?.warnings) ? report.warnings : [];
                              const failed = Array.isArray(report?.failed_spans) ? report.failed_spans.length : 0;
                              return (
                                <div style={{ fontSize: '0.76rem', color: 'var(--text-secondary)', marginTop: 4, wordBreak: 'break-word' }}>
                                  Voices: {list.length ? list.map((c, i) => {
                                    const lines = Array.isArray(c.spans) ? c.spans.length : 0;
                                    return (
                                      <span key={`${c.speaker}-${c.voice}-${i}`}>
                                        {i ? ', ' : ''}<code>{c.speaker}</code> → <code>{c.voice}</code>
                                        {` (${lines} line${lines === 1 ? '' : 's'}, ${Number(c.seconds || 0).toFixed(1)} s)`}
                                      </span>
                                    );
                                  }) : (report?.note || 'none converted')}
                                  {failed > 0 && (
                                    <span>{` · ${failed} line${failed === 1 ? '' : 's'} kept the original voice`}</span>
                                  )}
                                  {warnings.map((w, i) => (
                                    <div key={i} style={{ color: 'var(--text-muted)', fontSize: '0.72rem' }}>{w}</div>
                                  ))}
                                </div>
                              );
                            })()}
                          </div>
                        )}
                        {!!proj.metadata?.output_path && (!status || status.state === 'idle' || status.state === 'ready') && (
                          <YouTubePublish key={String(proj.metadata.output_path)} projectId={proj.id} onToast={toast} />
                        )}
                      </div>
                    );
                  })()}
                  </>)}
                </div>
              );
            })}
          </div>
        </div>

        {/* Right Side Drawer for Selected Project */}
        {open && (
          <div className="panel-card project-detail-drawer" style={{ marginTop: drawerTop }}>
            {/* Drawer Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
              <div style={{ minWidth: 0, flex: 1 }}>
                <h3 className="panel-title" style={{ margin: 0, border: 'none', padding: 0, fontSize: '1.15rem' }}>
                  {open.name}
                </h3>
                <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: 4, display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span>{open.brand}</span>
                  <span>·</span>
                  <code>{open.workflow_name}</code>
                </div>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <button
                  type="button"
                  className="btn btn-outline btn-sm"
                  onClick={(e) => handleArchiveProject(open, open.status !== 'archived', e)}
                  disabled={archivingId === open.id || runningId === open.id}
                  title={open.status === 'archived' ? 'Bring this project back' : 'Archive this project (keeps its files)'}
                  style={{ padding: '4px 8px', fontSize: '0.75rem', background: 'transparent', color: 'var(--text-secondary)', display: 'inline-flex', alignItems: 'center', gap: 4 }}
                >
                  {open.status === 'archived' ? <ArchiveRestore size={13} /> : <Archive size={13} />}
                  <span>{open.status === 'archived' ? 'Bring back' : 'Archive'}</span>
                </button>
                <button
                  type="button"
                  className="btn btn-outline btn-sm"
                  onClick={(e) => handleDeleteProject(open, e)}
                  disabled={deletingId === open.id || runningId === open.id}
                  title={`Delete project "${open.name}"`}
                  style={{
                    padding: '4px 8px',
                    fontSize: '0.75rem',
                    borderColor: 'rgba(239, 68, 68, 0.4)',
                    color: '#f87171',
                    background: 'transparent',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 4,
                  }}
                >
                  <Trash2 size={13} />
                  <span>{deletingId === open.id ? 'Deleting…' : 'Delete'}</span>
                </button>
                <button
                  type="button"
                  onClick={() => setOpenId(null)}
                  aria-label="Close panel"
                  style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', display: 'flex', padding: 4 }}
                >
                  <X size={18} />
                </button>
              </div>
            </div>

            {/* Allow All mode card in side panel */}
            <div
              style={{
                marginTop: 14,
                marginBottom: 16,
                padding: '10px 14px',
                borderRadius: 8,
                backgroundColor: Boolean(open.metadata?.allow_all) ? 'rgba(16, 185, 129, 0.1)' : 'var(--bg-pill)',
                border: `1px solid ${Boolean(open.metadata?.allow_all) ? 'rgba(16, 185, 129, 0.3)' : 'var(--border-card)'}`,
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                gap: 12,
              }}
            >
              <div>
                <div style={{ fontSize: '0.85rem', fontWeight: 600, color: Boolean(open.metadata?.allow_all) ? '#34d399' : 'var(--text-primary)' }}>
                  Allow All Mode: {Boolean(open.metadata?.allow_all) ? 'Enabled' : 'Disabled'}
                </div>
                <div style={{ fontSize: '0.74rem', color: 'var(--text-secondary)' }}>
                  {Boolean(open.metadata?.allow_all)
                    ? 'Steps advance automatically without pausing for approval.'
                    : 'Steps will pause at approval gates.'}
                </div>
              </div>
              <button
                type="button"
                className={`btn btn-sm ${Boolean(open.metadata?.allow_all) ? 'btn-outline' : ''}`}
                onClick={() => toggleAllowAll(open)}
                style={{
                  fontSize: '0.76rem',
                  padding: '4px 10px',
                  borderColor: Boolean(open.metadata?.allow_all) ? '#10b981' : 'var(--border-card)',
                  color: Boolean(open.metadata?.allow_all) ? '#34d399' : 'var(--text-on-accent)',
                  background: Boolean(open.metadata?.allow_all) ? 'transparent' : 'var(--accent-gradient)',
                }}
              >
                {Boolean(open.metadata?.allow_all) ? 'Turn Off' : 'Enable Allow All'}
              </button>
            </div>

            {/* Drawer Sub-tabs: Steps Timeline vs Assets */}
            <div style={{ display: 'flex', gap: 6, borderBottom: '1px solid var(--border-card)', paddingBottom: 8, marginBottom: 16 }}>
              <button
                type="button"
                className={`btn btn-sm ${sideTab === 'steps' ? '' : 'btn-outline'}`}
                onClick={() => setSideTab('steps')}
                style={{
                  padding: '5px 12px',
                  fontSize: '0.78rem',
                  background: sideTab === 'steps' ? 'var(--accent-gradient)' : 'transparent',
                  borderColor: sideTab === 'steps' ? 'transparent' : 'var(--border-card)',
                  color: sideTab === 'steps' ? 'var(--text-on-accent)' : 'var(--text-secondary)',
                }}
              >
                <span>Timeline ({openWorkflow?.steps?.length || 0} Stages)</span>
              </button>
              <button
                type="button"
                className={`btn btn-sm ${sideTab === 'assets' ? '' : 'btn-outline'}`}
                onClick={() => setSideTab('assets')}
                style={{
                  padding: '5px 12px',
                  fontSize: '0.78rem',
                  background: sideTab === 'assets' ? 'var(--accent-gradient)' : 'transparent',
                  borderColor: sideTab === 'assets' ? 'transparent' : 'var(--border-card)',
                  color: sideTab === 'assets' ? 'var(--text-on-accent)' : 'var(--text-secondary)',
                }}
              >
                <span>Produced Assets ({Object.keys(open.assets || {}).length})</span>
              </button>
            </div>

            {/* Tab: Steps Timeline */}
            {sideTab === 'steps' && (
              <div>
                {openWorkflow?.steps?.length ? (
                  <div className="timeline-container" style={{ marginTop: 0 }}>
                    {openWorkflow.steps.map((s, i) => {
                      const state = stepState(open, s);
                      const isAutoApproved = Boolean(open.metadata?.allow_all) && s.requires_approval;
                      return (
                        <div
                          key={s.name}
                          className="timeline-step"
                          style={{
                            padding: '10px 14px',
                            gap: 12,
                            borderColor: state === 'pending' ? 'var(--border-card)' : STATE_COLOR[state],
                          }}
                        >
                          <div className="step-num" style={{ color: STATE_COLOR[state] }}>{i + 1}</div>
                          <div style={{ minWidth: 0, flex: 1 }}>
                            <div style={{ color: 'var(--text-primary)', fontSize: '0.88rem', fontWeight: 600 }}>{s.name}</div>
                            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                              {s.agent_role}
                              {s.requires_approval && (
                                <span style={{ color: isAutoApproved ? '#34d399' : 'var(--accent-primary)' }}>
                                  {isAutoApproved ? ' · auto-approved' : ' · needs approval'}
                                </span>
                              )}
                            </div>
                            {s.description && (
                              <div style={{ fontSize: '0.73rem', color: 'var(--text-muted)', marginTop: 4 }}>
                                {s.description}
                              </div>
                            )}
                          </div>
                          <span style={{ fontSize: '0.72rem', color: STATE_COLOR[state], textTransform: 'uppercase', fontWeight: 700 }}>
                            {state}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', margin: 0 }}>
                    No definition loaded for <code>{open.workflow_name}</code>.
                  </p>
                )}
              </div>
            )}

            {/* Tab: Produced Assets */}
            {sideTab === 'assets' && (
              <div>
                {Object.keys(open.assets || {}).length === 0 ? (
                  <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', margin: 0 }}>
                    No assets produced yet. Run workflow stages to generate script, research, and production notes.
                  </p>
                ) : (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                    {Object.entries(open.assets || {}).map(([name, file]) => (
                      <button
                        key={name}
                        type="button"
                        onClick={() => showAsset(open, name)}
                        title={file}
                        style={{
                          backgroundColor: assetName === name ? 'var(--bg-card-hover)' : 'var(--bg-pill)',
                          border: `1px solid ${assetName === name ? 'var(--border-highlight)' : 'var(--border-card)'}`,
                          color: 'var(--text-primary)',
                          padding: '6px 12px',
                          borderRadius: 8,
                          fontSize: '0.8rem',
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          gap: 6,
                        }}
                      >
                        <FileText size={13} />
                        <span>{name}</span>
                      </button>
                    ))}
                  </div>
                )}

                {assetName && (
                  <div style={{ marginTop: 16, borderTop: '1px solid var(--border-card)', paddingTop: 16 }}>
                    <div
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        marginBottom: 12,
                        flexWrap: 'wrap',
                        gap: 10,
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0, flex: '1 1 200px' }}>
                        <FileText size={16} style={{ color: 'var(--accent-primary)', flexShrink: 0 }} />
                        <div style={{ minWidth: 0 }}>
                          <div style={{ fontWeight: 600, fontSize: '0.9rem', color: 'var(--text-primary)', textTransform: 'capitalize' }}>
                            {assetName.replace(/_/g, ' ')}
                          </div>
                          <div style={{ fontSize: '0.74rem', color: 'var(--text-muted)', wordBreak: 'break-all' }}>
                            {open.assets?.[assetName] || assetName}
                          </div>
                        </div>
                      </div>

                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                        <button
                          type="button"
                          className="btn btn-outline btn-sm"
                          onClick={() =>
                            printArtifact(
                              assetName.replace(/_/g, ' '),
                              open.assets?.[assetName] || `${assetName}.md`,
                              assetBody,
                              open,
                            )
                          }
                          disabled={assetBusy || !assetBody}
                          title="Print artifact (Press Ctrl+Shift+P in print dialog to select your physical printer)"
                          style={{
                            padding: '4px 11px',
                            fontSize: '0.78rem',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: 5,
                            borderRadius: 6,
                          }}
                        >
                          <Printer size={13} />
                          <span>Print</span>
                        </button>
                        <button
                          type="button"
                          className="btn btn-outline btn-sm"
                          onClick={() => openBrowserPrint(open.id, assetName)}
                          disabled={assetBusy || !assetBody}
                          title="Open in your default system browser (Chrome/Edge) to detect all network/local printers"
                          style={{
                            padding: '4px 11px',
                            fontSize: '0.78rem',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: 5,
                            borderRadius: 6,
                          }}
                        >
                          <ExternalLink size={13} />
                          <span>Browser Print</span>
                        </button>
                        <button
                          type="button"
                          className="btn btn-outline btn-sm"
                          onClick={() =>
                            saveArtifact(
                              open.assets?.[assetName] || `${assetName}.md`,
                              rawAssetBody || assetBody,
                              open,
                            )
                          }
                          disabled={assetBusy || !assetBody}
                          title="Save artifact file to disk"
                          style={{
                            padding: '4px 11px',
                            fontSize: '0.78rem',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: 5,
                            borderRadius: 6,
                          }}
                        >
                          <Download size={13} />
                          <span>Save</span>
                        </button>
                        <CopyButton text={rawAssetBody || assetBody} label="Copy artifact content" />
                      </div>
                    </div>

                    {assetBusy ? (
                      <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: 8 }}>
                        <Clock size={14} className="spin" /> Loading…
                      </div>
                    ) : assetBody ? (
                      <>
                        {seoPlain && <SeoPlainText seo={seoPlain} />}
                        <Markdown text={assetBody} />
                      </>
                    ) : (
                      <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: 8 }}>
                        <Circle size={12} /> Nothing to show.
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Teleprompter: full-screen auto-scrolling view of the written script
          (to record from) or the as-recorded annotated one, with a
          dialogue-only mode and a full mode that highlights spoken lines. */}
      {teleprompterId && (
        <Teleprompter
          title={allProjects.find((p) => p.id === teleprompterId)?.name || teleprompterId}
          text={teleprompterText}
          busy={teleprompterBusy}
          onClose={() => { setTeleprompterId(null); setTeleprompterText(''); setScriptEditing(false); }}
          actions={(
            <>
              {(() => {
                const proj = allProjects.find((p) => p.id === teleprompterId);
                const sources = proj ? teleprompterSourcesFor(proj) : [];
                return sources.length > 1 && proj ? (
                  <select
                    value={teleprompterSource}
                    onChange={(e) => openTeleprompter(proj, e.target.value)}
                    title="Which script to read"
                    aria-label="Which script to read"
                    style={{ background: 'transparent', color: '#e5e7eb', border: '1px solid rgba(255,255,255,0.3)', borderRadius: 6, padding: '4px 8px', fontSize: '0.8rem' }}
                  >
                    {sources.map(([k, label]) => <option key={k} value={k} style={{ color: '#111' }}>{label}</option>)}
                  </select>
                ) : null;
              })()}
              {teleprompterText && (<>
              <button
                type="button"
                className="btn btn-outline btn-sm"
                onClick={async () => {
                  try {
                    await navigator.clipboard.writeText(teleprompterText);
                    toast('Script copied. Fix it anywhere, then use Edit to paste it back.', 'success');
                  } catch {
                    toast('Could not reach the clipboard; use Edit -> Copy all.', 'error');
                  }
                }}
                style={{ color: '#e5e7eb', borderColor: 'rgba(255,255,255,0.3)', padding: '5px 12px', fontSize: '0.8rem', display: 'inline-flex', alignItems: 'center', gap: 6 }}
                title="Copy the whole script to the clipboard"
              >
                <Copy size={14} />
                <span>Copy</span>
              </button>
              <button
                type="button"
                className="btn btn-outline btn-sm"
                onClick={() => setScriptEditing(true)}
                style={{ color: '#e5e7eb', borderColor: 'rgba(255,255,255,0.3)', padding: '5px 12px', fontSize: '0.8rem', display: 'inline-flex', alignItems: 'center', gap: 6 }}
                title="Rectify the script here, or paste / load your corrected version, and save it back for the teleprompter"
              >
                <PenLine size={14} />
                <span>Edit</span>
              </button>
              <button
                type="button"
                className="btn btn-outline btn-sm"
                onClick={() => {
                  const proj = allProjects.find((p) => p.id === teleprompterId);
                  printArtifact('Script (Teleprompter)', `${teleprompterSource}.txt`, teleprompterText, proj);
                }}
                style={{ color: '#e5e7eb', borderColor: 'rgba(255,255,255,0.3)', padding: '5px 12px', fontSize: '0.8rem', display: 'inline-flex', alignItems: 'center', gap: 6 }}
                title="Print script to printer (Press Ctrl+Shift+P for Windows system printers)"
              >
                <Printer size={14} />
                <span>Print</span>
              </button>
              <button
                type="button"
                className="btn btn-outline btn-sm"
                onClick={() => openBrowserPrint(teleprompterId, teleprompterSource)}
                style={{ color: '#e5e7eb', borderColor: 'rgba(255,255,255,0.3)', padding: '5px 12px', fontSize: '0.8rem', display: 'inline-flex', alignItems: 'center', gap: 6 }}
                title="Open in default system browser to detect all printers"
              >
                <ExternalLink size={14} />
                <span>Browser Print</span>
              </button>
              <button
                type="button"
                className="btn btn-outline btn-sm"
                onClick={() => {
                  const proj = allProjects.find((p) => p.id === teleprompterId);
                  saveArtifact(`${teleprompterSource}.txt`, teleprompterText, proj);
                }}
                style={{ color: '#e5e7eb', borderColor: 'rgba(255,255,255,0.3)', padding: '5px 12px', fontSize: '0.8rem', display: 'inline-flex', alignItems: 'center', gap: 6 }}
                title="Save script to file"
              >
                <Download size={14} />
                <span>Save</span>
              </button>
              </>)}
            </>
          )}
        />
      )}

      {teleprompterId && scriptEditing && (
        <ScriptEditor
          title={`${allProjects.find((p) => p.id === teleprompterId)?.name || teleprompterId} · ${TELEPROMPTER_SOURCES.find(([k]) => k === teleprompterSource)?.[1] ?? teleprompterSource}`}
          text={teleprompterText}
          onToast={toast}
          onClose={() => setScriptEditing(false)}
          onSave={async (next) => {
            try {
              await putJson(
                `/api/projects/${encodeURIComponent(teleprompterId)}/asset/${encodeURIComponent(teleprompterSource)}`,
                { content: next },
              );
              setTeleprompterText(next.replace(/\r\n/g, '\n'));
              toast('Script saved back. The teleprompter is reading your version; the old one is kept in history/.', 'success');
            } catch (err) {
              toast(`Could not save the script: ${describeError(err)}`, 'error');
              throw err;
            }
          }}
        />
      )}

      {/* Hidden printable area for artifacts mounted directly on document.body */}
      {printable &&
        createPortal(
          <div id="buzzcaf-printable-artifact" aria-hidden="true">
            <style>
              {`
                @page {
                  margin: 0;
                  size: auto;
                }
              `}
            </style>
            <table className="buzzcaf-print-table">
              <thead>
                <tr>
                  <td className="buzzcaf-print-top-spacer">
                    <div style={{ height: '0.5in', minHeight: '0.5in', maxHeight: '0.5in', lineHeight: '0.5in', fontSize: 1 }}>&nbsp;</div>
                  </td>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td className="buzzcaf-print-content-cell">
                    <div className="printable-artifact-header">
                      <h1>{printable.title}</h1>
                      <div className="printable-artifact-meta">
                        <span><strong>Project:</strong> {printable.projectName}</span>
                        <span><strong>Channel:</strong> {printable.brand}</span>
                        <span><strong>File:</strong> {printable.filename}</span>
                        <span><strong>Printed:</strong> {printable.date}</span>
                      </div>
                    </div>
                    <div className="printable-artifact-content">
                      <Markdown text={printable.content} />
                    </div>
                    <div className="printable-artifact-footer">
                      <span>Buzzcaf Media Studio — Generated Artifact</span>
                      <span>{printable.projectName}</span>
                    </div>
                  </td>
                </tr>
              </tbody>
              <tfoot>
                <tr>
                  <td className="buzzcaf-print-bottom-spacer">
                    <div style={{ height: '0.5in', minHeight: '0.5in', maxHeight: '0.5in', lineHeight: '0.5in', fontSize: 1 }}>&nbsp;</div>
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>,
          document.body,
        )}
    </div>
  );
}
