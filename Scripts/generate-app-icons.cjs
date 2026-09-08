// Run with Node and sharp installed: node Scripts/generate-app-icons.cjs
// The SVG is the single source for browser, Apple touch, and PWA icons.
const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');
const sharp = require('sharp');

async function main(){
  const root = path.resolve(__dirname, '..');
  const source = Buffer.from((await fs.readFile(path.join(root, 'icons/debripod-app-icon.svg'), 'utf8')).replace(/\r\n/g, '\n'));
  const output = path.join(root, 'debripod/static/icons');
  const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
  const assets = {};
  const images = new Map();
  for(const size of [16, 32, 180, 192, 512]){
    const png = await sharp(source, {density:1152}).resize(size, size).png().toBuffer();
    const name = `icon-${size}.png`;
    await fs.writeFile(path.join(output, name), png);
    assets[name] = hash(png);
    images.set(size, png);
  }
  // ICO supports PNG-compressed entries; include both favicon sizes.
  const sizes = [16, 32];
  const header = Buffer.alloc(6 + sizes.length * 16);
  header.writeUInt16LE(1, 2);
  header.writeUInt16LE(sizes.length, 4);
  let offset = header.length;
  sizes.forEach((size, index)=>{
    const entry = 6 + index * 16;
    header[entry] = header[entry + 1] = size;
    header.writeUInt16LE(1, entry + 4);
    header.writeUInt16LE(32, entry + 6);
    header.writeUInt32LE(images.get(size).length, entry + 8);
    header.writeUInt32LE(offset, entry + 12);
    offset += images.get(size).length;
  });
  const ico = Buffer.concat([header, ...sizes.map(size=>images.get(size))]);
  await fs.writeFile(path.join(output, 'favicon.ico'), ico);
  assets['favicon.ico'] = hash(ico);
  await fs.writeFile(path.join(output, 'app-icon-assets.json'), JSON.stringify({source:'icons/debripod-app-icon.svg', sha256:hash(source), assets}, null, 2) + '\n');
}
main().catch(error=>{ console.error(error); process.exitCode = 1; });
