// The five channel brands, their strategist persona and default workflow.
//
// The brand *list* the UI offers comes from GET /api/brands so it cannot drift
// from the backend; this table only adds presentation and the persona/workflow
// mapping for a brand name. An unknown brand falls back to the documentary
// strategist, which is the same default the old code used.

export interface ChannelMeta {
  id: string;
  icon: string;
  desc: string;
  strategist: string;
  workflow: string;
}

export const CHANNEL_META: ChannelMeta[] = [
  {
    id: 'Originals',
    icon: '✍️',
    desc: 'Original stories, fiction & analysis',
    strategist: 'SpilledCoffeeStudioStrategist',
    workflow: 'spilled_coffee_story',
  },
  {
    id: 'Raat3Baje',
    icon: '👻',
    desc: 'Horror, paranormal & urban legends',
    strategist: 'AfterDarkStrategist',
    workflow: 'after_dark_narration',
  },
  {
    id: 'Beyond3Baje',
    icon: '🕵️',
    desc: 'True stories, dark history & true crime',
    strategist: 'Beyond3BajeStrategist',
    workflow: 'beyond3baje_documentary',
  },
  {
    id: 'Life3Baje',
    icon: '☕',
    desc: 'Creative journey & video essays',
    strategist: 'Life3BajeStrategist',
    workflow: 'life3baje_video',
  },
  {
    id: 'Khayal3Baje',
    icon: '🏛️',
    desc: 'Ancient mythology & sacred lore',
    strategist: 'Khayal3BajeStrategist',
    workflow: 'khayal3baje_horror',
  },
];

const DEFAULT_META = CHANNEL_META[2];

export function metaFor(channel: string | undefined | null): ChannelMeta {
  if (!channel) return DEFAULT_META;
  const exact = CHANNEL_META.find((c) => c.id === channel);
  if (exact) return exact;
  const lower = channel.toLowerCase();
  if (lower.includes('raat3baje') || lower.includes('after dark')) return CHANNEL_META[1];
  // 'originals' before the legacy 'studio' so old localStorage values still resolve.
  if (lower.includes('originals')) return CHANNEL_META[0];
  if (lower.includes('spilled coffee')) return CHANNEL_META[0];
  if (lower.includes('life')) return CHANNEL_META[3];
  if (lower.includes('khayal')) return CHANNEL_META[4];
  return DEFAULT_META;
}

export const strategistFor = (channel: string | undefined | null) => metaFor(channel).strategist;
export const workflowFor = (channel: string | undefined | null) => metaFor(channel).workflow;
