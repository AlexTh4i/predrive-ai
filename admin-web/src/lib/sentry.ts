/**
 * Lightweight zero-dependency Sentry Envelope reporter for Admin Web (R1: never sends PII/images).
 * Activated automatically when VITE_SENTRY_DSN is configured.
 */
interface ParsedDsn {
  envelopeUrl: string;
  publicKey: string;
}

function parseSentryDsn(dsn: string): ParsedDsn | null {
  try {
    const url = new URL(dsn.trim());
    const publicKey = url.username;
    const projectId = url.pathname.replace(/^\/+/, '');
    if (!publicKey || !projectId) return null;
    return {
      publicKey,
      envelopeUrl: `${url.protocol}//${url.host}/api/${projectId}/envelope/`,
    };
  } catch {
    return null;
  }
}

export function initSentryClient(): void {
  const dsn = (import.meta.env.VITE_SENTRY_DSN as string | undefined)?.trim();
  if (!dsn) return;
  const parsed = parseSentryDsn(dsn);
  if (!parsed) return;

  const report = (message: string, stack?: string) => {
    const eventId = crypto.randomUUID().replace(/-/g, '');
    const header = JSON.stringify({
      event_id: eventId,
      sent_at: new Date().toISOString(),
      dsn,
    });
    const itemHeader = JSON.stringify({ type: 'event' });
    const payload = JSON.stringify({
      event_id: eventId,
      timestamp: Date.now() / 1000,
      platform: 'javascript',
      environment: import.meta.env.MODE,
      message,
      extra: stack ? { stack: stack.slice(0, 2000) } : undefined,
    });
    void fetch(`${parsed.envelopeUrl}?sentry_key=${parsed.publicKey}&sentry_version=7`, {
      method: 'POST',
      body: `${header}\n${itemHeader}\n${payload}`,
      keepalive: true,
    }).catch(() => undefined);
  };

  window.addEventListener('error', (ev) => {
    report(ev.message || 'Unhandled error', ev.error instanceof Error ? ev.error.stack : undefined);
  });
  window.addEventListener('unhandledrejection', (ev) => {
    const reason = ev.reason;
    report(
      reason instanceof Error ? reason.message : String(reason),
      reason instanceof Error ? reason.stack : undefined,
    );
  });
}
