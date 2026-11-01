import assert from 'node:assert/strict';
import fs from 'node:fs';

// Exercise the actual scheduling gate without needing a GPU or a browser.
const source = fs.readFileSync(new URL('../meetingroom/static/room3d.js', import.meta.url), 'utf8');
const start = source.indexOf('  const frameInterval =');
const gate = source.slice(start, source.indexOf('    const dt =', start));
const simulate = new Function('hz', 'document', 'wrap', 'performance', 'requestAnimationFrame',
  gate + '\ncount++;\n}\nlet count=0; for(let n=1;n<=hz*10;n++) frame(n*1000/hz); return count;');
for (const hz of [60, 120, 144]) {
  const run = (hidden, width) => simulate(hz, {hidden}, {clientWidth:width, clientHeight:100}, {now:()=>0}, ()=>{});
  const count = run(false, 100);
  assert.ok(count >= 299 && count <= 301, `${hz} Hz produced ${count} frames`);
  assert.equal(run(true, 100), 0);
  assert.equal(run(false, 0), 0);
  console.log(`${hz} Hz: ${count} rendered frames in 10 seconds; hidden/collapsed: 0`);
}
