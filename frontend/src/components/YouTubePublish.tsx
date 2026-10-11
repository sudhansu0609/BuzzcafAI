import { useCallback, useEffect, useRef, useState } from 'react';
import { describeError, getJson, postJson } from '../services/api';
import type { YtStatus } from './YouTubeChannels';

/** Publish a rendered video to YouTube. Title options, description and tags
 *  come from the SEO manager's package (publish/publish.json) and can be
 *  edited first (backend app/api/youtube_api.py). */

type Draft = {
  seo_found: boolean;
  titles: string[];
  description: string;
  tags: string[];
  video_path: string;
  video_exists: boolean;
  thumbnail_path: string;
  channel_id: string;
  category_id: string;
};
type Job = { state: 'uploading' | 'done' | 'failed'; progress?: number; message?: string; error?: string | null };
type Result = {
  video_id: string; url: string; privacy: string; channel_title?: string; title?: string;
  thumbnail_set?: boolean; thumbnail_error?: string; uploaded_at?: string; publish_at?: string | null;
};
type ProjectYt = { draft: Draft; job: Job | null; result: Result | null };

type Props = { projectId: string; onToast?: (message: string, kind: 'success' | 'error' | 'info') => void };

export default function YouTubePublish({ projectId, onToast }: Props) {
  const [data, setData] = useState<ProjectYt | null>(null);
  const [yt, setYt] = useState<YtStatus | null>(null);
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [tags, setTags] = useState('');
  const [channel, setChannel] = useState('');
  const [privacy, setPrivacy] = useState<'private' | 'unlisted' | 'public' | 'schedule'>('unlisted');
  const [when, setWhen] = useState('');
  const [category, setCategory] = useState('24');
  const [synthetic, setSynthetic] = useState(true);
  const [thumb, setThumb] = useState(true);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState('');
  const [studio, setStudio] = useState<{ upload_url: string; channel_id: string } | null>(null);
  const [link, setLink] = useState('');
  const poll = useRef<number | null>(null);

  const load = useCallback(async (fillForm: boolean) => {
    try {
      const [d, s] = await Promise.all([
        getJson<ProjectYt>(`/api/projects/${projectId}/youtube`),
        getJson<YtStatus>('/api/youtube/status'),
      ]);
      setData(d);
      setYt(s);
      if (fillForm) {
        getJson<{ upload_url: string; channel_id: string }>(`/api/projects/${projectId}/youtube/studio`)
          .then(setStudio).catch(() => undefined);
      }
      if (fillForm) {
        setTitle(d.draft.titles[0] || '');
        setDescription(d.draft.description);
        setTags(d.draft.tags.join(', '));
        setChannel(d.draft.channel_id || s.channels.find((c) => c.signed_in)?.id || '');
        setCategory(d.draft.category_id);
      }
      return d;
    } catch (err) {
      setError(describeError(err));
      return null;
    }
  }, [projectId]);

  useEffect(() => {
    load(true);
    return () => { if (poll.current) window.clearInterval(poll.current); };
  }, [load]);

  const watch = () => {
    if (poll.current) window.clearInterval(poll.current);
    poll.current = window.setInterval(async () => {
      const d = await load(false);
      if (d && d.job?.state !== 'uploading' && poll.current) {
        window.clearInterval(poll.current);
        poll.current = null;
        if (d.job?.state === 'done') onToast?.('Uploaded to YouTube.', 'success');
        if (d.job?.state === 'failed') onToast?.(d.job.error || 'YouTube upload failed.', 'error');
      }
    }, 2000);
  };

  useEffect(() => { if (data?.job?.state === 'uploading' && !poll.current) watch(); });  // eslint-disable-line react-hooks/exhaustive-deps

  const publish = async () => {
    setError('');
    let publishAt: string | null = null;
    if (privacy === 'schedule') {
      const t = new Date(when);
      if (!when || isNaN(t.getTime()) || t.getTime() < Date.now() + 15 * 60_000) {
        setError('Pick a time at least 15 minutes from now.');
        return;
      }
      publishAt = t.toISOString();
    }
    try {
      await postJson(`/api/projects/${projectId}/youtube/publish`, {
        channel_id: channel,
        title,
        description,
        tags: tags.split(',').map((t) => t.trim()).filter(Boolean),
        privacy: privacy === 'schedule' ? 'private' : privacy,
        publish_at: publishAt,
        category_id: category,
        synthetic_media: synthetic,
        thumbnail: thumb,
      });
      await load(false);
      watch();
    } catch (err) {
      setError(describeError(err));
    }
  };

  const copy = async (what: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(what);
      window.setTimeout(() => setCopied((c) => (c === what ? '' : c)), 2000);
    } catch {
      setError('Could not copy to the clipboard; select the text and press Ctrl+C.');
    }
  };

  const openStudio = async () => {
    setError('');
    try {
      setStudio(await postJson<{ upload_url: string; channel_id: string }>(`/api/projects/${projectId}/youtube/studio`));
    } catch (err) {
      setError(describeError(err));
    }
  };

  const reveal = async (what: 'video' | 'thumbnail') => {
    try {
      await postJson(`/api/projects/${projectId}/youtube/reveal`, { what });
    } catch (err) {
      setError(describeError(err));
    }
  };

  const saveLink = async () => {
    setError('');
    try {
      await postJson(`/api/projects/${projectId}/youtube/manual`, { url: link, title });
      setLink('');
      setOpen(false);
      await load(false);
      onToast?.('Saved the YouTube link.', 'success');
    } catch (err) {
      setError(describeError(err));
    }
  };

  if (!data || !data.draft.video_exists) return null;
  const { draft, job, result } = data;
  const uploading = job?.state === 'uploading';
  const signedIn = (yt?.channels || []).filter((c) => c.signed_in);
  const small = { fontSize: '0.78rem', color: 'var(--text-secondary)' } as const;
  const titleBytes = title.length;
  const field = { width: '100%', boxSizing: 'border-box', padding: '9px 12px', fontSize: '0.85rem' } as const;
  const tagText = tags.split(',').map((t) => t.trim()).filter(Boolean).join(', ');
  const CopyBtn = ({ what, text }: { what: string; text: string }) => (
    <button type="button" className="btn btn-outline btn-sm" style={{ padding: '1px 8px', fontSize: '0.7rem', marginLeft: 6 }}
      disabled={!text} onClick={() => copy(what, text)}>
      {copied === what ? 'Copied' : 'Copy'}
    </button>
  );

  return (
    <div style={{ marginTop: 10, padding: 10, border: '1px solid var(--border-color, #333)', borderRadius: 8 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <b style={{ fontSize: '0.86rem' }}>YouTube</b>
        {result && (
          <span style={small}>
            Uploaded{result.channel_title ? ` to ${result.channel_title}` : ''} as <b>{result.privacy}</b>
            {result.publish_at ? `, goes public ${new Date(result.publish_at).toLocaleString()}` : ''}:{' '}
            <a href={result.url} target="_blank" rel="noreferrer">{result.url}</a>
            {result.thumbnail_error ? ` (thumbnail not set: ${result.thumbnail_error})` : ''}
          </span>
        )}
        {uploading && <span style={small}>{job?.message} {Math.round((job?.progress || 0) * 100)}%</span>}
        {!uploading && (
          <button type="button" className="btn btn-sm" style={{ padding: '3px 10px', fontSize: '0.74rem' }}
            onClick={() => setOpen(!open)}>
            {open ? 'Close' : result ? 'Upload again…' : 'Publish to YouTube…'}
          </button>
        )}
      </div>
      {job?.state === 'failed' && !open && <p style={{ ...small, color: '#f87171' }}>{job.error}</p>}

      {open && !uploading && (
        <div style={{ display: 'grid', gap: 8, marginTop: 10, fontSize: '0.82rem' }}>
          {!draft.seo_found && (
            <p style={{ ...small, color: '#f59e0b', margin: 0 }}>
              No SEO package found for this project; fill in the title, description and tags yourself.
            </p>
          )}
          <div className="form-group" style={{ minWidth: 0 }}>
            <label>Title <span style={small}>({titleBytes}/100)</span><CopyBtn what="title" text={title} /></label>
            <input className="form-control" style={field} value={title} maxLength={100} onChange={(e) => setTitle(e.target.value)} />
          </div>
          {draft.titles.length > 1 && (
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              <span style={small}>SEO manager's options:</span>
              {draft.titles.map((t) => (
                <button key={t} type="button" className="btn btn-outline btn-sm"
                  style={{ padding: '2px 8px', fontSize: '0.72rem', opacity: t === title ? 1 : 0.75 }}
                  onClick={() => setTitle(t)}>{t}</button>
              ))}
            </div>
          )}
          <div className="form-group" style={{ minWidth: 0 }}>
            <label>Description<CopyBtn what="description" text={description} /></label>
            <textarea className="form-control" style={{ ...field, resize: 'vertical' }} rows={8} value={description} onChange={(e) => setDescription(e.target.value)} />
          </div>
          <div className="form-group" style={{ minWidth: 0 }}>
            <label>Tags <span style={small}>(comma separated; YouTube keeps 500 characters)</span><CopyBtn what="tags" text={tagText} /></label>
            <textarea className="form-control" style={{ ...field, resize: 'vertical' }} rows={3} value={tags} onChange={(e) => setTags(e.target.value)} />
          </div>
          {error && <p style={{ ...small, color: '#f87171', margin: 0 }}>{error}</p>}

          <div style={{ borderTop: '1px solid var(--border-color, #333)', paddingTop: 8 }}>
            <b>Upload in YouTube Studio</b>{' '}
            <span style={small}>(works now; you can make it public)</span>
            <ol style={{ ...small, margin: '6px 0', paddingLeft: 18, lineHeight: 1.6 }}>
              <li>
                <button type="button" className="btn btn-sm" style={{ padding: '2px 10px', fontSize: '0.74rem' }} onClick={openStudio}>
                  Open YouTube Studio upload
                </button>{' '}
                opens your browser on {studio?.channel_id ? "this brand's channel" : "YouTube's upload page (check you are on the right channel)"} and
                shows the video in Explorer. Drag the video into the upload box.
                {' '}<button type="button" className="btn btn-outline btn-sm" style={{ padding: '1px 8px', fontSize: '0.7rem' }}
                  onClick={() => reveal('video')}>Show video</button>
              </li>
              <li>Paste the title, description and tags with the Copy buttons above (tags are under "Show more").</li>
              {draft.thumbnail_path && (
                <li>
                  Thumbnail: "Upload file" and pick BuzzEdit's{' '}
                  <button type="button" className="btn btn-outline btn-sm" style={{ padding: '1px 8px', fontSize: '0.7rem' }}
                    onClick={() => reveal('thumbnail')}>Show thumbnail</button>
                </li>
              )}
              <li>Audience: "No, it's not made for kids". Altered content: "Yes" if the pictures or clips are realistic AI.</li>
              <li>Visibility: <b>Unlisted</b>.</li>
              <li>
                Once it is up, paste its link here:{' '}
                <input className="form-control" style={{ display: 'inline-block', width: 260, maxWidth: '100%', boxSizing: 'border-box', padding: '4px 8px', fontSize: '0.78rem' }}
                  placeholder="https://youtu.be/..." value={link} onChange={(e) => setLink(e.target.value)} />{' '}
                <button type="button" className="btn btn-outline btn-sm" style={{ padding: '2px 10px', fontSize: '0.72rem' }}
                  disabled={!link.trim()} onClick={saveLink}>Save link</button>
              </li>
            </ol>
          </div>

          <div style={{ borderTop: '1px solid var(--border-color, #333)', paddingTop: 8 }}>
            <b>Upload directly (API)</b>{' '}
            <span style={small}>
              One click, but until your Google project passes YouTube's API audit, YouTube locks these uploads to Private.
            </span>
            <div style={{ display: 'grid', gap: 8, marginTop: 6 }}>
              {signedIn.length === 0 && (
                <p style={{ ...small, color: '#f87171', margin: 0 }}>
                  No YouTube channel is connected. Connect one under the Bulk Editor tab (YouTube channels).
                </p>
              )}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12 }}>
                <div className="form-group" style={{ minWidth: 0 }}>
                  <label>Channel</label>
                  <select className="form-control" style={field} value={channel} onChange={(e) => setChannel(e.target.value)}>
                    <option value="">— pick a channel —</option>
                    {signedIn.map((c) => <option key={c.id} value={c.id}>{c.title}{c.brand ? ` (${c.brand})` : ''}</option>)}
                  </select>
                </div>
                <div className="form-group" style={{ minWidth: 0 }}>
                  <label>Visibility</label>
                  <select className="form-control" style={field} value={privacy} onChange={(e) => setPrivacy(e.target.value as typeof privacy)}>
                    <option value="unlisted">Unlisted</option>
                    <option value="private">Private</option>
                    <option value="public">Public</option>
                    <option value="schedule">Scheduled</option>
                  </select>
                </div>
                {privacy === 'schedule' && (
                  <div className="form-group" style={{ minWidth: 0 }}>
                    <label>Goes public at</label>
                    <input type="datetime-local" className="form-control" style={field} value={when} onChange={(e) => setWhen(e.target.value)} />
                  </div>
                )}
                <div className="form-group" style={{ minWidth: 0 }}>
                  <label>Category</label>
                  <select className="form-control" style={field} value={category} onChange={(e) => setCategory(e.target.value)}>
                    {Object.entries(yt?.categories || {}).map(([id, name]) => <option key={id} value={id}>{name}</option>)}
                  </select>
                </div>
              </div>
              <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <input type="checkbox" checked={synthetic} onChange={(e) => setSynthetic(e.target.checked)} />
                Disclose altered or synthetic content (AI-made realistic pictures or clips)
              </label>
              {draft.thumbnail_path && (
                <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                  <input type="checkbox" checked={thumb} onChange={(e) => setThumb(e.target.checked)} />
                  Use BuzzEdit's thumbnail <code style={{ fontSize: '0.72rem' }}>{draft.thumbnail_path}</code>
                </label>
              )}
            </div>
            <div style={{ marginTop: 6 }}>
              <button type="button" className="btn btn-sm" disabled={!channel || !title.trim()} onClick={publish}>
                Upload to YouTube
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
