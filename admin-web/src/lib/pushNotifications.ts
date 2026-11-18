const baseUrl = (import.meta.env.VITE_API_URL || '/api/v1').replace(/\/+$/, '');

export async function registerWebPushTokenIfConfigured(accessToken: string): Promise<boolean> {
  const configuredToken = import.meta.env.VITE_FCM_WEB_TOKEN?.trim();
  const vapidKey = import.meta.env.VITE_FCM_VAPID_KEY?.trim();
  if (!configuredToken && !vapidKey) return false;
  if (typeof window === 'undefined' || !('serviceWorker' in navigator)) return false;

  try {
    const registration = await navigator.serviceWorker.register('/firebase-messaging-sw.js');
    let fcmToken = configuredToken || '';
    if (!fcmToken && vapidKey && 'pushManager' in registration) {
      const sub =
        (await registration.pushManager.getSubscription()) ||
        (await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: vapidKey,
        }));
      fcmToken = sub.endpoint;
    }
    if (!fcmToken) return false;

    const res = await fetch(`${baseUrl}/push-tokens`, {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        Authorization: `Bearer ${accessToken}`,
      },
      body: JSON.stringify({ fcmToken, platform: 'web' }),
    });
    return res.ok;
  } catch {
    return false;
  }
}
