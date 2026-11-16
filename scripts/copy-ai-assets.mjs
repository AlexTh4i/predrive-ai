import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const root = path.resolve(__dirname, '..');

const modelSrc = path.join(root, 'ai', 'models', 'face_landmarker.task');
const modelDestDir = path.join(root, 'frontend', 'public', 'models');
const modelDest = path.join(modelDestDir, 'face_landmarker.task');

const wasmSrcDir = path.join(root, 'frontend', 'node_modules', '@mediapipe', 'tasks-vision', 'wasm');
const wasmDestDir = path.join(root, 'frontend', 'public', 'mediapipe', 'wasm');

// 1. Copy face_landmarker.task
if (fs.existsSync(modelSrc)) {
  fs.mkdirSync(modelDestDir, { recursive: true });
  fs.copyFileSync(modelSrc, modelDest);
  console.log('✓ Đã đồng bộ model AI vào frontend/public/models/face_landmarker.task');
} else {
  console.warn('⚠ Không tìm thấy file model gốc tại:', modelSrc);
}

// 2. Copy MediaPipe WASM assets
if (fs.existsSync(wasmSrcDir)) {
  fs.mkdirSync(wasmDestDir, { recursive: true });
  const files = fs.readdirSync(wasmSrcDir);
  for (const file of files) {
    fs.copyFileSync(path.join(wasmSrcDir, file), path.join(wasmDestDir, file));
  }
  console.log(`✓ Đã đồng bộ ${files.length} tệp MediaPipe WASM vào frontend/public/mediapipe/wasm/`);
} else {
  console.warn('⚠ Không tìm thấy thư mục wasm trong node_modules:', wasmSrcDir);
}

