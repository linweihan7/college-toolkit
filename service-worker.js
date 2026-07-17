// Network-first with cache fallback, so the installed app still opens offline
// but always prefers a fresh copy when one is reachable.
const CACHE_NAME = 'college-toolkit-v2';
const PRECACHE_URLS = [
  './',
  './index.html',
  './manifest.json',
  './icon-192.png',
  './icon-512.png',
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;

  // Never intercept cross-origin requests (Canvas feeds, weather API, future APIs):
  // the page must see their real success/failure, not a cached stand-in.
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;

  event.respondWith(
    fetch(event.request)
      .then(response => {
        const copy = response.clone();
        caches.open(CACHE_NAME).then(cache => cache.put(event.request, copy));
        return response;
      })
      .catch(() =>
        caches.match(event.request).then(cached =>
          // index.html fallback only makes sense when the user is opening a page,
          // never as a substitute for a failed data/asset request.
          cached || (event.request.mode === 'navigate' ? caches.match('./index.html') : Response.error())
        )
      )
  );
});
