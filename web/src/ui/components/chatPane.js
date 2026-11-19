import { quickReplies, turnSteps } from '../../state/selectors.js';
import { h } from '../dom.js';
import { elapsed } from '../format.js';

const IDLE_HINT = 'Ask for flights, or change your plans…';

const STEP_ICON = { done: '✓', running: '', waiting: '⏸', failed: '✕', skipped: '–' };

/**
 * Right pane: the conversation — for NEW requests only (search, change of plan).
 * Actions (approve, pay, cancel…) are buttons in the flights pane.
 * Input is locked while ATLAS is working: one turn at a time.
 * Agent steps live inside the chat, right where they happened:
 *   live turn  -> open list with spinner
 *   past turn  -> one line "✓ 6 steps · 4.2s", tap to open
 */
export function createChatPane(root, { onSend }) {
  const timeline = h('div', { class: 'timeline', role: 'log', 'aria-live': 'polite' });
  const scroller = h('div', { class: 'chat-scroll' }, timeline);
  const quick = h('div', { class: 'quick' });

  const input = h('textarea', { class: 'composer-input', rows: '1', placeholder: IDLE_HINT, 'aria-label': 'Message ATLAS' });
  const sendBtn = h('button', { class: 'send', type: 'submit', 'aria-label': 'Send' }, '↑');
  const form = h('form', { class: 'composer' }, input, sendBtn);

  root.append(
    h('header', { class: 'pane-head' },
      h('div', {},
        h('h2', { class: 'pane-title' }, 'Chat'),
        h('p', { class: 'pane-sub' }, 'Ask for flights or change your plans'))),
    scroller, quick, form,
  );

  let locked = false;
  const send = (text) => {
    const value = text.trim();
    if (!value || locked) return;
    onSend(value);
    input.value = '';
    autosize();
  };
  const autosize = () => {
    input.style.height = 'auto';
    input.style.height = `${Math.min(input.scrollHeight, 140)}px`;
  };
  form.addEventListener('submit', (e) => { e.preventDefault(); send(input.value); input.focus(); });
  input.addEventListener('input', autosize);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input.value); }
  });

  // live timers on running turns
  setInterval(() => {
    for (const el of timeline.querySelectorAll('.activity.is-live [data-start]')) el.textContent = elapsed(el.dataset.start);
  }, 200);

  const items = new Map();         // "msg:m1" | "turn:t1" -> element
  const opened = new Set();        // turns the user expanded

  function nearBottom() {
    return scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 80;
  }
  function toBottom() {
    requestAnimationFrame(() => scroller.scrollTo({ top: scroller.scrollHeight, behavior: 'smooth' }));
  }

  return { update };

  function update(state, prev) {
      const stick = nearBottom();
      let grew = false;

      if (state.timeline !== prev.timeline || state.messages !== prev.messages) {
        for (const item of state.timeline) {
          const key = `${item.type}:${item.id}`;
          if (items.has(key)) continue;
          const el = item.type === 'msg'
            ? bubble(state.messages.find((m) => m.id === item.id))
            : h('div', { class: 'activity', dataset: { turn: item.id } });
          if (!el) continue;
          items.set(key, el);
          timeline.append(el);
          grew = true;
        }
        if (state.timeline.length < items.size) {   // snapshot replaced history
          timeline.replaceChildren(); items.clear();
          return update(state, { ...prev, timeline: [] });
        }
      }

      if (state.steps !== prev.steps || state.status !== prev.status || state.timeline !== prev.timeline) {
        const liveTurn = state.status.busy ? lastTurn(state) : null;
        for (const item of state.timeline) {
          if (item.type !== 'turn') continue;
          renderActivity(items.get(`turn:${item.id}`), state, item.id, item.id === liveTurn, opened);
        }
      }

      // one turn at a time: no typing while ATLAS works
      const busy = state.status.busy || state.approvalSending || state.connection !== 'online';
      if (busy !== locked) {
        locked = busy;
        input.disabled = busy;
        sendBtn.disabled = busy;
        form.classList.toggle('is-locked', busy);
      }
      input.placeholder = state.connection !== 'online' ? 'Connecting…'
        : busy ? 'ATLAS is working — you can type when it finishes'
        : state.approval || state.passengerRequest ? 'Or ask for something different…'
        : IDLE_HINT;

      const replies = quickReplies(state);
      if (replies.join('|') !== quick.dataset.key) {
        quick.dataset.key = replies.join('|');
        quick.replaceChildren(...replies.map((text) =>
          h('button', { class: 'chip', type: 'button', onClick: () => send(text) }, text)));
      }

      if (grew || stick) toBottom();
  }
}

// ---- pieces -------------------------------------------------------------------

function bubble(message) {
  if (!message) return null;
  if (message.role === 'system') return h('div', { class: 'msg msg-system' }, message.text);

  return h('div', { class: `msg msg-${message.role}` },
    message.role === 'assistant' ? h('span', { class: 'avatar', 'aria-hidden': 'true' }, '✦') : null,
    h('div', { class: 'bubble' }, message.text),
  );
}

function renderActivity(el, state, turnId, live, opened) {
  if (!el) return;
  const steps = turnSteps(state, turnId);
  const waiting = steps.some((s) => s.status === 'waiting');

  if (!steps.length && !live) { el.hidden = true; return; }
  el.hidden = false;

  const running = steps.find((s) => s.status === 'running');
  const first = steps[0]?.started_at;
  const last = steps.at(-1)?.ended_at;
  const isOpen = live || opened.has(turnId);

  el.className = `activity ${live ? 'is-live' : ''} ${waiting && !live ? 'is-waiting' : ''} ${isOpen ? 'is-open' : ''}`;

  const label = live
    ? (running?.title ?? state.status.text)
    : waiting ? 'Paused — waiting for your OK'
    : `${steps.length} step${steps.length === 1 ? '' : 's'}`;

  const head = h('button', {
    class: 'act-head', type: 'button', 'aria-expanded': String(isOpen),
    onClick: () => {
      if (live) return;
      opened.has(turnId) ? opened.delete(turnId) : opened.add(turnId);
      renderActivity(el, state, turnId, live, opened);
    },
  },
    h('span', { class: 'act-icon' }, live ? h('span', { class: 'spinner' }) : waiting ? '⏸' : '✓'),
    h('span', { class: 'act-label' }, label),
    first ? h('span', { class: 'act-time', dataset: live ? { start: first } : {} }, elapsed(first, live ? null : last)) : null,
    live ? null : h('span', { class: 'act-chevron', 'aria-hidden': 'true' }, '›'),
  );

  const list = isOpen
    ? h('ol', { class: 'act-steps' }, ...steps.map((s) => h('li', { class: `astep is-${s.status}` },
        h('span', { class: 'astep-icon' }, s.status === 'running' ? h('span', { class: 'spinner sm' }) : STEP_ICON[s.status] ?? '•'),
        h('div', { class: 'astep-body' },
          h('span', { class: 'astep-title' }, s.title),
          s.detail ? h('small', {}, s.detail) : null,
          s.tool ? h('code', {}, s.tool) : null),
        h('span', { class: 'astep-time' }, s.started_at ? elapsed(s.started_at, s.ended_at) : ''))))
    : null;

  el.replaceChildren(head, list ?? '');
}

function lastTurn(state) {
  for (let i = state.timeline.length - 1; i >= 0; i--) {
    if (state.timeline[i].type === 'turn') return state.timeline[i].id;
  }
  return null;
}
