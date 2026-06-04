#!/usr/bin/env node
/**
 * Generate production installer icons (delegates to scripts/generate_installer_icons.py).
 */
const { execSync } = require('child_process');
const path = require('path');

const script = path.join(__dirname, 'scripts', 'generate_installer_icons.py');
try {
  execSync(`python "${script}"`, { stdio: 'inherit', cwd: __dirname });
} catch (e) {
  console.error('Icon generation failed. Install Pillow: pip install Pillow');
  process.exit(1);
}
