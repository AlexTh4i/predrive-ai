/**
 * AI chạy trực tiếp trên thiết bị (On-Device) — port từ ai/inference/analyzer.py.
 * Dùng MediaPipe FaceLandmarker (WASM) để tính EAR + hướng đầu, giữ nguyên ngưỡng và
 * logic thời gian của bản Python để kết quả hai bên nhất quán.
 */
import { FaceLandmarker, FilesetResolver } from '@mediapipe/tasks-vision';
import type { AlertLevel, DriverState, ImageQuality } from '../types/monitor';

export const ON_DEVICE_MODEL_VERSION = 'on-device-mediapipe-v0.1';

/** Ngưỡng — trùng với DriverMonitorAI trong ai/inference/analyzer.py và quality.py */
export const AI_CONFIG = {
  earThreshold: 0.28,
  drowsyWarningSec: 1.0,
  drowsyCriticalSec: 2.0,
  distractedSec: 1.8,
  tooDarkBrightness: 20,
  lowLightBrightness: 45,
} as const;

const LEFT_EYE = [33, 160, 158, 133, 153, 144] as const;
const RIGHT_EYE = [362, 385, 387, 263, 373, 380] as const;

export interface AnalysisResult {
  state: DriverState;
  alertLevel: AlertLevel;
  faceVisible: boolean;
  imageQuality: ImageQuality;
  /** EAR trung bình hai mắt (chỉ dùng để debug, không hiển thị cho tài xế) */
  ear: number | null;
  processingMs: number;
}

interface Point {
  x: number;
  y: number;
}

function distance(a: Point, b: Point): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function eyeAspectRatio(
  landmarks: Point[],
  indices: readonly number[],
  width: number,
  height: number,
): number {
  const p = indices.map((i) => ({ x: landmarks[i].x * width, y: landmarks[i].y * height }));
  const horizontal = distance(p[0], p[3]);
  if (horizontal < 1e-6) return 0;
  return (distance(p[1], p[5]) + distance(p[2], p[4])) / (2 * horizontal);
}

/** True = đầu hướng thẳng về phía trước (bình thường), False = quay ngang hoặc gục xuống */
function isFacingFront(landmarks: Point[]): boolean {
  const nose = landmarks[1];
  return !(nose.y > 0.72 || nose.x < 0.3 || nose.x > 0.7);
}

export class DriverAnalyzer {
  private landmarker: FaceLandmarker;
  private eyeClosedSince: number | null = null;
  private distractedSince: number | null = null;
  private qualityCanvas: HTMLCanvasElement;
  private qualityCtx: CanvasRenderingContext2D | null;

  private constructor(landmarker: FaceLandmarker) {
    this.landmarker = landmarker;
    this.qualityCanvas = document.createElement('canvas');
    this.qualityCanvas.width = 48;
    this.qualityCanvas.height = 36;
    this.qualityCtx = this.qualityCanvas.getContext('2d', { willReadFrequently: true });
  }

  /** Tải WASM + model từ thư mục public (hoạt động offline hoàn toàn trong app Android) */
  static async create(): Promise<DriverAnalyzer> {
    const base = import.meta.env.BASE_URL;
    const fileset = await FilesetResolver.forVisionTasks(`${base}mediapipe/wasm`);
    const landmarker = await FaceLandmarker.createFromOptions(fileset, {
      baseOptions: {
        modelAssetPath: `${base}models/face_landmarker.task`,
        // CPU ổn định hơn GPU trên WebView của nhiều dòng máy Android
        delegate: 'CPU',
      },
      runningMode: 'VIDEO',
      numFaces: 1,
    });
    return new DriverAnalyzer(landmarker);
  }

  reset(): void {
    this.eyeClosedSince = null;
    this.distractedSince = null;
  }

  close(): void {
    this.landmarker.close();
  }

  private measureQuality(video: HTMLVideoElement): ImageQuality {
    const ctx = this.qualityCtx;
    if (!ctx) return 'UNKNOWN';
    ctx.drawImage(video, 0, 0, 48, 36);
    const { data } = ctx.getImageData(0, 0, 48, 36);
    let sum = 0;
    for (let i = 0; i < data.length; i += 4) {
      sum += 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
    }
    const mean = sum / (data.length / 4);
    if (mean < AI_CONFIG.tooDarkBrightness) return 'TOO_DARK';
    if (mean < AI_CONFIG.lowLightBrightness) return 'LOW_LIGHT';
    return 'GOOD';
  }

  private unavailable(started: number, quality: ImageQuality, faceVisible: boolean): AnalysisResult {
    this.reset();
    return {
      state: 'MONITORING_UNAVAILABLE',
      alertLevel: 'NONE',
      faceVisible,
      imageQuality: quality,
      ear: null,
      processingMs: Math.round(performance.now() - started),
    };
  }

  analyze(video: HTMLVideoElement): AnalysisResult {
    const started = performance.now();
    const nowSec = started / 1000;

    if (video.readyState < 2 || !video.videoWidth || !video.videoHeight) {
      return this.unavailable(started, 'UNKNOWN', false);
    }

    // Quá tối thì không đoán mò — báo "không giám sát được", tuyệt đối không báo NORMAL
    const quality = this.measureQuality(video);
    if (quality === 'TOO_DARK') {
      return this.unavailable(started, quality, false);
    }

    let landmarks: Point[] | undefined;
    try {
      landmarks = this.landmarker.detectForVideo(video, started).faceLandmarks[0];
    } catch (err) {
      console.error('FaceLandmarker lỗi:', err);
      return this.unavailable(started, quality, false);
    }

    if (!landmarks) {
      return this.unavailable(started, quality, false);
    }

    const w = video.videoWidth;
    const h = video.videoHeight;
    const ear =
      (eyeAspectRatio(landmarks, LEFT_EYE, w, h) + eyeAspectRatio(landmarks, RIGHT_EYE, w, h)) / 2;

    if (ear < AI_CONFIG.earThreshold) {
      if (this.eyeClosedSince === null) this.eyeClosedSince = nowSec;
    } else {
      this.eyeClosedSince = null;
    }

    if (!isFacingFront(landmarks)) {
      if (this.distractedSince === null) this.distractedSince = nowSec;
    } else {
      this.distractedSince = null;
    }

    const closedFor = this.eyeClosedSince === null ? 0 : nowSec - this.eyeClosedSince;
    const distractedFor = this.distractedSince === null ? 0 : nowSec - this.distractedSince;

    let state: DriverState = 'NORMAL';
    let alertLevel: AlertLevel = 'NONE';
    if (closedFor >= AI_CONFIG.drowsyCriticalSec) {
      state = 'CRITICAL';
      alertLevel = 'CRITICAL';
    } else if (closedFor >= AI_CONFIG.drowsyWarningSec) {
      state = 'DROWSINESS_SIGNS';
      alertLevel = 'WARNING';
    } else if (distractedFor >= AI_CONFIG.distractedSec) {
      state = 'DISTRACTED';
      alertLevel = 'WARNING';
    }

    return {
      state,
      alertLevel,
      faceVisible: true,
      imageQuality: quality,
      ear: Math.round(ear * 1000) / 1000,
      processingMs: Math.round(performance.now() - started),
    };
  }
}

