import { h } from '../dom.js';
import { isNotAvailable, loadingState, screenHead, writeErrorText } from './shared.js';

/**
 * You: name (GET/PATCH /api/me), email (from the Firebase sign-in, read-only),
 * theme (opens the same ⚙ popover) and sign out (the host's link).
 * Email, theme and sign-out work even before /api/me exists.
 */
export function profileScreen({ api, viewer, links, openTheme, themeName }) {
  const nameBox = h('div', {}, loadingState('Loading your details…'));
  loadName();

  const signOut = links.find((l) => /sign out/i.test(l.label));

  return h('section', { class: 'acct-screen', 'aria-label': 'Profile and settings' },
    screenHead('Profile & settings', 'How ATLAS knows you'),
    h('div', { class: 'acct-card' }, h('h3', { class: 'acct-card-title' }, 'Name'), nameBox),
    h('div', { class: 'acct-card' },
      h('h3', { class: 'acct-card-title' }, 'Email'),
      h('p', { class: 'acct-value' }, viewer?.email ?? 'Not signed in'),
      h('p', { class: 'pane-sub' }, 'From your sign-in. Change it with your Google / Firebase account.')),
    h('div', { class: 'acct-card' },
      h('h3', { class: 'acct-card-title' }, 'Theme'),
      h('div', { class: 'acct-actions' },
        h('span', { class: 'acct-value' }, themeName()),
        h('button', { class: 'chip', type: 'button', onClick: openTheme }, 'Change theme…'))),
    signOut
      ? h('div', { class: 'acct-card' },
          h('h3', { class: 'acct-card-title' }, 'Session'),
          signOut.href
            ? h('a', { class: 'acct-danger acct-link-btn', href: signOut.href }, 'Sign out')
            : h('button', { class: 'acct-danger', type: 'button', onClick: signOut.onClick }, 'Sign out'))
      : null,
  );

  async function loadName() {
    try {
      nameBox.replaceChildren(nameForm(await api.getMe()));
    } catch (error) {
      nameBox.replaceChildren(
        h('p', { class: 'pane-sub', role: 'status' }, isNotAvailable(error)
          ? 'Editing your name needs GET/PATCH /api/me, which the backend doesn\'t have yet (contract v1.2, planned).'
          : error.message));
    }
  }

  function nameForm(me) {
    const message = h('p', { class: 'pf-error', role: 'alert' });
    const done = h('span', { class: 'pane-sub', role: 'status' });
    const save = h('button', { class: 'btn-primary', type: 'submit' }, 'Save');

    const form = h('form', { class: 'acct-form', novalidate: true },
      h('div', { class: 'pf-grid' },
        h('label', { class: 'pf-field' }, h('span', {}, 'First name'),
          h('input', { name: 'given_name', required: true, maxlength: '100', autocomplete: 'given-name', value: me.given_name ?? '' })),
        h('label', { class: 'pf-field' }, h('span', {}, 'Last name'),
          h('input', { name: 'family_name', required: true, maxlength: '100', autocomplete: 'family-name', value: me.family_name ?? '' }))),
      message,
      h('div', { class: 'acct-actions' }, save, done));

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const body = {
        given_name: form.elements.given_name.value.trim(),
        family_name: form.elements.family_name.value.trim(),
      };
      done.textContent = '';
      message.textContent = body.given_name && body.family_name ? '' : 'First and last name are required.';
      if (message.textContent) return;

      save.disabled = true;
      try {
        await api.updateMe(body);
        done.textContent = 'Saved ✓';
      } catch (error) {
        message.textContent = writeErrorText(error, 'PATCH /api/me');
      } finally {
        save.disabled = false;
      }
    });

    return form;
  }
}
