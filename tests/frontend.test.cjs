const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');

// DOM mínimo, sem bibliotecas ou navegador: executa o app.js real e controla
// a ordem das respostas HTTP para reproduzir corridas de forma determinística.
class Element {
  constructor() {
    this.children = [];
    this.attributes = {};
    this.listeners = {};
    this.dataset = {};
    this.className = '';
    this.textContent = '';
    this.value = '';
    this.namespaceURI = 'http://www.w3.org/2000/svg';
    this.classList = {
      contains: (name) => this.className.split(' ').includes(name),
      toggle: (name, enabled) => {
        const names = new Set(this.className.split(' ').filter(Boolean));
        if (enabled) names.add(name); else names.delete(name);
        this.className = [...names].join(' ');
      },
      remove: (name) => this.classList.toggle(name, false),
      add: (name) => this.classList.toggle(name, true),
    };
  }
  get lastElementChild() { return this.children.at(-1); }
  setAttribute(name, value) { this.attributes[name] = value; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  focus() {}
}
const response = (data) => ({ ok: true, json: async () => data });
const deferred = () => {
  let complete;
  const promise = new Promise((resolve) => { complete = resolve; });
  return { promise, complete };
};
const memoryStorage = () => {
  const values = new Map();
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  };
};
const documentData = (id) => ({
  id, filename: `${id}.png`, duration_seconds: 1, preprocess: false, page_count: 2,
  pages: [1, 2].map((number) => ({
    number, width: 200, height: 300, text: `Página ${number}`, image_url: `/${id}/${number}.png`,
  })),
});
const boxes = [[[10, 10], [100, 10], [100, 30], [10, 30]]];
const hit = (id) => ({
  id: `hit-${id}`, document_id: id, filename: `${id}.png`, page: 1,
  text: `Trecho ${id}`, score: 0.02, boxes,
});

async function app(fetcher, localStorage) {
  const nodes = new Map();
  const modes = ['hybrid', 'semantic', 'tfidf'].map((mode) => {
    const node = new Element();
    node.dataset.mode = mode;
    return node;
  });
  const element = (selector) => {
    if (!nodes.has(selector)) nodes.set(selector, new Element());
    return nodes.get(selector);
  };
  const document = {
    querySelector: element,
    querySelectorAll: (selector) => {
      if (selector === '.mode') return modes;
      if (selector === '[data-query]') return [];
      const all = [];
      const visit = (node) => { all.push(node); for (const child of node.children || []) visit(child); };
      for (const node of nodes.values()) visit(node);
      return all.filter((node) => node.className?.split(' ').includes(selector.slice(1)));
    },
    createElement: () => new Element(),
    createElementNS: () => new Element(),
    createTextNode: (text) => ({ textContent: text }),
  };
  const context = vm.createContext({
    document, AbortController, localStorage,
    fetch: (url, options) => url === '/documents' ? Promise.resolve(response([])) : fetcher(url, options),
  });
  vm.runInContext(readFileSync(resolve(__dirname, '../static/app.js'), 'utf8'), context);
  await new Promise(setImmediate); // Finaliza loadLibrary inicial.
  return { element, run: (code) => vm.runInContext(code, context) };
}

test('prévia atrasada não restaura destaques depois de uma busca vazia', async () => {
  const pending = deferred();
  const ui = await app((url) => url === '/search' ? response({ results: [] }) : pending.promise);
  const old = ui.run(`openDocument('A', 1, ${JSON.stringify(boxes)}, 'hit-A')`);
  ui.element('#query').value = 'consulta sem resposta';
  await ui.run('search()');
  pending.complete(response(documentData('A')));
  await old;
  assert.equal(ui.element('#highlights').children.length, 0);
  assert.notEqual(ui.element('#preview-subtitle').textContent, 'A.png');
});

test('uma nova busca vence a resposta atrasada da busca anterior', async () => {
  const pending = deferred();
  const ui = await app((url, options) => {
    if (url.startsWith('/documents/')) return response(documentData(url.split('/').at(-1)));
    return JSON.parse(options.body).query === 'antiga' ? pending.promise : response({ results: [hit('B')] });
  });
  ui.element('#query').value = 'antiga';
  const old = ui.run('search()');
  ui.element('#query').value = 'nova';
  await ui.run('search()');
  pending.complete(response({ results: [hit('A')] }));
  await old;
  assert.equal(ui.element('#results-subtitle').textContent, '“nova” · Híbrida');
  assert.equal(ui.element('#preview-subtitle').textContent, 'B.png');
});

