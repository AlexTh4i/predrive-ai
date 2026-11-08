/**
 * REST API Service for PREDRIVE AI Session Management
 */
import { CONFIG } from '../config/env';
import type { SessionResponse } from '../types/monitor';

export async function createSession(): Promise<SessionResponse> {
  const url = `${CONFIG.BACKEND_URL}/api/v1/sessions`;
  
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    // Chế độ dev MVP không gửi thông tin tài xế thực
    body: JSON.stringify({
      client_type: 'pwa',
      app_version: CONFIG.APP_VERSION,
    }),
  });

  if (!response.ok) {
    throw new Error(`Tạo session thất bại: ${response.status} ${response.statusText}`);
  }

  const data = await response.json();
  return data;
}

export async function checkBackendHealth(): Promise<boolean> {
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 2000);
    const res = await fetch(`${CONFIG.BACKEND_URL}/health`, {
      method: 'GET',
      signal: controller.signal,
    });
    clearTimeout(timeoutId);
    return res.ok;
  } catch {
    return false;
  }
}
