export function readStorage<T>(key: string, fallback: T, area: 'localStorage' | 'sessionStorage' = 'localStorage'): T {
  try {
    const value = window[area].getItem(key);
    return value === null ? fallback : JSON.parse(value) as T;
  } catch {
    return fallback;
  }
}

export function writeStorage(key: string, value: unknown, area: 'localStorage' | 'sessionStorage' = 'localStorage') {
  try {
    if (value === null) window[area].removeItem(key);
    else window[area].setItem(key, JSON.stringify(value));
  } catch {
    // The app still works in memory when storage is blocked.
  }
}
