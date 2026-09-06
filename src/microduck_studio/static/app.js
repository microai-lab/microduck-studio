const $ = selector => document.querySelector(selector);
let moveTimer = null;
let monitorSocket = null;
let monitorRetry = null;
let simulatorSocket = null;
let simulatorRetry = null;
let simulatorFrameUrl = null;
let simulatorPendingFrame = null;
let simulatorFrameDecoding = false;
let simulatorFrameMeta = null;
let simulatorFrameTimes = [];
let simulatorPointerId = null;
let simulatorPointerX = 0;
let simulatorPointerY = 0;
let simulatorOrbitDx = 0;
let simulatorOrbitDy = 0;
let simulatorOrbitFrame = null;
let simulatorResizeTimer = null;
let simulatorProfile = localStorage.getItem('microduck-render-profile') || 'clear';
let monitorPolicyInfo = null;
let monitorHealth = null;
let monitorLoopHistory = [];
let monitorLoopPeak = 0;
let monitorFrames = 0;
let monitorPath = [];
let latestRobotPolicy = null;
const serviceOperations = new Set();
let interfaceLanguage = localStorage.getItem('microduck-studio-language') || 'zh';

function markStaticChinese() {
  const walker = document.createTreeWalker(document.querySelector('.workbench'), NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (
      /\p{Script=Han}/u.test(node.nodeValue || '')
      && !node.parentElement?.closest('.label-en, #language-toggle, option')
    ) nodes.push(node);
  }
  for (const node of nodes) {
    const label = document.createElement('span');
    label.className = 'label-zh';
    node.parentNode?.replaceChild(label, node);
    label.append(node);
  }
}

function setInterfaceLanguage(language) {
  interfaceLanguage = language === 'en' ? 'en' : 'zh';
  document.body.classList.toggle('lang-en', interfaceLanguage === 'en');
  document.documentElement.lang = interfaceLanguage === 'en' ? 'en' : 'zh-CN';
  localStorage.setItem('microduck-studio-language', interfaceLanguage);
  document.querySelectorAll('#sim-quality option').forEach(option => {
    option.textContent = option.dataset[interfaceLanguage] || option.textContent;
  });
  void refreshJobs();
}

const jointNames = [
  'left_hip_yaw', 'left_hip_roll', 'left_hip_pitch', 'left_knee', 'left_ankle',
  'neck_pitch', 'head_pitch', 'head_yaw', 'head_roll', 'mouth',
  'right_hip_yaw', 'right_hip_roll', 'right_hip_pitch', 'right_knee', 'right_ankle',
];

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {'content-type': 'application/json', ...(options.headers || {})},
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || JSON.stringify(data));
  return data;
}

function setBilingual(node, zh, en) {
  const primary = document.createElement('span');
  primary.className = 'label-zh';
  primary.textContent = zh;
  const secondary = document.createElement('span');
  secondary.className = 'label-en';
  secondary.textContent = en;
  node.replaceChildren(primary, secondary);
}

function setPairedStatus(id, zh, en) {
  const primary = $(`#${id}-zh`);
  primary.classList.add('label-zh');
  primary.textContent = zh;
  $(`#${id}-en`).textContent = en;
}

function renderServiceAction(service, connected, manageable) {
  const button = $(`#${service === 'mujoco' ? 'mujoco' : 'robotd'}-service-action`);
  if (serviceOperations.has(service)) return;
  const action = connected ? 'restart' : 'start';
  button.dataset.action = action;
  button.disabled = !manageable;
  const zh = connected ? '重启' : '启动';
  const en = connected ? 'Restart' : 'Start';
  button.replaceChildren(
    Object.assign(document.createElement('span'), {className: 'label-zh', textContent: zh}),
    Object.assign(document.createElement('small'), {className: 'label-en', textContent: en}),
  );
  button.title = manageable ? `${zh} ${service}` : '请通过 dev-stack.sh 启动服务管理器';
}

