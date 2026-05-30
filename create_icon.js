#!/usr/bin/env node
/**
 * Generate a simple ICO file for SentinelAI
 * Creates a 32x32 dark blue icon with green accent
 *
 * Note: This is a minimal valid ICO file structure.
 * For production, replace with a proper branded icon.
 */

const fs = require('fs');
const path = require('path');

// Ensure assets directory exists
const assetsDir = path.join(__dirname, 'desktop-shell', 'assets');
if (!fs.existsSync(assetsDir)) {
  fs.mkdirSync(assetsDir, { recursive: true });
}

// Minimal valid 32x32 32-bit BMP ICO file
// This is a placeholder - create a simple dark blue square with green accent
const icoData = Buffer.from([
  0x00, 0x00, // Reserved
  0x01, 0x00, // Type (1 = ICO)
  0x01, 0x00, // Number of images

  // Image directory entry (32x32 32-bit)
  0x20, // Width (32)
  0x20, // Height (32)
  0x00, // Palette colors (0 = no palette)
  0x00, // Reserved
  0x01, 0x00, // Color planes
  0x20, 0x00, // Bits per pixel (32)
  0xE0, 0x00, 0x00, 0x00, // Image size
  0x16, 0x00, 0x00, 0x00, // Image offset
]);

// Create minimal BMP data for 32x32 image
// BMP header (40 bytes)
const bmpHeader = Buffer.from([
  0x28, 0x00, 0x00, 0x00, // Header size
  0x20, 0x00, 0x00, 0x00, // Width (32)
  0x40, 0x00, 0x00, 0x00, // Height (64, double for ICO)
  0x01, 0x00, // Planes
  0x20, 0x00, // Bits per pixel (32)
  0x00, 0x00, 0x00, 0x00, // Compression
  0x00, 0x01, 0x00, 0x00, // Image size
  0x00, 0x00, 0x00, 0x00, // X pixels per meter
  0x00, 0x00, 0x00, 0x00, // Y pixels per meter
  0x00, 0x00, 0x00, 0x00, // Colors used
  0x00, 0x00, 0x00, 0x00, // Important colors
]);

// Create image data (32x32 pixels x 4 bytes per pixel = 4096 bytes)
// Dark blue (#0a0a2e) with green accent (#00ff88)
const imageData = Buffer.alloc(4096);
for (let i = 0; i < 4096; i += 4) {
  const pixelIndex = i / 4;
  const x = pixelIndex % 32;
  const y = Math.floor(pixelIndex / 32);

  // Create a simple pattern: blue background with green border
  if (x < 3 || x > 28 || y < 3 || y > 28) {
    // Green border
    imageData[i] = 0x88; // B
    imageData[i + 1] = 0xff; // G
    imageData[i + 2] = 0x00; // R
    imageData[i + 3] = 0xff; // A
  } else {
    // Dark blue background
    imageData[i] = 0x2e; // B
    imageData[i + 1] = 0x0a; // G
    imageData[i + 2] = 0x0a; // R
    imageData[i + 3] = 0xff; // A
  }
}

// Combine all parts
const ico = Buffer.concat([icoData, bmpHeader, imageData]);

// Write to file
const iconPath = path.join(assetsDir, 'icon.ico');
fs.writeFileSync(iconPath, ico);

console.log(`✓ Icon created: ${iconPath}`);
console.log(`  Size: ${ico.length} bytes`);
console.log(`  Note: This is a placeholder. Replace with branded icon for production.`);
