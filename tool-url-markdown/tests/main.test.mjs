// Offline source-linked tests. No browser, network, installed HTML dependencies or user config.
// Run: node --experimental-vm-modules --test tests/main.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { stripTypeScriptTypes } from 'node:module';
import * as fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { EventEmitter } from 'node:events';
import { PassThrough } from 'node:stream';

const skill = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const htmlSource = await fs.readFile(path.join(skill, 'scripts/html-to-markdown.ts'), 'utf8');
const extractionScript = htmlSource.match(/const cleanupAndExtractScriptBody = String.raw`([\s\S]*?)`;/)[1];

async function fixture(options = {}) {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'tool-url-markdown-test-'));
  const calls = [], launches = [], diagnostics = [], output = [];
  const input = new PassThrough();
  const stderr = new PassThrough();
  let socket, child;
  let bodyStarted = false, requestSignal;
  const fakeProcess = Object.assign(new EventEmitter(), {
    argv: ['node'], env: { URL_CHROME_PROFILE_DIR: path.join(directory, 'ignored-env-profile') }, platform: 'win32', stdin: input, stderr,
    stdout: { write: text => { output.push(text); return true; } }, cwd: () => directory
  });
  class FakeWebSocket extends EventTarget {
    constructor() { super(); socket = this; queueMicrotask(() => this.dispatchEvent(new Event('open'))); }
    close() { this.dispatchEvent(new Event('close')); }
    send(raw) {
      const msg = JSON.parse(raw); calls.push(msg);
      if (options.interruptMethod === msg.method) queueMicrotask(() => fakeProcess.emit("SIGINT"));
      let result = {};
      if (options.failMethod === msg.method) return this.reply({ id: msg.id, error: { message: 'native mocked failure' } });
      if (msg.method === 'Target.createTarget') result = { targetId: options.missingId ? '' : 'created' };
      if (msg.method === 'Target.getTargets') result = { targetInfos: options.targets ?? [
        { targetId: 'other', type: 'page', url: 'https://example.test/private' },
        { targetId: 'foreign-frame', type: 'iframe', url: 'https://example.test/private-frame' },
        { targetId: 'created', type: 'page', url: 'about:blank' }
      ] };
      if (msg.method === 'Target.attachToTarget') result = { sessionId: 'bound-session' };
      if (msg.method === 'Page.navigate' && options.navigationError) result = { errorText: 'net::ERR_DENIED' };
      if (msg.method === 'Runtime.evaluate') {
        let value;
        const expr = msg.params.expression;
        if (expr === extractionScript) value = { title: 'Target', html: options.empty ? '' : '<p>BOUND ONLY</p>' };
        else if (expr === 'window.location.href') value = 'https://redirect.test/final';
        else if (expr === 'document.readyState') value = options.loading ? 'loading' : 'complete';
        else if (expr.includes('ready: document.readyState')) value = { url: options.readyUrl ?? 'https://example.test/article', title: 'Target', ready: 'complete' };
        else value = 100;
        result = options.evaluationError ? { exceptionDetails: { exception: { description: 'native evaluation failure' } }, result: {} } : { result: { value } };
      }
      this.reply({ id: msg.id, result });
    }
    reply(data) { queueMicrotask(() => this.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(data) }))); }
    event(method, params, sessionId) { this.dispatchEvent(new MessageEvent('message', { data: JSON.stringify({ method, params, sessionId }) })); }
  }
  const context = vm.createContext({
    console: { error: (...args) => diagnostics.push(args.map(String).join(' ')) },
    setTimeout, clearTimeout, queueMicrotask, URL, Date, TextDecoder, AbortController,
    WebSocket: FakeWebSocket, fetch: async (_url, init) => {
      requestSignal = init.signal;
      if (options.debugError) throw new Error('mock debug unavailable');
      return { ok: true, json: async () => {
        bodyStarted = true;
        if (options.interruptBody) queueMicrotask(() => fakeProcess.emit(options.interruptBody));
        if (options.hangBody) return new Promise(() => {});
        return { webSocketDebuggerUrl: 'ws://mock' };
      } };
    }
  });
  const modules = new Map();
  const constants = {
    DEFAULT_TIMEOUT_MS: 300, CDP_CONNECT_TIMEOUT_MS: 100, NETWORK_IDLE_TIMEOUT_MS: 1,
    POST_LOAD_DELAY_MS: 0, SCROLL_STEP_WAIT_MS: 0, SCROLL_MAX_STEPS: 1
  };
  const builtins = {
    'node:process': { default: fakeProcess },
    'node:os': { default: { ...os, tmpdir: () => directory } },
    'node:fs': { default: { existsSync: () => true } },
    'node:fs/promises': { ...fs, rm: async (...args) => {
      if (options.cleanupError) throw new Error('mock cleanup denied');
      return fs.rm(...args);
    } },
    'node:child_process': { spawn: (exe, args) => {
      launches.push({ exe, args }); child = new EventEmitter();
      child.exitCode = null; child.signalCode = null;
      child.kill = signal => { if (options.killError) throw new Error('mock kill denied'); child.signalCode = signal; queueMicrotask(() => child.emit('exit', null, signal)); return true; };
      queueMicrotask(() => options.spawnError ? child.emit('error', new Error('mock spawn denied')) : child.emit('spawn'));
      return child;
    } },
    'node:net': { default: { createServer: () => {
      const server = new EventEmitter(); server.unref = () => {}; server.listen = (...args) => args.at(-1)();
      server.address = () => ({ port: 12345 }); server.close = cb => cb(); return server;
    } } }
  };
  async function load(name) {
    if (modules.has(name)) return modules.get(name);
    let mod;
    if (name.startsWith('node:') || name.endsWith('constants.ts') || name.endsWith('html-to-markdown.ts')) {
      const exports = name.endsWith('constants.ts') ? constants : name.endsWith('html-to-markdown.ts') ? {
        cleanupAndExtractScript: extractionScript,
        htmlToMarkdown: html => { assert.equal(html, '<p>BOUND ONLY</p>'); return 'BOUND ONLY'; },
        createMarkdownDocument: result => `# ${result.metadata.title}\n${result.markdown}`
      } : builtins[name] ?? await import(name);
      mod = new vm.SyntheticModule(Object.keys(exports), function () {
        for (const [key, value] of Object.entries(exports)) this.setExport(key, value);
      }, { context, identifier: name });
    } else {
      const source = await fs.readFile(name, 'utf8');
      mod = new vm.SourceTextModule(stripTypeScriptTypes(source), { context, identifier: name,
        initializeImportMeta(meta) { meta.url = 'file:///offline-test'; }
      });
    }
    modules.set(name, mod);
    await mod.link((specifier, referencing) => load(specifier.startsWith('node:') ? specifier : path.resolve(path.dirname(referencing.identifier), specifier.replace(/\.js$/, '.ts'))));
    return mod;
  }
  const main = await load(path.join(skill, 'scripts/main.ts'));
  await main.evaluate();
  return {
    main: main.namespace, cdp: modules.get(path.join(skill, 'scripts/cdp.ts')).namespace,
    directory, calls, launches, diagnostics, output, input, fakeProcess, socket: () => socket,
    debug: () => ({ bodyStarted, requestSignal, child }),
    cleanup: () => { input.destroy(); stderr.destroy(); return fs.rm(directory, { recursive: true, force: true }); }
  };
}

