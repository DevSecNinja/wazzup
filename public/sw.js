const BUILD_ID = new URL(self.location.href).searchParams.get('v') || 'dev';
const CACHE_NAME = `wazzup-${BUILD_ID}`;
const STATIC_ASSETS = ['./', 'index.html', 'styles.css', 'app.js', 'manifest.webmanifest', 'icons/icon.svg', 'icons/favicon.svg', 'icons/icon-192.png'];

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
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
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
