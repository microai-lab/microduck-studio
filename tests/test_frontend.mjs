import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../src/microduck_studio/static/app.js', import.meta.url), 'utf8');
const index = readFileSync(new URL('../src/microduck_studio/static/index.html', import.meta.url), 'utf8');
const movementDatasets = [...index.matchAll(/<button\b([^>]*)>/g)].map(([, attributes]) =>
  Object.fromEntries([...attributes.matchAll(/data-(vx|vy|vyaw)="([^"]*)"/g)]
    .map(([, name, value]) => [name, value])));
const leftButtonDataset = movementDatasets.find(dataset => Number(dataset.vy) > 0);
assert.ok(leftButtonDataset, 'the rendered page must contain a left movement button');
const leftCommand = Object.fromEntries(['vx', 'vy', 'vyaw']
  .map(axis => [axis, Number(leftButtonDataset[axis] || 0)]));

class Element {
  constructor() {
    this.children = [];
    this.dataset = {};
    this.style = {};
    this.attributes = {};
    this.className = '';
    this.disabled = false;
    this.hidden = false;
    this.checked = false;
    this._text = '';
    this.listeners = new Map();
    this.capturedPointers = new Set();
    this.classList = {
      contains: name => this.className.split(/\s+/).includes(name),
      add: name => { if (!this.classList.contains(name)) this.className += ` ${name}`; },
      remove: name => { this.className = this.className.split(/\s+/).filter(item => item !== name).join(' '); },
      toggle: (name, on) => on ? this.classList.add(name) : this.classList.remove(name),
    };
  }
  set textContent(value) { this.children = []; this._text = String(value); }
  get textContent() { return this.children.length ? this.children.map(child => child.textContent).join('') : this._text; }
  replaceChildren(...children) { this._text = ''; this.children = children; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  addEventListener(type, callback) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(callback);
  }
  emit(type, event = {}) {
    return Promise.all((this.listeners.get(type) || []).map(callback => callback({
      preventDefault() {}, ...event, currentTarget: this,
    })));
  }
  setPointerCapture(pointerId) { this.capturedPointers.add(pointerId); }
  hasPointerCapture(pointerId) { return this.capturedPointers.has(pointerId); }
  releasePointerCapture(pointerId) {
    this.capturedPointers.delete(pointerId);
    // Exercise reentrancy when clearing or replacing the active movement.
    this.emit('lostpointercapture', {pointerId});
  }
}

function app() {
  const nodes = new Map();
  const moveButtons = [{...leftButtonDataset}, {vx: '-0.3'}].map(dataset => {
    const button = new Element();
    button.dataset = dataset;
    return button;
  });
  const stopButtons = [new Element(), new Element()];
  const documentEvents = new Element();
  const windowEvents = new Element();
  const intervals = new Map();
  let intervalId = 0;
  const skills = ['sit_toggle', 'roulade', 'kick_left', 'kick_right'].map(skill => {
    const button = new Element();
    button.dataset.skill = skill;
    return button;
  });
  const node = selector => {
    if (!nodes.has(selector)) nodes.set(selector, new Element());
    return nodes.get(selector);
  };
  class Socket {
    constructor() { this.listeners = {}; }
    addEventListener(type, callback) { this.listeners[type] = callback; }
    emit(type, event) { this.listeners[type]?.(event); }
  }
  const context = vm.createContext({
    document: {
      querySelector: node,
      querySelectorAll: selector => {
        if (selector === '[data-skill]') return skills;
        if (selector === '[data-vx],[data-vy],[data-vyaw]') return moveButtons;
        if (selector === '[data-action="stop"]') return stopButtons;
        if (selector === '[data-vx].active,[data-vy].active,[data-vyaw].active') {
          return moveButtons.filter(button => button.classList.contains('active'));
        }
        return [];
      },
      createElement: () => new Element(),
      addEventListener: (type, callback) => documentEvents.addEventListener(type, callback),
    },
    localStorage: {getItem: () => null},
    window: {addEventListener: (type, callback) => windowEvents.addEventListener(type, callback)},
    ResizeObserver: class { observe() {} },
    WebSocket: Socket,
    location: {protocol: 'http:', host: 'localhost'},
    clearTimeout() {},
    setTimeout() { return 1; },
    clearInterval(id) { intervals.delete(id); },
    setInterval(callback) { const id = ++intervalId; intervals.set(id, callback); return id; },
  });
  // Load the actual event handlers and renderers; skip only application boot/network startup.
  vm.runInContext(source.slice(0, source.lastIndexOf('\nmarkStaticChinese();')), context);
  return {
    context, node, skills, moveButtons, stopButtons, documentEvents, windowEvents, intervals,
    run: code => vm.runInContext(code, context),
  };
}

