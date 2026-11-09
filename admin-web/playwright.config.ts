import { defineConfig } from '@playwright/test';

const mockUrl = 'http://127.0.0.1:5184';
const httpUrl = 'http://127.0.0.1:5185';

export default defineConfig({
  testDir: './tests',
  timeout: 30_000,
  use: { browserName: 'chromium', reducedMotion: 'reduce', trace: 'retain-on-failure' },
  projects: [
    { name: 'mock', testMatch: 'mock.spec.ts', use: { baseURL: mockUrl } },
    { name: 'http-m3-fixture', testMatch: 'http.spec.ts', use: { baseURL: httpUrl } },
  ],
  webServer: [
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 5184',
      env: { VITE_USE_MOCK: 'true' },
      url: mockUrl,
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 5185',
      env: { VITE_USE_MOCK: 'false', VITE_API_URL: '/api/v1', API_PROXY_TARGET: 'http://127.0.0.1:5186' },
      url: httpUrl,
    },
  ],
});
