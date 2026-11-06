/**
 * lib/api.js
 * Cliente HTTP con caché TTL y deduplicación de peticiones.
 * Conectado al backend FastAPI en /api/
 */

const getCache = new Map();
const pendingGets = new Map();
let cacheGeneration = 0;
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
  const pathname = path.split('?', 1)[0];
  return ttlByPath.find(([pattern]) => pattern.test(pathname))?.[1] ?? 15_000;
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
  cacheGeneration += 1;
  const guildMatch = path.match(/\/api\/guilds\/([^/]+)/);
  const keys = [...getCache.keys()];
  for (const key of keys) {
    if (key === path || (guildMatch && key.includes(`/api/guilds/${guildMatch[1]}/`))) {
      getCache.delete(key);
    }
  }
  for (const key of [...pendingGets.keys()]) {
    if (key === path || (guildMatch && key.includes(`/api/guilds/${guildMatch[1]}/`))) {
      pendingGets.delete(key);
    }
  }
}

async function requestJson(path, options = {}) {
  const headers = {
    Accept: 'application/json',
    ...(options.headers || {}),
  };

  const response = await fetch(path, {
    credentials: 'include',
    ...options,
    headers,
  });

  if (response.status === 401) {
    sessionStorage.removeItem('botES_guilds_cache');
    sessionStorage.removeItem('botES_user_cache');
    window.location.href = '/';
    throw new Error('No autorizado');
  }

  if (!response.ok) {
    const rawBody = await response.text().catch(() => '');
    let errBody;
    try {
      errBody = rawBody ? JSON.parse(rawBody) : {};
    } catch {
      errBody = { detail: rawBody.slice(0, 500) };
    }
    let permissionDebug = null;
    if (response.status === 403) {
      getCache.clear();
      sessionStorage.removeItem('botES_guilds_cache');
      sessionStorage.removeItem('botES_user_cache');
      permissionDebug = await fetchPermissionDebug(path);
      console.warn('[CatBot API] 403', { path, detail: errBody?.detail, permissionDebug });
    }
    const detail = errBody?.detail;
    const debugReason = permissionDebug?.live?.reason || permissionDebug?.jwt?.reason;
    const message = typeof detail === 'string'
      ? detail
      : detail?.message || detail?.reason || debugReason || `Error ${response.status}`;
    const error = new Error(message);
    error.status = response.status;
    if (["http_confirmation_required", "private_confirmation_required", "endpoint_confirmation_required"].includes(detail?.code)) {
      error.code = detail.code;
      error.endpointUrl = typeof detail.endpoint_url === "string" ? detail.endpoint_url : "";
      error.requiredConfirmations = Array.isArray(detail.required_confirmations) ? detail.required_confirmations.filter((value) => value === "http" || value === "private") : [];
    }
    throw error;
  }

  return response.json();
}

async function fetchPermissionDebug(path) {
  const guildMatch = path.match(/\/api\/(?:guilds|moderation)\/(\d+)/);
  const guildId = guildMatch?.[1];
  if (!guildId || path.includes('/api/auth/permissions/')) return null;
  try {
    const response = await fetch(`/api/auth/permissions/${guildId}`, {
      credentials: 'include',
      headers: {
        Accept: 'application/json',
      },
    });
    return await response.json();
  } catch {
    return null;
  }
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

  const generation = cacheGeneration;
  const request = requestJson(path)
    .then((data) => {
      if (useCache && generation === cacheGeneration) {
        getCache.set(path, { data, expiresAt: Date.now() + getTtl(path) });
        pruneGetCache();
      }
      return data;
    })
    .finally(() => {
      if (pendingGets.get(path) === request) pendingGets.delete(path);
    });

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

export async function apiUpload(path, file) {
  const data = await requestJson(path, {
    method: 'POST',
    headers: {
      'Content-Type': file.type || 'application/octet-stream',
      'X-Filename': encodeURIComponent(file.name),
    },
    body: file,
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
