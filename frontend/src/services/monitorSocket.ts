/**
 * WebSocket Service for Driver Monitoring Protocol (MVP v0.1)
 * Tuân thủ theo API contract chung của PREDRIVE AI
 */
import { CONFIG } from '../config/env';
import type { AnalysisResultPayload, FramePayload } from '../types/monitor';

export type SocketStatus = 'disconnected' | 'connecting' | 'connected' | 'error';

export interface MonitorSocketOptions {
  sessionId: string;
  onStatusChange: (status: SocketStatus, errorMsg?: string) => void;
  onAnalysisResult: (result: AnalysisResultPayload) => void;
  onError: (error: Error) => void;
}

export class MonitorSocketClient {
  private ws: WebSocket | null = null;
  private sessionId: string;
  private options: MonitorSocketOptions;
  private lastReceivedFrameId = -1;
  private isIntentionallyClosed = false;

  constructor(options: MonitorSocketOptions) {
    this.sessionId = options.sessionId;
    this.options = options;
  }

  public connect(): void {
    this.isIntentionallyClosed = false;
    const baseWsUrl = CONFIG.WS_URL;
    const url = `${baseWsUrl}?session_id=${encodeURIComponent(this.sessionId)}`;

    try {
      this.options.onStatusChange('connecting');
      this.ws = new WebSocket(url);

      this.ws.onopen = () => {
        this.options.onStatusChange('connected');
      };

      this.ws.onmessage = (event: MessageEvent) => {
        try {
          const rawData = JSON.parse(event.data);
          this.handleIncomingMessage(rawData);
        } catch (parseErr) {
          console.error('Lỗi giải mã payload WebSocket:', parseErr);
        }
      };

      this.ws.onerror = (event: Event) => {
        console.warn('WebSocket gặp lỗi kết nối:', event);
        this.options.onStatusChange('error', 'Không thể kết nối đến WebSocket Gateway.');
      };

      this.ws.onclose = (event: CloseEvent) => {
        if (!this.isIntentionallyClosed) {
          this.options.onStatusChange('disconnected', `Kết nối đóng: code ${event.code}`);
        } else {
          this.options.onStatusChange('disconnected');
        }
      };
    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));
      this.options.onStatusChange('error', error.message);
      this.options.onError(error);
    }
  }

  public sendFrame(frameId: number, base64Image: string, capturedAt: string): boolean {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      return false;
    }

    const payload: FramePayload = {
      type: 'frame',
      session_id: this.sessionId,
      frame_id: frameId,
      captured_at: capturedAt,
      image_format: 'jpeg',
      image_base64: base64Image,
    };

    try {
      this.ws.send(JSON.stringify(payload));
      return true;
    } catch (sendErr) {
      console.error('Lỗi khi gửi frame qua WebSocket:', sendErr);
      return false;
    }
  }

  private handleIncomingMessage(data: unknown): void {
    if (!data || typeof data !== 'object') return;

    const payload = data as Partial<AnalysisResultPayload>;

    // Kiểm tra contract type
    if (payload.type !== 'analysis_result') {
      return;
    }

    // 1. Kiểm tra session_id
    if (payload.session_id !== this.sessionId) {
      console.warn('Bỏ qua kết quả không khớp session_id:', payload.session_id, 'vs', this.sessionId);
      return;
    }

    // 2. Bỏ qua frame cũ (out-of-order)
    if (typeof payload.frame_id === 'number') {
      if (payload.frame_id < this.lastReceivedFrameId) {
        console.warn('Bỏ qua frame cũ đến sau:', payload.frame_id, '<', this.lastReceivedFrameId);
        return;
      }
      this.lastReceivedFrameId = payload.frame_id;
    }

    // 3. Kiểm tra tính kịp thời (tránh frame trễ quá hạn)
    if (payload.captured_at) {
      const capturedTime = new Date(payload.captured_at).getTime();
      const now = Date.now();
      if (!isNaN(capturedTime) && (now - capturedTime > CONFIG.MAX_STALE_FRAME_MS)) {
        console.warn('Bỏ qua kết quả phân tích quá hạn (stale):', now - capturedTime, 'ms');
        return;
      }
    }

    this.options.onAnalysisResult(payload as AnalysisResultPayload);
  }

  public disconnect(): void {
    this.isIntentionallyClosed = true;
    if (this.ws) {
      try {
        this.ws.close();
      } catch {
        // ignore
      }
      this.ws = null;
    }
  }
}
