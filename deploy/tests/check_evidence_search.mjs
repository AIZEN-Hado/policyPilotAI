// Exercise case-scoped evidence search using the browser event contract.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

class Element extends EventTarget {
  constructor() {
    super();
    this.children = [];
    this.dataset = {};
    this.textContent = '';
    this.value = '';
  }
  append(...values) { this.children.push(...values); }
  replaceChildren(...values) { this.children = values; }
}

const controls = Object.fromEntries(['form', 'input', 'ul', '[role=status]'].map(key => [key, new Element()]));
const section = new Element();
section.querySelector = selector => controls[selector];
const document = new EventTarget();
document.getElementById = id => id === 'evidence-search' ? section : null;
document.createElement = () => new Element();
let clickCount = 0;
const app = { document, active: null, openEvidenceCitation() { clickCount++; } };
vm.runInNewContext(readFileSync(new URL('../../pilot/static/evidence-search.js', import.meta.url), 'utf8'), app);
const { form, input, ul } = controls;
const status = controls['[role=status]'];

function openCase(id, documents = []) {
  app.active = id ? { id, documents } : null;
  const change = new Event('policy:case');
  change.detail = id ? { id } : null;
  document.dispatchEvent(change);
}
function submit(value) {
  input.value = value;
  input.dispatchEvent(new Event('input'));
  form.dispatchEvent(new Event('submit', { cancelable: true }));
}

const documents = [
  { id: 'policy', filename: 'schedule.pdf', pages: [
    { page: 1, text: 'Plan [A+] room\nrent is capped.' },
    { page: 2, text: ' ' },
  ] },
  { id: 'claim', filename: '<claim>.pdf', pages: [{ page: 3, text: 'ROOM RENT' }] },
];
openCase('case-1', documents);
assert.equal(section.hidden, false);
submit('room rent');
assert.match(status.textContent, /2 matching pages of 2/);
const [link, snippet] = ul.children[0].children;
assert.equal(link.dataset.evidence, 'policy');
assert.equal(link.dataset.page, 1);
assert.equal(snippet.children[1].textContent, 'room\nrent');
assert.equal(ul.children[1].children[0].textContent, '<claim>.pdf · page 3');
openCase('case-1', documents);
assert.equal(ul.children[0].children[0], link, 'poll should preserve result focus');
ul.dispatchEvent(new Event('click'));
assert.equal(clickCount, 1);
submit('[A+]');
assert.match(status.textContent, /1 matching page of 2/);
submit('no such phrase');
assert.match(status.textContent, /No match in 2 readable pages/);
assert.equal(ul.children.length, 0);
submit('room rent');
openCase('case-2', [{ id: 'unread', pages: null }]);
assert.equal(section.hidden, true);
assert.equal(input.value, '');
assert.equal(ul.children.length, 0);
assert.equal(status.textContent, '');
openCase(null);
assert.equal(section.hidden, true);
console.log('PASS: exact phrases, PDF line wraps, literal punctuation, page links, stable polls and case isolation.');
