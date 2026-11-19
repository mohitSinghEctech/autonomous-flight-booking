import { h } from '../dom.js';

/**
 * Brand · demo/live pill · host links · Account · ⚙.
 * Also owns the thin progress line that runs while ATLAS is working.
 * (The booking journey moved into the flights pane: see journeyBar.js.)
 */
export function createTopBar(root, { links = [], onAccount } = {}) {
  const pill = h('span', { class: 'live-pill' });
  const settings = h('div', { class: 'settings-anchor' });
  const account = h('button', {
    class: 'account-btn', type: 'button', 'aria-label': 'My account', title: 'My account', onClick: onAccount,
  }, h('span', { class: 'account-avatar', 'aria-hidden': 'true' }, '◉'), h('span', { class: 'account-label' }, 'My account'));

  root.append(
    h('div', { class: 'brand' },
      h('span', { class: 'brand-mark', 'aria-hidden': 'true' }, '✦'),
      h('span', { class: 'brand-name' }, 'ATLAS'),
      h('span', { class: 'brand-sub' }, 'Flight assistant'),
    ),
    h('div', { class: 'top-spacer' }),   // keeps the 3-column grid: brand · space · actions
    h('div', { class: 'top-actions' },
      pill,
      ...links.map((link) => link.href
        ? h('a', { class: 'top-link', href: link.href }, link.label)
        : h('button', { class: 'top-link', type: 'button', onClick: link.onClick }, link.label)),
      onAccount ? account : null,
      settings,
    ),
    h('div', { class: 'busy-line', 'aria-hidden': 'true' }),
  );

  return {
    settingsAnchor: settings,

    update(state, prev) {
      root.classList.toggle('is-busy', state.status.busy);

      if (state.connection !== prev.connection || state.mock !== prev.mock) {
        const online = state.connection === 'online';
        pill.dataset.state = online ? 'ok' : 'warn';
        pill.textContent = !online ? 'Connecting…' : state.mock ? 'Demo data' : 'Live';
        pill.title = state.mock ? 'Flights, bookings and payments here are simulated.' : '';
      }
    },
  };
}
