import { useRef, useState } from 'react';
import { Loader2, Upload } from 'lucide-react';
import { describeError, postForm } from '../services/api';

/* Add your own music to BuzzEdit's library (uploads/). Each file is
 * loudness-normalised on the way in, so a level picked for one track means the
 * same for any other, and is stored with the licence chosen here: the music
 * guard never puts a file with no licence on record into a video. */

// The licences BuzzEdit's guard accepts that make sense for a file you add.
const LICENSES: { value: string; label: string }[] = [
  { value: 'own', label: 'My own music' },
  { value: 'royalty-free', label: 'Royalty-free (bought / licensed)' },
  { value: 'youtube-audio-library', label: 'YouTube Audio Library' },
  { value: 'cc0', label: 'CC0 / public domain' },
  { value: 'cc-by', label: 'CC-BY (credit the artist)' },
  { value: 'licensed', label: 'Licensed for this channel' },
];

const ACCEPT = '.mp3,.wav,.ogg,.m4a,.flac,.aac,.opus,audio/*';
// Uploads are normalised by ffmpeg; a long track can take a while.
const UPLOAD_TIMEOUT_MS = 15 * 60_000;

export type UploadedTrack = { file: string; seconds: number | null };

type Props = {
  onUploaded: (tracks: UploadedTrack[]) => void;
  onToast: (text: string, kind?: 'success' | 'error' | 'info') => void;
  disabled?: boolean;
  compact?: boolean;
};

export default function MusicUpload({ onUploaded, onToast, disabled, compact }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [license, setLicense] = useState('');
  const [busy, setBusy] = useState('');

  const upload = async (files: FileList | null) => {
    if (!files || !files.length) return;
    if (!license) {
      onToast('Pick the licence for these tracks first: a track with no licence is never used.', 'error');
      return;
    }
    const made: UploadedTrack[] = [];
    const list = Array.from(files);
    for (const [i, f] of list.entries()) {
      setBusy(list.length > 1 ? `Adding ${i + 1}/${list.length}: ${f.name}` : `Adding ${f.name}`);
      const form = new FormData();
      form.append('file', f);
      form.append('license', license);
      form.append('label', f.name.replace(/\.[^.]+$/, ''));
      try {
        made.push(await postForm<UploadedTrack>('/api/music/upload', form,
          { signal: AbortSignal.timeout(UPLOAD_TIMEOUT_MS) }));
      } catch (err) {
        onToast(`${f.name}: ${describeError(err)}`, 'error');
      }
    }
    setBusy('');
    if (inputRef.current) inputRef.current.value = '';
    if (made.length) {
      onToast(`${made.length} track${made.length > 1 ? 's' : ''} added to the music library.`, 'success');
      onUploaded(made);
    }
  };

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
      <select className="form-control" value={license} disabled={disabled || !!busy}
        onChange={(e) => setLicense(e.target.value)} style={{ width: compact ? 200 : 240 }}
        title="Where the music comes from. Required: only licensed music goes into a video."
        aria-label="Licence">
        <option value="">Licence…</option>
        {LICENSES.map((l) => <option key={l.value} value={l.value}>{l.label}</option>)}
      </select>
      <input ref={inputRef} type="file" accept={ACCEPT} multiple hidden
        onChange={(e) => upload(e.target.files)} aria-label="Music files" />
      <button type="button" className="btn btn-outline btn-sm" disabled={disabled || !!busy}
        onClick={() => (license ? inputRef.current?.click()
          : onToast('Pick the licence for these tracks first: a track with no licence is never used.', 'error'))}
        style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
        {busy ? <Loader2 size={14} className="spin" /> : <Upload size={14} />}
        {busy || 'Add music files'}
      </button>
    </div>
  );
}
