import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source = fs.readFileSync(new URL('../meetingroom/static/room3d.js', import.meta.url), 'utf8');
const section = (start, end) => source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start)));
const stored = new Map();
const context = {
  location: {pathname:'/r/alpha/'},
  localStorage: {getItem:k=>stored.get(k) ?? null, setItem:(k,v)=>stored.set(k,v)},
  performance: {now:()=>10000},
};
vm.createContext(context);
const loader = section('  // One snapshot per room', '  const renderer =');
const saver = section('  function saveState()', '  window.addEventListener("pagehide"');
const pos = {toArray:()=>[0.1, -0.26, 0.66]};
context.chars = new Map([['kenji', {pos,yaw:3.14,sit:1,lean:0,walk:0,phase:2,doze:0,lastActive:8000,atComputer:true,arrived:true}]]);
context.seatOwner = 'kenji'; context.leanSpots = new Map([['other', 0]]);
context.dayTarget = 1;
context.jukebox = {snapshot:()=>({playing:true,step:23})};
vm.runInContext(`{ ${loader}\n${saver}\nsaveState(); }`, context);
const snapshot = JSON.parse(stored.get('mr_roomstate_v1:/r/alpha'));
assert.equal(snapshot.agents.kenji.inactiveMs, 2000);
assert.equal(snapshot.agents.kenji.atComputer, true);
assert.equal(snapshot.music.playing, true);
assert.equal(snapshot.music.step, 23);
assert.equal(snapshot.seatOwner, 'kenji');
assert.equal(snapshot.day, 1);
assert.equal(snapshot.agents.kenji.status, undefined);
vm.runInContext(`{ ${loader}; globalThis.restored = saved; }`, context);
assert.equal(context.restored.agents.kenji.sit, 1);
context.location.pathname = '/r/beta';
vm.runInContext(`{ ${loader}; globalThis.restored = saved; }`, context);
assert.equal(Object.keys(context.restored).length, 0);
stored.set('mr_roomstate_v1:/r/beta', '{broken');
vm.runInContext(`{ ${loader}; globalThis.restored = saved; }`, context);
assert.equal(Object.keys(context.restored).length, 0);
context.localStorage.setItem = () => {throw Error('blocked')};
vm.runInContext(`{ ${loader}\n${saver}\nsaveState(); }`, context);
console.log('Snapshots: room isolation, positions, poses, PC occupancy, music, corrupt/blocked storage passed.');

// Exercise real restored-agent fields without requiring WebGL.
const restore = section('        const prior = saved.agents', '        chars.set(a.name, c);');
const c = {pos:{fromArray(v){this.value=v}}, rig:{root:{rotation:{}}}, lastActive:10000};
vm.runInNewContext(restore, {saved:snapshot, a:{name:'kenji'}, c});
assert.deepEqual(c.pos.value, [0.1,-0.26,0.66]);
assert.equal(c.sit, 1); assert.equal(c.atComputer, true); assert.equal(c.lastActive, 8000);
assert.equal(c.rig.root.rotation.y, 3.14);
console.log('Agent restoration: saved position, seated pose, yaw, inactivity and PC latch passed.');

const events = new Map(); let timers = 0, changes = 0;
const param = {setValueAtTime(){},linearRampToValueAtTime(){},exponentialRampToValueAtTime(){},setTargetAtTime(){},cancelScheduledValues(){}};
let allowAudio = false;
class AudioContext {
  currentTime = 0; state = 'suspended'; destination = {};
  resume(){ if(allowAudio) this.state='running'; return Promise.resolve(); }
  createGain(){return {gain:param, connect(){}};}
  createOscillator(){return {frequency:{},connect(){},start(){},stop(){}};}
  createBiquadFilter(){return {frequency:{},connect(){}};}
}
const audioContext = {window:{AudioContext, addEventListener(){}}, document:{addEventListener:(e,f)=>events.set(e,f)}, localStorage:{getItem:()=>null}, setInterval:()=>++timers, clearInterval:()=>timers--};
vm.createContext(audioContext);
vm.runInContext(section('function createJukebox(', '\n\nexport function createRoom')+'\nglobalThis.make = createJukebox;', audioContext);
const music = audioContext.make({playing:true, step:23}, ()=>changes++);
await Promise.resolve();
assert.equal(music.playing,true); assert.equal(timers,0);
allowAudio = true; events.get('pointerdown')(); await Promise.resolve();
assert.equal(timers,1); assert.ok(music.snapshot().step > 23);
events.get('keydown')(); await Promise.resolve(); assert.equal(timers,1);
music.toggle(); assert.equal(music.playing,false); assert.equal(timers,0);
events.get('pointerdown')(); await Promise.resolve(); assert.equal(timers,0);
music.toggle(); await Promise.resolve(); assert.equal(timers,1); assert.equal(changes,2);
console.log('Music: autoplay suspension, gesture resume, saved sequence, single scheduler and persisted toggles passed.');
