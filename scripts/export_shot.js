// CDP screenshot helper for the nightly brief image export.
// Usage: node export_shot.js <html_file> <out_png> <width_css_px> <dsf>
// Drives Chromium over CDP (headless --screenshot can hang in some VMs).
// CHROME_BIN below points at the Muse VM's bundled chromium — adjust
// if yours lives elsewhere.
const { spawn } = require('child_process');
const fs = require('fs');
const http = require('http');

const [htmlFile, outPng, widthArg, dsfArg] = process.argv.slice(2);
const WIDTH = parseInt(widthArg || '600', 10);
const DSF = parseFloat(dsfArg || '3');
const PORT = 9400 + (process.pid % 400);

const CHROME_BIN = process.env.CHROME_BIN || '/opt/meta-chromium/chrome';
const chrome = spawn(CHROME_BIN, [
  '--headless=new', '--disable-gpu', '--no-sandbox', '--no-first-run',
  '--disable-dev-shm-usage', '--disable-component-update',
  '--user-data-dir=/tmp/chrome-cdp-' + process.pid,
  '--remote-debugging-port=' + PORT,
  '--window-size=' + WIDTH + ',2400', 'about:blank'
], { stdio: 'ignore' });

function getJSON(path) {
  return new Promise((res, rej) => {
    http.get({ host: '127.0.0.1', port: PORT, path }, r => {
      let d = ''; r.on('data', c => d += c);
      r.on('end', () => { try { res(JSON.parse(d)); } catch (e) { rej(e); } });
    }).on('error', rej);
  });
}
const sleep = ms => new Promise(r => setTimeout(r, ms));

(async () => {
  let targets = null;
  for (let i = 0; i < 60; i++) {
    try { targets = await getJSON('/json/list'); if (targets && targets.length) break; } catch (e) {}
    await sleep(300);
  }
  if (!targets) throw new Error('no devtools targets');
  const page = targets.find(t => t.type === 'page');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise(r => ws.onopen = r);
  let id = 0; const pending = new Map();
  ws.onmessage = ev => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m.result); pending.delete(m.id); }
  };
  const send = (method, params = {}) => new Promise(r => {
    const i = ++id; pending.set(i, r);
    ws.send(JSON.stringify({ id: i, method, params }));
  });
  await send('Page.enable');
  await send('Emulation.setDeviceMetricsOverride',
    { width: WIDTH, height: 2400, deviceScaleFactor: DSF, mobile: false });
  await send('Page.navigate', { url: 'file://' + htmlFile });
  await sleep(2500);
  const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
  fs.writeFileSync(outPng, Buffer.from(shot.data, 'base64'));
  console.log('saved', outPng);
  ws.close(); chrome.kill('SIGKILL');
  process.exit(0);
})().catch(e => {
  console.error('ERR', e.message);
  try { chrome.kill('SIGKILL'); } catch (_) {}
  process.exit(1);
});
