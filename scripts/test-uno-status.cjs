/* Focused display test in Node, without a browser or hardware access. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../dashboard/static/app.js'), 'utf8');
const nodes = new Map();
const node = id => {
  if (!nodes.has(id)) nodes.set(id, {textContent:'', innerHTML:'', hidden:false});
  return nodes.get(id);
};
const context = vm.createContext({$:node, latestData:null, fmtTime:()=>''});
vm.runInContext(source.slice(source.indexOf('const P3_PHASE='), source.indexOf('function unavailable()')), context);
const telemetry = {phase:5,reason:7,lane:0,cycle:0,u1_distance_cm:10,u1_state:'detected',
  u2_distance_cm:32,u2_state:'clear',minimum_open_ms:5000};
context.current = {enabled:true,fresh:true,pending_feedback:0};
context.telemetry = telemetry;
vm.runInContext('renderG3(current,telemetry)',context);
assert.match(node('p3-link').textContent,/Connected/);
assert.match(node('p3-u1').textContent,/Detected.*10 cm/);
assert.match(node('p3-u2').textContent,/Clear.*32 cm/);
assert.match(node('parking3-status').textContent,/Hold/);
assert.equal(node('legacy-gate-panel').hidden,true);
assert.equal(node('gate-source-note').hidden,true);
telemetry.u1_distance_cm=null;telemetry.u1_state='unknown';
vm.runInContext('renderG3(current,telemetry)',context);
assert.match(node('p3-link').textContent,/Connected/);
assert.match(node('p3-u1').textContent,/No echo/);
vm.runInContext('renderG3({enabled:true},null)',context);
assert.match(node('p3-link').textContent,/Stale/);
vm.runInContext('renderG3({enabled:false},null)',context);
assert.equal(node('legacy-gate-panel').hidden,false);
assert.equal(node('gate-source-note').hidden,false);
vm.runInContext(source.slice(source.indexOf('const TOPIC_ROWS='),source.indexOf('function renderDevices()')),context);
context.latestData={parking3:{enabled:true,fresh:true},sources:{gate:{},uno:{}},mqtt_connected:true};
vm.runInContext('renderTopics()',context);
assert.match(node('topic-body').innerHTML,/Current G3 telemetry/);
assert.equal((node('topic-body').innerHTML.match(/Inactive legacy schema/g)||[]).length,2);
console.log('UNO display checks passed: connected vs no echo, stale, legacy routing and G3 topics.');
