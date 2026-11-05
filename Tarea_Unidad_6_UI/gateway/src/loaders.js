import DataLoader from 'dataloader';
import { call } from './upstream.js';

const CONCURRENCY = 8;

// Ningún servicio ofrece un endpoint por lote, así que el lote de DataLoader
// (todas las llaves pedidas en un mismo tick, sin repetidas) se despacha en
// paralelo acotado. Una llave que falla devuelve un Error solo para ella.
async function batch(keys, fetchOne) {
  const results = [];
  for (let i = 0; i < keys.length; i += CONCURRENCY) {
    const chunk = keys.slice(i, i + CONCURRENCY);
    results.push(...(await Promise.all(chunk.map((key) => fetchOne(key).catch((error) => error)))));
  }
  return results;
}

const enc = encodeURIComponent;

/** Un juego de loaders por request: la caché no sobrevive entre consultas. */
export function createLoaders(userId) {
  const loader = (fetchOne) => new DataLoader((keys) => batch(keys, fetchOne));
  return {
    user: loader((id) => call('users', `/api/v1/users/${enc(id)}`, { nullOn404: true })),
    channel: loader((id) => call('channels', `/api/v1/channels/${enc(id)}`, { nullOn404: true })),
    reactions: loader((id) => call('reactions', `/api/v1/messages/${enc(id)}/reactions`, { nullOn404: true })),
    // Sin preview todavía (404): el mensaje se muestra igual, sin tarjeta.
    preview: loader((url) => call('media', `/api/v1/links/preview?url=${enc(url)}`, { userId, nullOn404: true })),
  };
}
