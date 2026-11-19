/**
 * h('div', { class: 'card', onClick: fn }, 'text', childNode)
 * Text is always inserted as text (never innerHTML) -> LLM output can't inject HTML.
 */
export function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);

  for (const [key, value] of Object.entries(props ?? {})) {
    if (value == null || value === false) continue;
    if (key === 'class') el.className = value;
    else if (key === 'dataset') Object.assign(el.dataset, value);
    else if (key.startsWith('on')) el.addEventListener(key.slice(2).toLowerCase(), value);
    else el.setAttribute(key, value === true ? '' : value);
  }

  for (const child of children.flat()) {
    if (child == null || child === false) continue;
    el.append(child instanceof Node ? child : String(child));
  }
  return el;
}

/** SVG elements need a namespace. */
export function svg(tag, attrs = {}, ...children) {
  const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, value);
  for (const child of children.flat()) if (child) el.append(child);
  return el;
}

/** Re-run a CSS animation class even if it is already applied. */
export function replay(el, className) {
  el.classList.remove(className);
  void el.offsetWidth; // force reflow
  el.classList.add(className);
}

export function panelHead(index, title, ...right) {
  return h('header', { class: 'panel-head' },
    h('div', { class: 'panel-title' },
      h('span', { class: 'panel-index' }, index),
      h('span', {}, title),
    ),
    h('div', { class: 'panel-head-right' }, ...right),
  );
}
