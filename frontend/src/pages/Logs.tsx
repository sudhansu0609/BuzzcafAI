import { useCallback, useEffect, useState } from 'react';
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Copy,
  Info,
  Play,
  RotateCw,
  Search,
  Square,
  Trash2,
} from 'lucide-react';
import { getJson, postJson, describeError } from '../services/api';
import { LogEntry, LogsResponse } from '../lib/types';

export default function Logs() {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [errorCount, setErrorCount] = useState(0);
  const [warningCount, setWarningCount] = useState(0);
  const [totalParsed, setTotalParsed] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [levelFilter, setLevelFilter] = useState<'ALL' | 'ERROR' | 'WARNING' | 'INFO'>('ALL');
  const [sourceFilter, setSourceFilter] = useState<'all' | 'app' | 'studio'>('all');
  const [limit, setLimit] = useState(250);
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');

  // Auto-refresh
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [expandedTracebacks, setExpandedTracebacks] = useState<Record<number, boolean>>({});

  // Debounce search
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(timer);
  }, [search]);

  const fetchLogs = useCallback(async () => {
    try {
      const q = new URLSearchParams({
        level: levelFilter,
        source: sourceFilter,
        limit: String(limit),
      });
      if (debouncedSearch.trim()) {
        q.set('search', debouncedSearch.trim());
      }
      const data = await getJson<LogsResponse>(`/api/system/logs?${q.toString()}`);
      setLogs(data.logs || []);
      setErrorCount(data.error_count || 0);
      setWarningCount(data.warning_count || 0);
      setTotalParsed(data.total_parsed || 0);
      setError(null);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setLoading(false);
    }
  }, [levelFilter, sourceFilter, limit, debouncedSearch]);

  // Initial and on filter change
  useEffect(() => {
    setLoading(true);
    fetchLogs();
  }, [fetchLogs]);

  // Auto-refresh timer
  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(() => {
      fetchLogs();
    }, 3000);
    return () => clearInterval(interval);
  }, [autoRefresh, fetchLogs]);

  const handleClear = async () => {
    if (!window.confirm('Clear all logs and reset log files?')) return;
    try {
      await postJson('/api/system/logs/clear');
      await fetchLogs();
    } catch (err) {
      setError(describeError(err));
    }
  };

  const copyToClipboard = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const copyAll = () => {
    const text = logs
      .map(
        (l) =>
          `[${l.timestamp || 'NO_TS'}] [${l.level}] [${l.logger}] ${l.message}${
            l.traceback.length ? '\n' + l.traceback.join('\n') : ''
          }`
      )
      .join('\n');
    copyToClipboard(text, 'all');
  };

  const toggleTraceback = (idx: number) => {
    setExpandedTracebacks((prev) => ({ ...prev, [idx]: !prev[idx] }));
  };

  const getBadgeStyle = (lvl: string) => {
    switch (lvl) {
      case 'CRITICAL':
      case 'ERROR':
        return { bg: 'rgba(239, 68, 68, 0.15)', color: '#f87171', border: '1px solid rgba(239, 68, 68, 0.3)' };
      case 'WARN':
      case 'WARNING':
        return { bg: 'rgba(245, 158, 11, 0.15)', color: '#fbbf24', border: '1px solid rgba(245, 158, 11, 0.3)' };
      case 'INFO':
        return { bg: 'rgba(56, 189, 248, 0.15)', color: '#38bdf8', border: '1px solid rgba(56, 189, 248, 0.3)' };
      default:
        return { bg: 'rgba(148, 163, 184, 0.1)', color: '#94a3b8', border: '1px solid rgba(148, 163, 184, 0.2)' };
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, height: '100%', paddingBottom: 24 }}>
      {/* Top Header Card */}
      <div className="panel-card" style={{ padding: '16px 20px', marginBottom: 0 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div
              style={{
                width: 40,
                height: 40,
                borderRadius: 10,
                background: 'rgba(239, 68, 68, 0.12)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#ef4444',
                border: '1px solid rgba(239, 68, 68, 0.25)',
              }}
            >
              <AlertCircle size={22} />
            </div>
            <div>
              <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, letterSpacing: '-0.02em', display: 'flex', alignItems: 'center', gap: 8 }}>
                System & Error Logs
              </h2>
              <p style={{ margin: 0, fontSize: 12, color: 'var(--text-muted, #94a3b8)' }}>
                Real-time backend logs, AI model timings, error tracebacks, and channel execution diagnostics
              </p>
            </div>
          </div>

          {/* Quick Metrics */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                padding: '6px 12px',
                borderRadius: 8,
                background: 'rgba(239, 68, 68, 0.1)',
                border: '1px solid rgba(239, 68, 68, 0.3)',
                color: '#f87171',
                fontSize: 13,
                fontWeight: 600,
              }}
            >
              <AlertCircle size={15} />
              <span>{errorCount} {errorCount === 1 ? 'Error' : 'Errors'}</span>
            </div>

            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                padding: '6px 12px',
                borderRadius: 8,
                background: 'rgba(245, 158, 11, 0.1)',
                border: '1px solid rgba(245, 158, 11, 0.3)',
                color: '#fbbf24',
                fontSize: 13,
                fontWeight: 600,
              }}
            >
              <AlertTriangle size={15} />
              <span>{warningCount} Warnings</span>
            </div>

            <div
              style={{
                padding: '6px 12px',
                borderRadius: 8,
                background: 'rgba(148, 163, 184, 0.08)',
                border: '1px solid rgba(148, 163, 184, 0.15)',
                color: '#94a3b8',
                fontSize: 13,
              }}
            >
              <span>{logs.length} / {totalParsed} entries</span>
            </div>
          </div>

          {/* Actions */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <button
              type="button"
              className="btn btn-outline"
              onClick={() => setAutoRefresh(!autoRefresh)}
              style={{
                borderColor: autoRefresh ? 'rgba(34, 197, 94, 0.4)' : undefined,
                color: autoRefresh ? '#4ade80' : undefined,
                background: autoRefresh ? 'rgba(34, 197, 94, 0.08)' : undefined,
                display: 'flex',
                alignItems: 'center',
                gap: 6,
              }}
              title={autoRefresh ? 'Auto-refresh active (3s)' : 'Auto-refresh paused'}
            >
              {autoRefresh ? <Square size={13} fill="#4ade80" /> : <Play size={13} />}
              <span>{autoRefresh ? 'Live (3s)' : 'Paused'}</span>
            </button>

            <button
              type="button"
              className="btn btn-outline"
              onClick={() => {
                setLoading(true);
                fetchLogs();
              }}
              disabled={loading}
              title="Refresh logs now"
            >
              <RotateCw size={14} className={loading ? 'animate-spin' : ''} />
              <span>Refresh</span>
            </button>

            <button
              type="button"
              className="btn btn-outline"
              onClick={copyAll}
              disabled={logs.length === 0}
              title="Copy all currently filtered logs to clipboard"
            >
              {copiedId === 'all' ? <CheckCircle2 size={14} style={{ color: '#4ade80' }} /> : <Copy size={14} />}
              <span>{copiedId === 'all' ? 'Copied!' : 'Copy All'}</span>
            </button>

            <button
              type="button"
              className="btn btn-outline"
              onClick={handleClear}
              style={{ color: '#f87171', borderColor: 'rgba(239, 68, 68, 0.3)' }}
              title="Clear all log files"
            >
              <Trash2 size={14} />
              <span>Clear</span>
            </button>
          </div>
        </div>

        {/* Filters Row */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 12,
            marginTop: 14,
            paddingTop: 14,
            borderTop: '1px solid var(--border-color, rgba(255, 255, 255, 0.08))',
            flexWrap: 'wrap',
          }}
        >
          {/* Level Switcher */}
          <div style={{ display: 'flex', gap: 4, background: 'rgba(0, 0, 0, 0.25)', padding: 3, borderRadius: 8 }}>
            {(['ALL', 'ERROR', 'WARNING', 'INFO'] as const).map((lvl) => {
              const active = levelFilter === lvl;
              return (
                <button
                  key={lvl}
                  type="button"
                  onClick={() => setLevelFilter(lvl)}
                  style={{
                    padding: '4px 10px',
                    fontSize: 12,
                    fontWeight: active ? 600 : 400,
                    borderRadius: 6,
                    border: 'none',
                    cursor: 'pointer',
                    background: active ? (lvl === 'ERROR' ? '#ef4444' : lvl === 'WARNING' ? '#f59e0b' : 'var(--accent-color, #38bdf8)') : 'transparent',
                    color: active ? '#fff' : 'var(--text-muted, #94a3b8)',
                    transition: 'all 0.15s ease',
                  }}
                >
                  {lvl === 'ALL' ? 'All Levels' : lvl === 'ERROR' ? 'Errors Only' : lvl === 'WARNING' ? 'Warnings' : 'Info'}
                </button>
              );
            })}
          </div>

          {/* Source Dropdown */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: 12, color: 'var(--text-muted, #94a3b8)' }}>Source:</span>
            <select
              value={sourceFilter}
              onChange={(e) => setSourceFilter(e.target.value as 'all' | 'app' | 'studio')}
              style={{
                fontSize: 12,
                padding: '4px 8px',
                borderRadius: 6,
                background: 'rgba(0, 0, 0, 0.25)',
                color: 'var(--text-primary, #e2e8f0)',
                border: '1px solid var(--border-color, rgba(255, 255, 255, 0.1))',
              }}
            >
              <option value="all">All Sources (app + studio)</option>
              <option value="app">app.log</option>
              <option value="studio">studio.log</option>
            </select>
          </div>

          {/* Search Box */}
          <div style={{ flex: 1, minWidth: 200, position: 'relative' }}>
            <Search size={14} style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: '#64748b' }} />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search in message, logger name, or stack trace..."
              style={{
                width: '100%',
                padding: '6px 12px 6px 32px',
                fontSize: 12,
                borderRadius: 6,
                background: 'rgba(0, 0, 0, 0.25)',
                color: 'var(--text-primary, #e2e8f0)',
                border: '1px solid var(--border-color, rgba(255, 255, 255, 0.1))',
              }}
            />
            {search && (
              <button
                type="button"
                onClick={() => setSearch('')}
                style={{
                  position: 'absolute',
                  right: 8,
                  top: '50%',
                  transform: 'translateY(-50%)',
                  background: 'none',
                  border: 'none',
                  color: '#64748b',
                  cursor: 'pointer',
                  fontSize: 12,
                }}
              >
                ✕
              </button>
            )}
          </div>

          {/* Limit */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: 12, color: 'var(--text-muted, #94a3b8)' }}>Limit:</span>
            <select
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
              style={{
                fontSize: 12,
                padding: '4px 8px',
                borderRadius: 6,
                background: 'rgba(0, 0, 0, 0.25)',
                color: 'var(--text-primary, #e2e8f0)',
                border: '1px solid var(--border-color, rgba(255, 255, 255, 0.1))',
              }}
            >
              <option value="100">100</option>
              <option value="250">250</option>
              <option value="500">500</option>
              <option value="1000">1000</option>
            </select>
          </div>
        </div>
      </div>

      {/* Error notification if fetch failed */}
      {error && (
        <div
          style={{
            padding: '10px 16px',
            borderRadius: 8,
            background: 'rgba(239, 68, 68, 0.15)',
            border: '1px solid rgba(239, 68, 68, 0.3)',
            color: '#f87171',
            fontSize: 13,
            display: 'flex',
            alignItems: 'center',
            gap: 8,
          }}
        >
          <AlertCircle size={16} />
          <span>Could not load system logs: {error}</span>
        </div>
      )}

      {/* Logs Stream Container */}
      <div
        className="panel-card"
        style={{
          flex: 1,
          padding: 12,
          margin: 0,
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          background: 'rgba(10, 15, 26, 0.85)',
          border: '1px solid var(--border-color, rgba(255, 255, 255, 0.08))',
          boxShadow: 'inset 0 2px 8px rgba(0, 0, 0, 0.4)',
        }}
      >
        <div
          style={{
            flex: 1,
            overflowY: 'auto',
            display: 'flex',
            flexDirection: 'column',
            gap: 6,
            paddingRight: 4,
            fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
          }}
        >
          {logs.length === 0 ? (
            <div
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                height: '100%',
                minHeight: 260,
                color: '#64748b',
                gap: 12,
              }}
            >
              <Info size={32} />
              <div style={{ textAlign: 'center' }}>
                <p style={{ margin: 0, fontSize: 14, fontWeight: 500, color: '#94a3b8' }}>
                  {loading ? 'Fetching logs...' : 'No log entries match the selected filters.'}
                </p>
                <p style={{ margin: '4px 0 0', fontSize: 12 }}>
                  {debouncedSearch ? `Search query: "${debouncedSearch}"` : 'Everything is running smoothly.'}
                </p>
              </div>
            </div>
          ) : (
            logs.map((entry, idx) => {
              const badge = getBadgeStyle(entry.level);
              const isError = entry.level === 'ERROR' || entry.level === 'CRITICAL';
              const isWarn = entry.level === 'WARN' || entry.level === 'WARNING';
              const hasTraceback = entry.traceback && entry.traceback.length > 0;
              const isExpanded = !!expandedTracebacks[idx];
              const logKey = `log-${idx}-${entry.timestamp}`;

              return (
                <div
                  key={logKey}
                  style={{
                    background: isError
                      ? 'rgba(239, 68, 68, 0.06)'
                      : isWarn
                      ? 'rgba(245, 158, 11, 0.04)'
                      : 'rgba(255, 255, 255, 0.02)',
                    borderLeft: `3px solid ${isError ? '#ef4444' : isWarn ? '#f59e0b' : 'rgba(56, 189, 248, 0.4)'}`,
                    borderRadius: '0 6px 6px 0',
                    padding: '8px 12px',
                    fontSize: 12,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 6,
                    transition: 'background 0.15s ease',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    {/* Timestamp */}
                    <span style={{ color: '#64748b', fontSize: 11 }}>
                      {entry.timestamp || '—'}
                    </span>

                    {/* Level Badge */}
                    <span
                      style={{
                        padding: '1px 6px',
                        borderRadius: 4,
                        fontSize: 10,
                        fontWeight: 700,
                        letterSpacing: '0.04em',
                        ...badge,
                      }}
                    >
                      {entry.level}
                    </span>

                    {/* Source */}
                    <span
                      style={{
                        fontSize: 10,
                        padding: '1px 5px',
                        borderRadius: 4,
                        background: 'rgba(148, 163, 184, 0.1)',
                        color: '#94a3b8',
                      }}
                    >
                      {entry.source}
                    </span>

                    {/* Logger Name */}
                    <span style={{ color: '#38bdf8', fontWeight: 600, fontSize: 11 }}>
                      {entry.logger}
                    </span>

                    {/* Action buttons on hover/right */}
                    <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6 }}>
                      {hasTraceback && (
                        <button
                          type="button"
                          onClick={() => toggleTraceback(idx)}
                          style={{
                            background: 'rgba(239, 68, 68, 0.15)',
                            border: '1px solid rgba(239, 68, 68, 0.3)',
                            borderRadius: 4,
                            color: '#f87171',
                            padding: '2px 6px',
                            cursor: 'pointer',
                            fontSize: 11,
                            display: 'flex',
                            alignItems: 'center',
                            gap: 4,
                          }}
                        >
                          {isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                          <span>Traceback ({entry.traceback.length} lines)</span>
                        </button>
                      )}

                      <button
                        type="button"
                        onClick={() =>
                          copyToClipboard(
                            `[${entry.timestamp}] [${entry.level}] [${entry.logger}] ${entry.message}${
                              entry.traceback.length ? '\n' + entry.traceback.join('\n') : ''
                            }`,
                            String(idx)
                          )
                        }
                        style={{
                          background: 'transparent',
                          border: 'none',
                          color: '#64748b',
                          cursor: 'pointer',
                          padding: 2,
                          display: 'flex',
                          alignItems: 'center',
                        }}
                        title="Copy entry"
                      >
                        {copiedId === String(idx) ? (
                          <CheckCircle2 size={13} style={{ color: '#4ade80' }} />
                        ) : (
                          <Copy size={13} />
                        )}
                      </button>
                    </div>
                  </div>

                  {/* Log message */}
                  <div
                    style={{
                      color: isError ? '#fca5a5' : isWarn ? '#fde68a' : '#e2e8f0',
                      wordBreak: 'break-word',
                      whiteSpace: 'pre-wrap',
                      lineHeight: 1.5,
                    }}
                  >
                    {entry.message}
                  </div>

                  {/* Traceback collapsible section */}
                  {hasTraceback && isExpanded && (
                    <div
                      style={{
                        marginTop: 4,
                        padding: '10px 12px',
                        borderRadius: 6,
                        background: 'rgba(0, 0, 0, 0.6)',
                        border: '1px solid rgba(239, 68, 68, 0.25)',
                        color: '#f87171',
                        fontSize: 11,
                        overflowX: 'auto',
                        whiteSpace: 'pre-wrap',
                        lineHeight: 1.4,
                      }}
                    >
                      {entry.traceback.join('\n')}
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
