// Loads Playwright from the project if installed, otherwise from the global
// npm root (the render machine ships a preinstalled Playwright + Chromium).
import { createRequire } from 'node:module';
import { execSync } from 'node:child_process';
import path from 'node:path';

const require = createRequire(import.meta.url);
let pw;
try {
  pw = require('playwright');
} catch {
  const root = execSync('npm root -g').toString().trim();
  pw = require(path.join(root, 'playwright'));
}
export const chromium = pw.chromium;

// SwiftShader WebGL2 works headless without a GPU; a real GPU is used if present.
export const GL_ARGS = ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--disable-gpu-vsync'];
