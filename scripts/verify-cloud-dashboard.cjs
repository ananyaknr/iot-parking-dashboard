/* Read-only real Chrome acceptance against the existing native dashboard. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('../.tools/browser-check/node_modules/playwright');
const root = path.resolve(__dirname, '..');
let step = 'launch';
(async () => {
  const env = Object.fromEntries(fs.readFileSync(path.join(root,'.env'),'utf8').split(/\r?\n/)
    .filter(line=>line && !line.startsWith('#') && line.includes('='))
    .map(line=>[line.slice(0,line.indexOf('=')),line.slice(line.indexOf('=')+1)]));
  const browser = await chromium.launch({channel:'chrome',headless:true});
  try {
    const page = await browser.newPage({httpCredentials:{
      username:env.DASHBOARD_USERNAME || env.GRAFANA_USERNAME,
      password:env.DASHBOARD_PASSWORD || env.GRAFANA_PASSWORD}});
    const errors=[];page.on('pageerror',error=>errors.push(error.message));
    step = 'local dashboard';
    await page.goto('http://127.0.0.1:5000');
    await page.waitForFunction(()=>charts.length===4 && !historyBusy);
    await page.selectOption('#range','5');
    await page.waitForFunction(()=>!historyBusy);
    step = 'cloud charts';
    await page.selectOption('#history-source','cloud');
    await page.waitForFunction(()=>!historyBusy,{},{timeout:90000});
    assert.match(await page.locator('#history-status').innerText(),/Cloud archive/);
    step = 'fresh hardware cards';
    assert.match(await page.locator('#uno-status').innerText(),/Receiving/);
    assert.match(await page.locator('#esp32-status').innerText(),/Receiving/);
    assert.match(await page.locator('#storage-status').innerText(),/Connected/);
    step = 'actual cloud points';
    const numericPoints = await page.evaluate(()=>charts.map(chart=>
      chart.data.datasets.map(set=>set.data.filter(point=>Number.isFinite(point.y)).length)));
    assert.equal(numericPoints.length,4);
    assert.ok(numericPoints[1].every(count=>count>0),'Actual temperature/humidity cloud points required');
    assert.ok(numericPoints[2][0]>0 && numericPoints[3][0]>0);
    assert.deepEqual(errors,[]);
    const screenshot = '.runtime/cloud-dashboard-chrome.png';
    await page.screenshot({path:path.join(root,screenshot),fullPage:true});
    step = 'local history recovery';
    await page.selectOption('#history-source','local');
    await page.waitForFunction(()=>!historyBusy);
    assert.equal(await page.evaluate(()=>charts.length),4);
    assert.match(await page.locator('#history-status').innerText(),/Actual stored readings/);
    const receipt = {verified_at_utc:new Date().toISOString(),browser:'Chrome',
      cloud_numeric_points:numericPoints,live_sources:'Receiving',local_history_recovery:'PASS',
      javascript_errors:errors,screenshot};
    fs.writeFileSync(path.join(root,'.runtime/cloud-dashboard-verification.json'),JSON.stringify(receipt,null,2));
    console.log('PASS real Chrome: actual production cloud history, fresh hardware cards and local history recovery.');
    console.log(JSON.stringify(receipt,null,2));
  } finally {await browser.close();}
})().catch(()=>{console.error('Real dashboard acceptance failed at '+step+'; no credentials printed and no PASS claimed.');process.exitCode=1;});
