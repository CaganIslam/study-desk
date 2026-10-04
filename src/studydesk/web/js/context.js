// What the input bar talks about: the page that is open registers itself here.
let current = null;

/** page = { payload: () => object, showAnswer: async (answer, idx) => void, handleAction: async (action) => void } */
export function setPage(page) {
  current = page;
}

export function clearPage(page) {
  if (current === page) current = null;
}

export function page() {
  return current;
}
