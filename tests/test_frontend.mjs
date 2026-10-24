import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../src/microduck_studio/static/app.js', import.meta.url), 'utf8');

class Element {
  constructor() {
    this.children = [];
    this.dataset = {};
    this.style = {};
    this.attributes = {};
    this.className = '';
    this.disabled = false;
    this.hidden = false;
    this._text = '';
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
  addEventListener() {}
}

function app() {
  const nodes = new Map();
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
      querySelectorAll: selector => selector === '[data-skill]' ? skills : [],
      createElement: () => new Element(),
      addEventListener() {},
    },
    localStorage: {getItem: () => null},
    window: {addEventListener() {}},
    ResizeObserver: class { observe() {} },
    WebSocket: Socket,
    location: {protocol: 'http:', host: 'localhost'},
    clearTimeout() {},
    setTimeout() { return 1; },
    clearInterval() {},
    setInterval() { return 1; },
  });
  // Load the actual event handlers and renderers; skip only application boot/network startup.
  vm.runInContext(source.slice(0, source.lastIndexOf('\nmarkStaticChinese();')), context);
  return {context, node, skills, run: code => vm.runInContext(code, context)};
}

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
