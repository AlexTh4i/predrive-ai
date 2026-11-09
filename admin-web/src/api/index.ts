import { httpApi } from './httpApi';
import type { AdminApi } from './contract';

export const isMock = import.meta.env.VITE_USE_MOCK !== 'false';
export const api: AdminApi = isMock ? (await import('./mockApi')).mockApi : httpApi;