async function withFixture(options, run) {
  const f = await fixture(options);
  try { await run(f); } finally { await f.cleanup(); }
}
const argv = (...rest) => ['node', 'main.ts', 'https://example.test/article', ...rest];
const noProfiles = async f => assert.deepEqual(await fs.readdir(f.directory), []);

test('main: created target only, redirects retained, stdout-only and temporary profile removed', () => withFixture({}, async f => {
  await f.main.main(argv());
  assert.equal(f.output.join(''), '# Target\nBOUND ONLY\n');
  assert.deepEqual(f.calls.filter(c => c.method === 'Target.attachToTarget').map(c => c.params.targetId), ['created']);
  assert.ok(f.calls.filter(c => c.method === 'Runtime.evaluate').every(c => c.sessionId === 'bound-session'));
  assert.equal(f.launches[0].args.at(-1), 'about:blank');
  assert.ok(f.launches[0].args.some(a => a.startsWith('--user-data-dir=') && !a.includes('ignored-env-profile')));
  assert.ok(!f.diagnostics.join(' ').includes('Saved:'));
  await noProfiles(f);
}));

test('captureUrl: same-target redirect metadata', () => withFixture({}, async f => {
  const result = await f.main.captureUrl(f.main.parseArgs(argv('--wait')));
  assert.equal(result.metadata.url, 'https://redirect.test/final');
  await noProfiles(f);
}));

