import { isNativeApp } from '../config/env';
import { m3Api } from './m3Api';

export async function registerDriverPushTokenIfAvailable(
  accessToken: string,
  serverUrl?: string,
): Promise<boolean> {
  const staticToken = import.meta.env.VITE_FCM_ANDROID_TOKEN?.trim();
  const globalBridgeToken =
    typeof window !== 'undefined'
      ? (window as unknown as { __PREDRIVE_FCM_TOKEN__?: string }).__PREDRIVE_FCM_TOKEN__
      : undefined;
  const fcmToken = globalBridgeToken || staticToken;
  if (!fcmToken) return false;

  try {
    await m3Api.registerPushToken(
      accessToken,
      fcmToken,
      isNativeApp() ? 'android' : 'web',
      serverUrl,
    );
    return true;
  } catch {
    return false;
  }
}
