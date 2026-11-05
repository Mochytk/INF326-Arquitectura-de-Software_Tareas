import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { urls } from '../src/upstream.js';
import { yoga } from '../src/server.js';

// Un único upstream simulado atiende a todos los servicios y cuenta sus llamadas.
const AUTHORS = ['u1', 'u2', 'u3'];
const messages = Array.from({ length: 12 }, (_, i) => ({
  id: `m${i}`, channel_id: 'c1', author_id: AUTHORS[i % 3], content: i < 6 ? 'ver https://example.com/a' : `hola ${i}`,
  created_at: `2026-01-01T00:00:${String(i).padStart(2, '0')}Z`,
}));
const hits = {};
let mock;
let uploaded;

before(async () => {
  mock = createServer((req, res) => {
    const { pathname } = new URL(req.url, 'http://mock');
    const key = pathname.endsWith('/reactions') ? 'reactions' : pathname.replace(/\/[^/]*$/, '/*');
    hits[key] = (hits[key] ?? 0) + 1;
    const json = (body, status = 200) => res.writeHead(status, { 'content-type': 'application/json' }).end(JSON.stringify(body));
    if (req.method === 'POST' && pathname === '/api/v1/channels/c1/attachments') {
      const chunks = [];
      return req.on('data', (c) => chunks.push(c)).on('end', () => {
        uploaded = { user: req.headers['x-user-id'], body: Buffer.concat(chunks).toString() };
        json({ id: 'a1', category: 'DOCUMENT', filename: 'nota.txt', mime_type: 'text/plain', size_bytes: 5, uploader_id: 'u1', created_at: '2026-01-01T00:00:00Z' }, 201);
      });
    }
    if (pathname === '/api/v1/channels/c1/messages') return json(messages);
    if (pathname === '/api/v1/channels/c1') return json({ id: 'c1', name: 'general' });
    if (pathname.startsWith('/api/v1/users/')) return json({ id: pathname.split('/').pop(), display_name: `Usuario ${pathname.split('/').pop()}` });
    if (pathname.endsWith('/reactions')) return json({ message_id: 'x', total_reactions: 1, summary: [{ reaction_type: 'like', count: 1 }],
      reactions: [{ id: 'r1', message_id: 'x', user_id: 'u1', reaction_type: 'like', created_at: '2026-01-01T00:00:00Z' }] });
    if (pathname === '/api/v1/links/preview') return json({ url: 'https://example.com/a', title: 'Ejemplo' });
    if (pathname === '/api/v1/search/messages') return json({ total_results: 1, messages: [{ ...messages[0], highlights: ['**ver**'] }] });
    return json({ detail: 'no existe' }, 404);
  });
  await new Promise((resolve) => mock.listen(0, resolve));
  const base = `http://127.0.0.1:${mock.address().port}`;
  for (const name of Object.keys(urls)) urls[name] = base;
});

after(() => mock.close());

const run = async (query, headers = {}) => {
  const response = await yoga.fetch('http://gateway/graphql', {
    method: 'POST', headers: { 'content-type': 'application/json', ...headers }, body: JSON.stringify({ query }),
  });
  return response.json();
};

const NESTED = `{ channel(id: "c1") { name messages(limit: 12) {
  id author { displayName } reactions { total counts { type count } } previews { title } } } }`;

test('una consulta anidada pide cada recurso una sola vez (sin N+1)', async () => {
  Object.keys(hits).forEach((k) => delete hits[k]);
  const { data, errors } = await run(NESTED, { 'x-user-id': 'u1' });
  assert.equal(errors, undefined);
  assert.equal(data.channel.messages.length, 12);
  assert.equal(data.channel.messages[0].author.displayName, 'Usuario u1');
  assert.equal(data.channel.messages[0].previews[0].title, 'Ejemplo');
  assert.equal(hits['/api/v1/users/*'], 3, '12 mensajes, 3 autores distintos => 3 llamadas a users');
  assert.equal(hits['/api/v1/links/*'], 1, '6 mensajes con la misma URL => 1 preview');
  assert.equal(hits.reactions, 12, 'reacciones: una por mensaje (no hay endpoint por lote), nunca repetidas');
});

test('si Reacciones cae, el resto de la consulta responde y el error queda localizado', async () => {
  const original = urls.reactions;
  urls.reactions = 'http://127.0.0.1:1';
  const { data, errors } = await run(NESTED, { 'x-user-id': 'u1' });
  urls.reactions = original;
  assert.equal(data.channel.messages.length, 12);
  assert.equal(data.channel.messages[0].reactions, null);
  assert.equal(data.channel.messages[0].author.displayName, 'Usuario u1');
  assert.equal(errors[0].extensions.code, 'UPSTREAM_UNAVAILABLE');
  assert.equal(errors[0].extensions.service, 'reactions');
});

test('las llamadas a Media sin X-User-Id se rechazan', async () => {
  const { errors } = await run('{ channel(id: "c1") { quota { usedBytes } } }');
  assert.equal(errors[0].extensions.code, 'UNAUTHENTICATED');
});

test('la búsqueda devuelve resultados con highlights y el autor resuelto', async () => {
  const { data, errors } = await run('{ search(content: "ver") { total messages { highlights author { displayName } } } }');
  assert.equal(errors, undefined);
  assert.equal(data.search.total, 1);
  assert.deepEqual(data.search.messages[0].highlights, ['**ver**']);
  assert.equal(data.search.messages[0].author.displayName, 'Usuario u1');
});

test('la subida multipart llega a Media con el archivo y el X-User-Id', async () => {
  const form = new FormData();
  form.append('operations', JSON.stringify({
    query: 'mutation($file: File!) { uploadAttachment(channelId: "c1", file: $file) { id filename downloadUrl uploader { displayName } } }',
    variables: { file: null },
  }));
  form.append('map', JSON.stringify({ 0: ['variables.file'] }));
  form.append('0', new File(['hola!'], 'nota.txt', { type: 'text/plain' }));
  const response = await yoga.fetch('http://gateway/graphql', { method: 'POST', headers: { 'x-user-id': 'u1' }, body: form });
  const { data, errors } = await response.json();
  assert.equal(errors, undefined);
  assert.equal(data.uploadAttachment.downloadUrl, '/files/a1');
  assert.equal(data.uploadAttachment.uploader.displayName, 'Usuario u1');
  assert.equal(uploaded.user, 'u1');
  assert.match(uploaded.body, /hola!/);
});
