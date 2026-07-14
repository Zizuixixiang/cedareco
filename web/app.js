"use strict";

const STORAGE_KEY = "cedareco_standalone_binding_v1";
const ASSET_PREFIX = /\/web\/(?:index\.html)?$/u.test(location.pathname) ? "../assets/" : "assets/";
const GAME_INFO = {
  rat: { title: "鼠患打地鼠", action: "hunt_rat" },
  turtle: { title: "巴西龟驱赶", action: "expel_turtle" },
  snail: { title: "福寿螺捞螺", action: "catch_snail" },
  hyacinth: { title: "水葫芦拔草", action: "pull_hyacinth" },
  algae: { title: "绿潮捞藻", action: "skim_algae" },
  ice: { title: "凿冰", action: "crack_ice" }
};
const ACTION_TO_GAME = Object.fromEntries(Object.entries(GAME_INFO).map(([game, info]) => [info.action, game]));

let binding = readBinding() || { url: defaultServerUrl() };
let latestState = null;
let currentView = "state";
let pollTimer = null;
let modalCleanup = null;

const bindingNode = document.getElementById("binding");
const appNode = document.getElementById("pond-app");
const bindForm = document.getElementById("bind-form");
const serverUrlInput = document.getElementById("server-url");
const bindError = document.getElementById("bind-error");
const connectionNode = document.getElementById("connection");
const modal = document.getElementById("modal");
const modalTitle = document.getElementById("modal-title");
const modalBody = document.getElementById("modal-body");

function h(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function button(text, className, onClick) {
  const node = h("button", className, text);
  node.type = "button";
  if (onClick) node.addEventListener("click", onClick);
  return node;
}

function clear(node) {
  node.replaceChildren();
  return node;
}

function readBinding() {
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
    if (value && typeof value.url === "string") return { url: normalizeUrl(value.url) };
  } catch (_error) { /* 重新连接即可。 */ }
  return null;
}

function defaultServerUrl() {
  return /^https?:$/u.test(location.protocol) ? location.origin : "http://127.0.0.1:8765";
}

function normalizeUrl(value) {
  return String(value || "").trim().replace(/\/+$/u, "");
}

function assetUrl(path) {
  return new URL(ASSET_PREFIX + path, location.href).href;
}

async function api(path, options = {}) {
  if (!binding) throw new Error("尚未连接池塘服务");
  let response;
  try {
    response = await fetch(binding.url + path, {
      method: options.method || "GET",
      headers: options.body === undefined ? {} : { "Content-Type": "application/json" },
      body: options.body === undefined ? undefined : JSON.stringify(options.body)
    });
  } catch (_error) {
    throw new Error("连接不到池塘服务，请确认服务仍在运行");
  }
  let payload = null;
  try { payload = await response.json(); } catch (_error) { /* 下方统一报错。 */ }
  if (!response.ok || !payload) throw new Error((payload && (payload.error || payload.message)) || `请求失败 (${response.status})`);
  return payload;
}

function showConnection(ok, message) {
  connectionNode.textContent = message || (ok ? "已连接" : "连接中断");
  connectionNode.classList.toggle("bad", !ok);
}

function activeGames(state) {
  const games = [];
  const disasters = state.disasters || {};
  const flags = state.flags || {};
  if (disasters.invasion === "巴西龟入侵") games.push("turtle");
  if (disasters.invasion === "福寿螺入侵" || (flags.apple_snail && flags.apple_snail.status === "incubating")) games.push("snail");
  if (disasters.water_hyacinth_cover !== null && disasters.water_hyacinth_cover !== undefined) games.push("hyacinth");
  const biological = disasters.biological || [];
  if (biological.some(item => item && item.name === "鼠患")) games.push("rat");
  if (biological.some(item => item && item.name === "绿潮")) games.push("algae");
  if (flags.ice_on === true) games.push("ice");
  return games;
}

function availableGames(state) {
  const actions = new Set(state.available_human_actions || []);
  return new Set([...actions].map(action => ACTION_TO_GAME[action]).filter(Boolean));
}

