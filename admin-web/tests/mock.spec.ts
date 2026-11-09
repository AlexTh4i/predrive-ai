import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';

const testTime = new Date('2026-11-09T07:00:00Z');
const consoleProblems = new WeakMap<Page, string[]>();

async function login(page: Page, role = 'manager', password = 'predrive123') {
  await page.getByLabel('Tên đăng nhập').fill(role);
  await page.locator('#password').fill(password);
  await page.getByRole('button', { name: 'Đăng nhập', exact: true }).click();
}

test.beforeEach(async ({ page }) => {
  const problems: string[] = [];
  consoleProblems.set(page, problems);
  page.on('pageerror', (error) => problems.push(error.message));
  page.on('console', (message) => {
    if (['error', 'warning'].includes(message.type())) problems.push(message.text());
  });
  await page.clock.install({ time: testTime });
});

test.afterEach(({ page }) => { expect(consoleProblems.get(page)).toEqual([]); });

test('dashboard phát CRITICAL, xác nhận liên hệ và che dữ liệu cũ khi mất mạng', async ({ page, context }) => {
  await page.goto('/');
  await expect(page).toHaveURL(/\/login$/);
  await login(page);
  const drivers = page.locator('.driver-card');
  await expect(page.locator('.sidebar .sidebar-user')).toContainText('Nguyễn Minh Khanh');
  await expect(page.locator('.topbar-account')).toContainText('Nguyễn Minh Khanh');
  await expect(page.getByText('Nguyễn Khánh An', { exact: true })).toHaveCount(0);
  await expect(drivers).toHaveCount(6);
  await expect(drivers.first()).toContainText('Nguyễn Văn Minh');
  await expect(drivers.first()).toContainText('Nguy hiểm');
  await expect(page.locator('.chart-frame .recharts-surface').first()).toBeVisible();
  await expect(page.getByRole('switch', { name: 'Âm báo nguy hiểm' })).not.toBeChecked();
  await page.getByRole('switch', { name: 'Âm báo nguy hiểm' }).click();
  await expect(page.getByRole('switch', { name: 'Âm báo nguy hiểm' })).toBeChecked();
  await page.getByRole('switch', { name: 'Âm báo nguy hiểm' }).click();
  await expect(page.getByRole('switch', { name: 'Âm báo nguy hiểm' })).not.toBeChecked();
  await page.getByRole('searchbox').fill('khong tim thay');
  await expect(page.getByText('Không tìm thấy tài xế phù hợp')).toBeVisible();
  await page.getByRole('button', { name: 'Xóa bộ lọc' }).click();
  await expect(drivers).toHaveCount(6);
  const alert = page.locator('.alert-item').filter({ hasText: 'Nguyễn Văn Minh' }).first();
  await alert.getByRole('button', { name: 'Đã liên hệ' }).click();
  await expect(alert.getByRole('textbox')).toBeFocused();
  await alert.getByRole('button', { name: 'Hủy ghi nhận' }).click();
  await expect(alert.getByRole('button', { name: 'Đã liên hệ' })).toBeFocused();
  await alert.getByRole('button', { name: 'Đã liên hệ' }).click();
  await alert.getByRole('textbox').fill('Đã nhắc dừng nghỉ.');
  await alert.getByRole('button', { name: 'Lưu xác nhận' }).click();
  await expect(alert.locator('.ack-done')).toContainText('Đã nhắc dừng nghỉ.');
  await page.reload();
  await expect(page.getByText('Đã nhắc dừng nghỉ.')).toBeVisible();
  await page.clock.runFor(16_100);
  await expect(drivers.first()).toContainText('Lê Hoàng Nam');
  await expect(drivers.first()).toContainText('Nguy hiểm');
  await expect(page.locator('.alert-item').filter({ hasText: 'Lê Hoàng Nam' }).first()).toContainText('Nguy hiểm');
  await context.setOffline(true);
  await expect(page.locator('.connection')).toHaveText('Đang kết nối lại…');
  await expect(drivers.filter({ hasText: 'Chưa xác nhận' })).toHaveCount(6);
  await expect(drivers.filter({ hasText: 'Bình thường' })).toHaveCount(0);
  await context.setOffline(false);
  await expect(page.locator('.connection')).toHaveText('Trực tuyến');
});

