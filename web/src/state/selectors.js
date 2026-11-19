/** Derived data. Views ask questions here instead of digging through state. */

// ---- flights -----------------------------------------------------------------

export function sortedFlights(state) {
  const key = {
    price: (f) => f.price,
    departure: (f) => f.departure_datetime,
    duration: (f) => f.duration_minutes ?? Infinity,
  }[state.sort];

  return state.flights.slice().sort((a, b) => (key(a) < key(b) ? -1 : key(a) > key(b) ? 1 : 0));
}

export function findFlight(state, flightId) {
  return state.flights.find((f) => f.flight_id === flightId)
    ?? (state.approval?.flight_id === flightId ? state.approval.flight : null);
}

export function cheapestId(flights) {
  return flights.length ? minBy(flights, (f) => f.price).flight_id : null;
}

export function activeBooking(state) {
  const b = state.booking;
  return b && !['cancelled', 'expired'].includes(b.lifecycle) ? b : null;
}

/** One word for a row: what is this flight to the user right now? */
export function rowMark(state, flightId) {
  if (activeBooking(state)?.flight_id === flightId) return 'booked';
  if (state.approval?.flight_id === flightId) return 'pending';
  if (state.selection?.flight_id === flightId) return state.selection.by === 'user' ? 'chosen' : 'pick';
  return null;
}

// ---- the journey bar ---------------------------------------------------------

export const JOURNEY = ['Search', 'Choose', 'Approve', 'Hold', 'Pay', 'Confirmed'];

/** Index of the step the user is on (JOURNEY.length = all done). */
export function journeyIndex(state) {
  const booking = activeBooking(state);
  const { approval, flights, status } = state;

  if (booking?.lifecycle === 'confirmed') return JOURNEY.length;
  if (approval) return approval.kind === 'cancel' ? 4 : 2;
  if (state.passengerRequest) return 1;
  if (status.busy && status.stage === 'booking') return 3;
  if (booking) return 4;                                   // held / awaiting payment -> pay next
  if (flights.length) return 1;
  return 0;
}

// ---- what to suggest next ----------------------------------------------------

function today() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

const examples = () => [
  `Find flights from DEL to DXB on ${today()} and book the cheapest`,
  `Show me business class BOM to LHR on ${today()}`,
];

/** One-tap requests that match where the user is. Empty while ATLAS is busy or waiting for an OK. */
export function quickReplies(state) {
  if (state.status.busy || state.approval || state.passengerRequest) return [];

  // requests only — actions (book, pay, cancel) are buttons in the flights pane
  const booking = activeBooking(state);
  if (booking?.lifecycle === 'confirmed') return [`Find flights from DEL to BOM on ${today()}`];
  if (booking) return ['Find me a later flight', 'Find me an earlier flight'];
  if (state.flights.length) return ['Show me a later flight', 'Show me an earlier flight'];
  return examples();
}

// ---- agent activity (steps) per turn ----------------------------------------

export function turnSteps(state, turnId) {
  return state.steps.filter((s) => s.turn_id === turnId);
}

function minBy(list, fn) {
  return list.reduce((best, item) => (fn(item) < fn(best) ? item : best));
}
