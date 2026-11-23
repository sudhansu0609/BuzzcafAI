// The wake-the-PC settings of one scheduler on the Scheduler Desk: on/off, wake
// time, hibernate after, idle minutes, and the Windows task's status. Shorts and
// Long form each render their own, backed by their own Windows task.

export type NightlyTask = {
  registered: boolean; wake_timers: boolean; next_run_time?: string; last_run_time?: string; status?: string;
};
export type NightlyLastRun = {
  started_at?: string; finished_at?: string;
  tasks?: { task: string; built?: unknown[]; skipped?: unknown; error?: string }[];
  hibernate?: { hibernate: boolean; reasons: string[] };
};
export type NightlyState = {
  enabled: boolean; time: string; hibernate: boolean; idle_minutes: number;
  task: NightlyTask; last_run?: NightlyLastRun;
};
export type NightlyPatch = Partial<Pick<NightlyState, 'enabled' | 'time' | 'hibernate' | 'idle_minutes'>>;

export default function NightlyControls({ title, blurb, state, onSave }: {
  title: string;
  blurb: string;
  state: NightlyState;
  onSave: (patch: NightlyPatch) => void;
}) {
  const { task, last_run: last } = state;
  return (
    <div style={{ marginTop: 16, paddingTop: 14, borderTop: '1px solid var(--border-subtle)' }}>
      <div style={{ fontWeight: 700, marginBottom: 6 }}>{title}</div>
      <div style={{ color: 'var(--text-secondary)', fontSize: '0.84rem', marginBottom: 10 }}>{blurb}</div>
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center' }}>
        <label style={{ display: 'flex', gap: 8, alignItems: 'center', cursor: 'pointer' }}>
          <input type="checkbox" checked={state.enabled} onChange={(e) => onSave({ enabled: e.target.checked })} aria-label={`${title} enabled`} style={{ width: 18, height: 18 }} />
          <strong>{state.enabled ? 'On' : 'Off'}</strong>
        </label>
        <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          wake at <input type="time" className="form-control" value={state.time} onChange={(e) => e.target.value && onSave({ time: e.target.value })} aria-label={`${title} wake time`} style={{ width: 120 }} /> IST
        </label>
        <label style={{ display: 'flex', gap: 8, alignItems: 'center', cursor: 'pointer' }}>
          <input type="checkbox" checked={state.hibernate} onChange={(e) => onSave({ hibernate: e.target.checked })} aria-label={`${title} hibernate after`} style={{ width: 16, height: 16 }} />
          hibernate after
        </label>
        <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          if idle <input type="number" className="form-control" min={1} max={120} value={state.idle_minutes}
            onChange={(e) => onSave({ idle_minutes: Math.max(1, Math.min(120, Number(e.target.value) || 10)) })} aria-label={`${title} idle minutes`} style={{ width: 70 }} /> min
        </label>
      </div>
      <div style={{ marginTop: 10, fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
        Windows task: {task.registered ? `registered · next run ${task.next_run_time || '—'}` : (
          <span style={state.enabled ? { color: '#f87171' } : undefined}>
            not registered{state.enabled ? ' — switch Off and On again to register it' : ''}
          </span>
        )}
        {' · '}wake timers {task.wake_timers ? 'on' : <span style={{ color: '#f87171' }}>off (the PC cannot wake itself)</span>}
      </div>
      {last?.started_at && (
        <div style={{ marginTop: 6, fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
          Last scheduled run {last.started_at}
          {last.tasks?.map((t) => (
            <span key={t.task}> · {t.task}: {t.error ? `failed (${t.error})` : t.skipped ? `skipped (${String(t.skipped)})` : `${(t.built || []).length} built`}</span>
          ))}
          {last.hibernate && (
            <div>{last.hibernate.hibernate ? 'Hibernated afterwards.' : `Stayed on: ${last.hibernate.reasons.join('; ')}`}</div>
          )}
        </div>
      )}
    </div>
  );
}
