import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { Readable } from 'node:stream';
import { createYoga } from 'graphql-yoga';
import { schema } from './schema.js';
import { createLoaders } from './loaders.js';
import { urls } from './upstream.js';

export const yoga = createYoga({
  schema,
  graphqlEndpoint: '/graphql',
  // X-User-Id no autentica (igual que en Media): el gateway solo lo reenvía.
  context: ({ request }) => {
    const userId = request.headers.get('x-user-id') ?? undefined;
    return { userId, loaders: createLoaders(userId) };
  },
});

const STATIC = {
  '/': ['index.html', 'text/html; charset=utf-8'],
  '/app.js': ['app.js', 'text/javascript; charset=utf-8'],
  '/style.css': ['style.css', 'text/css; charset=utf-8'],
};

// Media exige X-User-Id, que un <a href> no puede enviar: el gateway hace de proxy.
async function download(req, res, pathname, searchParams) {
  const id = pathname.slice('/files/'.length);
  const userId = req.headers['x-user-id'] ?? searchParams.get('userId');
  const upstream = await fetch(`${urls.media}/api/v1/attachments/${encodeURIComponent(id)}/download`, {
    headers: userId ? { 'x-user-id': userId } : {},
    signal: AbortSignal.timeout(Number(process.env.UPSTREAM_TIMEOUT_MS ?? 5000)),
  }).catch(() => null);
  if (!upstream) return res.writeHead(502).end('media no disponible');
  const headers = {};
  for (const name of ['content-type', 'content-disposition', 'x-content-type-options']) {
    if (upstream.headers.has(name)) headers[name] = upstream.headers.get(name);
  }
  res.writeHead(upstream.status, headers);
  if (upstream.body) Readable.fromWeb(upstream.body).pipe(res);
  else res.end();
}

export const server = createServer(async (req, res) => {
  const { pathname, searchParams } = new URL(req.url, 'http://gateway');
  if (pathname === '/health') return res.writeHead(200, { 'content-type': 'application/json' }).end('{"status":"ok"}');
  if (pathname.startsWith('/files/')) return download(req, res, pathname, searchParams);
  if (STATIC[pathname]) {
    const [file, type] = STATIC[pathname];
    const body = await readFile(new URL(`../public/${file}`, import.meta.url));
    return res.writeHead(200, { 'content-type': type }).end(body);
  }
  return yoga(req, res);
});

if (import.meta.url === `file://${process.argv[1]}`) {
  const port = Number(process.env.PORT ?? 4000);
  server.listen(port, () => console.log(`gateway en http://0.0.0.0:${port}/graphql`));
}
