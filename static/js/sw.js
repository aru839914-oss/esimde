const CACHE = 'esimde-v1';
const PRECACHE = [
  '/offline',
  '/static/css/style.css',
  '/static/js/main.js',
  '/static/js/notifications.js',
  '/static/img/icon-192.png',
  '/static/img/badge-96.png',
  '/static/img/favicon.svg',
];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  if (req.mode === 'navigate') {
    event.respondWith(fetch(req).catch(() => caches.match('/offline')));
    return;
  }

  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      fetch(req)
        .then((res) => {
          if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(req, copy)); }
          return res;
        })
        .catch(() => caches.match(req))
    );
  }

});

self.addEventListener('push', (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = { body: event.data && event.data.text() }; }
  const options = {
    body: data.body || 'Жаңа еске салу',
    icon: '/static/img/icon-192.png',
    badge: '/static/img/badge-96.png',
    tag: data.tag || 'esimde',
    renotify: true,
    requireInteraction: !!data.event_id,
    lang: 'kk',
    data: { url: data.url || '/', token: data.token || null },
  };
  if (data.token) {
    options.actions = [
      { action: 'done', title: '✅ Орындалды' },
      { action: 'snooze10', title: '⏰ 10 мин' },
    ];
  }
  event.waitUntil(self.registration.showNotification(data.title || 'Esimde', options));
});

self.addEventListener('notificationclick', (event) => {
  const { url, token } = event.notification.data || {};
  event.notification.close();

  if (token && (event.action === 'done' || event.action === 'snooze10')) {
    event.waitUntil(
      fetch('/api/push/action', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, action: event.action }),
      })
        .then((r) => r.json())
        .then((d) => self.registration.showNotification('Esimde', {
          body: d.message || d.error || 'Дайын',
          icon: '/static/img/icon-192.png',
          badge: '/static/img/badge-96.png',
          tag: 'esimde-action',
          silent: true,
        }))
        .catch(() => null)
    );
    return;
  }

  const target = new URL(url || '/', self.location.origin).href;
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((wins) => {
      for (const w of wins) {
        if (new URL(w.url).origin === self.location.origin && 'focus' in w) {
          return w.navigate(target).then((nw) => (nw || w).focus());
        }
      }
      return self.clients.openWindow(target);
    })
  );
});