function number(value, fallback = "—") {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Number(parsed.toFixed(2)).toString() : fallback;
}

function metric(label, value) {
  const node = h("div", "metric");
  node.append(h("small", "", label), h("strong", "", value));
  return node;
}

function renderState(state) {
  latestState = state;
  const view = clear(document.getElementById("view-state"));
  const status = h("section", "status-card card");
  status.append(h("div", "score", number(state.score, "0")));
  const copy = h("div");
  copy.append(
    h("h2", "", `第 ${number(state.day, "0")} 天 · ${state.season || "—"} · ${state.weather || "—"}`),
    h("p", "", state.comment || "池塘安静地呼吸着。")
  );
  status.append(copy);
  view.append(status);

  const env = state.environment || {};
  const metrics = h("section", "metrics");
  metrics.append(
    metric("水温", `${number(env.water_temp)}℃`),
    metric("溶氧", number(env.dissolved_oxygen && env.dissolved_oxygen.value)),
    metric("光照", number(env.light)),
    metric("营养盐", number(env.nutrients && env.nutrients.value)),
    metric("碎屑", number(env.detritus && env.detritus.value)),
    metric("浑浊", number(env.turbidity))
  );
  view.append(metrics);

  const games = activeGames(state);
  if (games.length) {
    const available = availableGames(state);
    const section = h("section", "section disaster-section card");
    section.append(h("h2", "", "池塘正在经历灾害"), h("p", "muted", "只有当前灾害对应的小游戏会出现；处理结果会写回这座池塘。"));
    const actions = h("div", "disaster-actions");
    games.forEach(gameId => {
      const canHelp = available.has(gameId);
      const node = button(canHelp ? `帮忙 · ${GAME_INFO[gameId].title}` : `已帮忙 · ${GAME_INFO[gameId].title}`, "disaster-button", () => startGame(gameId));
      node.disabled = !canHelp;
      actions.append(node);
    });
    section.append(actions);
    view.append(section);
  }

  const populationSection = h("section", "section card");
  populationSection.append(h("h2", "", "种群"));
  const groups = h("div", "population-groups");
  (state.populations || []).forEach(group => {
    const node = h("article", "population-group");
    node.append(h("h3", "", group.label || group.trophic));
    (group.species || []).filter(species => species.name !== "???" && Number(species.count) > 0).forEach(species => {
      const line = h("div", "species-line");
      line.append(h("span", "", species.name), h("strong", "", number(species.count)));
      node.append(line);
    });
    groups.append(node);
  });
  populationSection.append(groups);
  view.append(populationSection);

  const observeSection = h("section", "section card");
  observeSection.append(h("h2", "", "小机看到的池塘"), h("pre", "observe", state.observe_text || "—"));
  view.append(observeSection);
}

async function loadState() {
  try {
    const payload = await api("/api/state");
    renderState(payload.data);
    showConnection(true);
  } catch (error) {
    showConnection(false, error.message);
    throw error;
  }
}

async function renderCodex() {
  const view = clear(document.getElementById("view-codex"));
  view.append(h("p", "loading card", "正在翻图鉴…"));
  try {
    const payload = await api("/api/codex");
    clear(view);
    const data = payload.data || {};
    const section = h("section", "section card");
    const count = data.species_count || {};
    section.append(h("h2", "", `物种图鉴 ${number(count.appeared, "0")} / ${number(count.total, "0")}`));
    const grid = h("div", "codex-grid");
    (data.species || []).forEach(species => grid.append(h("div", "codex-item", species.name)));
    section.append(grid);
    view.append(section);
  } catch (error) {
    clear(view).append(h("p", "error card", error.message));
  }
}

async function renderAnnals() {
  const view = clear(document.getElementById("view-annals"));
  view.append(h("p", "loading card", "正在翻年鉴…"));
  try {
    const payload = await api("/api/annals");
    clear(view);
    const section = h("section", "section card");
    section.append(h("h2", "", "池塘年鉴"));
    const list = h("ol", "annals");
    (payload.data.timeline || []).forEach(entry => list.append(h("li", "", entry)));
    if (!list.childElementCount) list.append(h("li", "muted", "尚无记录。"));
    section.append(list);
    view.append(section);
  } catch (error) {
    clear(view).append(h("p", "error card", error.message));
  }
}

