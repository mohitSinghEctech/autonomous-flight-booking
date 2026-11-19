import { ALIASES, DEFAULT_THEME, THEMES } from './palettes.js';

const STORAGE_KEY = 'atlas.theme';

/**
 * Turn one BASE × ACCENT pair into the CSS variables from styles/tokens.css.
 * Signal colours move if the accent would collide with them:
 *   orange/gold accent -> approval becomes magenta (not amber)
 *   green/lime accent  -> "done" becomes blue (not green)
 */
export function buildTheme({ base, accent }) {
  const { h, s } = base;
  const accentRgb = hexToRgb(accent.hex);
  const a = rgbToHsl(accentRgb);
  const textSat = Math.min(s, 25);

  const approvalClash = a.s > 40 && a.h >= 18 && a.h <= 62;
  const doneClash = a.s > 40 && a.h > 62 && a.h <= 150;
  const amber = approvalClash ? [255, 110, 214] : [255, 181, 71];
  const green = doneClash ? [98, 200, 255] : [126, 231, 135];

  return {
    '--bg': hsl(h, s, 4.5),
    '--bg-2': hsl(h, s, 8),
    '--panel': hsl(h, s, 8.5, 0.95),
    '--panel-2': hsl(h, s, 12.5, 0.95),
    '--panel-solid': hsl(h, s, 10),
    '--deep-rgb': triple(hslToRgb(h, s, 4)),
    '--raise-rgb': triple(hslToRgb(h, s, 17)),
    '--ambient-rgb': triple(hslToRgb(a.h, a.s * 0.6, 34)),

    '--line-rgb': triple(hslToRgb(h, Math.min(s, 30) * 0.6, 62)),   // neutral dividers; accent is for meaning
    '--primary': accent.hex,
    '--primary-2': hsl(a.h, a.s, Math.max(a.l - 18, 25)),
    '--primary-rgb': triple(accentRgb),
    '--primary-glow': `rgb(${triple(accentRgb)} / ${a.s < 20 ? 0.22 : 0.4})`,

    '--amber': rgbHex(amber),
    '--amber-rgb': triple(amber),
    '--green': rgbHex(green),
    '--green-rgb': triple(green),

    '--text': hsl(h, textSat * 0.6, 96.5),
    '--text-2': hsl(h, textSat, 80),
    '--text-3': hsl(h, textSat * 0.8, 63),
  };
}

export function findTheme(id) {
  const resolved = ALIASES[id] ?? id;
  return THEMES.find((t) => t.id === resolved) ?? THEMES.find((t) => t.id === DEFAULT_THEME);
}

export function applyTheme(id, { persist = true } = {}) {
  const theme = findTheme(id);
  const root = document.documentElement;

  for (const [name, value] of Object.entries(buildTheme(theme))) root.style.setProperty(name, value);
  root.dataset.theme = theme.id;

  if (persist) {
    try { localStorage.setItem(STORAGE_KEY, theme.id); } catch { /* private mode */ }
  }
  return theme;
}

/** URL ?theme= wins, then the saved choice, then the default. */
export function initialThemeId(urlTheme) {
  if (urlTheme) return urlTheme;
  try { return localStorage.getItem(STORAGE_KEY) ?? DEFAULT_THEME; } catch { return DEFAULT_THEME; }
}

export function themeSwatch(theme) {
  const vars = buildTheme(theme);
  return { bg: vars['--panel-solid'], edge: vars['--bg'], accent: theme.accent.hex };
}

// ---- colour maths ----------------------------------------------------------

function hsl(h, s, l, alpha) {
  return alpha == null ? `hsl(${h} ${s}% ${l}%)` : `hsl(${h} ${s}% ${l}% / ${alpha})`;
}

function triple([r, g, b]) {
  return `${r} ${g} ${b}`;
}

function hexToRgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function rgbHex(rgb) {
  return '#' + rgb.map((v) => v.toString(16).padStart(2, '0')).join('');
}

function hslToRgb(h, s, l) {
  s /= 100; l /= 100;
  const k = (n) => (n + h / 30) % 12;
  const a = s * Math.min(l, 1 - l);
  const f = (n) => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  return [f(0), f(8), f(4)].map((v) => Math.round(v * 255));
}

function rgbToHsl([r, g, b]) {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  if (max === min) return { h: 0, s: 0, l: l * 100 };

  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  const h = max === r ? (g - b) / d + (g < b ? 6 : 0) : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return { h: h * 60, s: s * 100, l: l * 100 };
}
