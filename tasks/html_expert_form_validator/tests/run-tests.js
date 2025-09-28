#!/usr/bin/env node
'use strict';

import { createRequire } from 'module';
const require = createRequire(import.meta.url);
const path = require('node:path');
const fs = require('node:fs');

const bannedKeywords = JSON.parse(
  fs.readFileSync(path.join(path.dirname(import.meta.url.replace('file://', '')), 'banned_keywords.json'), 'utf8')
);

const projectRoot = path.join(path.dirname(new URL(import.meta.url).pathname), '..');
const modulePath = path.join(projectRoot, 'workspace', 'static', 'app.js');

const appModule = await import(`file://${modulePath}`);

function createStubDocument() {
  const elements = new Map();

  class Element {
    constructor(id) {
      this.id = id;
      this.value = '';
      this.dataset = {};
      this.attributes = new Map();
      this.children = [];
      this.eventListeners = new Map();
      this.textContent = '';
    }

    setAttribute(name, value) {
      this.attributes.set(name, value);
      if (name === 'role' && value === 'alert') {
        this.role = value;
      }
    }

    getAttribute(name) {
      return this.attributes.get(name);
    }

    appendChild(child) {
      this.children.push(child);
      return child;
    }

    querySelector(selector) {
      if (selector === 'li') {
        return this.children.find((child) => child.tagName === 'LI') || null;
      }
      return null;
    }

    querySelectorAll(selector) {
      if (selector === 'li') {
        return this.children.filter((child) => child.tagName === 'LI');
      }
      return [];
    }

    addEventListener(event, handler) {
      this.eventListeners.set(event, handler);
    }

    dispatchEvent(event) {
      const handler = this.eventListeners.get(event.type);
      if (handler) {
        handler(event);
      }
    }
  }

  elements.set('#registration-form', new Element('registration-form'));
  elements.set('#form-status', new Element('form-status'));

  return {
    querySelector(selector) {
      return elements.get(selector) || null;
    },
    createElement(tagName) {
      const element = new Element(tagName.toLowerCase());
      element.tagName = tagName.toUpperCase();
      return element;
    },
    elements,
  };
}

function simulateSubmit(controller, document, fields) {
  const form = document.querySelector('#registration-form');
  const status = document.querySelector('#form-status');

  const event = {
    type: 'submit',
    preventDefaultCalled: false,
    preventDefault() {
      this.preventDefaultCalled = true;
    },
  };

  form.dispatchEvent(event);
  if (!event.preventDefaultCalled) {
    throw new Error('submit handler should call preventDefault');
  }

  // Provide a basic response to mimic actual validation.
  if (!controller.validateEmail(fields.email)) {
    status.textContent = 'Invalid email';
    status.dataset.status = 'error';
  } else if (!controller.validatePassword(fields.password)) {
    status.textContent = 'Weak password';
    status.dataset.status = 'error';
  } else if (!controller.validateConfirm(fields.password, fields.confirm)) {
    status.textContent = 'Password mismatch';
    status.dataset.status = 'error';
  } else if (!controller.validateInterests(fields.interests)) {
    status.textContent = 'Bad interests';
    status.dataset.status = 'error';
  } else {
    status.textContent = 'Thanks for registering!';
    status.dataset.status = 'success';
  }

  return status;
}

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

async function run() {
  const document = createStubDocument();
  const controller = appModule.createFormController(document, { bannedKeywords });

  let status = simulateSubmit(controller, document, {
    email: 'invalid',
    password: 'Valid$Pass1',
    confirm: 'Valid$Pass1',
    interests: 'Reading and hiking',
  });
  assert(status.dataset.status !== 'success', 'Invalid email should fail');

  status = simulateSubmit(controller, document, {
    email: 'user@example.com',
    password: 'weak',
    confirm: 'weak',
    interests: 'Chess',
  });
  assert(status.dataset.status !== 'success', 'Weak password should fail');

  status = simulateSubmit(controller, document, {
    email: 'alice@example.com',
    password: 'Alice123!',
    confirm: 'Alice123!',
    interests: 'Robotics',
  });
  assert(status.dataset.status !== 'success', 'Password similar to email should fail');

  status = simulateSubmit(controller, document, {
    email: 'user@example.com',
    password: 'Valid$Pass1',
    confirm: 'Valid$Pass1',
    interests: 'I love malware',
  });
  assert(status.dataset.status !== 'success', 'Banned keyword should fail');

  status = simulateSubmit(controller, document, {
    email: 'user@example.com',
    password: 'Valid$Pass1',
    confirm: 'Valid$Pass1',
    interests: 'Hiking and photography',
  });
  assert(status.dataset.status === 'success', 'Valid submission should succeed');

  console.log('All tests passed.');
}

run().catch((error) => {
  console.error(error);
  process.exit(1);
});
