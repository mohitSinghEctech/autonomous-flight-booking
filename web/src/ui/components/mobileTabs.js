import { h } from '../dom.js';

/** Phones only (CSS hides it on wide screens): one pane at a time. */
export function createMobileTabs(root, { onTab }) {
  const badge = h('span', { class: 'tab-badge' });
  const chat = h('button', { class: 'tab', type: 'button', onClick: () => onTab('chat') }, 'Chat');
  const flights = h('button', { class: 'tab', type: 'button', onClick: () => onTab('flights') }, 'Flights', badge);
  root.append(chat, flights);

  return {
    update(state, prev) {
      if (state.tab !== prev.tab) {
        chat.classList.toggle('is-active', state.tab === 'chat');
        flights.classList.toggle('is-active', state.tab === 'flights');
        document.querySelector('.app').dataset.tab = state.tab;
      }
      if (state.flights !== prev.flights) badge.textContent = state.flights.length || '';
      // something new on the other tab -> nudge
      const flightNews = state.selection !== prev.selection || state.booking !== prev.booking;
      if (flightNews && state.tab === 'chat' && state.flights.length) flights.classList.add('has-news');
      if (state.tab === 'flights') flights.classList.remove('has-news');
    },
  };
}
