/**
 * Tiny store. One state object, one way to change it (dispatch), many listeners.
 * Listeners get (state, prev) so they can redraw only what changed.
 */
export function createStore(reducer, initialState) {
  let state = initialState;
  const listeners = new Set();

  return {
    getState: () => state,

    dispatch(event) {
      const prev = state;
      state = reducer(state, event);
      if (state !== prev) listeners.forEach((listener) => listener(state, prev));
    },

    subscribe(listener) {
      listeners.add(listener);
      listener(state, {}); // first render: everything counts as changed
      return () => listeners.delete(listener);
    },
  };
}
