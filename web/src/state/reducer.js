import { EVENTS } from '../api/contract.js';

/**
 * (state, event) -> new state. Pure: no DOM, no network.
 * Server events come from SSE; 'ui/*' events are local to this browser.
 * Every slice is replaced (never mutated) so views can compare with ===.
 */

export function initialState({ mock }) {
  return {
    mock,
    threadId: null,
    connection: 'connecting',   // connecting | online | reconnecting | offline
    lastEventId: null,

    status: { busy: false, stage: 'idle', text: 'Standing by' },
    turns: [],
    steps: [],
    messages: [],
    timeline: [],               // [{ type: 'msg'|'turn', id }] in arrival order -> chat layout

    search: null,
    flights: [],
    selection: null,            // { flight_id, by, reason }
    approval: null,
    approvalSending: false,
    passengerRequest: null,     // v1.1 passenger.required
    booking: null,
    payment: null,

    sort: 'price',              // price | departure | duration
    tab: 'chat',                // phones only: chat | flights
    showFlights: false,         // trip view: user asked to see the list again
  };
}

export function reducer(state, event) {
  const { type, data } = event;
  const s = event.id ? { ...state, lastEventId: event.id } : state;

  switch (type) {
    // ---- server events ------------------------------------------------
    case EVENTS.SESSION_SNAPSHOT:
      return {
        ...s,
        ...data,
        timeline: data.timeline ?? (data.messages ?? []).map((m) => ({ type: 'msg', id: m.id })),
        passengerRequest: data.passenger_request ?? null,
        approvalSending: false,
      };

    case EVENTS.STATUS:
      return { ...s, status: data };

    case EVENTS.TURN_STARTED:
      return {
        ...s,
        turns: upsert(s.turns, data, 'turn_id'),
        timeline: addOnce(s.timeline, { type: 'turn', id: data.turn_id }),
      };

    case EVENTS.TURN_COMPLETED:
      return s;

    case EVENTS.STEP:
      return { ...s, steps: upsert(s.steps, data) };

    case EVENTS.MESSAGE:
      return {
        ...s,
        messages: upsert(s.messages, data),
        timeline: addOnce(s.timeline, { type: 'msg', id: data.id }),
      };

    case EVENTS.FLIGHTS_RESULTS:
      return { ...s, search: data.query, flights: data.flights, selection: null };

    case EVENTS.FLIGHTS_SELECTED:
      return { ...s, selection: data };

    case EVENTS.APPROVAL_REQUIRED:
      return { ...s, approval: data, approvalSending: false, tab: 'flights' };   // tab only matters on phones

    case EVENTS.APPROVAL_RESOLVED:
      return s.approval?.approval_id === data.approval_id
        ? { ...s, approval: null, approvalSending: false }
        : s;

    case EVENTS.PASSENGER_REQUIRED:
      return { ...s, passengerRequest: data, approvalSending: false, tab: 'flights' };

    case EVENTS.PASSENGER_RESOLVED:
      return s.passengerRequest?.request_id === data.request_id
        ? { ...s, passengerRequest: null, approvalSending: false }
        : s;

    case EVENTS.BOOKING_UPDATED:
      return { ...s, booking: data, showFlights: false };

    case EVENTS.PAYMENT_UPDATED:
      return { ...s, payment: data };

    case EVENTS.ERROR: {
      const id = `error-${event.id ?? Date.now()}`;
      return {
        ...s,
        approvalSending: false,
        messages: [...s.messages, { id, role: 'system', text: data.message }],
        timeline: [...s.timeline, { type: 'msg', id }],
      };
    }

    // ---- local UI events ----------------------------------------------
    case 'ui/thread':
      return { ...s, threadId: data };

    case 'ui/connection':
      return { ...s, connection: data };

    case 'ui/sort':
      return { ...s, sort: data };

    case 'ui/approval_sending':
      return { ...s, approvalSending: data };

    case 'ui/tab':
      return { ...s, tab: data };

    case 'ui/show_flights':
      return { ...s, showFlights: data };

    default:
      console.warn('Unknown event', type);
      return s;
  }
}

function addOnce(timeline, item) {
  return timeline.some((t) => t.type === item.type && t.id === item.id) ? timeline : [...timeline, item];
}

/** Replace the item with the same key (merging fields) or append it. */
function upsert(list, item, key = 'id') {
  const index = list.findIndex((existing) => existing[key] === item[key]);
  if (index === -1) return [...list, item];

  const copy = list.slice();
  copy[index] = { ...copy[index], ...item };
  return copy;
}
