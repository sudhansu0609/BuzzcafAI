import { useStudio } from '../state/studio';
import { CHANNEL_META } from '../lib/channels';
import type { TabId } from '../lib/types';

// The header's channel picker, on every page. List pages (projects, board,
// scheduler, dashboard) filter by it and offer "All channels"; pages that
// always work on one channel (chat, analyze, research, vault) follow it too
// but have no "all" to pick.
const SINGLE_CHANNEL_TABS: TabId[] = ['studio_chat', 'analyze', 'research', 'topic_vault'];

export function ChannelPicker() {
  const { tab, brands, selectedChannel, channelFilter, setChannelFilter, setSelectedChannel } = useStudio();
  const options = brands.length > 0 ? brands : CHANNEL_META.map((c) => c.id);
  const single = SINGLE_CHANNEL_TABS.includes(tab);
  const value = single ? selectedChannel : channelFilter;
  const icon = (b: string) => CHANNEL_META.find((c) => c.id === b)?.icon || '📺';

  return (
    <select
      className="form-control channel-picker"
      value={value}
      onChange={(e) => (single ? setSelectedChannel(e.target.value) : setChannelFilter(e.target.value))}
      title={single ? 'Channel this page works on' : 'Show one channel, or all of them'}
      aria-label="Channel"
      style={{ width: 'auto', minWidth: 150, padding: '6px 10px', fontSize: '0.85rem' }}
    >
      {!single && <option value="">📺 All channels</option>}
      {options.map((b) => (
        <option key={b} value={b}>{icon(b)} {b}</option>
      ))}
    </select>
  );
}
