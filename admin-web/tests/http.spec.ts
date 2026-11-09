import { createServer } from 'node:http';
import type { IncomingMessage, ServerResponse } from 'node:http';
import { expect, test } from '@playwright/test';
import type { AlertEvent, LiveDriverState, Settings } from '../src/types';

const accessToken = 'fixture-m3-access-token';
const user = { id: 'op-1', role: 'manager', fullName: 'Nguyễn Quản Lý', organizationId: 'org-1' };
const driver: LiveDriverState = {
  driverId: 'm3-1', fullName: 'Nguyễn M3', phone: '0901234567', vehicleName: '51B-100.01',
  state: 'NORMAL', sessionId: 'session-1', continuousDrivingSec: 120, totalDrivingSec: 120,
  drowsyCountToday: 0, lastHeartbeatAt: '2026-11-09T07:00:00Z', location: null,
};
const alert: AlertEvent = {
  id: 'event-1', sessionId: 'session-1', driverId: driver.driverId, driverName: driver.fullName, vehicleName: driver.vehicleName,
  type: 'DROWSINESS', level: 'CRITICAL', status: 'ESCALATED', state: 'CRITICAL', riskScore: null,
  startedAt: '2026-11-09T07:00:01Z', durationSec: 2, delayed: false,
  capturedAt: '2026-11-09T07:00:01Z', receivedAt: '2026-11-09T07:00:01Z',
  ackBy: null, ackAt: null, note: null,
};
const delayed: AlertEvent = {
  ...alert, id: 'delayed-1', driverName: 'Dữ liệu gửi muộn', delayed: true, receivedAt: '2026-11-09T07:03:00Z',
};
let settings: Settings = {
  continuousWarnSec: 7200, continuousCriticalSec: 10800, restResetMin: 15, shareLocation: false, heartbeatIntervalSec: 30,
};

const requests: { path: string; authorization?: string; query: URLSearchParams }[] = [];
const streams = new Set<ServerResponse>();
let current = driver;
let events: AlertEvent[] = [delayed];
let ackBody: unknown;
let loginBody: unknown;
let expired = false;
let healthUnavailable = true;
let settingsUnavailable = true;

function json(res: ServerResponse, data: unknown, status = 200) {
  res.writeHead(status, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(data));
}

async function readBody(req: IncomingMessage) {
  let body = '';
  for await (const chunk of req) body += String(chunk);
  return JSON.parse(body) as unknown;
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url ?? '/', 'http://127.0.0.1');
  const path = url.pathname.replace(/^\/api\/v1/, '');
  requests.push({ path, authorization: req.headers.authorization, query: url.searchParams });
  if (path === '/auth/login' && req.method === 'POST') {
    loginBody = await readBody(req);
    return json(res, { accessToken, user });
  }
  if (expired || req.headers.authorization !== `Bearer ${accessToken}`) {
    return json(res, { error: { code: 'UNAUTHORIZED', message: 'Unauthorized' } }, 401);
  }
  if (path === '/auth/me') return json(res, user);
  if (path === '/live') return json(res, [current]);
  if (path === '/settings' && req.method === 'PUT') {
    const updated = await readBody(req) as Settings;
    if (settingsUnavailable) return json(res, { error: { code: 'UNAVAILABLE', message: 'Unavailable' } }, 503);
    settings = updated;
    return json(res, settings);
  }
  if (path === '/settings') return json(res, settings);
  if (path === '/events') {
    const query = url.searchParams;
    const items = events.filter((event) => {
      const from = query.get('from');
      const to = query.get('to');
      const acked = query.get('acked');
      return (!from || Date.parse(event.capturedAt) >= Date.parse(from))
        && (!to || Date.parse(event.capturedAt) <= Date.parse(to))
        && (!acked || Boolean(event.ackAt) === (acked === 'true'))
        && ['driverId', 'type', 'level'].every((key) => !query.has(key) || query.get(key) === event[key as 'driverId' | 'type' | 'level']);
    });
    const pageSize = Number(query.get('pageSize') || 10);
    const offset = (Number(query.get('page') || 1) - 1) * pageSize;
    return json(res, { items: items.slice(offset, offset + pageSize), total: items.length });
  }
  if (path === '/drivers') return json(res, [{
    id: driver.driverId, fullName: driver.fullName, phone: driver.phone,
    vehicleId: 'vehicle-1', vehicleName: driver.vehicleName, avatarUrl: null,
  }]);
  if (path === '/stats/hourly') return json(res, [{ hour: 14, warning: 0, critical: 1 }]);
  if (path === '/stats/ranking') return json(res, [{ driverId: driver.driverId, fullName: driver.fullName, alertsPerDrivingHour: 0.5, alertCount: 2 }]);
  if (path === '/stats/system-health') {
    return healthUnavailable
      ? json(res, { error: { code: 'UNAVAILABLE', message: 'Unavailable' } }, 503)
      : json(res, { tooDarkRate: 0.028, unavailableRate: 0.047, disconnectedCount: 1 });
  }
  if (path === '/events/event-1/ack' && req.method === 'POST') {
    ackBody = await readBody(req);
    const updated = { ...alert, ackAt: '2026-11-09T07:00:04Z', ackBy: user.id, note: (ackBody as { note: string }).note };
    events = [updated, delayed];
    return json(res, updated);
  }
  if (path === '/live/stream') {
    res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' });
    res.write(': connected\n\n');
    streams.add(res);
    res.on('close', () => { streams.delete(res); });
    return;
  }
  return json(res, { error: { code: 'NOT_FOUND', message: 'Not found' } }, 404);
});

