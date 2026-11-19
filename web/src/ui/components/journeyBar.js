import { JOURNEY, journeyIndex } from '../../state/selectors.js';
import { h } from '../dom.js';

/**
 * Booking progress for THIS session's trip: Search → … → Confirmed.
 * Lives at the top of the flights pane (the trip's own area), not in the app chrome,
 * and hides itself while the session has no booking flow yet.
 */
export function createJourneyBar() {
  const steps = JOURNEY.map((label, i) => h('li', { class: 'jstep' },
    h('span', { class: 'jdot', 'aria-hidden': 'true' }, h('span', { class: 'jnum' }, String(i + 1))),
    h('span', { class: 'jlabel' }, label),
  ));
  const list = h('ol', { class: 'journey' }, ...steps);
  const compact = h('p', { class: 'journey-compact', 'aria-hidden': 'true' });   // phone: one line instead of six dots
  const root = h('nav', { class: 'journey-bar', 'aria-label': 'Booking progress', hidden: true }, list, compact);

  return {
    el: root,

    update(state) {
      root.hidden = !hasBookingFlow(state);
      if (root.hidden) return;

      const index = journeyIndex(state);
      steps.forEach((li, i) => {
        li.className = `jstep ${i < index ? 'is-done' : ''} ${i === index ? 'is-current' : ''}`;
        li.querySelector('.jnum').textContent = i < index ? '✓' : String(i + 1);
        if (i === index) li.setAttribute('aria-current', 'step');
        else li.removeAttribute('aria-current');
      });
      compact.textContent = index >= JOURNEY.length
        ? 'Trip confirmed ✓'
        : `Step ${index + 1} of ${JOURNEY.length} · ${JOURNEY[index]}`;
    },
  };
}

/** Something to track: a search under way, results, a pick, an approval, passengers or a booking. */
function hasBookingFlow(state) {
  return Boolean(state.flights.length || state.search || state.booking || state.approval
    || state.passengerRequest || state.selection
    || (state.status.busy && ['searching', 'booking'].includes(state.status.stage)));
}
