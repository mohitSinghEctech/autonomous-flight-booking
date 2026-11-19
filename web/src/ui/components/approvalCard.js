import { findFlight } from '../../state/selectors.js';
import { h } from '../dom.js';
import { day, duration, moneyShort, stops, time } from '../format.js';

const COPY = {
  book: { title: 'Hold this flight?', note: 'Nothing is booked until you confirm.', yes: 'Hold flight', no: 'Not now', tone: 'go' },
  change: { title: 'Switch to this flight?', note: 'Your current hold is released first.', yes: 'Switch flight', no: 'Keep current', tone: 'go' },
  cancel: { title: 'Cancel your booking?', note: 'The seat is released. Nothing is charged.', yes: 'Yes, cancel', no: 'Keep booking', tone: 'danger' },
};

/**
 * The graph is paused at interrupt(). Nothing irreversible happens
 * until the user presses the yes button. Lives in the flights pane:
 * actions are buttons on the left; the chat is for new requests.
 */
export function approvalCard(state, onDecide) {
  const a = state.approval;
  if (!a) return null;

  const copy = COPY[a.kind] ?? COPY.book;
  const f = a.flight ?? findFlight(state, a.flight_id);
  const sending = state.approvalSending;
  const pax = a.passengers ?? [];

  return h('section', { class: `approval tone-${copy.tone}`, role: 'alertdialog', 'aria-label': copy.title },
    h('div', { class: 'ap-head' },
      h('span', { class: 'ap-kicker' }, 'Needs your OK'),
      h('h3', {}, copy.title)),
    f ? h('div', { class: 'ap-flight' },
      h('div', { class: 'ap-leg' },
        h('b', {}, time(f.departure_datetime)),
        h('span', { class: 'ap-path' }, h('small', {}, duration(f.duration_minutes)), h('i'), h('small', {}, stops(f))),
        h('b', {}, time(f.arrival_datetime))),
      h('p', {}, `${f.flight_name} · ${f.origin.airport_code} → ${f.destination.airport_code} · ${day(f.departure_datetime)}`)) : null,
    h('div', { class: 'ap-meta' },
      h('span', {}, pax.length ? `${pax.length} passenger${pax.length > 1 ? 's' : ''}: ${pax.map((p) => p.name).join(', ')}` : ''),
      a.kind === 'cancel' ? null : h('b', { class: 'ap-price' }, moneyShort(a.total_amount, a.currency))),
    h('p', { class: 'ap-note' }, copy.note),
    h('div', { class: 'ap-actions' },
      h('button', { class: 'ap-no', type: 'button', disabled: sending, onClick: () => onDecide(a.approval_id, 'rejected') }, copy.no),
      h('button', { class: 'ap-yes', type: 'button', disabled: sending, onClick: () => onDecide(a.approval_id, 'approved') },
        sending ? 'Sending…' : copy.yes)),
  );
}