function movementApp() {
  const state = app();
  const requests = [];
  state.context.fetch = async (path, options) => {
    requests.push({path, body: options.body ? JSON.parse(options.body) : null});
    return {ok: true, json: async () => ({accepted: true})};
  };
  state.context.renderMonitor({policy: 'walk'});
  return {...state, requests};
}

const settle = () => new Promise(resolve => setImmediate(resolve));

test('the rendered left button requests stronger pure lateral motion', async () => {
  assert.deepEqual(leftCommand, {vx: 0, vy: 0.6, vyaw: 0});
  const {moveButtons: [left], requests} = movementApp();
  await left.emit('pointerdown', {pointerId: 1});
  await settle();
  assert.deepEqual(requests, [{path: '/api/control/move', body: leftCommand}]);
  await left.emit('pointerup', {pointerId: 1});
  assert.equal(requests.at(-1).path, '/api/control/stop');
});

function delayFirstMove(state, failure = null) {
  const deliver = state.context.fetch;
  let finish;
  let concurrent = 0;
  let maximum = 0;
  state.context.fetch = async (path, options) => {
    concurrent += 1;
    maximum = Math.max(maximum, concurrent);
    try {
      if (path === '/api/control/move' && !finish) {
        await new Promise(resolve => { finish = resolve; });
        if (failure) throw failure;
      }
      return await deliver(path, options);
    } finally {
      concurrent -= 1;
    }
  };
  return {finish: () => finish(), maximum: () => maximum};
}

for (const nextPointerId of [8, 7]) {
  test(`switching left to backward ignores the old button, next pointer ${nextPointerId}`, async () => {
    const {moveButtons: [left, backward], intervals, requests} = movementApp();
    await left.emit('pointerdown', {pointerId: 7});
    const oldTick = [...intervals.values()][0];
    await backward.emit('pointerdown', {pointerId: nextPointerId});
    await settle();
    assert.equal(left.classList.contains('active'), false);
    assert.equal(left.hasPointerCapture(7), false);
    assert.equal(backward.classList.contains('active'), true);
    assert.equal(intervals.size, 1);
    assert.deepEqual(requests, [
      {path: '/api/control/move', body: leftCommand},
      {path: '/api/control/move', body: {vx: -0.3, vy: 0, vyaw: 0}},
    ]);
    const currentTick = [...intervals.values()][0];
    for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) {
      await left.emit(type, {pointerId: 7});
      assert.equal(intervals.size, 1, `old ${type} must preserve the current timer`);
      assert.equal([...intervals.values()][0], currentTick);
      assert.equal(backward.classList.contains('active'), true);
    }
    await backward.emit('pointerup', {pointerId: 99});
    await oldTick();
    assert.equal(requests.length, 2, 'a stale timer callback cannot send another movement');
    await currentTick();
    await settle();
    assert.deepEqual(requests.at(-1), {
      path: '/api/control/move', body: {vx: -0.3, vy: 0, vyaw: 0},
    });
    await backward.emit('pointerup', {pointerId: nextPointerId});
    assert.equal(intervals.size, 0);
    assert.equal(backward.classList.contains('active'), false);
    assert.equal(requests.filter(request => request.path === '/api/control/stop').length, 1);
  });
}

