const defaultOptions = {
  bannedKeywords: [],
};

export function createFormController(document, options = {}) {
  const { bannedKeywords } = { ...defaultOptions, ...options };
  const form = document.querySelector('#registration-form');
  const status = document.querySelector('#form-status');
  if (!form || !status) {
    throw new Error('Missing form or status element');
  }

  const state = {
    lastSuccessAt: 0,
  };

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    status.textContent = 'Form submitted';
    status.dataset.status = 'info';
  });

  return {
    validateEmail: (value) => value.includes('@'),
    validatePassword: (value) => value.length >= 6,
    validateConfirm: (password, confirm) => password === confirm,
    validateInterests: (text) => text.length <= 200 && !bannedKeywords.some((word) => text.includes(word)),
    getState: () => ({ ...state }),
  };
}

if (typeof window !== 'undefined') {
  const document = window.document;
  if (document) {
    createFormController(document);
  }
}