test('explicit output and persistent opt-in preserve synthetic profile', () => withFixture({}, async f => {
  const profile = path.join(f.directory, 'selected-profile');
  await fs.mkdir(profile); await fs.writeFile(path.join(profile, 'marker'), 'synthetic');
  const out = path.join(f.directory, 'saved.md');
  await f.main.main(argv('--wait', '--profile', profile, '-o', out));
  assert.equal(await fs.readFile(out, 'utf8'), '# Target\nBOUND ONLY');
  assert.equal(await fs.readFile(path.join(profile, 'marker'), 'utf8'), 'synthetic');
  assert.deepEqual(f.output, []);
  assert.ok(f.diagnostics.some(line => line === `Saved: ${out}`));
}));

for (const [name, options, error] of [
  ['missing id', { missingId: true }, /target missing/],
  ['missing target', { targets: [{ targetId: 'other', type: 'page' }] }, /missing or ambiguous/],
  ['ambiguous target', { targets: [{ targetId: 'created', type: 'page' }, { targetId: 'created', type: 'page' }] }, /missing or ambiguous/],
  ['navigation error', { navigationError: true }, /net::ERR_DENIED/],
  ['CDP error', { failMethod: 'Page.enable' }, /native mocked failure/],
  ['evaluation error', { evaluationError: true }, /native evaluation failure/],
  ['empty extraction', { empty: true }, /No main-page content/],
  ['spawn error', { spawnError: true }, /mock spawn denied/],
  ['debug timeout', { debugError: true }, /mock debug unavailable/],
  ['load timeout', { loading: true }, /Page load timeout/],
]) test(`main: ${name} rejects, no output, cleans temporary profile`, () => withFixture(options, async f => {
  await assert.rejects(f.main.main(argv('--timeout', '40')), error);
  assert.deepEqual(f.output, []);
  assert.ok(!f.diagnostics.some(line => line.includes('Saved:')));
  await noProfiles(f);
}));

test('cleanup failure prevents successful content', () => withFixture({ cleanupError: true }, async f => {
  await assert.rejects(f.main.main(argv('--wait')), /Capture cleanup failed/);
  assert.deepEqual(f.output, []);
  assert.ok(f.diagnostics.some(line => line.includes('mock cleanup denied')));
}));

for (const readyUrl of ['https://example.test.evil/article', 'https://evil.test/?next=example.test']) {
  test(`wait: rejects substring hostname ${readyUrl}`, () => withFixture({ readyUrl }, async f => {
    await assert.rejects(f.main.main(argv('--wait', '--timeout', '20')), /Timed out waiting/);
    assert.equal(f.input.listenerCount('data'), 0);
    await noProfiles(f);
  }));
}

test('wait: Enter permits same-target cross-domain redirect and releases readline', () => withFixture({ readyUrl: 'https://redirect.test/final' }, async f => {
  const pending = f.main.main(argv('--wait', '--timeout', '500'));
  const timer = setTimeout(() => f.input.write('\n'), 50);
  try { await pending; } finally { clearTimeout(timer); }
  assert.equal(f.input.listenerCount('data'), 0);
  await noProfiles(f);
}));

test('invalid arguments rejected before launch', () => withFixture({}, async f => {
  for (const extra of [['--output'], ['--profile'], ['--timeout', '0'], ['--timeout', 'junk'], ['--unknown']]) {
    await assert.rejects(f.main.main(argv(...extra)));
  }
  await assert.rejects(f.main.main(['node', 'main.ts', 'file:///private']));
  assert.deepEqual(f.launches, []); await noProfiles(f);
}));

test('CDP network idle: session isolation and bounded busy timeout', () => withFixture({}, async f => {
  const cdp = await f.cdp.CdpConnection.connect('ws://mock', 100);
  const idle = f.cdp.waitForNetworkIdle(cdp, 'bound-session', 5, 50);
  f.socket().event('Network.requestWillBeSent', { requestId: 'foreign' }, 'foreign-session');
  await idle;
  const busy = f.cdp.waitForNetworkIdle(cdp, 'bound-session', 5, 20);
  f.socket().event('Network.requestWillBeSent', { requestId: 'own' }, 'bound-session');
  await assert.rejects(busy, /Network idle timeout/);
  assert.ok([...cdp.eventHandlers.values()].every(handlers => handlers.size === 0));
  cdp.close();
}));

