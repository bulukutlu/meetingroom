import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const page = fs.readFileSync(new URL('../meetingroom/static/index.html', import.meta.url), 'utf8');
const esc = page.slice(page.indexOf('const esc ='), page.indexOf('\nconst personOf'));
const markdown = page.slice(page.indexOf('function md(src)'), page.indexOf('// ---------------- sounds:'));
const ctx = vm.createContext({});
vm.runInContext(esc + '\n' + markdown + '\nglobalThis.render = {md, mdDoc};', ctx);
for (const input of [
  '<img src=x onerror="alert(1)">',
  '<script>fetch("/api/rooms")</script>',
  '[click](javascript:alert(1))',
  '[click](https://example.com/" onclick="alert(1))',
  'https://example.com/" onmouseover="alert(1)',
  '| A | B |\n| -- | -- |\n| <svg onload="alert(1)"> | safe |',
  '```html\n<img src=x onerror="alert(1)">\n```',
]) {
  for (const render of Object.values(ctx.render)) {
    const html = render(input);
    assert.doesNotMatch(html, /<(?:script|img|svg)\b/i);
    assert.doesNotMatch(html, /href="javascript:/i);
    assert.doesNotMatch(html, /"\s+on(?:click|mouseover|error|load)=/i);
  }
}
assert.match(ctx.render.mdDoc('[Safe](https://example.com)'), /href="https:\/\/example.com"/);
console.log('Rendering checks passed: hostile HTML, code, links and table cells remain inert.');
