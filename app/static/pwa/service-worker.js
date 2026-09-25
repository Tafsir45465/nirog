// Service Worker for Nirog PWA
const CACHE_NAME = 'nirog-pwa-v1';
const API_CACHE_NAME = 'nirog-pwa-api-v1';
const OFFLINE_URL = '/offline.html';

// Precached static assets
const PRECACHE_URLS = [
  '/',
  '/patient/dashboard',
  '/static/css/style.css',
  '/static/css/mobile.css',
  '/static/js/main.js',
  '/manifest.json',
  // icons
  '/static/pwa/icons/icon-192.png',
  '/static/pwa/icons/icon-512.png'
];

// Install event - cache precache URLs
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting())
  );
});

// Activate event - clean up old caches
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.filter(name => name !== CACHE_NAME && name !== API_CACHE_NAME)
                  .map(name => caches.delete(name))
      );
    })
    .then(() => self.clients.claim())
  );
});

// Fetch event - serve from cache, fallback to network
self.addEventListener('fetch', event => {
  // Skip cross-origin requests (like to analytics services)
  const url = new URL(event.request.url);
  if (!url.pathname.startsWith('/api/')) {
    // For non-API requests, use cache-first with fallback to network and offline page
    event.respondWith(
      caches.match(event.request)
        .then(cachedResponse => {
          if (cachedResponse) {
            return cachedResponse;
          }
          return fetch(event.request)
            .then(networkResponse => {
              // Cache successful GET requests for static assets
              if (event.request.method === 'GET' && networkResponse.status === 200) {
                return caches.open(CACHE_NAME).then(cache => {
                  cache.put(event.request, networkResponse.clone());
                  return networkResponse;
                });
              }
              return networkResponse;
            })
            .catch(() => {
              // If network fails, try to return offline page for navigation requests
              if (event.request.mode === 'navigate') {
                return caches.match(OFFLINE_URL);
              }
              // Otherwise, return error response (or fallback to cache if any)
              return caches.match(event.request).then(resp => resp || new Response('Network error', {status: 408}));
            });
        })
    );
    return;
  }

  // For API requests: network-first with fallback to cache (stale-while-revalidate could be implemented)
  // We'll try network first, then cache, and update cache in background.
  event.respondWith(
    fetch(event.request)
      .then(networkResponse => {
        // Cache successful GET API responses
        if (event.request.method === 'GET' && networkResponse.status === 200) {
          return caches.open(API_CACHE_NAME).then(cache => {
            cache.put(event.request, networkResponse.clone());
            return networkResponse;
          });
        }
        return networkResponse;
      })
      .catch(() => {
        // If network fails, try to return cached response
        return caches.match(event.request)
          .then(cachedResponse => {
            if (cachedResponse) {
              return cachedResponse;
            }
            // If no cache, return a generic error response (could be improved)
            return new Response(JSON.stringify({error: 'Network unavailable'}), {
              status: 503,
              headers: {'Content-Type': 'application/json'}
            });
          });
      })
  );
});

// Push event handler
self.addEventListener('push', event => {
  const options = {
    body: event.data ? event.data.text() : 'You have a new notification',
    icon: '/static/pwa/icons/icon-192.png',
    badge: '/static/pwa/icons/icon-192.png',
    vibrate: [100, 50, 100],
    data: {
      dateOfArrival: Date.now(),
      primaryKey: 1
    }
  };
  event.waitUntil(
    self.registration.showNotification('Nirog Health', options)
  );
});

// Notification click handler
self.addEventListener('notificationclick', event => {
  event.notification.close();
  // Check if the notification has a data URL to open
  const urlToOpen = event.notification.data && event.notification.data.url ?
    event.notification.data.url : '/patient/dashboard';

  event.waitUntil(
    clients.matchAll({type: 'window'}).then(windowClients => {
      // Check if there is already a window/tab open with the target URL
      for (let client of windowClients) {
        if (client.url === urlToOpen && 'focus' in client) {
          return client.focus();
        }
      }
      // If not, open a new window/tab
      if (clients.openWindow) {
        return clients.openWindow(urlToOpen);
      }
    })
  );
});