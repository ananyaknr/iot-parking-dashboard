const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
const {chromium}=require(path.join(root,'.tools/browser-check/node_modules/playwright'));
(async()=>{
 const env=Object.fromEntries(fs.readFileSync(path.join(root,'.env'),'utf8').split(/\r?\n/).filter(x=>x&&!x.startsWith('#')&&x.includes('=')).map(x=>[x.slice(0,x.indexOf('=')),x.slice(x.indexOf('=')+1)]));
 const browser=await chromium.launch({channel:'chrome',headless:true});
 const receipts=[];
 try{
  for(const port of [5000,5001]){
   const page=await browser.newPage({httpCredentials:{username:env.DASHBOARD_USERNAME||env.GRAFANA_USERNAME,password:env.DASHBOARD_PASSWORD||env.GRAFANA_PASSWORD}});
   const errors=[];page.on('pageerror',e=>errors.push(e.message));
   await page.goto('http://127.0.0.1:'+port);
   await page.waitForFunction(()=>charts.length===6&&!historyBusy,null,{timeout:60000});
   const r=await page.request.get('http://127.0.0.1:'+port+'/api/latest');
   assert.equal(r.status(),200);const state=await r.json();
   assert.equal(state.mqtt_connected,true);assert.equal(state.storage_connected,true);
   assert.equal(state.gate_routing,port===5000?'off':'isolated');
   if(!state.sources.gate.fresh)assert.equal(await page.locator('#gate-sim-state').innerText(),'Unknown');
   else assert.equal(state.sources.gate.servo_enabled,false);
   assert.deepEqual(errors,[]);
   const shot='.runtime/native-gate-ui-'+port+'.png';await page.screenshot({path:path.join(root,shot),fullPage:true});
   receipts.push({port,mqtt:true,storage:true,charts:6,routing:state.gate_routing,gate_fresh:state.sources.gate.fresh,environment_fresh:state.sources.esp32.fresh,screenshot:shot});
   await page.close();
  }
  fs.writeFileSync(path.join(root,'.runtime/native-gate-ui-verification.json'),JSON.stringify({verified_at_utc:new Date().toISOString(),receipts,physical_gate_acceptance:false},null,2));
  console.log('PASS actual Chrome: both native dashboards, six history charts, broker/database connected, absent gate visibly unknown; no physical acceptance.');
  console.log(JSON.stringify(receipts));
 }finally{await browser.close();}
})().catch(()=>{console.error('Native dashboard check failed; no credentials printed.');process.exitCode=1;});
