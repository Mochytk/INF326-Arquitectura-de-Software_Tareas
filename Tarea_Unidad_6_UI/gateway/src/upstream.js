import { GraphQLError } from 'graphql';

// En Kubernetes se cambian con el ConfigMap; los valores por defecto son los
// nombres de servicio de docker compose (red `microsvcs`).
export const urls = {
  users: process.env.USERS_URL ?? 'http://users:8000',
  channels: process.env.CHANNELS_URL ?? 'http://channels:8000',
  messages: process.env.MESSAGES_URL ?? 'http://messages:8000',
  search: process.env.SEARCH_URL ?? 'http://search:8000',
  media: process.env.MEDIA_URL ?? 'http://media:8000',
  reactions: process.env.REACTIONS_URL ?? 'http://reactions:8000',
};

const TIMEOUT_MS = Number(process.env.UPSTREAM_TIMEOUT_MS ?? 5000);

const fail = (message, service, code, status) =>
  new GraphQLError(message, { extensions: { code, service, status } });

// Los servicios reportan errores con formas distintas (`detail`, `error.message`).
const errorText = (body) =>
  body?.error?.message ?? (typeof body?.detail === 'string' ? body.detail : body?.message);

/** Llama a un servicio. Un 404 devuelve null si `nullOn404`; el resto de fallos lanza GraphQLError. */
export async function call(service, path, { method = 'GET', userId, json, form, nullOn404 = false } = {}) {
  const headers = {};
  if (userId) headers['x-user-id'] = userId;
  let body = form;
  if (json !== undefined) {
    headers['content-type'] = 'application/json';
    body = JSON.stringify(json);
  }
  let response;
  try {
    response = await fetch(urls[service] + path, { method, headers, body, signal: AbortSignal.timeout(TIMEOUT_MS) });
  } catch {
    throw fail(`El servicio ${service} no está disponible`, service, 'UPSTREAM_UNAVAILABLE');
  }
  if (response.status === 404 && nullOn404) return null;
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw fail(errorText(detail) ?? `${service} respondió ${response.status}`, service, 'UPSTREAM_ERROR', response.status);
  }
  return response.status === 204 ? null : response.json();
}

export const requireUser = (context) => {
  if (!context.userId) {
    throw new GraphQLError('Falta el header X-User-Id', { extensions: { code: 'UNAUTHENTICATED' } });
  }
  return context.userId;
};
