import { cpSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const rootDir = resolve(__dirname, '..');

const wasmSrc = resolve(rootDir, 'node_modules/@mediapipe/tasks-vision/wasm');
const wasmDest = resolve(rootDir, 'public/mediapipe/wasm');
mkdirSync(wasmDest, { recursive: true });
cpSync(wasmSrc, wasmDest, { recursive: true });

const modelSrc = resolve(rootDir, '../ai/models/face_landmarker.task');
const modelDest = resolve(rootDir, 'public/models/face_landmarker.task');
mkdirSync(dirname(modelDest), { recursive: true });
cpSync(modelSrc, modelDest);

console.log('Copied MediaPipe WASM and face_landmarker.task to public/');