for (const release of ['pointerup', 'pointercancel', 'lostpointercapture']) {
  test(`${release} stops once despite capture release and later duplicate events`, async () => {
    const {moveButtons: [left], intervals, requests, run} = movementApp();
    await left.emit('pointerdown', {pointerId: 3});
    await left.emit(release, {pointerId: 3});
    for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) {
      await left.emit(type, {pointerId: 3});
    }
    assert.equal(requests.filter(request => request.path === '/api/control/stop').length, 1);
    assert.equal(intervals.size, 0);
    assert.equal(run('activeMove'), null);
    assert.equal(left.classList.contains('active'), false);
    assert.equal(left.hasPointerCapture(3), false);
  });
}

test('held policy rejects a press without capture, highlight, timer or movement', async () => {
  const {context, moveButtons, intervals, requests, run} = movementApp();
  context.renderMonitor({policy: 'held'});
  for (const button of moveButtons) {
    await button.emit('pointerdown', {pointerId: 1});
    assert.equal(button.classList.contains('active'), false);
    assert.equal(button.hasPointerCapture(1), false);
  }
  assert.equal(intervals.size, 0);
  assert.equal(run('activeMove'), null);
  assert.deepEqual(requests, []);
});

test('a held state retires the active movement and a later walk state never restarts it', async () => {
  const {context, moveButtons: [left, backward], intervals, requests, node, run} = movementApp();
  await left.emit('pointerdown', {pointerId: 5});
  const oldTick = [...intervals.values()][0];
  context.renderMonitor({policy: 'held'});
  assert.equal(intervals.size, 0);
  assert.equal(run('activeMove'), null);
  assert.equal(left.classList.contains('active'), false);
  assert.equal(left.hasPointerCapture(5), false);
  assert.match(node('#control-status-en').textContent, /Enable RL \/ Stand up first/);
  await oldTick();
  context.renderMonitor({policy: 'walk'});
  await left.emit('pointerup', {pointerId: 5});
  assert.equal(intervals.size, 0);
  await settle();
  assert.equal(requests.filter(request => request.path === '/api/control/move').length, 1);
  await backward.emit('pointerdown', {pointerId: 5});
  assert.equal(intervals.size, 1, 'a fresh press can start movement again');
  assert.equal(requests.at(-1).body.vx, -0.3);
});

test('stop buttons, hidden pages and pagehide send explicit stops even without an active pointer', async () => {
  const {
    context, moveButtons: [left], stopButtons, documentEvents, windowEvents, intervals, requests,
  } = movementApp();
  for (const button of stopButtons) await button.emit('click');
  assert.equal(requests.filter(request => request.path === '/api/control/stop').length, 2);
  await left.emit('pointerdown', {pointerId: 4});
  await stopButtons[0].emit('click');
  await left.emit('pointerup', {pointerId: 4});
  assert.equal(intervals.size, 0);
  assert.equal(left.classList.contains('active'), false);
  assert.equal(requests.filter(request => request.path === '/api/control/stop').length, 3);
  context.document.hidden = true;
  await documentEvents.emit('visibilitychange');
  await settle();
  await windowEvents.emit('pagehide');
  await settle();
  assert.equal(requests.filter(request => request.path === '/api/control/stop').length, 5);
  context.document.hidden = false;
  await documentEvents.emit('visibilitychange');
  assert.equal(requests.filter(request => request.path === '/api/control/stop').length, 5);
});