async function manageService(button) {
  const service = button.dataset.service;
  const action = button.dataset.action;
  if (!service || !action || serviceOperations.has(service)) return;
  serviceOperations.add(service);
  button.disabled = true;
  button.classList.add('pending');
  button.replaceChildren(
    Object.assign(document.createElement('span'), {className: 'label-zh', textContent: action === 'restart' ? '重启中' : '启动中'}),
    Object.assign(document.createElement('small'), {className: 'label-en', textContent: 'Please wait'}),
  );
  try {
    await api(`/api/services/${service}/${action}`, {method: 'POST'});
    await new Promise(resolve => setTimeout(resolve, 800));
  } catch (error) {
    alert(`${service}: ${error.message}`);
  } finally {
    serviceOperations.delete(service);
    button.classList.remove('pending');
    await refresh();
  }
}

function controlMessage(zh, en, error = false) {
  setPairedStatus('control-status', zh, en);
  $('#control-status').className = `bilingual ${error ? 'bad' : 'ok'}`;
}

function acceptedResult(result) {
  if (result?.accepted === false) throw new Error(result.reason || 'robotd refused the command');
  return result;
}

function monitorStatus(zh, en, state = '') {
  setPairedStatus('monitor-status', zh, en);
  $('#monitor-status').className = `pill bilingual ${state}`;
}

function signed(value, digits = 2) {
  const number = Number(value || 0);
  return `${number >= 0 ? '+' : ''}${number.toFixed(digits)}`;
}

function degrees(radians) {
  return Number(radians || 0) * 180 / Math.PI;
}

function renderMonitorPolicy() {
  if (!monitorPolicyInfo) return;
  const info = monitorPolicyInfo;
  if (info.unavailable) {
    $('#monitor-policy-files').textContent = `unavailable · ${info.unavailable}`;
    return;
  }
  const policies = [info.walk && `walking ${info.walk}`, info.stand && `standing ${info.stand}`].filter(Boolean);
  const skills = [
    info.sitstand && 'sit', info.ground_pick && 'pick', info.kick_left && 'kick-left',
    info.kick_right && 'kick-right', info.roulade && 'roulade',
  ].filter(Boolean);
  $('#monitor-policy-files').textContent = `${policies.join(' · ') || 'no policy names'}${skills.length ? ` · skills ${skills.join('+')}` : ''}`;
}

function renderMonitorHealth(health) {
  monitorHealth = health;
  if (!health) {
    $('#monitor-power').textContent = 'asking robotd for the battery…';
    $('#monitor-power').className = '';
    return;
  }
  const parts = [];
  if (health.battery) parts.push(`batt ${Number(health.battery.volts).toFixed(2)} V ${Number(health.battery.percent).toFixed(0)}%`);
  else parts.push('batt not read yet');
  if (!health.healthy) parts.push(`${health.degraded ? 'degraded' : 'unhealthy'}: ${health.reason || 'no reason given'}`);
  if (health.imu?.consecutive_stale_blocks >= 25) parts.push(`orientation frozen — ${health.imu.consecutive_stale_blocks} stale reads`);
  if (health.bus?.consecutive_errors > 0) parts.push(`bus ${health.bus.consecutive_errors} read failures running`);
  if (health.motors) parts.push(`motors ${Number(health.motors.max_c).toFixed(0)} °C max (${health.motors.hottest})`);
  if (health.cpu_temp_c != null) parts.push(`cpu ${Number(health.cpu_temp_c).toFixed(0)} °C`);
  $('#monitor-power').textContent = parts.join(' · ');
  $('#monitor-power').className = health.healthy ? 'ok' : 'bad';
}

function renderLoopTrace(hz) {
  const value = Math.max(0, Math.round(Number(hz || 0)));
  monitorFrames += 1;
  monitorLoopPeak = Math.max(monitorLoopPeak, value);
  monitorLoopHistory.push(value);
  if (monitorLoopHistory.length > 160) monitorLoopHistory.shift();
  const low = Math.min(...monitorLoopHistory);
  const high = Math.max(...monitorLoopHistory);
  $('#monitor-loop-caption').textContent = `loop rate · ${low}–${high} Hz over ${monitorFrames} frames · full height ${monitorLoopPeak} Hz`;
  const peak = Math.max(1, monitorLoopPeak);
  $('#monitor-loop-trace').replaceChildren(...monitorLoopHistory.map(sample => {
    const bar = document.createElement('i');
    bar.className = 'loop-sample';
    bar.style.height = `${Math.max(2, sample / peak * 100)}%`;
    return bar;
  }));
}