test('lịch sử lọc, phân trang, giờ Việt Nam và trang hồ sơ tài xế', async ({ page }) => {
  await page.goto('/history');
  await login(page);
  await expect(page).toHaveURL(/\/history$/);
  await expect(page.locator('tbody tr')).toHaveCount(10);
  await page.getByRole('button', { name: 'Trang sau' }).click();
  await expect(page.locator('.pagination')).toContainText('Trang 2 /');
  await page.getByRole('combobox', { name: 'Tài xế', exact: true }).selectOption('driver-1');
  await page.getByLabel('Từ ngày').fill('2026-11-09');
  await page.getByLabel('Đến ngày').fill('2026-11-09');
  await page.getByLabel('Mức độ').selectOption('CRITICAL');
  await page.getByLabel('Loại sự kiện').selectOption('DROWSINESS');
  await page.getByRole('combobox', { name: 'Liên hệ', exact: true }).selectOption('no');
  await expect(page.locator('tbody tr').first()).toContainText('13:58');
  await expect(page.locator('.pagination')).toContainText('Trang 1 / 1');
  const event = page.locator('tbody tr').first();
  await event.getByRole('button', { name: 'Đã liên hệ' }).click();
  await event.getByRole('textbox').fill('Ghi nhận từ lịch sử.');
  await event.getByRole('button', { name: 'Lưu xác nhận' }).click();
  await expect(page.locator('tbody tr')).toHaveCount(1);
  await expect(page.locator('tbody tr')).not.toContainText('13:58');
  await page.getByRole('combobox', { name: 'Liên hệ', exact: true }).selectOption('yes');
  await expect(page.getByText('Ghi nhận từ lịch sử.', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Xóa bộ lọc' }).click();
  await expect(page.getByText('Gửi muộn', { exact: true }).first()).toBeVisible();
  await page.getByRole('navigation').getByRole('link', { name: 'Danh sách tài xế' }).click();
  await page.getByRole('searchbox').fill('nguyen van minh');
  await expect(page.locator('.driver-row')).toHaveCount(1);
  await page.locator('.driver-row').click();
  await expect(page.getByRole('heading', { name: 'Nguyễn Văn Minh', level: 1 })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Gọi', exact: true })).toHaveAttribute('href', 'tel:+84000000001');
  await expect(page.getByRole('link', { name: 'Nhắn Zalo' })).toHaveAttribute('href', 'https://zalo.me/84000000001');
  await expect(page.getByRole('heading', { name: 'Phiên giám sát gần đây' })).toBeVisible();
  await expect(page.getByText('Cảnh báo mỗi giờ lái')).toBeVisible();
});

test('thống kê ngày/tuần và lưu cài đặt hợp lệ cho quản lý', async ({ page }) => {
  await page.goto('/stats');
  await login(page);
  await expect(page.getByText('Tỷ lệ quá tối')).toBeVisible();
  await expect(page.getByText('Số sự kiện theo ngày')).toBeVisible();
  await page.getByRole('button', { name: '4 tuần' }).click();
  await expect(page.getByText('Số sự kiện theo nhóm 7 ngày')).toBeVisible();
  await expect(page.locator('.recharts-line').first()).toBeVisible();
  await expect(page.locator('tbody tr')).toHaveCount(6);
  await page.getByRole('navigation').getByRole('link', { name: 'Cài đặt hệ thống' }).click();
  await page.getByLabel('Ngưỡng cảnh báo (phút)').fill('181');
  await expect(page.getByText('Có thay đổi chưa lưu')).toBeVisible();
  await page.getByRole('button', { name: 'Lưu cài đặt' }).click();
  await expect(page.getByRole('alert')).toContainText('Ngưỡng nguy hiểm phải lớn hơn');
  await expect(page.getByLabel('Ngưỡng nguy hiểm (phút)')).toBeFocused();
  await page.getByLabel('Ngưỡng cảnh báo (phút)').fill('121');
  await page.getByRole('switch', { name: 'Cho phép chia sẻ vị trí' }).check();
  await page.getByRole('button', { name: 'Lưu cài đặt' }).click();
  await expect(page.getByText('Đã lưu cài đặt.')).toBeVisible();
  await page.reload();
  await expect(page.getByLabel('Ngưỡng cảnh báo (phút)')).toHaveValue('121');
  await expect(page.getByRole('switch', { name: 'Cho phép chia sẻ vị trí' })).toBeChecked();
});

test('tài xế bị chặn, người trực dùng menu mobile và không truy cập cài đặt', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/login');
  await page.getByRole('button', { name: 'Người trực', exact: true }).click();
  await expect(page.getByLabel('Tên đăng nhập')).toHaveValue('dispatcher');
  await page.getByRole('button', { name: 'Hiện mật khẩu' }).click();
  await expect(page.locator('#password')).toHaveAttribute('type', 'text');
  await page.getByRole('button', { name: 'Ẩn mật khẩu' }).click();
  await expect(page.locator('#password')).toHaveAttribute('type', 'password');
  await login(page, 'manager', 'sai');
  await expect(page.getByRole('alert')).toContainText('mật khẩu không đúng');
  await login(page, 'driver');
  await expect(page.getByRole('alert')).toContainText('Tài khoản tài xế không có quyền');
  await login(page, 'dispatcher');
  await expect(page.getByText('Ca trực của Huỳnh Tấn Gia Huy', { exact: true })).toBeVisible();
  await expect(page.getByText('Lê Hoài Linh', { exact: true })).toHaveCount(0);
  await expect(page.locator('.driver-card')).toHaveCount(6);
  const columns = () => page.locator('.driver-grid').evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(' ').length);
  expect(await columns()).toBe(1);
  await page.setViewportSize({ width: 820, height: 1024 });
  expect(await columns()).toBe(2);
  await page.setViewportSize({ width: 1440, height: 900 });
  expect(await columns()).toBe(3);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: 'Mở menu' }).click();
  const dialog = page.getByRole('dialog', { name: 'Điều hướng' });
  await expect(dialog).toBeVisible();
  await expect(dialog.locator('.sidebar-user')).toContainText('Huỳnh Tấn Gia Huy');
  await expect(dialog.getByRole('link', { name: 'Cài đặt hệ thống' })).toHaveCount(0);
  await dialog.getByRole('link', { name: 'Lịch sử cảnh báo' }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole('heading', { name: 'Lịch sử cảnh báo', level: 1 })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.goto('/settings');
  await expect(page.getByText('Bạn không có quyền truy cập cài đặt')).toBeVisible();
  await page.getByRole('button', { name: 'Mở menu' }).click();
  await dialog.getByRole('button', { name: 'Đăng xuất' }).click();
  await expect(page).toHaveURL(/\/login$/);
});

