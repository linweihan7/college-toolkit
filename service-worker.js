// Network-first with cache fallback, so the installed app still opens offline
// but always prefers a fresh copy when one is reachable.
const CACHE_NAME = 'college-toolkit-v5';
const PRECACHE_URLS = [
  './',
  './index.html',
  './manifest.json',
  './icon-192.png',
  './icon-512.png',
  './icon-192-maskable.png',
  './icon-512-maskable.png',
  './vendor/supabase.min.js',
  './vendor/chart.umd.js',
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

// The page posts {type:'show-notification', title, body} here. Displaying through
// the service worker (instead of `new Notification()`) is required on Android
// PWAs and keeps working when the tab is backgrounded.
self.addEventListener('message', event => {
  const data = event.data;
  if (!data || data.type !== 'show-notification') return;
  self.registration.showNotification(data.title, {
    body: data.body || '',
    icon: './icon-192.png',
    badge: './icon-192.png',
    tag: data.tag || undefined,
  });
});

// Tapping a notification focuses the app if it's open, or opens it fresh.
self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(clientList => {
      for (const client of clientList) {
        if ('focus' in client) return client.focus();
      }
      return self.clients.openWindow('./');
    })
  );
});