async function selectView(name) {
  currentView = name;
  document.querySelectorAll(".tab").forEach(node => node.classList.toggle("active", node.dataset.view === name));
  document.querySelectorAll(".view").forEach(node => { node.hidden = node.id !== `view-${name}`; });
  if (name === "state") await loadState();
  else if (name === "codex") await renderCodex();
  else await renderAnnals();
}

function openModal(title) {
  closeModal();
  modalTitle.textContent = title;
  clear(modalBody);
  modal.hidden = false;
  return modalBody;
}

function closeModal() {
  if (modalCleanup) {
    modalCleanup();
    modalCleanup = null;
  }
  modal.hidden = true;
  clear(modalBody);
}

function resultView(ok, title, message) {
  const body = openModal(title);
  const result = h("div", "result");
  result.append(h("div", `result-mark${ok ? "" : " bad"}`, ok ? "✓" : "!"), h("h3", "", ok ? "已经写回池塘" : "这次没有生效"), h("p", "", message || "—"));
  result.append(button("回到池塘", "primary", async () => { closeModal(); await loadState(); }));
  body.append(result);
}

async function submitGame(gameId, payload) {
  const info = GAME_INFO[gameId];
  const body = openModal(info.title);
  body.append(h("p", "loading", "正在把结果写回池塘…"));
  try {
    const result = await api("/api/human_action", { method: "POST", body: { action: info.action, ...(payload === null ? {} : { payload }) } });
    resultView(Boolean(result.ok), info.title, result.message || result.error);
  } catch (error) {
    resultView(false, info.title, error.message);
  }
}

function clock(node, deadline) {
  node.textContent = `剩余 ${Math.max(0, Math.ceil((deadline - Date.now()) / 1000))} 秒`;
}

function startRatGame() {
  const body = openModal(GAME_INFO.rat.title);
  const hud = h("div", "game-hud");
  const scoreNode = h("span", "", "命中 0");
  const timeNode = h("span");
  hud.append(scoreNode, timeNode);
  const stage = h("div", "game-stage");
  const target = button("", "game-target");
  const image = h("img");
  image.src = assetUrl("props/田鼠探头.png");
  image.alt = "田鼠";
  target.append(image);
  stage.append(target);
  body.append(hud, stage);
  let score = 0;
  const deadline = Date.now() + 30000;
  function move() {
    target.style.left = `${5 + Math.random() * 78}%`;
    target.style.top = `${5 + Math.random() * 75}%`;
  }
  target.addEventListener("click", () => { score += 1; scoreNode.textContent = `命中 ${score}`; move(); });
  move();
  const mover = setInterval(move, 850);
  const timer = setInterval(() => {
    clock(timeNode, deadline);
    if (Date.now() >= deadline) submitGame("rat", { count: Math.min(score, 12) });
  }, 100);
  clock(timeNode, deadline);
  modalCleanup = () => { clearInterval(mover); clearInterval(timer); };
}