test('extraction source: no frame reads, inline srcdoc excluded, main content retained', () => {
  let removed = false;
  const frame = { remove() { removed = true; }, get contentDocument() { throw new Error('frame read'); } };
  const document = {
    baseURI: 'https://example.test/article', title: 'Target',
    querySelectorAll(selector) { return selector === 'iframe' ? [frame] : []; }, querySelector() { return null; },
    documentElement: { get outerHTML() { return removed ? '<p>MAIN</p>' : '<iframe srcdoc="PRIVATE"></iframe><p>MAIN</p>'; } }
  };
  const result = vm.runInNewContext(extractionScript, { document, URL });
  assert.equal(result.html, '<p>MAIN</p>'); assert.equal(result.title, 'Target');
});

test('unconfirmed browser exit fails and retains recovery profile', () => withFixture({ killError: true }, async f => {
  await assert.rejects(f.main.main(argv('--wait')), /Capture cleanup failed/);
  assert.deepEqual(f.output, []);
  assert.ok(f.diagnostics.some(line => line.includes('exit unconfirmed')));
  assert.equal((await fs.readdir(f.directory)).length, 1);
}));

test('persistent profile survives a failed capture', () => withFixture({ navigationError: true }, async f => {
  const profile = path.join(f.directory, 'selected-profile');
  await fs.mkdir(profile); await fs.writeFile(path.join(profile, 'marker'), 'synthetic');
  await assert.rejects(f.main.main(argv('--profile', profile)), /net::ERR_DENIED/);
  assert.equal(await fs.readFile(path.join(profile, 'marker'), 'utf8'), 'synthetic');
  assert.deepEqual(f.output, []);
}));

test('SIGINT: bounded failure cleans profile and releases process handlers', () => withFixture({ interruptMethod: 'Page.navigate' }, async f => {
  await assert.rejects(f.main.main(argv('--wait')), /Capture interrupted/);
  assert.deepEqual(f.output, []);
  assert.equal(f.fakeProcess.listenerCount('SIGINT'), 0);
  assert.equal(f.fakeProcess.listenerCount('SIGTERM'), 0);
  await noProfiles(f);
}));

for (const interruptBody of [undefined, 'SIGINT', 'SIGTERM']) {
  test(`debug response body hang: ${interruptBody ?? 'timeout'} cleans before connect`, { timeout: 2000 }, () => withFixture({ hangBody: true, interruptBody }, async f => {
    const start = Date.now();
    await assert.rejects(f.main.main(argv('--timeout', '80')), interruptBody ? /Capture interrupted/ : /debug response timeout/);
    assert.ok(Date.now() - start < 1000, 'debug body must not block cleanup');
    assert.equal(f.debug().bodyStarted, true);
    assert.equal(f.debug().requestSignal.aborted, true);
    assert.equal(f.debug().child.signalCode, 'SIGTERM');
    assert.equal(f.socket(), undefined);
    assert.deepEqual(f.output, []);
    assert.ok(!f.diagnostics.some(line => line.includes('Saved:')));
    assert.equal(f.fakeProcess.listenerCount('SIGINT'), 0);
    assert.equal(f.fakeProcess.listenerCount('SIGTERM'), 0);
    await noProfiles(f);
  }));
}

test('fixture writes only an OS temporary directory and removes it', async () => {
  let directory;
  await withFixture({}, async f => {
    directory = f.directory;
    assert.equal(path.dirname(directory), path.resolve(os.tmpdir()));
    await f.main.main(argv('--wait'));
    await noProfiles(f);
  });
  await assert.rejects(fs.access(directory), { code: 'ENOENT' });
});

test('installed test module never creates a directory adjacent to the skill', async () => {
  const source = await fs.readFile(fileURLToPath(import.meta.url), 'utf8');
  const context = vm.createContext({});
  const writes = [];
  const rejectWrite = async target => { writes.push(target); throw new Error('unexpected installation write'); };
  const module = new vm.SourceTextModule(source, {
    context,
    initializeImportMeta(meta) { meta.url = pathToFileURL(path.join(os.tmpdir(), 'synthetic/shared-skills/tool-url-markdown/tests/main.test.mjs')).href; }
  });
  await module.link(async name => {
    const exports = name === 'node:test' ? { default: () => {} } : name === 'node:fs/promises' ? {
      readFile: async () => htmlSource, mkdir: rejectWrite, mkdtemp: rejectWrite,
      writeFile: rejectWrite, rm: rejectWrite
    } : await import(name);
    return new vm.SyntheticModule(Object.keys(exports), function () {
      for (const [key, value] of Object.entries(exports)) this.setExport(key, value);
    }, { context });
  });
  await module.evaluate();
  assert.deepEqual(writes, []);
});
