/**
 * Theme ingredients. Every BASE × ACCENT pair is a theme (6 × 10 = 60).
 * base:   the surfaces (hue + saturation of the dark background)
 * accent: the system colour (borders, glows, prices, active states)
 */

export const BASES = [
  { id: 'graphite', name: 'Graphite', h: 215, s: 8 },
  { id: 'obsidian', name: 'Obsidian', h: 0, s: 0 },
  { id: 'midnight', name: 'Midnight', h: 222, s: 42 },
  { id: 'abyss', name: 'Abyss', h: 184, s: 45 },
  { id: 'nebula', name: 'Nebula', h: 266, s: 30 },
  { id: 'ember', name: 'Ember', h: 18, s: 18 },
];

export const ACCENTS = [
  { id: 'silver', name: 'Silver', hex: '#e4e9ef' },
  { id: 'cyan', name: 'Cyan', hex: '#45e9ff' },
  { id: 'teal', name: 'Teal', hex: '#2de2c8' },
  { id: 'azure', name: 'Azure', hex: '#5b9dff' },
  { id: 'violet', name: 'Violet', hex: '#a78bfa' },
  { id: 'rose', name: 'Rose', hex: '#ff6b9a' },
  { id: 'crimson', name: 'Crimson', hex: '#ff4d5e' },
  { id: 'tangerine', name: 'Tangerine', hex: '#ff8a3d' },
  { id: 'gold', name: 'Gold', hex: '#ffd75e' },
  { id: 'lime', name: 'Lime', hex: '#b4ff4d' },
];

export const DEFAULT_THEME = 'midnight-teal';

/** Old ?theme= values still work. */
export const ALIASES = { grey: 'graphite-silver', gray: 'graphite-silver', teal: 'abyss-teal' };

export const THEMES = BASES.flatMap((base) => ACCENTS.map((accent) => ({
  id: `${base.id}-${accent.id}`,
  name: `${base.name} · ${accent.name}`,
  base,
  accent,
})));