function startTurtleGame() {
  const body = openModal(GAME_INFO.turtle.title);
  const hud = h("div", "game-hud");
  const progressText = h("span", "", "进度 0%");
  const timeNode = h("span");
  hud.append(progressText, timeNode);
  const meter = h("div", "progress");
  const fill = h("span");
  meter.append(fill);
  const stage = h("div", "turtle-stage");
  const target = button("");
  const image = h("img", "plant-art");
  image.src = assetUrl("species/巴西龟.png");
  image.alt = "巴西龟";
  target.append(image);
  stage.append(target);
  body.append(hud, meter, stage);
  let progress = 0;
  let last = performance.now();
  const deadline = Date.now() + 20000;
  let stopped = false;
  function paint() { progressText.textContent = `进度 ${Math.round(progress)}%`; fill.style.width = `${progress}%`; }
  target.addEventListener("click", () => { progress = Math.min(100, progress + 3); paint(); if (progress >= 100) { stopped = true; submitGame("turtle", null); } });
  function frame(now) {
    if (stopped) return;
    progress = Math.max(0, progress - (now - last) / 1000 * 8);
    last = now;
    paint();
    clock(timeNode, deadline);
    if (Date.now() >= deadline) resultView(false, GAME_INFO.turtle.title, "没能及时赶走巴西龟，它又游了回来。");
    else requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
  modalCleanup = () => { stopped = true; };
}

function startSnailGame() {
  const apple = latestState && latestState.flags && latestState.flags.apple_snail;
  if (apple && apple.status === "incubating") {
    const body = openModal(GAME_INFO.snail.title);
    const result = h("div", "result");
    result.append(h("h3", "", "岸边发现粉色卵块"), h("p", "", "在孵化前清掉，可以直接阻止这场福寿螺灾害。"), button("清理卵块", "primary", () => submitGame("snail", { count: 1 })));
    body.append(result);
    return;
  }
  const total = Math.max(1, Math.min(12, Number(apple && apple.count) || 12));
  const body = openModal(GAME_INFO.snail.title);
  const hud = h("div", "game-hud");
  const scoreNode = h("span", "", `福寿螺 0/${total}`);
  const timeNode = h("span");
  hud.append(scoreNode, timeNode);
  const stage = h("div", "game-stage");
  body.append(hud, stage);
  let caught = 0;
  let deadline = Date.now() + 30000;
  let finished = false;
  function addSnail(kind, index) {
    const node = button("", `snail-item${kind === "pond" ? " native" : ""}`);
    const image = h("img", "plant-art");
    image.src = assetUrl(kind === "apple" ? "species/福寿螺.png" : "species/田螺.png");
    image.alt = kind === "apple" ? "福寿螺" : "田螺";
    node.append(image);
    node.style.left = `${8 + (index * 23 + Math.random() * 18) % 82}%`;
    node.style.top = `${10 + (index * 31 + Math.random() * 22) % 78}%`;
    node.addEventListener("click", () => {
      node.remove();
      if (kind === "apple") {
        caught += 1;
        scoreNode.textContent = `福寿螺 ${caught}/${total}`;
        if (caught >= total) { finished = true; submitGame("snail", { count: caught }); }
      } else deadline -= 3000;
    });
    stage.append(node);
  }
  for (let index = 0; index < total; index += 1) addSnail("apple", index);
  for (let index = 0; index < 4; index += 1) addSnail("pond", index + total);
  const timer = setInterval(() => {
    clock(timeNode, deadline);
    if (!finished && Date.now() >= deadline) {
      finished = true;
      if (caught > 0) submitGame("snail", { count: caught });
      else resultView(false, GAME_INFO.snail.title, "这次没有捞到福寿螺。");
    }
  }, 100);
  clock(timeNode, deadline);
  modalCleanup = () => { finished = true; clearInterval(timer); };
}

function startHyacinthGame() {
  const body = openModal(GAME_INFO.hyacinth.title);
  const card = h("div", "timing-card");
  const label = h("h3", "", "小株 · 停在亮区");
  const count = h("p", "", "已拔 0 株 · 剩余 7 次");
  const track = h("div", "timing-track");
  const zone = h("span", "timing-zone");
  const marker = h("span", "timing-marker");
  track.append(zone, marker);
  const action = button("开始", "primary");
  card.append(label, count, track, action);
  body.append(card);
  const sizes = ["small", "medium", "large", "small", "medium", "large", "medium"];
  const tuning = { small: [1750, 50, "小株"], medium: [1350, 32.5, "中株"], large: [1000, 20, "大株"] };
  let round = 0;
  let pulled = 0;
  let running = false;
  let position = 2;
  let direction = 1;
  let last = performance.now();
  let stopped = false;
  function configure() {
    const config = tuning[sizes[round]];
    label.textContent = `${config[2]} · 停在亮区`;
    zone.style.width = `${config[1]}%`;
    zone.style.left = `${(100 - config[1]) / 2}%`;
    position = 2;
    marker.style.left = "2%";
  }
  action.addEventListener("click", () => {
    if (!running) { running = true; action.textContent = "停下"; last = performance.now(); return; }
    running = false;
    const width = tuning[sizes[round]][1];
    if (Math.abs(position - 50) <= width / 2) pulled += 1;
    round += 1;
    count.textContent = `已拔 ${pulled} 株 · 剩余 ${7 - round} 次`;
    if (round >= 7) {
      stopped = true;
      if (pulled > 0) submitGame("hyacinth", { stalks: pulled });
      else resultView(false, GAME_INFO.hyacinth.title, "这次没有成功拔出水葫芦。");
      return;
    }
    action.textContent = "开始";
    configure();
  });
  function frame(now) {
    if (stopped) return;
    if (running) {
      const sweep = tuning[sizes[round]][0];
      position += direction * (now - last) * 96 / sweep;
      if (position >= 98 || position <= 2) { position = Math.max(2, Math.min(98, position)); direction *= -1; }
      marker.style.left = `${position}%`;
      last = now;
    } else last = now;
    requestAnimationFrame(frame);
  }
  configure();
  requestAnimationFrame(frame);
  modalCleanup = () => { stopped = true; };
}

function startAlgaeGame() {
  const body = openModal(GAME_INFO.algae.title);
  const hud = h("div", "game-hud");
  const scoreNode = h("span", "", "得分 0");
  const timeNode = h("span");
  hud.append(scoreNode, timeNode);
  const stage = h("div", "game-stage");
  const net = h("div", "algae-net");
  const netImage = h("img");
  netImage.src = assetUrl("props/捞网.png");
  netImage.alt = "捞网";
  net.append(netImage);
  stage.append(net);
  body.append(hud, stage);
  let score = 0;
  let currentX = 250;
  let targetX = 250;
  let stickyUntil = 0;
  let objects = [];
  let last = performance.now();
  let stopped = false;
  const deadline = Date.now() + 45000;
  const algaeAssets = ["绿藻团.png", "绿藻团_a.png", "绿藻团_b.png"];
  function pointer(event) {
    const bounds = stage.getBoundingClientRect();
    targetX = Math.max(56, Math.min(bounds.width - 56, event.clientX - bounds.left));
  }
  stage.addEventListener("pointerdown", pointer);
  stage.addEventListener("pointermove", pointer);
  function spawn() {
    if (stopped) return;
    const roll = Math.random();
    const kind = roll < .15 ? "debris" : (roll < .78 ? "ordinary" : (roll < .93 ? "sticky" : "rare"));
    const settings = {
      ordinary: [1, assetUrl(`props/${algaeAssets[Math.floor(Math.random() * algaeAssets.length)]}`), 65],
      sticky: [1, assetUrl("props/黏性藻团.png"), 70],
      rare: [2, assetUrl("props/稀有蓝藻.png"), 125],
      debris: [-2, assetUrl(Math.random() < .5 ? "props/枯叶.png" : "props/小杂鱼.png"), 90]
    }[kind];
    const node = h("span", "algae-object");
    const image = h("img");
    image.src = settings[1];
    image.alt = "";
    node.append(image);
    const bounds = stage.getBoundingClientRect();
    const record = { node, kind, points: settings[0], speed: settings[2], x: 25 + Math.random() * Math.max(1, bounds.width - 50), y: -50 };
    objects.push(record);
    stage.append(node);
  }
  const spawner = setInterval(spawn, 750);
  spawn(); spawn(); spawn();
  function frame(now) {
    if (stopped) return;
    const bounds = stage.getBoundingClientRect();
    const delta = Math.min(.05, (now - last) / 1000);
    last = now;
    const damping = Date.now() < stickyUntil ? .055 : .14;
    currentX += (targetX - currentX) * damping;
    net.style.left = `${currentX}px`;
    net.classList.toggle("sticky", Date.now() < stickyUntil);
    const netY = bounds.height - 47;
    objects = objects.filter(record => {
      record.y += record.speed * delta;
      record.node.style.left = `${record.x}px`;
      record.node.style.top = `${record.y}px`;
      if (Math.abs(record.x - currentX) < 52 && Math.abs(record.y - netY) < 27) {
        score = Math.max(0, Math.min(50, score + record.points));
        if (record.kind === "sticky") stickyUntil = Date.now() + 2000;
        scoreNode.textContent = `得分 ${score}`;
        record.node.remove();
        return false;
      }
      if (record.y > bounds.height + 50) { record.node.remove(); return false; }
      return true;
    });
    clock(timeNode, deadline);
    if (Date.now() >= deadline) {
      stopped = true;
      if (score > 0) submitGame("algae", { amount: score });
      else resultView(false, GAME_INFO.algae.title, "这次没有捞到绿藻。 ");
    } else requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
  modalCleanup = () => { stopped = true; clearInterval(spawner); objects.forEach(record => record.node.remove()); objects = []; };
}

function startIceGame() {
  const body = openModal(GAME_INFO.ice.title);
  const progressText = h("p", "game-hud", "凿冰进度 0%");
  const meter = h("div", "progress");
  const fill = h("span");
  meter.append(fill);
  const stage = h("div", "turtle-stage");
  const target = button("");
  const image = h("img", "plant-art");
  image.src = assetUrl("props/锤子.png");
  image.alt = "锤子";
  target.append(image);
  stage.append(target);
  body.append(progressText, meter, stage);
  let progress = 0;
  target.addEventListener("click", () => {
    progress = Math.min(100, progress + 5);
    progressText.textContent = `凿冰进度 ${progress}%`;
    fill.style.width = `${progress}%`;
    if (progress >= 100) submitGame("ice", null);
  });
}

function startGame(gameId) {
  if (!latestState || !activeGames(latestState).includes(gameId) || !availableGames(latestState).has(gameId)) return;
  if (gameId === "rat") startRatGame();
  else if (gameId === "turtle") startTurtleGame();
  else if (gameId === "snail") startSnailGame();
  else if (gameId === "hyacinth") startHyacinthGame();
  else if (gameId === "algae") startAlgaeGame();
  else startIceGame();
}

async function connect(candidate) {
  binding = candidate;
  const payload = await api("/api/state");
  localStorage.setItem(STORAGE_KEY, JSON.stringify(binding));
  bindingNode.hidden = true;
  appNode.hidden = false;
  renderState(payload.data);
  showConnection(true);
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(() => {
    if (currentView === "state" && modal.hidden) loadState().catch(() => {});
  }, 15000);
}

bindForm.addEventListener("submit", async event => {
  event.preventDefault();
  bindError.hidden = true;
  const candidate = { url: normalizeUrl(serverUrlInput.value) };
  try {
    await connect(candidate);
  } catch (error) {
    binding = null;
    bindError.textContent = error.message;
    bindError.hidden = false;
  }
});

document.getElementById("refresh").addEventListener("click", () => selectView(currentView));
document.getElementById("change-server").addEventListener("click", () => {
  localStorage.removeItem(STORAGE_KEY);
  binding = null;
  latestState = null;
  if (pollTimer) clearInterval(pollTimer);
  appNode.hidden = true;
  bindingNode.hidden = false;
});
document.getElementById("modal-close").addEventListener("click", closeModal);
modal.addEventListener("click", event => { if (event.target === modal) closeModal(); });
document.addEventListener("keydown", event => { if (event.key === "Escape" && !modal.hidden) closeModal(); });
document.querySelectorAll(".tab").forEach(node => node.addEventListener("click", () => selectView(node.dataset.view)));

serverUrlInput.value = binding ? binding.url : defaultServerUrl();
if (binding) connect(binding).catch(error => {
  binding = null;
  localStorage.removeItem(STORAGE_KEY);
  appNode.hidden = true;
  bindingNode.hidden = false;
  bindError.textContent = error.message;
  bindError.hidden = false;
});
