import { ACCENTS, BASES, THEMES } from '../../theme/palettes.js';
import { findTheme, themeSwatch } from '../../theme/theme.js';
import { h } from '../dom.js';

/**
 * Gear popover: a BASE × ACCENT matrix of all themes + shuffle.
 * Theme is a local preference, so it lives here, not in the app store.
 * Returns { open } so other screens (account → Profile) can open it.
 */
export function createSettingsPanel(anchor, { currentId, onChange }) {
  let current = findTheme(currentId);

  const name = h('div', { class: 'settings-current' });
  const cells = new Map();

  const matrix = h('div', { class: 'theme-matrix', role: 'grid', style: `--cols: ${ACCENTS.length}` },
    h('span', { class: 'tm-corner' }),
    ...ACCENTS.map((accent) => h('span', { class: 'tm-col', title: accent.name },
      h('i', { style: `background: ${accent.hex}` }))),
    ...BASES.flatMap((base) => [
      h('span', { class: 'tm-row' }, base.name),
      ...ACCENTS.map((accent) => {
        const theme = THEMES.find((t) => t.id === `${base.id}-${accent.id}`);
        const sw = themeSwatch(theme);
        const cell = h('button', {
          class: 'tm-cell', type: 'button', title: theme.name, 'aria-label': theme.name,
          style: `--sw-bg: ${sw.bg}; --sw-edge: ${sw.edge}; --sw-accent: ${sw.accent}`,
          onClick: () => select(theme.id),
          onMouseEnter: () => preview(theme.id),
          onMouseLeave: () => preview(current.id),
        }, h('i'));
        cells.set(theme.id, cell);
        return cell;
      }),
    ]),
  );

  const panel = h('div', { class: 'settings-panel', role: 'dialog', 'aria-label': 'Display settings', hidden: true },
    h('div', { class: 'settings-head' },
      h('span', { class: 'settings-title' }, 'Theme'),
      h('span', { class: 'settings-count' }, `${THEMES.length} themes`),
    ),
    h('div', { class: 'settings-row' },
      name,
      h('button', { class: 'chip', type: 'button', onClick: shuffle }, '⟳ Shuffle'),
    ),
    matrix,
    h('div', { class: 'settings-hint' }, 'Hover to preview · click to apply · saved in this browser'),
  );

  const button = h('button', {
    class: 'gear-btn', type: 'button', 'aria-label': 'Display settings', 'aria-expanded': 'false',
    onClick: () => toggle(),
  }, gearIcon());

  anchor.append(h('div', { class: 'settings' }, button, panel));

  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') toggle(false); });
  document.addEventListener('pointerdown', (e) => {
    if (!panel.hidden && !anchor.contains(e.target)) toggle(false);
  });

  mark();

  // the account Profile screen opens this same popover instead of keeping a second copy
  return {
    open() {
      toggle(true);
      matrix.querySelector('.tm-cell.is-active')?.focus();
    },
  };

  function toggle(open = panel.hidden) {
    panel.hidden = !open;
    button.setAttribute('aria-expanded', String(open));
    button.classList.toggle('is-open', open);
    if (!open) preview(current.id);
  }

  function select(id) {
    current = findTheme(id);
    onChange(current.id, { persist: true });
    mark();
  }

  function preview(id) {
    onChange(id, { persist: false });
    name.textContent = findTheme(id).name;
  }

  function shuffle() {
    const others = THEMES.filter((t) => t.id !== current.id);
    select(others[Math.floor(Math.random() * others.length)].id);
  }

  function mark() {
    for (const [id, cell] of cells) cell.classList.toggle('is-active', id === current.id);
    name.textContent = current.name;
  }
}

function gearIcon() {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('aria-hidden', 'true');
  const path = document.createElementNS(ns, 'path');
  path.setAttribute('d',
    'M12 8.6a3.4 3.4 0 1 0 0 6.8 3.4 3.4 0 0 0 0-6.8Zm8.6 4.6-1.9.4a6.9 6.9 0 0 1-.6 1.5l1.1 1.6-1.6 1.6-1.6-1.1c-.5.3-1 .5-1.5.6l-.4 1.9h-2.2l-.4-1.9a6.9 6.9 0 0 1-1.5-.6l-1.6 1.1-1.6-1.6 1.1-1.6a6.9 6.9 0 0 1-.6-1.5l-1.9-.4v-2.2l1.9-.4c.1-.5.3-1 .6-1.5L5.6 6.9l1.6-1.6 1.6 1.1c.5-.3 1-.5 1.5-.6l.4-1.9h2.2l.4 1.9c.5.1 1 .3 1.5.6l1.6-1.1 1.6 1.6-1.1 1.6c.3.5.5 1 .6 1.5l1.9.4v2.2Z');
  svg.append(path);
  return svg;
}