function renderPath(position, yaw) {
  const point = {x: Number(position[0] || 0), y: Number(position[1] || 0), yaw: Number(yaw || 0)};
  const previous = monitorPath.at(-1);
  if (!previous || Math.hypot(point.x - previous.x, point.y - previous.y) > 0.002 || Math.abs(point.yaw - previous.yaw) > 0.02) {
    monitorPath.push(point);
    if (monitorPath.length > 600) monitorPath.shift();
  } else {
    monitorPath[monitorPath.length - 1] = point;
  }
  const xs = monitorPath.map(item => item.x);
  const ys = monitorPath.map(item => item.y);
  const minX = Math.min(0, ...xs), maxX = Math.max(0, ...xs);
  const minY = Math.min(0, ...ys), maxY = Math.max(0, ...ys);
  const across = Math.max(1, (maxX - minX) * 1.25, (maxY - minY) * 1.25 * 1.75);
  const centerX = (minX + maxX) / 2;
  const centerY = (minY + maxY) / 2;
  const project = item => ({
    x: 160 + (item.x - centerX) / across * 280,
    y: 95 - (item.y - centerY) / across * 280,
  });
  $('#monitor-path-line').setAttribute('points', monitorPath.map(item => {
    const p = project(item);
    return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
  }).join(' '));
  const origin = project({x: 0, y: 0});
  $('#monitor-path-origin').setAttribute('cx', origin.x);
  $('#monitor-path-origin').setAttribute('cy', origin.y);
  const current = project(point);
  const angle = -point.yaw * 180 / Math.PI + 90;
  $('#monitor-path-heading').setAttribute('transform', `translate(${current.x - 160} ${current.y - 95}) rotate(${angle} 160 95)`);
  $('#monitor-path-scale').textContent = `${across.toFixed(1)} m across`;
}

function renderMonitor(state) {
  latestRobotPolicy = state.policy || null;
  $('#monitor-policy').textContent = state.policy || '—';
  $('#monitor-time').textContent = Number(state.t || 0).toFixed(2);
  const loop = state.loop || {};
  $('#monitor-loop').textContent = Number(loop.hz || 0).toFixed(1);
  $('#monitor-missed').textContent = loop.missed || 0;
  renderLoopTrace(loop.hz);

  const safety = state.safety || {};
  const movement = state.move || {};
  const requested = movement.requested || [0, 0, 0];
  const applied = movement.applied || [0, 0, 0];
  [['vx', 0, false], ['vy', 1, false], ['vyaw', 2, true]].forEach(([name, index, angular]) => {
    const asked = angular ? degrees(requested[index]) : requested[index];
    const actual = angular ? degrees(applied[index]) : applied[index];
    $(`#monitor-${name}-asked`).textContent = signed(asked);
    const appliedNode = $(`#monitor-${name}-applied`);
    appliedNode.textContent = signed(actual);
    appliedNode.style.color = Math.abs(Number(requested[index] || 0) - Number(applied[index] || 0)) > 1e-6 ? '#d0c43a' : '';
  });

  const gravity = safety.gravity || [0, 0, -1];
  $('#monitor-gravity-x').textContent = signed(gravity[0]);
  $('#monitor-gravity-y').textContent = signed(gravity[1]);
  $('#monitor-gravity-z').textContent = signed(gravity[2]);
  $('#monitor-upright').textContent = safety.fallen ? 'FALLEN' : 'upright';
  $('#monitor-upright').className = safety.fallen ? 'bad' : 'ok';

  const explanations = {
    deadman: 'deadman — no intent arrived recently, velocity zeroed',
    joint_range: "joint_range — a target was outside the actuator's travel",
    not_finite: 'not_finite — a target was NaN or infinite',
    fallen: 'fallen — the robot is down, the policy is not driving',
  };
  const limits = movement.limited_by || [];
  $('#monitor-limits').textContent = limits.length ? limits.map(limit => explanations[limit] || limit).join('; ') : 'none — the command went through untouched';

  const head = state.head || [0, 0, 0, 0];
  $('#monitor-head').textContent = `neck_pitch ${signed(degrees(head[0]))}°  head_pitch ${signed(degrees(head[1]))}°  head_yaw ${signed(degrees(head[2]))}°  head_roll ${signed(degrees(head[3]))}°  kp ${safety.gain ?? '—'}${safety.limp ? '  limp — gains dropped so the robot yields' : ''}`;

  const position = state.odom?.position || [0, 0, 0];
  $('#monitor-odom').textContent = `x ${signed(position[0])} m  y ${signed(position[1])} m  yaw ${signed(degrees(state.odom?.yaw))}°`;
  renderPath(position, state.odom?.yaw);

  const joints = state.joints || [];
  const targets = state.targets || [];
  $('#monitor-joints').replaceChildren(...jointNames.map((name, index) => {
    const measured = Number(joints[index] || 0);
    const target = Number(targets[index] || 0);
    const error = measured - target;
    const magnitude = Math.abs(error) / 0.20;
    const tone = magnitude < 0.25 ? 'good' : magnitude < 0.6 ? 'warn' : 'bad';
    const width = Math.min(50, magnitude * 50);
    const left = error < 0 ? 50 - width : 50;
    const row = document.createElement('div');
    row.className = 'joint-grid joint-row';
    row.innerHTML = `<span>${name}</span><span class="joint-value">${signed(degrees(measured))}°</span><span class="joint-value">${signed(degrees(target))}°</span><span class="joint-value joint-error ${tone}">${signed(degrees(error))}°</span><span class="deviation"><i class="deviation-bar ${tone}" style="left:${left}%;width:${width}%"></i>${magnitude > 1 ? `<b class="deviation-edge" style="${error < 0 ? 'left:0' : 'right:0'}">${error < 0 ? '«' : '»'}</b>` : ''}</span>`;
    return row;
  }));
}