function emit(event: 'driver_state' | 'alert', data: LiveDriverState | AlertEvent) {
  for (const stream of streams) stream.write(`event: ${event}\r\ndata: ${JSON.stringify(data)}\r\n\r\n`);
}

test.beforeAll(async () => {
  await new Promise<void>((resolve) => server.listen(5186, '127.0.0.1', resolve));
});

test.afterAll(async () => {
  for (const stream of streams) stream.end();
  server.closeAllConnections();
  await new Promise<void>((resolve) => server.close(() => resolve()));
});

test('fixture M3 kiểm tra SSE, trạng thái mất kết nối, truy vấn lịch sử/thống kê, lưu cài đặt và 401', async ({ page }) => {
  const browserErrors: string[] = [];
  page.on('pageerror', (error) => browserErrors.push(error.message));
  await page.clock.install({ time: new Date('2026-11-09T07:00:05Z') });
  await page.goto('/');
  await expect(page.getByText('Tài khoản mô phỏng')).toHaveCount(0);
  await page.getByLabel('Tên đăng nhập').fill('fixture-manager');
  await page.locator('#password').fill('fixture-password');
  await page.getByRole('button', { name: 'Đăng nhập', exact: true }).click();
  await expect(page.locator('.driver-card')).toContainText('Bình thường');
  expect(loginBody).toEqual({ username: 'fixture-manager', password: 'fixture-password' });
  expect(requests.find((request) => request.path === '/live/stream')?.authorization).toBe(`Bearer ${accessToken}`);
  expect(requests.find((request) => request.path === '/stats/hourly')?.query.get('to')).toBe('2026-11-09T16:59:59.999Z');
  await expect(page.getByText('Dữ liệu gửi muộn')).toHaveCount(0);
  await expect(page.getByText('Nguyễn Văn Minh')).toHaveCount(0);

  current = { ...driver, state: 'CRITICAL', lastHeartbeatAt: '2026-11-09T07:00:04Z' };
  events = [alert, delayed];
  emit('driver_state', current);
  emit('alert', alert);
  emit('alert', delayed);
  await expect(page.locator('.driver-card')).toContainText('Nguy hiểm');
  const item = page.locator('.alert-item');
  await expect(item).toHaveCount(1);
  await expect(item).toContainText('14:00');
  await item.getByRole('button', { name: 'Đã liên hệ' }).click();
  await item.getByRole('textbox').fill('Gọi từ M3');
  await item.getByRole('button', { name: 'Lưu xác nhận' }).click();
  await expect(item.locator('.ack-done')).toContainText('Gọi từ M3');
  expect(ackBody).toEqual({ note: 'Gọi từ M3' });
  emit('alert', alert);
  await expect(item).toContainText('Gọi từ M3');

  current = { ...driver, lastHeartbeatAt: '2026-11-09T06:55:00Z' };
  for (const stream of streams) stream.end();
  await expect(page.locator('.connection')).toHaveText('Đang kết nối lại…');
  await expect(page.locator('.driver-card')).toContainText('Chưa xác nhận');
  await expect(page.locator('.connection')).toHaveText('Trực tuyến');
  await expect(page.locator('.driver-card')).toContainText('Chưa xác nhận');
  await expect(page.locator('.driver-card')).not.toContainText('Bình thường');
  emit('driver_state', { ...driver, lastHeartbeatAt: '2026-11-09T07:00:05Z' });
  await expect(page.locator('.driver-card')).toContainText('Bình thường');
  emit('driver_state', { ...driver, state: 'DISCONNECTED', lastHeartbeatAt: '2026-11-09T07:00:05Z' });
  await expect(page.locator('.driver-card')).toContainText('Mất kết nối');

  const nav = page.getByRole('navigation', { name: 'Điều hướng chính' });
  await nav.getByRole('link', { name: 'Lịch sử cảnh báo' }).click();
  await expect(page.getByText('Gửi muộn', { exact: true })).toBeVisible();
  await page.getByRole('combobox', { name: 'Tài xế', exact: true }).selectOption(driver.driverId);
  await page.getByLabel('Từ ngày').fill('2026-11-09');
  await page.getByLabel('Đến ngày').fill('2026-11-09');
  await page.getByLabel('Mức độ').selectOption('CRITICAL');
  await page.getByLabel('Loại sự kiện').selectOption('DROWSINESS');
  await page.getByRole('combobox', { name: 'Liên hệ', exact: true }).selectOption('no');
  await expect(page.locator('tbody tr')).toHaveCount(1);
  const historyQuery = requests.filter(({ path, query }) => path === '/events' && query.get('acked') === 'false').at(-1)?.query;
  expect(Object.fromEntries(historyQuery ?? [])).toEqual({
    driverId: driver.driverId, from: '2026-11-08T17:00:00.000Z', to: '2026-11-09T16:59:59.999Z',
    level: 'CRITICAL', type: 'DROWSINESS', acked: 'false', page: '1', pageSize: '10',
  });

  await nav.getByRole('link', { name: 'Thống kê', exact: true }).click();
  const health = page.getByRole('region', { name: 'Sức khỏe hệ thống' });
  await expect(health.getByRole('alert')).toBeVisible();
  await expect(page.getByRole('region', { name: 'Xếp hạng tài xế' }).getByText(driver.fullName)).toBeVisible();
  await expect(page.locator('.recharts-line').first()).toBeVisible();
  healthUnavailable = false;
  await health.getByRole('button', { name: 'Thử lại' }).click();
  await expect(health.getByText('2,8%')).toBeVisible();
  await page.getByRole('button', { name: '4 tuần' }).click();
  await expect(page.getByText('Số sự kiện theo nhóm 7 ngày')).toBeVisible();
  await expect.poll(() => requests.filter(({ path }) => path === '/stats/ranking').at(-1)?.query.get('from')).toBe('2026-10-12T17:00:00.000Z');

  await nav.getByRole('link', { name: 'Cài đặt hệ thống' }).click();
  await page.getByLabel('Ngưỡng cảnh báo (phút)').fill('121.5');
  await page.getByRole('button', { name: 'Lưu cài đặt' }).click();
  await expect(page.getByRole('alert')).toContainText('Chưa lưu được cài đặt.');
  await expect(page.getByText('Có thay đổi chưa lưu')).toBeVisible();
  settingsUnavailable = false;
  await page.getByRole('button', { name: 'Lưu cài đặt' }).click();
  await expect(page.getByText('Đã lưu cài đặt.')).toBeVisible();
  expect(settings).toEqual({
    continuousWarnSec: 7290, continuousCriticalSec: 10800, restResetMin: 15, shareLocation: false, heartbeatIntervalSec: 30,
  });
  expired = true;
  await nav.getByRole('link', { name: 'Danh sách tài xế' }).click();
  await expect(page).toHaveURL(/\/login$/);
  expect(browserErrors).toEqual([]);
});
