// Service worker: maakt "Ligt er al ijs?" installeerbaar als app en laat de laatste versie zien als je offline bent.
// Pushmeldingen (OneSignal) lopen via dezelfde worker.
try { importScripts("https://cdn.onesignal.com/sdks/web/v16/OneSignalSDK.sw.js"); } catch (e) {}

const CACHE = "ijs-v2";
const SHELL = ["./", "index.html", "manifest.webmanifest", "icon-192.png", "icon-512.png", "apple-touch-icon.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
// Eerst het netwerk (altijd de nieuwste data), bij geen verbinding de bewaarde versie.
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  e.respondWith(
    fetch(e.request).then(r => {
      if (r.ok) { const copy = r.clone(); caches.open(CACHE).then(c => c.put(e.request, copy)); }
      return r;
    }).catch(() => caches.match(e.request, {ignoreSearch: true}).then(r => r || caches.match("index.html")))
  );
});
// Tik op een melding van de app zelf: open (of activeer) de app op het juiste tabblad.
self.addEventListener("notificationclick", e => {
  const d = e.notification.data || {};
  if (!d.ligt) return;   // meldingen van OneSignal handelt OneSignal zelf af
  e.notification.close();
  const url = d.url || self.registration.scope;
  e.waitUntil(self.clients.matchAll({type: "window", includeUncontrolled: true}).then(list => {
    const c = list.find(w => w.url.startsWith(self.registration.scope));
    if (c) return c.focus().then(w => (w || c).navigate ? (w || c).navigate(url) : null).catch(() => self.clients.openWindow(url));
    return self.clients.openWindow(url);
  }));
});
