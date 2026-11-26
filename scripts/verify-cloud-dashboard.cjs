/* Read-only real Chrome acceptance against the existing native dashboard. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('../.tools/browser-check/node_modules/playwright');
const root = path.resolve(__dirname, '..');
const isolated = process.argv.includes('--isolated-gate');
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
    await page.goto('http://127.0.0.1:'+(isolated?'5001':'5000'));
    await page.waitForFunction(()=>charts.length===6 && !historyBusy);
    await page.selectOption('#range','30');
    await page.waitForFunction(()=>!historyBusy);
    step = 'cloud charts';
    await page.selectOption('#history-source','cloud');
    await page.waitForFunction(()=>!historyBusy,{},{timeout:90000});
    assert.match(await page.locator('#history-status').innerText(),/Cloud archive/);
    step = 'hardware status cards';
    const hardwareStatus = {};
    for (const source of ['uno','esp32']) {
      hardwareStatus[source] = await page.locator('#'+source+'-status').innerText();
      assert.match(hardwareStatus[source],/Receiving|Stale \/ Unknown/);
    }
    assert.match(await page.locator('#storage-status').innerText(),/Connected/);
    step = 'actual cloud points';
    const numericPoints = await page.evaluate(()=>charts.map(chart=>
      chart.data.datasets.map(set=>set.data.filter(point=>Number.isFinite(point.y)).length)));
    assert.equal(numericPoints.length,6);
    assert.ok(numericPoints[1].every(count=>count>0),'Actual temperature/humidity cloud points required');
    assert.ok(numericPoints[2][0]>0 && numericPoints[3][0]>0);
    assert.deepEqual(errors,[]);
    const screenshot = isolated?'.runtime/gate-cloud-dashboard-chrome.png':'.runtime/cloud-dashboard-chrome.png';
    await page.screenshot({path:path.join(root,screenshot),fullPage:true});
    step = 'local history recovery';
    await page.selectOption('#history-source','local');
    await page.waitForFunction(()=>!historyBusy);
    assert.equal(await page.evaluate(()=>charts.length),6);
    assert.match(await page.locator('#history-status').innerText(),/Actual stored readings/);
    const receipt = {verified_at_utc:new Date().toISOString(),browser:'Chrome',
      range_minutes:30,cloud_numeric_points:numericPoints,hardware_status:hardwareStatus,local_history_recovery:'PASS',
      javascript_errors:errors,screenshot};
    receipt.environment=isolated?'isolated_gate_test':'production';
    fs.writeFileSync(path.join(root,isolated?'.runtime/gate-cloud-dashboard-verification.json':'.runtime/cloud-dashboard-verification.json'),JSON.stringify(receipt,null,2));
    console.log('PASS real Chrome: actual '+receipt.environment+' environmental cloud history, hardware status cards and local history recovery.');
    console.log(JSON.stringify(receipt,null,2));
  } finally {await browser.close();}
})().catch(()=>{console.error('Real dashboard acceptance failed at '+step+'; no credentials printed and no PASS claimed.');process.exitCode=1;});
