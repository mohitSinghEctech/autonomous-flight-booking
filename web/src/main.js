/**
 * Wiring only. Data flows one way:
 *
 *   Transport (SSE events) ──> store.dispatch ──> reducer ──> new state ──> components.update
 *        ▲                                                                        │
 *        └──────────────── actions (POST: message / approval / choose) ◄──────────┘
 */
import { API_BASE, THEME } from './config.js';
import { LiveTransport } from './api/transport.js';
import { createStore } from './state/store.js';
import { initialState, reducer } from './state/reducer.js';
import { createTopBar } from './ui/components/topBar.js';
import { createMobileTabs } from './ui/components/mobileTabs.js';
import { createFlightsPane } from './ui/components/flightsPane.js';
import { createChatPane } from './ui/components/chatPane.js';
import { createSettingsPanel } from './ui/components/settingsPanel.js';
import { createPaymentSheet } from './ui/components/paymentSheet.js';
import { createAccountView } from './ui/account/accountView.js';
import { applyTheme, findTheme, initialThemeId } from './theme/theme.js';
import { host } from './host.js';

const theme = applyTheme(initialThemeId(THEME), { persist: false });
let savedThemeId = theme.id;   // the applied one, not a hover preview (Profile shows its name)

// Standalone: no sign-in (see host.js).
const viewer = await host.ready();   // { email } or null

const transport = new LiveTransport(API_BASE, { getToken: host.token });
const store = createStore(reducer, initialState({ mock: false }));

// ---- actions: the only things the UI can ask the backend to do -----------

const actions = {
  // client_id makes a retried POST safe: the server dedupes on it (contract §6)
  send: (text) => run(() => transport.sendMessage(text, crypto.randomUUID())),

  choose: (flightId) => run(() => transport.selectFlight(flightId)),

  decide: (approvalId, decision) => {
    store.dispatch({ type: 'ui/approval_sending', data: true });
    run(() => transport.sendApproval(approvalId, decision));
  },

  sort: (key) => store.dispatch({ type: 'ui/sort', data: key }),

  tab: (name) => store.dispatch({ type: 'ui/tab', data: name }),

  showFlights: (show) => store.dispatch({ type: 'ui/show_flights', data: show }),

  // payment: open the sheet first, then ask the server for a checkout (or reuse the open one)
  pay: () => {
    sheet.open();
    const p = store.getState().payment;
    const reusable = p?.status === 'created' && p.checkout && !(p.checkout.expires_at && Date.parse(p.checkout.expires_at) < Date.now());
    if (!reusable) run(() => transport.startPayment());
  },

  syncPayment: (paymentId) => run(() => transport.syncPayment(paymentId)),

  cancelBooking: () => run(() => transport.cancelBooking()),

  submitPassengers: (requestId, body) => {
    store.dispatch({ type: 'ui/approval_sending', data: true });
    run(() => transport.submitPassengers(requestId, body));
  },
};

async function run(request) {
  try {
    await request();
  } catch (error) {
    store.dispatch({ type: 'error', data: { message: error.message, recoverable: true } });
  }
}

// ---- mount components ----------------------------------------------------

const byId = (id) => document.getElementById(id);

const topBar = createTopBar(byId('topbar'), { links: host.links, onAccount: () => account.open() });

const sheet = createPaymentSheet({
  onPay: actions.pay,
  onSync: actions.syncPayment,
  // offline demo checkout: "Pay" asks the backend to check the order (it answers paid);
  // "declined" sends nothing, so the payment stays open.
  onMockResult: (paymentId, outcome) => { if (outcome === 'paid') actions.syncPayment(paymentId); },
});

const components = [
  topBar,
  createMobileTabs(byId('tabs'), { onTab: actions.tab }),
  createFlightsPane(byId('flights'), {
    onChoose: actions.choose, onSort: actions.sort, onShowFlights: actions.showFlights, onDecide: actions.decide,
    onPay: actions.pay, onSync: actions.syncPayment, onCancel: actions.cancelBooking,
    onPassengers: actions.submitPassengers,
  }),
  createChatPane(byId('chat'), { onSend: actions.send }),
  sheet,
];

for (const component of components) store.subscribe(component.update);

const settings = createSettingsPanel(topBar.settingsAnchor, {
  currentId: theme.id,
  onChange: (id, options) => {
    applyTheme(id, options);
    if (options.persist) savedThemeId = id;
  },
});

// Account area (#account/...): REST only, contract §16 (v1.2, planned — backend not built yet).
const account = createAccountView(byId('account'), {
  api: transport.api,
  viewer,
  links: host.links,
  openTheme: () => settings.open(),
  themeName: () => findTheme(savedThemeId).name,
  chatBooking: () => store.getState().booking,
  payInChat: () => {
    account.close();
    actions.tab('flights');
    actions.pay();
  },
});

// ---- connect -------------------------------------------------------------

const threadId = await transport.openSession();
store.dispatch({ type: 'ui/thread', data: threadId });

transport.connect(
  threadId,
  (event) => store.dispatch(event),
  (connection) => store.dispatch({ type: 'ui/connection', data: connection }),
);

window.atlas = { store, transport }; // handy in DevTools
