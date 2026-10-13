// Serves docs/ (the GitHub Pages site) for the browser tests, with the page's API
// address pointed at the local test API instead of the live one.
const http = require('http');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '../../../docs');
const PORT = Number(process.env.PORT || 8088);
const API_BASE = process.env.API_BASE || 'http://127.0.0.1:5055';
const LIVE_API = /const API_BASE = "https:\/\/[^"]+";/;
const TYPES = { '.html': 'text/html; charset=utf-8', '.png': 'image/png', '.css': 'text/css', '.js': 'text/javascript' };

http.createServer((req, res) => {
  const url = new URL(req.url, 'http://localhost');
  const file = path.join(ROOT, url.pathname.endsWith('/') ? url.pathname + 'index.html' : url.pathname);
  if (!file.startsWith(ROOT) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
    res.writeHead(404).end('not found');
    return;
  }
  let body = fs.readFileSync(file);
  if (file.endsWith('index.html')) {
    const html = body.toString('utf8');
    if (!LIVE_API.test(html)) throw new Error('API_BASE line not found in docs/index.html');
    body = html.replace(LIVE_API, `const API_BASE = "${API_BASE}";`);
  }
  res.writeHead(200, { 'Content-Type': TYPES[path.extname(file)] || 'application/octet-stream' }).end(body);
}).listen(PORT, '127.0.0.1', () => console.log(`site on http://127.0.0.1:${PORT} (API ${API_BASE})`));
