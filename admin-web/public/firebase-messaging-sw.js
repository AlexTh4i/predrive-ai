/* Background Web Push / Firebase Cloud Messaging Service Worker (P3-7) */
self.addEventListener('push', (event) => {
  let payload = {
    title: 'PreDrive AI — Cảnh báo đội xe',
    body: 'Có sự kiện an toàn mới từ đội xe.',
    data: {},
  };
  if (event.data) {
    try {
      const parsed = event.data.json();
      const notif = parsed.notification || parsed;
      payload = {
        title: notif.title || payload.title,
        body: notif.body || payload.body,
        data: parsed.data || {},
      };
    } catch {
      payload.body = event.data.text() || payload.body;
    }
  }
  event.waitUntil(
    self.registration.showNotification(payload.title, {
      body: payload.body,
      tag: payload.data.eventId || 'predrive-alert',
      data: payload.data,
    }),
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const targetUrl = event.notification.data?.eventId
    ? `/history`
    : '/';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if ('focus' in client) return client.focus();
      }
      if (self.clients.openWindow) return self.clients.openWindow(targetUrl);
      return undefined;
    }),
  );
});
