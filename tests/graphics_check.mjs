import assert from 'node:assert/strict';
import fs from 'node:fs';
const src=fs.readFileSync(new URL('../meetingroom/static/graphics-check.js',import.meta.url),'utf8');
const {checkGraphics,requireGraphics,showGraphicsFailure}=await import('data:text/javascript;base64,'+Buffer.from(src).toString('base64'));
function canvas(options={}) {
 const calls={shaders:0,deleted:0,programs:0,freed:0,lost:0,removed:0};
 const gl={VERTEX_SHADER:1,FRAGMENT_SHADER:2,COMPILE_STATUS:3,LINK_STATUS:4,STENCIL_BITS:5,TRIANGLES:6,RGBA:7,UNSIGNED_BYTE:8,NO_ERROR:0,
 createShader(){calls.shaders++;return {}},shaderSource(){},compileShader(){},getShaderParameter(){return !options.shaderFails},deleteShader(){calls.deleted++},
 createProgram(){calls.programs++;return {}},attachShader(){},linkProgram(){},getProgramParameter(){return !options.linkFails},deleteProgram(){calls.freed++},
 getParameter(){return options.noStencil?0:8},useProgram(){},viewport(){},drawArrays(){},readPixels(x,y,w,h,format,type,pixel){pixel.set(options.badPixels?[0,0,0,0]:[51,204,102,255])},
 isContextLost(){return false},getError(){return 0},getExtension(){return {loseContext(){calls.lost++}}}};
 let listener;
 return {calls,addEventListener(name,fn){listener=fn},getContext(type,attrs){assert.equal(type,'webgl2');assert.equal(attrs.stencil,true);if(options.throws)throw Error('driver rejected context');if(options.unavailable){listener({statusMessage:'GPU disabled'});return null}return gl},remove(){calls.removed++}};
}
for(const options of [{},{shaderFails:true},{linkFails:true},{noStencil:true},{badPixels:true},{unavailable:true},{throws:true}]){
 const c=canvas(options),result=checkGraphics(()=>c);assert.equal(result.ok,Object.keys(options).length===0);
 assert.equal(c.calls.removed,1);if(!options.unavailable&&!options.throws){assert.equal(c.calls.lost,1);assert.equal(c.calls.deleted,c.calls.shaders);assert.equal(c.calls.freed,c.calls.programs)}
}
// Exercise the real blocking/retry UI with minimal DOM nodes; never access a real GPU.
let current=canvas({unavailable:true}),panel,download,blob,opened=0;const nodes=new Map();
function element(){return {hidden:false,textContent:'',focus(){},remove(){this.removed=true},setAttribute(){},click(){opened++},querySelector(id){if(!nodes.has(id))nodes.set(id,element());return nodes.get(id)}}}
globalThis.document={getElementById(){return null},createElement(tag){if(tag==='canvas')return current;const e=element();if(tag==='section')panel=e;if(tag==='a')download=e;return e},body:{append(){}}};
Object.defineProperty(globalThis,'navigator',{value:{userAgent:'Linux test browser'},configurable:true});
globalThis.location={origin:'http://127.0.0.1:8765',href:'http://127.0.0.1:8765/?t=private-secret',reload(){}};
URL.createObjectURL=b=>{blob=b;return 'blob:test'};URL.revokeObjectURL=()=>{};
const waiting=requireGraphics();let ready=false;waiting.then(()=>ready=true);await Promise.resolve();assert.equal(ready,false);
assert.equal(panel.querySelector('#graphicsLinux').hidden,false);
assert.equal(panel.querySelector('#graphicsDetail').textContent,'GPU disabled');
panel.querySelector('#graphicsDownload').onclick();const data=await blob.text();assert.ok(!data.includes('private-secret'));assert.equal(JSON.parse(data).origin,location.origin);assert.equal(download.download,'meetingroom-graphics.json');
current=canvas();panel.querySelector('#graphicsRetry').onclick();await waiting;assert.equal(ready,true);assert.equal(panel.removed,true);
showGraphicsFailure({detail:'<img src=x onerror=alert(1)>',ok:false});assert.ok(!panel.innerHTML.includes('onerror=alert'));assert.equal(panel.querySelector('#graphicsDetail').textContent,'<img src=x onerror=alert(1)>');
console.log('Graphics check: WebGL2, shader/link/stencil/draw failures, resource release, blocking/retry, safe error display and token-free diagnostics passed.');
