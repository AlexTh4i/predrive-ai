/**
 * PREDRIVE AI — Contract & Monitor Types (MVP v0.1)
 * Tuân thủ tuyệt đối PROJECT_CONTEXT.md, FRONTEND_CONTEXT.md và BACKEND_CONTEXT.md
 */

export type DriverState = 
  | 'NOT_EVALUATED'
  | 'NORMAL'
  | 'DISTRACTED'
  | 'DROWSINESS_SIGNS'
  | 'CRITICAL'
  | 'MONITORING_UNAVAILABLE';

export type AlertLevel = 
  | 'NONE'
  | 'INFO'
  | 'WARNING'
  | 'CRITICAL';

export type ImageQuality = 
  | 'GOOD'
  | 'LOW_LIGHT'
  | 'BLURRY'
  | 'TOO_DARK'
  | 'UNKNOWN';

export type UnavailableReason = 
  | 'not_started'
  | 'camera_denied'
  | 'camera_not_found'
  | 'camera_in_use'
  | 'camera_stopped'
  | 'tab_hidden'
  | 'network_lost'
  | 'stale_result'
  | 'server_error'
  | 'insecure_context';

export type BackendConnectionStatus = 
  | 'disconnected'
  | 'connecting'
  | 'connected'
  | 'error'
  | 'mock_demo';

export interface FramePayload {
  type: 'frame';
  session_id: string;
  frame_id: number;
  captured_at: string; // ISO 8601 UTC
  image_format: 'jpeg';
  image_base64: string;
}

export interface AnalysisResultPayload {
  type: 'analysis_result';
  session_id: string;
  frame_id: number;
  captured_at: string;
  processed_at: string;
  model_version: string;
  state: DriverState;
  alert_level: AlertLevel;
  face_visible: boolean | null;
  image_quality: ImageQuality;
  risk_score: number | null;
  processing_ms: number;
}

export interface SessionResponse {
  session_id: string;
  created_at: string;
}

export interface SystemDiagnostics {
  fps: number;
  rttMs: number | null;
  framesSent: number;
  framesReceived: number;
  lastCapturedAt: string | null;
  lastProcessedAt: string | null;
  modelVersion: string;
  imageQuality: ImageQuality;
  processingMs: number | null;
}

