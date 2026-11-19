import { h } from '../dom.js';
import { capitalize, day, money, time } from '../format.js';
import {
  ROUTES, dateTime, errorState, fullName, loadingState, screenHead, statusPill, writeErrorText,
} from './shared.js';

const CANCELLABLE = ['held', 'awaiting_payment'];

/**
 * One booking: flight, passengers, price, status, payment (GET /api/bookings/{id}).
 * Actions: Cancel (held / awaiting_payment) and Pay (held).
 */
export function bookingDetailScreen({ api, id, chatBooking, payInChat }) {
  const body = h('div', { class: 'acct-body' }, loadingState('Loading booking…'));
  load();

  return h('section', { class: 'acct-screen', 'aria-label': 'Booking details' },
    h('a', { class: 'acct-back', href: ROUTES.bookings }, '← All bookings'),
    body);

  async function load() {
    try {
      show(await api.getBooking(id));
    } catch (error) {
      body.replaceChildren(errorState(error, `GET /api/bookings/${id}`, () => {
        body.replaceChildren(loadingState());
        load();
      }));
    }
  }

  function show(booking) {
    const message = h('p', { class: 'pf-error', role: 'alert' });
    body.replaceChildren(
      screenHead(`${booking.flight.origin.airport_code} → ${booking.flight.destination.airport_code}`,
        `Reference ${booking.booking_reference}`, statusPill(booking.lifecycle)),
      flightCard(booking.flight),
      facts(booking),
      passengersCard(booking.passengers ?? []),
      message,
      actions(booking, message),
    );
  }

  function actions(booking, message) {
    const buttons = [];
    // The existing payment sheet works on the CURRENT chat session's booking (POST /sessions/{t}/payments),
    // so it can be reused only when this is that booking.
    const isChatBooking = Boolean(booking.booking_id) && chatBooking()?.booking_id === booking.booking_id;

    if (booking.lifecycle === 'held') {
      buttons.push(isChatBooking
        ? h('button', { class: 'btn-primary', type: 'button', onClick: payInChat }, 'Pay now')
        // TODO(account-api): paying any older booking needs POST /api/bookings/{id}/payments
        // (planned, see flight_booking/docs/account-api-plan.md §8); then open the payment sheet with its checkout.
        : h('button', { class: 'btn-primary', type: 'button', disabled: true, title: 'Paying from here is not built yet' }, 'Pay now'));
    }

    if (CANCELLABLE.includes(booking.lifecycle)) {
      buttons.push(h('button', { class: 'acct-danger', type: 'button', onClick: (e) => cancel(e.currentTarget, booking, message) }, 'Cancel booking'));
    }

    if (!buttons.length) return null;
    const hint = booking.lifecycle === 'held' && !isChatBooking
      ? h('p', { class: 'pane-sub' }, 'Paying from the account page is coming soon. For now, pay from the chat where you booked it.')
      : null;
    return h('div', { class: 'acct-footer' }, h('div', { class: 'acct-actions' }, ...buttons), hint);
  }

  async function cancel(button, booking, message) {
    const ok = window.confirm(`Cancel booking ${booking.booking_reference}? The airline hold is released and this can't be undone.`);
    if (!ok) return;

    button.disabled = true;
    message.textContent = '';
    try {
      show(await api.cancelBookingById(booking.id));
    } catch (error) {
      message.textContent = writeErrorText(error, `POST /api/bookings/${booking.id}/cancel`);
      button.disabled = false;
    }
  }
}

function flightCard(f) {
  return h('div', { class: 'acct-card' },
    h('div', { class: 'acct-leg' },
      h('div', {}, h('b', {}, time(f.departure_datetime)), h('small', {}, `${f.origin.airport_code} · ${day(f.departure_datetime)}`)),
      h('i', { class: 'acct-leg-line', 'aria-hidden': 'true' }),
      h('div', { class: 'is-end' }, h('b', {}, time(f.arrival_datetime)), h('small', {}, `${f.destination.airport_code} · ${day(f.arrival_datetime)}`)),
    ),
    h('p', { class: 'pane-sub' }, `${f.flight_name} · ${capitalize(f.cabin)} · ${f.origin.airport_name} → ${f.destination.airport_name}`));
}

function facts(booking) {
  const payment = booking.payment;
  const rows = [
    ['Total', money(booking.total_amount, booking.currency)],
    ['Payment', payment ? capitalize(payment.status) : 'Not started'],
    ['Pay by', booking.lifecycle === 'held' || booking.lifecycle === 'awaiting_payment' ? dateTime(booking.payment_required_by) : null],
    ['Booked on', dateTime(booking.created_at)],
    ['Airline order', booking.booking_id],
  ].filter(([, value]) => value);

  return h('dl', { class: 'acct-facts' }, ...rows.flatMap(([k, v]) => [h('dt', {}, k), h('dd', {}, v)]));
}

function passengersCard(passengers) {
  return h('div', { class: 'acct-card' },
    h('h3', { class: 'acct-card-title' }, passengers.length === 1 ? 'Passenger' : `Passengers (${passengers.length})`),
    passengers.length
      ? h('ul', { class: 'acct-plain' }, ...passengers.map((p) => h('li', {},
          p.passenger_id ? h('a', { href: ROUTES.passenger(p.passenger_id) }, fullName(p)) : fullName(p),
          p.email ? h('small', { class: 'pane-sub' }, ` · ${p.email}`) : null)))
      : h('p', { class: 'pane-sub' }, 'No passengers on this booking.'));
}