test('bảy màn hình vừa khung ở 320, 375, 390, 768, 1366 và 1920 px', async ({ page }) => {
  const widths = [320, 375, 390, 768, 1366, 1920];
  const checkWidths = async () => {
    for (const width of widths) {
      await page.setViewportSize({ width, height: 900 });
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
      for (const table of await page.locator('.table-scroll').all()) {
        await expect.poll(() => table.evaluate((element) => element.scrollWidth - element.clientWidth)).toBeLessThanOrEqual(1);
      }
    }
  };
  await page.goto('/login');
  await checkWidths();
  await login(page);
  await expect(page.locator('.driver-card').first()).toBeVisible();
  for (const [route, selector] of [
    ['/', '.driver-card'], ['/history', 'tbody tr'], ['/drivers', '.driver-row'],
    ['/drivers/driver-1', '.profile-contact'], ['/stats', '.recharts-line'], ['/settings', '.settings-form'],
  ]) {
    await page.goto(route);
    await expect(page.locator(selector).first()).toBeVisible();
    await checkWidths();
  }
  await page.setViewportSize({ width: 320, height: 740 });
  await page.goto('/');
  const menu = page.getByRole('button', { name: 'Mở menu' });
  await expect(page.locator('#main-content')).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  await expect(menu).toBeFocused();
  expect(await menu.evaluate((element) => getComputedStyle(element).outlineStyle)).not.toBe('none');
  await page.keyboard.press('Enter');
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(dialog).not.toBeVisible();
  await expect(menu).toBeFocused();
  await page.getByRole('link', { name: 'Cảnh báo', exact: true }).click();
  await expect(page.locator('#recent-alerts')).toBeFocused();
});
