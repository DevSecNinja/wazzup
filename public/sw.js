const BUILD_ID = new URL(self.location.href).searchParams.get('v') || 'dev';
const CACHE_NAME = `wazzup-${BUILD_ID}`;
const STATE_CACHE_NAME = 'wazzup-meta';
const BRIEFING_STATE_KEY = './__briefing_state__';
const STATIC_ASSETS = ['./', 'index.html', 'styles.css', 'app.js', 'manifest.webmanifest', 'icons/icon.svg', 'icons/favicon.svg', 'icons/icon-192.png'];
const BACKGROUND_SYNC_TAG = 'wazzup-hourly-update';

function resolveDataUrl(path) {
  const value = String(path || '');
  return value.startsWith('data/') ? value : `data/${value}`;
}

async function readBriefingState() {
  const cache = await caches.open(STATE_CACHE_NAME);
  const response = await cache.match(BRIEFING_STATE_KEY);
  if (!response) return null;
  try {
    return await response.json();
  } catch {
    return null;
  }
}

async function writeBriefingState(state) {
  const cache = await caches.open(STATE_CACHE_NAME);
  await cache.put(
    BRIEFING_STATE_KEY,
    new Response(JSON.stringify(state), {
      headers: { 'content-type': 'application/json' },
    }),
  );
}

async function fetchLatestBriefingState() {
  const latestResponse = await fetch('data/latest.json', { cache: 'no-store' });
  if (!latestResponse.ok) throw new Error(`Failed to load latest.json: ${latestResponse.status}`);
  const latest = await latestResponse.json();
  const briefingResponse = await fetch(resolveDataUrl(latest.latestBriefingUrl), { cache: 'no-store' });
  if (!briefingResponse.ok) throw new Error(`Failed to load latest briefing: ${briefingResponse.status}`);
  const briefing = await briefingResponse.json();
  return {
    latestBriefingUrl: latest.latestBriefingUrl,
    headline: briefing.headline || 'A new hourly update is ready',
  };
}

async function checkForBriefingUpdate(showNotification) {
  const current = await fetchLatestBriefingState();
  const previous = await readBriefingState();
  if (showNotification && previous?.latestBriefingUrl && previous.latestBriefingUrl !== current.latestBriefingUrl) {
    await self.registration.showNotification('Wazzup hourly update', {
      body: current.headline,
      icon: 'icons/icon-192.png',
      badge: 'icons/icon-192.png',
      tag: BACKGROUND_SYNC_TAG,
    });
  }
  await writeBriefingState(current);
}

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) =>
        Promise.all(
          STATIC_ASSETS.map((asset) =>
            fetch(new Request(asset, { cache: 'reload' })).then((response) => response.ok && cache.put(asset, response)),
          ),
        ),
      )
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME && key !== STATE_CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('message', (event) => {
  if (event.data?.type !== 'sync-latest-briefing' || !event.data.latestBriefingUrl) return;
  event.waitUntil(
    writeBriefingState({
      latestBriefingUrl: event.data.latestBriefingUrl,
      headline: event.data.headline || 'A new hourly update is ready',
    }),
  );
});

self.addEventListener('sync', (event) => {
  if (event.tag !== BACKGROUND_SYNC_TAG) return;
  event.waitUntil(checkForBriefingUpdate(true));
});

self.addEventListener('periodicsync', (event) => {
  if (event.tag !== BACKGROUND_SYNC_TAG) return;
  event.waitUntil(checkForBriefingUpdate(true));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      for (const client of clients) {
        if ('focus' in client) return client.focus();
      }
      if (self.clients.openWindow) return self.clients.openWindow('./');
      return undefined;
    }),
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;
  event.respondWith(
    fetch(request)
      .then((response) => {
        const copy = response.clone();
        if (response.ok) caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
        return response;
      })
      .catch(() => caches.match(request).then((cached) => cached || caches.match('./'))),
  );
});
