/* Real Chromium rendering against synthetic HTTP fixtures only.
   npm install --prefix .tools/browser-check --no-audit --no-fund playwright
   node scripts/test-dashboard.cjs
*/
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { chromium } = require('../.tools/browser-check/node_modules/playwright');
const root = path.resolve(__dirname, '..');
let failHistory = false, failLive = false;
const source = {fresh:true,payload_valid:true,a1_state:1,a1_allocation_eligible:true,
  a1_distance_cm:30,a1_distance_cm_valid:true,camera_state:0};
const server = http.createServer((req,res) => {
  const url = new URL(req.url, 'http://localhost');
  if (url.pathname === '/api/latest') {
    res.writeHead(failLive?503:200, {'Content-Type':'application/json'});
    return res.end(JSON.stringify({received_at_utc:new Date().toISOString(),mqtt_connected:true,
      storage_connected:false,ingestion_connected:true,storage_backlog:10,
      sources:{uno:source,esp32:source,camera:{fresh:false,payload_valid:false,camera_state:0}}}));
  }
  if (url.pathname === '/api/history') {
    res.writeHead(failHistory?503:200, {'Content-Type':'application/json'});
    const stop = Date.parse('2026-11-26T00:15:00Z');
    const span = Number(url.searchParams.get('minutes'))*60000;
    const offset = url.searchParams.get('field') === 'humidity_pct' ? 17000 : 0;
    return res.end(JSON.stringify({points:[{time:new Date(stop-span+offset).toISOString(),value:30},
      {time:new Date(stop-span/2+offset).toISOString(),value:null},
      {time:new Date(stop+offset).toISOString(),value:25}]}));
  }
  const file = url.pathname === '/' ? 'dashboard/templates/index.html'
    : url.pathname.startsWith('/static/') ? 'dashboard/'+url.pathname.slice(1) : '';
  if (!file || file.includes('..')) {res.writeHead(404);return res.end();}
  res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');
  res.end(fs.readFileSync(path.join(root,file)));
});
(async()=>{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const browser = await chromium.launch({channel:'chrome',headless:true});
  try {
    const page = await browser.newPage();
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    await page.waitForFunction(()=>charts.length===4);
    for (const range of ['30','1440','10080']) {
      await page.selectOption('#range',range);
      await page.waitForFunction(()=>!historyBusy);
      const result=await page.evaluate(()=>({type:charts[1].options.scales.x.type,
        sets:charts[1].data.datasets.map(d=>d.data),span:charts[1].data.datasets[0].spanGaps,
        width:charts[1].width}));
      assert.equal(result.type,'linear');assert.equal(result.span,false);assert.ok(result.width>0);
      assert.equal(result.sets[0][1].y,null);
      assert.equal(result.sets[1][0].x-result.sets[0][0].x,17000);
      assert.ok(result.sets[0][2].x>result.sets[0][0].x);
    }
    assert.match(await page.locator('#mqtt-status').innerText(),/Connected/);
    assert.match(await page.locator('#storage-status').innerText(),/Unavailable/);
    failHistory=true;
    await page.evaluate(()=>history());
    assert.equal(await page.evaluate(()=>charts.length),0);
    assert.match(await page.locator('#history-status').innerText(),/History unavailable/);
    failLive=true;await page.evaluate(()=>live());
    assert.equal(await page.locator('#a1-state').innerText(),'Unknown');
    failLive=false;failHistory=false;
    await page.evaluate(async()=>{await live();await history();});
    assert.equal(await page.evaluate(()=>charts.length),4);
    await page.reload();await page.waitForFunction(()=>charts.length===4);
    await page.setViewportSize({width:390,height:844});
    await page.waitForTimeout(300);
    await page.screenshot({path:path.join(root,'.tools/browser-check/dashboard.png'),fullPage:true});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    assert.deepEqual(errors,[]);
    console.log('PASS real Chromium: midnight/multiday/7-day axes, independent series, null gaps, health, HTTP failures, recovery, refresh, mobile width');
  } finally {await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
