const $ = selector => document.querySelector(selector);
let moveTimer = null;

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
  primary.textContent = zh;
  const secondary = document.createElement('span');
  secondary.className = 'label-en';
  secondary.textContent = en;
  node.replaceChildren(primary, secondary);
}

function setPairedStatus(id, zh, en) {
  $(`#${id}-zh`).textContent = zh;
  $(`#${id}-en`).textContent = en;
}

function controlMessage(zh, en, error = false) {
  setPairedStatus('control-status', zh, en);
  $('#control-status').className = `bilingual ${error ? 'bad' : 'ok'}`;
}

async function stop() {
  clearInterval(moveTimer);
  moveTimer = null;
  document.querySelectorAll('.active').forEach(node => node.classList.remove('active'));
  try {
    await api('/api/control/stop', {method: 'POST'});
    controlMessage('已停止', 'Stopped');
  } catch (error) {
    controlMessage(error.message, 'Control error', true);
  }
}

async function sendMove(button) {
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
    await api('/api/control/enable', {method: 'POST', body: '{"on":true}'});
    controlMessage('RL 已启用', 'RL enabled');
  } catch (error) {
    controlMessage(error.message, 'Control error', true);
  }
});

document.querySelectorAll('[data-skill]').forEach(button =>
  button.addEventListener('click', async () => {
    try {
      await api('/api/control/skill', {
        method: 'POST',
        body: JSON.stringify({skill: button.dataset.skill}),
      });
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
    } else {
      $('#robotd-detail').textContent = robotd.error || data.robotd_socket.path;
    }

    const sim = data.simulator;
    setBilingual($('#sim'), sim.connected ? '已连接' : '未连接', sim.connected ? 'Connected' : 'Disconnected');
    $('#sim').className = sim.connected ? 'ok' : 'bad';
    $('#sim-detail').textContent = sim.connected
      ? `t=${Number(sim.sim_time || 0).toFixed(1)}s · z=${Number(sim.trunk?.[2] || 0).toFixed(3)}m`
      : (sim.error || '');

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
      : '<p class="muted">还没有 Studio 启动的训练任务。<small class="label-en">No training jobs have been started by Studio.</small></p>';
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

refresh();
refreshJobs();
setInterval(refresh, 2000);
setInterval(refreshJobs, 3000);
