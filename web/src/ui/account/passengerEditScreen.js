import { h } from '../dom.js';
import { passengerFields, readPassenger, validatePassengers } from '../components/passengerForm.js';
import { ROUTES, errorState, fullName, loadingState, screenHead, writeErrorText } from './shared.js';

/**
 * Add (id = null) or view/edit/delete one passenger.
 *   GET /api/passengers/{id} · POST /api/passengers · PATCH /api/passengers/{id} · DELETE /api/passengers/{id}
 * Same fields and client-side rules as the chat's passenger form; the server validates again
 * (incl. "does this phone number exist") and its message is shown under the form.
 */
export function passengerEditScreen({ api, id, go }) {
  const body = h('div', { class: 'acct-body' }, id ? loadingState('Loading passenger…') : null);

  if (id) load();
  else body.replaceChildren(form(null));

  return h('section', { class: 'acct-screen', 'aria-label': id ? 'Passenger details' : 'Add passenger' },
    h('a', { class: 'acct-back', href: ROUTES.passengers }, '← All passengers'),
    body);

  async function load() {
    try {
      body.replaceChildren(form(await api.getPassenger(id)));
    } catch (error) {
      body.replaceChildren(errorState(error, `GET /api/passengers/${id}`, () => {
        body.replaceChildren(loadingState());
        load();
      }));
    }
  }

  function form(passenger) {
    const message = h('p', { class: 'pf-error', role: 'alert' });
    const save = h('button', { class: 'btn-primary', type: 'submit' }, passenger ? 'Save changes' : 'Add passenger');
    const remove = passenger
      ? h('button', { class: 'acct-danger', type: 'button', onClick: () => destroy(passenger, remove, message) }, 'Delete')
      : null;

    const el = h('form', { class: 'pf-form acct-form', novalidate: true },
      screenHead(passenger ? fullName(passenger) : 'New passenger',
        passenger ? usedIn(passenger) : 'All fields are needed by the airline.'),
      h('fieldset', { class: 'pf-person' }, h('legend', {}, 'Travel details'), passengerFields(passenger ?? {})),
      message,
      h('div', { class: 'acct-actions' }, save, h('a', { class: 'chip', href: ROUTES.passengers }, 'Cancel'), remove),
    );

    el.addEventListener('submit', async (event) => {
      event.preventDefault();
      const values = readPassenger(el);
      const problem = validatePassengers([values]);
      message.textContent = problem ?? '';
      if (problem) return;

      save.disabled = true;
      try {
        const saved = passenger ? await api.updatePassenger(passenger.id, values) : await api.createPassenger(values);
        go(ROUTES.passenger(saved.id));
        if (passenger) message.textContent = '';          // same route: the screen reloads itself
      } catch (error) {
        const endpoint = passenger ? `PATCH /api/passengers/${passenger.id}` : 'POST /api/passengers';
        message.textContent = writeErrorText(error, endpoint);
      } finally {
        save.disabled = false;
      }
    });

    return el;
  }

  async function destroy(passenger, button, message) {
    if (!window.confirm(`Delete ${fullName(passenger)}? Bookings keep their own copy of these details.`)) return;

    button.disabled = true;
    message.textContent = '';
    try {
      await api.deletePassenger(passenger.id);
      go(ROUTES.passengers);
    } catch (error) {
      // 409 passenger_in_use: on a booking that is still held / awaiting payment
      message.textContent = writeErrorText(error, `DELETE /api/passengers/${passenger.id}`);
      button.disabled = false;
    }
  }
}

function usedIn(p) {
  const n = p.booking_count ?? 0;
  return n ? `On ${n} booking${n === 1 ? '' : 's'}` : 'Not on any booking yet';
}