function connectMonitor() {
  clearTimeout(monitorRetry);
  const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
  monitorSocket = new WebSocket(`${protocol}://${location.host}/ws/monitor`);
  monitorStatus('连接中', 'Connecting');
  monitorSocket.addEventListener('message', event => {
    const message = JSON.parse(event.data);
    if (message.type === 'subscribed') {
      monitorPolicyInfo = message.data;
      renderMonitorPolicy();
      monitorStatus('实时 · 10 Hz', 'Live · 10 Hz', 'ok');
    } else if (message.type === 'state') {
      renderMonitor(message.data);
    } else if (message.type === 'error') {
      monitorStatus('连接失败', message.message || 'Connection failed', 'bad');
    }
  });
  monitorSocket.addEventListener('close', () => {
    monitorStatus('已断开', 'Disconnected', 'bad');
    monitorRetry = setTimeout(connectMonitor, 2000);
  });
  monitorSocket.addEventListener('error', () => monitorSocket.close());
}

function simulatorStatus(zh, en, state = '') {
  setPairedStatus('sim-stream-status', zh, en);
  $('#sim-stream-status').className = `pill bilingual ${state}`;
}

function decodeNextSimulatorFrame() {
  if (simulatorFrameDecoding || !simulatorPendingFrame) return;

  const pending = simulatorPendingFrame;
  simulatorPendingFrame = null;
  simulatorFrameDecoding = true;

  const nextUrl = URL.createObjectURL(new Blob([pending.bytes], {type: pending.meta?.mime || 'image/jpeg'}));
  const decoded = new Image();
  decoded.onload = () => {
    const frame = $('#sim-frame');
    const monitorFrame = $('#monitor-robot-frame');
    const previousUrl = simulatorFrameUrl;
    frame.src = nextUrl;
    monitorFrame.src = nextUrl;
    simulatorFrameUrl = nextUrl;
    frame.classList.add('ready');
    monitorFrame.classList.add('ready');
    $('#monitor-robot-placeholder').hidden = true;
    $('#sim-placeholder').hidden = true;
    const now = performance.now();
    simulatorFrameTimes.push(now);
    simulatorFrameTimes = simulatorFrameTimes.filter(value => now - value <= 3000);
    const elapsed = simulatorFrameTimes.at(-1) - simulatorFrameTimes[0];
    const fps = elapsed > 0 ? (simulatorFrameTimes.length - 1) * 1000 / elapsed : 0;
    const backend = pending.meta?.backend || 'unknown';
    const rate = fps > 0 ? fps.toFixed(1) : '—';
    simulatorStatus(`实时 · ${rate} FPS · ${backend}`, `Live · ${rate} FPS · ${backend}`, 'ok');
    if (pending.meta) {
      $('#sim-clock').textContent = `t ${Number(pending.meta.sim_time).toFixed(1)} s`;
      $('#sim-resolution').textContent = `${pending.meta.width}×${pending.meta.height}`;
    }
    if (previousUrl) URL.revokeObjectURL(previousUrl);
    simulatorFrameDecoding = false;
    decodeNextSimulatorFrame();
  };
  decoded.onerror = () => {
    URL.revokeObjectURL(nextUrl);
    simulatorFrameDecoding = false;
    simulatorStatus('画面解码失败', 'Frame decode failed', 'bad');
    decodeNextSimulatorFrame();
  };
  decoded.src = nextUrl;
}

