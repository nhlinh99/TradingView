import { build } from 'esbuild';
import { writeFileSync, mkdirSync } from 'node:fs';

const r = await build({
  entryPoints: ['src/App.jsx'], bundle: true, write: false, minify: true, format: 'iife',
  outdir: 'out', jsx: 'automatic', loader: { '.css': 'css' },
  define: { 'process.env.NODE_ENV': '"production"' },
});
let js = '', css = '';
for (const f of r.outputFiles) { if (f.path.endsWith('.js')) js = f.text; else if (f.path.endsWith('.css')) css = f.text; }
js = js.replaceAll('</script', '<\\/script');
const html = `<!doctype html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kế hoạch chart cá nhân</title><style>${css}</style></head>
<body><div id="root"></div><script>${js}</script></body></html>`;
mkdirSync('../docs/plan', { recursive: true });
writeFileSync('../docs/plan/plan.html', html);
console.log('docs/plan/plan.html', (html.length / 1024).toFixed(0) + ' KB');
