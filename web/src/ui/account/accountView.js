import { h } from '../dom.js';
import { bookingDetailScreen } from './bookingDetailScreen.js';
import { bookingsScreen } from './bookingsScreen.js';
import { passengerEditScreen } from './passengerEditScreen.js';
import { passengersScreen } from './passengersScreen.js';
import { profileScreen } from './profileScreen.js';
import { ROUTES, parseRoute } from './shared.js';

/**
 * The account area: Bookings · Passengers · Profile.
 *
 * It sits next to the chat workspace and replaces it while open (.app[data-view='account']).
 * The URL hash is the router (#account/bookings/<id> …), so Back works and screens can be linked.
 * Screens fetch their own data each time they open; nothing goes into the chat store,
 * because this data is plain request/response, not SSE events.
 *
 * ctx = { api, viewer, links, openTheme, themeName, chatBooking, payInChat }
 */
export function createAccountView(root, ctx) {
  const app = document.querySelector('.app');

  const navLinks = [
    ['bookings', 'Bookings', ROUTES.bookings],
    ['passengers', 'Passengers', ROUTES.passengers],
    ['profile', 'Profile', ROUTES.profile],
  ].map(([section, label, href]) => h('a', { class: 'tab', href, dataset: { section } }, label));

  const outlet = h('div', { class: 'acct-outlet' });

  root.append(
    h('div', { class: 'acct-bar' },
      h('button', { class: 'chip', type: 'button', onClick: close }, '← Back to chat'),
      h('nav', { class: 'acct-nav', 'aria-label': 'Account sections' }, ...navLinks)),
    outlet);

  window.addEventListener('hashchange', render);
  render();

  /** Navigate. Re-renders even when the hash doesn't change (e.g. after saving). */
  function go(hash) {
    if (location.hash === hash) render();
    else location.hash = hash;
  }

  function close() {
    // drop the hash without leaving a "#" behind; pushState doesn't fire hashchange, so render by hand
    history.pushState(null, '', location.pathname + location.search);
    render();
  }

  function render() {
    const route = parseRoute(location.hash);
    app.dataset.view = route ? 'account' : 'chat';
    if (!route) return outlet.replaceChildren();

    const section = route.screen.startsWith('passenger') || route.screen === 'newPassenger' ? 'passengers'
      : route.screen === 'profile' ? 'profile' : 'bookings';
    for (const link of navLinks) {
      const active = link.dataset.section === section;
      link.classList.toggle('is-active', active);
      if (active) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    }

    outlet.replaceChildren(screenFor(route));
    // move focus to the new screen's title, so keyboard and screen-reader users land on it
    (outlet.querySelector('.acct-title') ?? outlet.querySelector('a, button'))?.focus({ preventScroll: true });
    root.scrollTop = 0;
  }

  function screenFor(route) {
    const shared = { ...ctx, go, close };
    switch (route.screen) {
      case 'booking': return bookingDetailScreen({ ...shared, id: route.id });
      case 'passengers': return passengersScreen(shared);
      case 'newPassenger': return passengerEditScreen({ ...shared, id: null });
      case 'passenger': return passengerEditScreen({ ...shared, id: route.id });
      case 'profile': return profileScreen(shared);
      default: return bookingsScreen(shared);
    }
  }

  return {
    open: (hash = ROUTES.bookings) => go(hash),
    close,
  };
}