test('current subscriptions use runtime skill names and clear stale skills on disconnect', () => {
  const {context, skills, node, run} = app();
  context.connectMonitor();
  const socket = run('monitorSocket');
  assert.ok(skills.every(button => button.disabled));
  socket.emit('message', {data: JSON.stringify({type: 'subscribed', data: {
    accepted: true, walk: 'velstand.onnx', sitstand: 'alpha_sitstand.onnx',
    skills: ['roulade', 'kick_left'],
  }})});
  assert.deepEqual(skills.map(button => button.disabled), [false, false, false, true]);
  assert.match(node('#monitor-policy-files').textContent, /roulade\+kick_left/);
  socket.emit('message', {data: JSON.stringify({type: 'subscribed', data: {
    accepted: true, skills: [], kick_left: 'legacy.onnx',
  }})});
  assert.ok(skills.every(button => button.disabled), 'an explicit empty list is authoritative');
  socket.emit('message', {data: JSON.stringify({type: 'subscribed', data: {
    accepted: true, skills: [{name: 'roulade'}],
  }})});
  assert.equal(skills[1].disabled, false);
  socket.emit('close');
  assert.ok(skills.every(button => button.disabled));
});

test('legacy subscriptions fall back to reported loaded files and unavailable policies disable skills', () => {
  const {context, skills} = app();
  context.renderSkillAvailability({accepted: true, sitstand: 'sit.onnx', kick_right: 'right.onnx'});
  assert.deepEqual(skills.map(button => button.disabled), [false, true, true, false]);
  context.renderSkillAvailability({accepted: true, skills: ['roulade'], unavailable: 'ONNX failed to load'});
  assert.ok(skills.every(button => button.disabled));
  assert.equal(skills[1].title, 'ONNX failed to load');
});

test('daemon identity and API differences remain visible without disabling loaded skills', () => {
  const {context, node, skills} = app();
  context.renderSkillAvailability({accepted: true, skills: ['roulade']});
  context.renderRobotdService({
    connected: true,
    hello: {api_version: 43, daemon_version: '0.17.7', revision: '123456789abc'},
    protocol: {client_api_version: 44, matches: false},
    source: {ref: 'main', revision: '942e58e3aa6dbb28e7037203fff11866122c7567'},
  });
  const detail = node('#robotd-detail').textContent;
  assert.match(detail, /daemon 0\.17\.7 · API 43/);
  assert.match(detail, /revision 123456789abc/);
  assert.match(detail, /build main @ 942e58e3aa6d/);
  assert.match(detail, /API differs · Studio 44/);
  assert.equal(skills[1].disabled, false);
  context.renderRobotdService({connected: true, source: {ref: 'legacy'}}, '/tmp/robotd.sock');
  assert.match(node('#robotd-detail').textContent, /Runtime version not reported/);
});

