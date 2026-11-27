const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
const {chromium}=require(path.join(root,'.tools/browser-check/node_modules/playwright'));
(async()=>{
 const env=Object.fromEntries(fs.readFileSync(path.join(root,'.env'),'utf8').split(/\r?\n/).filter(x=>x&&!x.startsWith('#')&&x.includes('=')).map(x=>[x.slice(0,x.indexOf('=')),x.slice(x.indexOf('=')+1)]));
 const browser=await chromium.launch({channel:'chrome',headless:true});
 try{
  const page=await browser.newPage({httpCredentials:{username:env.DASHBOARD_USERNAME||env.GRAFANA_USERNAME,password:env.DASHBOARD_PASSWORD||env.GRAFANA_PASSWORD}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:5001');
  await page.waitForFunction(()=>charts.length===6&&!historyBusy,null,{timeout:60000});
  const response=await page.request.get('http://127.0.0.1:5001/api/latest');assert.equal(response.status(),200);
  const data=await response.json();assert.equal(data.parking3.enabled,true);assert.equal(data.parking3.fresh,true);
  assert.equal(data.parking3.telemetry.servo_enabled,false);assert.equal(data.parking3.feedback_enabled,true);
  assert.match(await page.locator('#parking3-detail').innerText(),/Servo disabled/);
  assert.match(await page.locator('#parking3-command').innerText(),/teammate owned/);
  assert.equal(data.mqtt_connected,true);assert.equal(data.storage_connected,true);assert.deepEqual(errors,[]);
  const screenshot='.runtime/parking-v3-dashboard.png';await page.screenshot({path:path.join(root,screenshot),fullPage:true});
  const receipt={verified_at_utc:new Date().toISOString(),actual_browser:'Chrome',charts:6,separate_g3_fresh:true,
   servo_enabled:false,feedback_enabled:true,session_writes:0,js_errors:errors,screenshot,physical_cycle_acceptance:false};
  fs.writeFileSync(path.join(root,'.runtime/parking-v3-dashboard-receipt.json'),JSON.stringify(receipt,null,2));
  console.log(JSON.stringify(receipt));
 }finally{await browser.close();}
})().catch(e=>{console.error('Parking v3 browser verification failed: '+e.name);process.exitCode=1;});
