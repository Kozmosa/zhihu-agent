'use strict';
const path = require('node:path');
const fs = require('node:fs');
const esbuild = require('esbuild');
const root = path.resolve(__dirname, '..');
esbuild.buildSync({
  absWorkingDir: root,
  entryPoints: ['src/zhijing/web/opinion-flow.jsx'],
  outfile: 'src/zhijing/web/opinion-flow.js',
  bundle: true,
  minify: true,
  format: 'iife',
  platform: 'browser',
  target: ['es2020'],
  define: {'process.env.NODE_ENV': '"production"'},
  jsx: 'automatic',
  legalComments: 'inline',
  sourcemap: false,
});
// Distribute licenses with the prebuilt offline bundle, including transitive packages.
const lock = JSON.parse(fs.readFileSync(path.join(root, 'package-lock.json'), 'utf8'));
const notices = ['# 知识地图前端依赖许可', '', '本地打包的 React Flow / React 依赖，无运行时 CDN 请求。'];
for (const [location, metadata] of Object.entries(lock.packages)) {
  if (!location || metadata.dev || metadata.optional) continue;
  const dir = path.join(root, location);
  const license = fs.readdirSync(dir).find(name => /^licen[cs]e(\.|$)/i.test(name));
  if (!license) throw new Error('License file missing: ' + location);
  notices.push('', '## ' + location.replace(/^node_modules\//, '') + ' ' + metadata.version,
    '', fs.readFileSync(path.join(dir, license), 'utf8'));
}
fs.writeFileSync(path.join(root, 'src/zhijing/web/ATTRIBUTION.md'), notices.join('\n'));
console.log('Built offline xyflow bundle and dependency notices.');