test('joint telemetry preserves reported zero and never invents missing velocity or current', () => {
  const {context, node} = app();
  context.renderMonitor({
    policy: 'held', t: 12.5, t_ns: 12500000000,
    joints: [0, 0.1], targets: [0, 0.2],
    velocities: [0, -2.125, NaN, Infinity, null], currents_ma: [0, 154, NaN, null],
    safety: {picked_up: true, gravity: [0, 0, -1], fallen: false},
    loop: {hz: 50, missed: 0},
  });
  const rows = node('#monitor-joints').children;
  assert.match(rows[0].innerHTML, /joint-velocity">\+0\.00<\/span>/);
  assert.match(rows[0].innerHTML, /joint-current">\+0<\/span>/);
  assert.match(rows[1].innerHTML, /joint-velocity">-2\.13<\/span>/);
  assert.match(rows[1].innerHTML, /joint-current">\+154<\/span>/);
  assert.ok(rows.slice(2).every(row => /joint-velocity">—<\/span>/.test(row.innerHTML)));
  assert.ok(rows.slice(2).every(row => /joint-current">—<\/span>/.test(row.innerHTML)));
  assert.ok(rows.every(row => !/NaN|Infinity/.test(row.innerHTML)));
  assert.match(node('#monitor-safety').textContent, /抱起暂停/);
  assert.match(node('#monitor-safety').textContent, /Picked up · policy paused/);
  context.renderMonitor({policy: 'walk', joints: [], targets: [], safety: {}});
  assert.ok(node('#monitor-joints').children.every(row => /joint-velocity">—<\/span>/.test(row.innerHTML)));
  assert.ok(node('#monitor-joints').children.every(row => /joint-current">—<\/span>/.test(row.innerHTML)));
  assert.match(node('#monitor-safety').textContent, /Pickup status not reported/);
});

test('structured HTTP rejections and nested runtime reasons remain readable', async () => {
  const {context} = app();
  context.fetch = async () => ({ok: false, status: 409, json: async () => ({detail: {
    code: -32000, message: 'robotd refused command', data: {reason: 'policy is paused while picked up'},
  }})});
  await assert.rejects(context.api('/api/control/skill'), /robotd refused command · policy is paused while picked up/);
  context.fetch = async () => ({ok: false, status: 409, json: async () => ({detail: {accepted: false, reason: 'skill not loaded'}})});
  await assert.rejects(context.api('/api/control/skill'), /skill not loaded/);
  assert.equal(context.errorText([{loc: ['body'], msg: 'invalid skill'}]), 'invalid skill');
  assert.equal(context.errorText({unexpected: true}), '{"unexpected":true}');
});

test('telemetry and camera selection preserve the authoritative robot image', () => {
  const {context, node} = app();
  node('#monitor-robot-frame').src = 'blob:authoritative-frame';
  context.setSimulatorView('head');
  context.renderMonitor({policy: 'held', safety: {picked_up: true}});
  assert.equal(node('#monitor-robot-frame').src, 'blob:authoritative-frame');
  assert.equal(node('#monitor-robot-frame').hidden, false);
  context.setSimulatorView('world');
  assert.equal(node('#monitor-robot-frame').src, 'blob:authoritative-frame');
});

test('pending motion requests do not accumulate or revive a released press', async () => {
  const {context, moveButtons: [left], intervals, requests} = movementApp();
  const fetch = context.fetch;
  let finishMove;
  context.fetch = async (path, options) => {
    const response = await fetch(path, options);
    if (path === '/api/control/move') {
      await new Promise(resolve => { finishMove = resolve; });
    }
    return response;
  };
  await left.emit('pointerdown', {pointerId: 4});
  const tick = [...intervals.values()][0];
  await tick();
  assert.equal(requests.filter(request => request.path === '/api/control/move').length, 1);
  const released = left.emit('pointerup', {pointerId: 4});
  assert.equal(requests.length, 1, 'stop waits behind the pending move instead of overtaking it');
  finishMove();
  await released;
  assert.equal(requests.at(-1).path, '/api/control/stop');
  await tick();
  assert.equal(requests.filter(request => request.path === '/api/control/move').length, 1);
  assert.equal(intervals.size, 0);
});

test('a delayed movement cannot reach the daemon after its release stop', async () => {
  const {context, moveButtons: [left], requests} = movementApp();
  const deliver = context.fetch;
  let finishFirstMove;
  context.fetch = async (path, options) => {
    if (path === '/api/control/move' && !finishFirstMove) {
      await new Promise(resolve => { finishFirstMove = resolve; });
    }
    return deliver(path, options);
  };
  await left.emit('pointerdown', {pointerId: 4});
  // Delay network delivery rather than the response: separate HTTP requests
  // can reach Studio in a different order from their fetch() invocation.
  const released = left.emit('pointerup', {pointerId: 4});
  finishFirstMove();
  await released;
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(requests.at(-1).path, '/api/control/stop');
});

test('a delayed previous direction cannot overwrite the current direction', async () => {
  const {context, moveButtons: [left, backward], requests} = movementApp();
  const deliver = context.fetch;
  let finishFirstMove;
  context.fetch = async (path, options) => {
    if (path === '/api/control/move' && !finishFirstMove) {
      await new Promise(resolve => { finishFirstMove = resolve; });
    }
    return deliver(path, options);
  };
  await left.emit('pointerdown', {pointerId: 4});
  await backward.emit('pointerdown', {pointerId: 5});
  finishFirstMove();
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(requests.at(-1), {
    path: '/api/control/move', body: {vx: -0.3, vy: 0, vyaw: 0},
  });
});

test('a stop barrier survives a fresh press and repeated ticks while delivery is pending', async () => {
  const state = movementApp();
  const gate = delayFirstMove(state);
  const {moveButtons: [left, backward], intervals, requests, node} = state;
  await left.emit('pointerdown', {pointerId: 4});
  const released = left.emit('pointerup', {pointerId: 4});
  await backward.emit('pointerdown', {pointerId: 5});
  const tick = [...intervals.values()][0];
  for (let index = 0; index < 100; index += 1) await tick();
  assert.deepEqual(requests, [], 'nothing overtakes the delayed first request');
  gate.finish();
  await released;
  await settle();
  assert.deepEqual(requests, [
    {path: '/api/control/move', body: leftCommand},
    {path: '/api/control/stop', body: null},
    {path: '/api/control/move', body: {vx: -0.3, vy: 0, vyaw: 0}},
  ]);
  assert.equal(gate.maximum(), 1);
  assert.match(node('#control-status-en').textContent, /Moving/);
});

test('canceling a queued new pointer drops its movement and preserves the stop', async () => {
  const state = movementApp();
  const gate = delayFirstMove(state);
  const {moveButtons: [left, backward], intervals, requests} = state;
  await left.emit('pointerdown', {pointerId: 4});
  await backward.emit('pointerdown', {pointerId: 5});
  const canceled = backward.emit('pointercancel', {pointerId: 5});
  gate.finish();
  await canceled;
  await settle();
  assert.deepEqual(requests, [
    {path: '/api/control/move', body: leftCommand},
    {path: '/api/control/stop', body: null},
  ]);
  assert.equal(gate.maximum(), 1);
  assert.equal(intervals.size, 0);
  assert.equal(backward.hasPointerCapture(5), false);
});

test('rapid pointer replacements coalesce to the newest live owner', async () => {
  const state = movementApp();
  const gate = delayFirstMove(state);
  const {moveButtons: [left, backward], intervals, requests} = state;
  await left.emit('pointerdown', {pointerId: 4});
  await backward.emit('pointerdown', {pointerId: 5});
  await left.emit('pointerdown', {pointerId: 6});
  await backward.emit('pointerup', {pointerId: 5});
  gate.finish();
  await settle();
  assert.equal(requests.length, 2);
  assert.ok(requests.every(request => request.body.vy === leftCommand.vy));
  assert.equal(gate.maximum(), 1);
  assert.equal(intervals.size, 1);
  await left.emit('pointerup', {pointerId: 6});
  assert.equal(requests.at(-1).path, '/api/control/stop');
});

test('held telemetry drains an in-flight move through stop and never resumes a queued owner', async () => {
  const state = movementApp();
  const gate = delayFirstMove(state);
  const {context, moveButtons: [left, backward], intervals, requests, node} = state;
  await left.emit('pointerdown', {pointerId: 4});
  await backward.emit('pointerdown', {pointerId: 5});
  context.renderMonitor({policy: 'held'});
  context.renderMonitor({policy: 'walk'});
  gate.finish();
  await settle();
  assert.deepEqual(requests, [
    {path: '/api/control/move', body: leftCommand},
    {path: '/api/control/stop', body: null},
  ]);
  assert.equal(intervals.size, 0);
  assert.match(node('#control-status-en').textContent, /Enable RL \/ Stand up first/);
});

test('a failed pending request does not strand the stop barrier or latest direction', async () => {
  const state = movementApp();
  const gate = delayFirstMove(state, new Error('network failed'));
  const {moveButtons: [left, backward], requests, node} = state;
  await left.emit('pointerdown', {pointerId: 4});
  const released = left.emit('pointerup', {pointerId: 4});
  await backward.emit('pointerdown', {pointerId: 5});
  gate.finish();
  await released;
  await settle();
  assert.deepEqual(requests, [
    {path: '/api/control/stop', body: null},
    {path: '/api/control/move', body: {vx: -0.3, vy: 0, vyaw: 0}},
  ]);
  assert.equal(gate.maximum(), 1);
  assert.match(node('#control-status-en').textContent, /Moving/);
});
