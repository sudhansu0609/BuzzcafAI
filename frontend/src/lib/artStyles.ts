// The art style: the medium a video's pictures, clips, thumbnail scene and
// text cards are made in (backend/integrations/art_style.py keeps the same
// table). Picked per channel (Settings -> Channel Profiles), per project
// (Projects -> Visuals) and per vault topic (carried into the project).
export const ART_STYLES: ReadonlyArray<{ id: string; label: string; hint: string }> = [
  { id: 'real', label: 'Real (cinematic, photoreal)', hint: 'Photoreal film-still pictures and clips; the main character gets his real face.' },
  { id: 'explainer', label: 'Explainer (flat vector)', hint: 'Flat vector explainer illustrations: diagrams, maps, simple figures, numbers on screen.' },
  { id: 'stick_figure', label: 'Stick figure (whiteboard)', hint: 'Black marker stick figures on white paper with one red accent; hand-written labels.' },
  { id: 'cartoon', label: 'Cartoon (2D animated)', hint: 'Bold 2D cartoon frames: thick outlines, flat cel shading, bright colours.' },
  { id: 'painterly', label: 'Painterly (soft oil / gouache)', hint: 'Soft oil and gouache paintings: muted earthy palette, one warm light, visible brush texture.' },
  { id: 'illustrated', label: 'Illustrated animation (hand-drawn)', hint: 'Soothing hand-drawn digital illustration, like frame-by-frame Procreate animation: soft gouache and pencil texture, pastel palette.' },
  { id: 'stick_world', label: 'Stick world (dressed stick figures in illustrated scenes)', hint: 'Hand-painted storybook places, rich period detail; people moments are dressed stick figures in the scene’s own era.' },
  { id: 'mixed', label: 'Mixed (real + stick figure + maps & charts)', hint: 'Photoreal story shots, stick-figure explainer drawings, maps and charts in one video; the planner picks per shot.' },
  { id: 'mixed_quirky', label: 'Quirky documentary (illustrated + stick figure, a little real)', hint: 'Mostly hand-drawn illustration and stick-figure gags, a few real shots, maps, charts and pop-up numbers: playful, fast and engaging.' },
];

export const artStyleLabel = (id?: string | null): string =>
  ART_STYLES.find((s) => s.id === (id || 'real'))?.label || id || 'Real';
