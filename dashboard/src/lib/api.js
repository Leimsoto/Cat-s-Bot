/**
 * lib/api.js
 * Cliente HTTP con caché TTL y deduplicación de peticiones.
 * Conectado al backend FastAPI en /api/
 */

const getCache = new Map();
const pendingGets = new Map();
const MAX_GET_CACHE_ENTRIES = 120;

const ttlByPath = [
  [/\/api\/guilds\/[^/]+\/commands$/, 5 * 60_000],
  [/\/api\/guilds\/[^/]+\/config$/, 30_000],
  [/\/api\/guilds\/[^/]+\/music$/, 5_000],
  [/\/api\/guilds\/[^/]+\/overview$/, 20_000],
  [/\/api\/guilds\/[^/]+\/ia$/, 30_000],
  [/\/api\/guilds\/[^/]+\/moderation$/, 30_000],
  [/\/api\/guilds\/[^/]+\/levels$/, 30_000],
  [/\/api\/guilds\/[^/]+\/levels\/rewards$/, 30_000],
  [/\/api\/guilds\/[^/]+\/tickets$/, 30_000],
  [/\/api\/guilds\/[^/]+\/radio$/, 30_000],
  [/\/api\/guilds\/[^/]+\/channels$/, 5 * 60_000],
  [/\/api\/guilds\/[^/]+\/roles$/, 5 * 60_000],
  [/\/api\/guilds$/, 60_000],
];

function getTtl(path) {
  return ttlByPath.find(([pattern]) => pattern.test(path))?.[1] ?? 15_000;
}

function pruneGetCache() {
  const now = Date.now();
  for (const [key, cached] of getCache) {
    if (cached.expiresAt <= now) getCache.delete(key);
  }

  while (getCache.size > MAX_GET_CACHE_ENTRIES) {
    const oldestKey = getCache.keys().next().value;
    if (!oldestKey) break;
    getCache.delete(oldestKey);
  }
}

function invalidateRelated(path) {
  const guildMatch = path.match(/\/api\/guilds\/([^/]+)/);
  const keys = [...getCache.keys()];
  for (const key of keys) {
    if (key === path || (guildMatch && key.includes(`/api/guilds/${guildMatch[1]}/`))) {
      getCache.delete(key);
    }
  }
}

async function requestJson(path, options = {}) {
  const token = localStorage.getItem('botES_token');
  const headers = {
    Accept: 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers || {}),
  };

  const response = await fetch(path, {
    credentials: 'include',
    ...options,
    headers,
  });

  if (response.status === 401) {
    localStorage.removeItem('botES_token');
    window.location.href = '/';
    throw new Error('No autorizado');
  }

  if (!response.ok) {
    const errBody = await response.json().catch(() => ({}));
    throw new Error(errBody?.detail || `Error ${response.status}`);
  }

  return response.json();
}

export async function apiGet(path, options = {}) {
  const useCache = options.cache !== false;
  if (useCache) pruneGetCache();

  const cached = getCache.get(path);

  if (useCache && cached && cached.expiresAt > Date.now()) {
    return cached.data;
  }

  if (useCache && pendingGets.has(path)) {
    return pendingGets.get(path);
  }

  const request = requestJson(path)
    .then((data) => {
      if (useCache) {
        getCache.set(path, { data, expiresAt: Date.now() + getTtl(path) });
        pruneGetCache();
      }
      return data;
    })
    .finally(() => pendingGets.delete(path));

  if (useCache) pendingGets.set(path, request);
  return request;
}

export function apiPreload(path) {
  apiGet(path).catch(() => {});
}

export async function apiPost(path, body) {
  const data = await requestJson(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  invalidateRelated(path);
  return data;
}

export async function apiPatch(path, body) {
  const data = await requestJson(path, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  invalidateRelated(path);
  return data;
}

export async function apiPut(path, body) {
  const data = await requestJson(path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  invalidateRelated(path);
  return data;
}

export async function apiDelete(path) {
  const data = await requestJson(path, { method: 'DELETE' });
  invalidateRelated(path);
  return data;
}