function connectSimulator() {
  clearTimeout(simulatorRetry);
  const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
  simulatorSocket = new WebSocket(`${protocol}://${location.host}/ws/simulator`);
  simulatorSocket.binaryType = 'arraybuffer';
  simulatorStatus('连接中', 'Connecting');
  simulatorSocket.addEventListener('open', sendSimulatorRenderProfile);
  simulatorSocket.addEventListener('message', event => {
    if (typeof event.data === 'string') {
      const message = JSON.parse(event.data);
      if (message.type === 'frame') {
        simulatorFrameMeta = message;
        return;
      }
      simulatorStatus('画面不可用', message.message || 'Frame unavailable', 'bad');
      return;
    }
    simulatorPendingFrame = {bytes: event.data, meta: simulatorFrameMeta};
    decodeNextSimulatorFrame();
  });
  simulatorSocket.addEventListener('close', () => {
    simulatorPendingFrame = null;
    simulatorFrameMeta = null;
    simulatorFrameTimes = [];
    simulatorStatus('已断开', 'Disconnected', 'bad');
    simulatorRetry = setTimeout(connectSimulator, 2000);
  });
  simulatorSocket.addEventListener('error', () => simulatorSocket.close());
}

function sendSimulatorCamera(action, dx = 0, dy = 0) {
  if (simulatorSocket?.readyState !== WebSocket.OPEN) return;
  simulatorSocket.send(JSON.stringify({type: 'camera', action, dx, dy}));
}

function sendSimulatorRenderProfile() {
  if (simulatorSocket?.readyState !== WebSocket.OPEN) return;
  const bounds = simulatorViewport.getBoundingClientRect();
  const pixelRatio = Math.max(1, window.devicePixelRatio || 1);
  simulatorSocket.send(JSON.stringify({
    type: 'render',
    profile: simulatorProfile,
    width: Math.max(1, Math.round(bounds.width * pixelRatio)),
    height: Math.max(1, Math.round(bounds.height * pixelRatio)),
  }));
}

function scheduleSimulatorRenderProfile() {
  clearTimeout(simulatorResizeTimer);
  simulatorResizeTimer = setTimeout(sendSimulatorRenderProfile, 200);
}

function flushSimulatorOrbit() {
  simulatorOrbitFrame = null;
  if (simulatorOrbitDx || simulatorOrbitDy) {
    sendSimulatorCamera('orbit', simulatorOrbitDx, simulatorOrbitDy);
    simulatorOrbitDx = 0;
    simulatorOrbitDy = 0;
  }
}

