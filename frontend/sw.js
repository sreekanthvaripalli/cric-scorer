/**
 * Cric-Scorer — Service Worker
 * Offline-first caching strategy for PWA
 */

const CACHE_NAME = 'cric-scoring-pwa-v1';
const SHELL_CACHE = [
  '/index.html',
  '/watch.html',
  '/css/global.css',
  '/css/live.css',
  '/css/toss.css',
  '/js/live.js',
  '/js/toss.js',
  '/js/scorer.js',
  '/js/watch.js',
  '/manifest.json'
];

self.addEventListener('install', function(event) {
  console.log('[SW] Installing...');
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(function(cache) {
        console.log('[SW] Caching shell');
        return cache.addAll(SHELL_CACHE);
      })
      .then(function() { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function(event) {
  console.log('[SW] Activating...');
  event.waitUntil(
    caches.keys()
      .then(function(names) {
        return Promise.all(
          names.filter(function(n) { return n !== CACHE_NAME; })
               .map(function(n) { return caches.delete(n); })
        );
      })
      .then(function() { return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function(event) {
  var request = event.request;
  if (request.method !== 'GET') return;

  var url = new URL(request.url);

  // API requests - network first
  if (url.origin === self.location.origin && request.url.includes('/matches/')) {
    event.respondWith(
      fetch(request)
        .then(function(res) {
          var clone = res.clone();
          caches.open(CACHE_NAME).then(function(cache) { cache.put(request, clone); });
          return res;
        })
        .catch(function() { return caches.match(request); })
    );
    return;
  }

  // Static assets - cache first
  event.respondWith(
    caches.match(request).then(function(res) {
      if (res) return res;
      return fetch(request).then(function(res) {
        var accept = request.headers.get('accept') || '';
        if (accept.includes('text/html')) return res;
        var clone = res.clone();
        caches.open(CACHE_NAME).then(function(cache) { cache.put(request, clone); });
        return res;
      });
    })
  );
});

self.addEventListener('sync', function(event) {
  if (event.tag === 'sync-deliveries') {
    event.waitUntil(syncDeliveries());
  }
});

async function syncDeliveries() {
  var db = await openDatabase();
  if (!db) return;

  var deliveries = await db.getAllAsync('deliveries');
  if (!deliveries.length) return;

  console.log('[SW] Syncing ' + deliveries.length + ' queued deliveries');
  var results = [];

  for (var i = 0; i < deliveries.length; i++) {
    var delivery = deliveries[i];
    try {
      var response = await fetch('/matches/' + delivery.match_id + '/balls', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(delivery.data)
      });
      if (response.ok) {
        await db.deleteAsync('deliveries', delivery.id);
        results.push({ status: 'success', id: delivery.id });
      } else {
        results.push({ status: 'error', id: delivery.id, error: response.status });
      }
    } catch (e) {
      results.push({ status: 'error', id: delivery.id, error: e.message });
    }
  }

  var message = { type: 'SYNC_RESULT', results: results };
  var clients = await self.clients.matchAll();
  clients.forEach(function(client) { client.postMessage(message); });
  return results;
}

function openDatabase() {
  return new Promise(function(resolve) {
    var request = indexedDB.open('cric-scoring', 1);
    request.onupgradeneeded = function(e) {
      var db = e.target.result;
      if (!db.objectStoreNames.contains('deliveries')) {
        var store = db.createObjectStore('deliveries', { keyPath: 'id', autoIncrement: true });
        store.createIndex('match_id', 'match_id', { unique: false });
      }
    };
    request.onsuccess = function() { resolve(request.result); };
    request.onerror = function() { resolve(null); };
  });
}

function asyncOpenDatabase() {
  return new Promise(function(resolve, reject) {
    var request = indexedDB.open('cric-scoring', 1);
    request.onupgradeneeded = function(e) {
      var db = e.target.result;
      if (!db.objectStoreNames.contains('deliveries')) {
        var store = db.createObjectStore('deliveries', { keyPath: 'id', autoIncrement: true });
        store.createIndex('match_id', 'match_id', { unique: false });
      }
    };
    request.onsuccess = function() { resolve(request.result); };
    request.onerror = function() { reject(request.error); };
  });
}

function asyncPut(storeName, data) {
  return new Promise(function(resolve, reject) {
    openDatabase().then(function(db) {
      if (!db) return resolve(false);
      var tx = db.transaction(storeName, 'readwrite');
      var store = tx.objectStore(storeName);
      var req = store.put(data);
      req.onsuccess = function() { resolve(true); };
      req.onerror = function() { reject(req.error); };
    });
  });
}

function asyncDelete(storeName, id) {
  return new Promise(function(resolve, reject) {
    openDatabase().then(function(db) {
      if (!db) return resolve(false);
      var tx = db.transaction(storeName, 'readwrite');
      var store = tx.objectStore(storeName);
      var req = store.delete(id);
      req.onsuccess = function() { resolve(true); };
      req.onerror = function() { reject(req.error); };
    });
  });
}

function asyncGetAll(storeName) {
  return new Promise(function(resolve, reject) {
    asyncOpenDatabase().then(function(db) {
      if (!db) return resolve([]);
      var tx = db.transaction(storeName, 'readonly');
      var store = tx.objectStore(storeName);
      var request = store.getAll();
      request.onsuccess = function() { resolve(request.result); };
      request.onerror = function() { reject(request.error); };
    });
  });
}