test('seleção manual da biblioteca não é sobrescrita por busca pendente', async () => {
  const pending = deferred();
  const ui = await app((url) => url === '/search' ? pending.promise : response(documentData('B')));
  ui.element('#query').value = 'tema';
  const search = ui.run('search()');
  await ui.run(`openDocument('B')`);
  pending.complete(response({ results: [hit('A')] }));
  await search;
  assert.equal(ui.element('#preview-subtitle').textContent, 'B.png');
  assert.equal(ui.element('#highlights').children.length, 0);
});

test('mudar página invalida uma prévia anterior ainda em trânsito', async () => {
  const pending = deferred();
  const ui = await app((url) => url.endsWith('/A') ? pending.promise : response(documentData('B')));
  await ui.run(`openDocument('B')`);
  const old = ui.run(`openDocument('A')`);
  ui.element('#page-select').listeners.change({ target: { value: '2' } });
  pending.complete(response(documentData('A')));
  await old;
  assert.equal(ui.element('#page-image').src, '/B/2.png');
});

test('finally de requisição velha não reativa controles da nova busca', async () => {
  const first = deferred();
  const second = deferred();
  const ui = await app((url, options) => JSON.parse(options.body).query === 'antiga' ? first.promise : second.promise);
  ui.element('#query').value = 'antiga';
  const old = ui.run('search()');
  ui.element('#query').value = 'nova';
  const latest = ui.run('search()');
  first.complete(response({ results: [] }));
  await old;
  assert.equal(ui.element('#search-button').disabled, true);
  second.complete(response({ results: [] }));
  await latest;
  assert.equal(ui.element('#search-button').disabled, false);
});

test('texto de documento é exibido literalmente, sem virar HTML', async () => {
  const text = '<img src=x onerror="alert(1)">';
  const ui = await app((url) => url === '/search'
    ? response({ results: [{ ...hit('A'), text }] })
    : response(documentData('A')));
  ui.element('#query').value = 'tema';
  await ui.run('search()');
  const card = ui.element('#results').children[0];
  assert.equal(card.children[1].textContent, text);
  assert.equal(card.children[1].children.length, 0);
});

test('editar consulta cancela busca pendente e impede resposta antiga', async () => {
  const pending = deferred();
  let signal;
  const ui = await app((url, options) => { signal = options.signal; return pending.promise; });
  ui.element('#query').value = 'antiga';
  const old = ui.run('search()');
  ui.element('#query').value = 'nova';
  ui.element('#query').listeners.input();
  assert.equal(signal.aborted, true);
  assert.equal(ui.element('#search-button').disabled, false);
  pending.complete(response({ results: [hit('A')] }));
  await old;
  assert.equal(ui.element('#highlights').children.length, 0);
  assert.notEqual(ui.element('#preview-subtitle').textContent, 'A.png');
});

test('consulta em branco invalida requisição anterior e libera controles', async () => {
  const pending = deferred();
  const ui = await app(() => pending.promise);
  ui.element('#query').value = 'antiga';
  const old = ui.run('search()');
  ui.element('#query').value = '   ';
  await ui.run('search()');
  pending.complete(response({ results: [hit('A')] }));
  await old;
  assert.equal(ui.element('#search-button').disabled, false);
  assert.equal(ui.element('#highlights').children.length, 0);
});

test('ajustes de consulta ficam visíveis sem substituir a consulta original', async () => {
  const interpreted = '<img src=x onerror="alert(1)">';
  const ui = await app(() => response({ results: [], interpreted_query: interpreted, excluded_terms: ['ar-condicionado'] }));
  ui.element('#query').value = 'Não quero ar-condicionado: preciso de luvas';
  await ui.run('search()');
  assert.equal(ui.element('#query').value, 'Não quero ar-condicionado: preciso de luvas');
  const note = ui.element('#results-subtitle').children[0];
  assert.equal(note.className, 'query-adjustment');
  assert.equal(note.textContent, `Busca ajustada: “${interpreted}”.`);
  assert.equal(note.children[0].textContent, ' Tema excluído: ar-condicionado.');
});

test('buscas concluídas podem ser reutilizadas ou limpas', async () => {
  const storage = memoryStorage();
  const ui = await app(() => response({ results: [] }), storage);
  ui.element('#query').value = 'consulta recente';
  await ui.run('search()');

  assert.deepEqual(
    JSON.parse(storage.getItem('doclens.recent-searches')),
    ['consulta recente'],
  );
  assert.equal(ui.element('#recent-searches').hidden, false);
  assert.equal(ui.element('#recent-search-list').children[0].textContent, 'consulta recente');

  ui.element('#clear-recent-searches').listeners.click();
  assert.equal(storage.getItem('doclens.recent-searches'), null);
  assert.equal(ui.element('#recent-searches').hidden, true);
});
