// Serves docs/ (the GitHub Pages site) for the browser tests. A page served from this
// computer talks to the API on this computer (LOCAL_API in docs/js/config.js); here
// that address is changed to the test API's.
const http = require('http');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '../../../docs');
const PORT = Number(process.env.PORT || 8088);
const API_BASE = process.env.API_BASE || 'http://127.0.0.1:5055';
const CONFIG = path.join(ROOT, 'js', 'config.js');
const LOCAL_API = /export const LOCAL_API = "[^"]+";/;
const TYPES = { '.html': 'text/html; charset=utf-8', '.png': 'image/png', '.css': 'text/css', '.js': 'text/javascript' };

http.createServer((req, res) => {
  const url = new URL(req.url, 'http://localhost');
  const file = path.join(ROOT, url.pathname.endsWith('/') ? url.pathname + 'index.html' : url.pathname);
  if (!file.startsWith(ROOT) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
    res.writeHead(404).end('not found');
    return;
  }
  let body = fs.readFileSync(file);
  if (file === CONFIG) {
    const js = body.toString('utf8');
    if (!LOCAL_API.test(js)) throw new Error('LOCAL_API line not found in docs/js/config.js');
    body = js.replace(LOCAL_API, `export const LOCAL_API = "${API_BASE}";`);
  }
  res.writeHead(200, { 'Content-Type': TYPES[path.extname(file)] || 'application/octet-stream' }).end(body);
}).listen(PORT, '127.0.0.1', () => console.log(`site on http://127.0.0.1:${PORT} (API ${API_BASE})`));