const simulatorViewport = $('.simulator-viewport');
const simulatorQuality = $('#sim-quality');
if (!['smooth', 'clear', 'lossless'].includes(simulatorProfile)) simulatorProfile = 'clear';
simulatorQuality.value = simulatorProfile;
simulatorQuality.addEventListener('change', () => {
  simulatorProfile = simulatorQuality.value;
  localStorage.setItem('microduck-render-profile', simulatorProfile);
  sendSimulatorRenderProfile();
});
new ResizeObserver(scheduleSimulatorRenderProfile).observe(simulatorViewport);
simulatorViewport.addEventListener('pointerdown', event => {
  if (event.target.closest('.sim-quality-control')) return;
  if (event.button !== 0) return;
  event.preventDefault();
  simulatorPointerId = event.pointerId;
  simulatorPointerX = event.clientX;
  simulatorPointerY = event.clientY;
  simulatorViewport.setPointerCapture(event.pointerId);
  simulatorViewport.classList.add('dragging');
});
simulatorViewport.addEventListener('pointermove', event => {
  if (event.pointerId !== simulatorPointerId) return;
  simulatorOrbitDx += event.clientX - simulatorPointerX;
  simulatorOrbitDy += event.clientY - simulatorPointerY;
  simulatorPointerX = event.clientX;
  simulatorPointerY = event.clientY;
  if (!simulatorOrbitFrame) simulatorOrbitFrame = requestAnimationFrame(flushSimulatorOrbit);
});
function endSimulatorDrag(event) {
  if (event.pointerId !== simulatorPointerId) return;
  simulatorPointerId = null;
  simulatorViewport.classList.remove('dragging');
}
simulatorViewport.addEventListener('pointerup', endSimulatorDrag);
simulatorViewport.addEventListener('pointercancel', endSimulatorDrag);
simulatorViewport.addEventListener('lostpointercapture', endSimulatorDrag);
simulatorViewport.addEventListener('wheel', event => {
  if (event.target.closest('.sim-quality-control')) return;
  event.preventDefault();
  sendSimulatorCamera('zoom', 0, Math.max(-200, Math.min(200, event.deltaY)));
}, {passive: false});
simulatorViewport.addEventListener('dblclick', event => {
  event.preventDefault();
  sendSimulatorCamera('reset');
});

async function stop() {
  clearInterval(moveTimer);
  moveTimer = null;
  document.querySelectorAll('.active').forEach(node => node.classList.remove('active'));
  try {
    acceptedResult(await api('/api/control/stop', {method: 'POST'}));
    controlMessage('已停止', 'Stopped');
  } catch (error) {
    controlMessage(error.message, 'Control error', true);
  }
}

async function sendMove(button) {
  if (latestRobotPolicy === 'held') {
    clearInterval(moveTimer);
    moveTimer = null;
    controlMessage('请先启用 RL / 站起', 'Enable RL / Stand up first', true);
    return;
  }
  const command = {
    vx: Number(button.dataset.vx || 0),
    vy: Number(button.dataset.vy || 0),
    vyaw: Number(button.dataset.vyaw || 0),
  };
  try {
    await api('/api/control/move', {method: 'POST', body: JSON.stringify(command)});
    const commandText = JSON.stringify(command);
    controlMessage(`移动 ${commandText}`, `Moving ${commandText}`);
  } catch (error) {
    controlMessage(error.message, 'Control error', true);
  }
}

document.querySelectorAll('[data-vx],[data-vy],[data-vyaw]').forEach(button => {
  button.addEventListener('pointerdown', event => {
    event.preventDefault();
    button.setPointerCapture(event.pointerId);
    button.classList.add('active');
    sendMove(button);
    clearInterval(moveTimer);
    moveTimer = setInterval(() => sendMove(button), 100);
  });
  button.addEventListener('pointerup', stop);
  button.addEventListener('pointercancel', stop);
  button.addEventListener('lostpointercapture', stop);
});

document.querySelectorAll('[data-action="stop"]').forEach(button =>
  button.addEventListener('click', stop)
);

$('[data-action="enable"]').addEventListener('click', async () => {
  try {
    acceptedResult(await api('/api/control/enable', {method: 'POST', body: '{"on":true}'}));
    controlMessage('RL 已启用', 'RL enabled');
  } catch (error) {
    controlMessage(error.message, 'Control error', true);
  }
});

document.querySelectorAll('[data-skill]').forEach(button =>
  button.addEventListener('click', async () => {
    try {
      acceptedResult(
        await api('/api/control/skill', {
          method: 'POST',
          body: JSON.stringify({skill: button.dataset.skill}),
        })
      );
      controlMessage(
        `已接受：${button.dataset.labelZh}`,
        `Accepted: ${button.dataset.labelEn}`
      );
    } catch (error) {
      controlMessage(error.message, 'Control error', true);
    }
  })
);

document.addEventListener('visibilitychange', () => {
  if (document.hidden) stop();
});
window.addEventListener('pagehide', stop);

async function refresh() {
  try {
    const data = await api('/api/status');
    const repos = data.repositories;
    for (const [key, prefix] of [['microduck', 'runtime'], ['microduck_rl', 'rl']]) {
      const repo = repos[key];
      const summary = $(`#repo-${prefix}`);
      const detail = $(`#repo-${prefix}-detail`);
      if (!repo.available) {
        setBilingual(summary, '不可用', 'Unavailable');
        detail.textContent = repo.error || repo.path;
      } else {
        summary.textContent = repo.branch;
        if (repo.dirty) {
          setBilingual(detail, `${repo.changed_files} 个文件未提交`, `${repo.changed_files} changed files`);
        } else {
          setBilingual(detail, '工作区干净', 'Working tree clean');
        }
      }
    }

    const robotd = data.robotd;
    setBilingual($('#robotd'), robotd.connected ? '已连接' : '未连接', robotd.connected ? 'Connected' : 'Disconnected');
    $('#robotd').className = robotd.connected ? 'ok' : 'bad';
    if (robotd.connected) {
      setBilingual($('#robotd-detail'), 'JSON-RPC 可达', 'JSON-RPC reachable');
      renderMonitorHealth(robotd.health);
    } else {
      $('#robotd-detail').textContent = robotd.error || data.robotd_socket.path;
      renderMonitorHealth(null);
    }

    const sim = data.simulator;
    setBilingual($('#sim'), sim.connected ? '已连接' : '未连接', sim.connected ? 'Connected' : 'Disconnected');
    $('#sim').className = sim.connected ? 'ok' : 'bad';
    $('#sim-detail').textContent = sim.connected
      ? `t=${Number(sim.sim_time || 0).toFixed(1)}s · z=${Number(sim.trunk?.[2] || 0).toFixed(3)}m`
      : (sim.error || '');
    $('#sim-clock').textContent = `t ${Number(sim.sim_time || 0).toFixed(1)} s`;
    $('#sim-height').textContent = `z ${Number(sim.trunk?.[2] || 0).toFixed(3)} m`;

    const manageable = Boolean(data.service_manager?.available);
    renderServiceAction('robotd', robotd.connected, manageable);
    renderServiceAction('mujoco', sim.connected, manageable);

    const online = robotd.connected && sim.connected;
    setPairedStatus('overall', online ? '系统在线' : '部分离线', online ? 'System online' : 'Partially offline');
    $('#overall').className = `pill bilingual ${online ? 'ok' : 'bad'}`;
    setPairedStatus(
      'jobs-mode',
      data.training_jobs_enabled ? '已启用' : '默认关闭',
      data.training_jobs_enabled ? 'Enabled' : 'Disabled by default'
    );
  } catch (error) {
    setPairedStatus('overall', '状态失败', 'Status unavailable');
    $('#overall').className = 'pill bilingual bad';
  }
}

async function refreshJobs() {
  try {
    const jobs = await api('/api/training/jobs');
    $('#jobs').innerHTML = jobs.length
      ? jobs.map(job => `<div class="job"><span><b>${job.task_id}</b><br><small>${job.kind} · pid ${job.pid}</small></span><span class="${job.status === 'succeeded' ? 'ok' : job.status === 'failed' ? 'bad' : ''}">${job.status}</span></div>`).join('')
      : `<p class="muted">${interfaceLanguage === 'en' ? 'No training jobs have been started by Studio.' : '还没有 Studio 启动的训练任务。'}</p>`;
  } catch {}
}

$('#smoke-form').addEventListener('submit', async event => {
  event.preventDefault();
  const task_id = $('#task-id').value.trim();
  if (!task_id) return;
  try {
    await api('/api/training/smoke', {method: 'POST', body: JSON.stringify({task_id})});
    await refreshJobs();
  } catch (error) {
    alert(error.message);
  }
});

document.querySelectorAll('.service-action').forEach(button =>
  button.addEventListener('click', () => manageService(button))
);

markStaticChinese();
setInterfaceLanguage(interfaceLanguage);
$('#language-toggle').addEventListener('click', () =>
  setInterfaceLanguage(interfaceLanguage === 'zh' ? 'en' : 'zh')
);

refresh();
refreshJobs();
connectMonitor();
connectSimulator();
setInterval(refresh, 2000);
setInterval(refreshJobs, 3000);
