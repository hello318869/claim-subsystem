"use strict";

const PAGE_SIZE = 20;
const MESSAGE_PAGE_SIZE = 50;
const POLL_MS = 5000;
const HANDOVER_HINT = "对方为校外人员，建议在失物招领处交接";
const POST_LABELS = { lost: "失物", found: "招领", open: "开放认领", in_handover: "交接中", completed: "已完成", withdrawn: "已撤回" };
const CLAIM_LABELS = { pending: "待审核", accepted: "待交接", rejected: "已拒绝", cancelled: "已取消", completed: "已完成", closed: "已关闭" };
const CLOSE_LABELS = { post_withdrawn: "信息已撤回", another_claim_accepted: "已选择另一认领申请" };
const REASON_LABELS = { category_same: "类别相同", location_same: "地点相同", time_near: "丢失与拾获时间接近", keyword_overlap: "标题关键词相似" };
const FIELD_LABELS = { username: "账号", password: "密码", post_id: "信息", verification_text: "私有认领证明", decision_note: "审核说明", content: "消息", after_id: "消息游标", limit: "消息批量上限" };
const beijingTime = new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Shanghai" });
const $ = (id) => document.getElementById(id);
const all = (selector) => Array.from(document.querySelectorAll(selector));

const state = {
  view: "posts",
  role: "applicant",
  demoAvailable: false,
  session: null,
  authBusy: false,
  application: null,
  match: null,
  detail: null
};
const pagers = Object.fromEntries(["posts", "sources", "claims"].map((key) => [key, {
  key, page: 1, controller: null, list: $(`${key}-list`), status: $(`${key}-status`), nav: document.querySelector(`[data-pager="${key}"]`)
}]));

class ApiError extends Error {
  constructor(status, payload, retryAfter = null) {
    super(payload?.message || "请求失败，请稍后再试。");
    this.status = status;
    this.code = payload?.code;
    this.fields = payload?.errors;
    this.retryAfter = retryAfter;
  }
}

async function request(path, { method = "GET", body, session = state.session, token = session?.token, signal = session?.controller.signal } = {}) {
  const headers = { Accept: "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(`/api/v1${path}`, {
    method, headers, signal, credentials: "omit", cache: "no-store",
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  let payload = null;
  try {
    payload = await response.json();
  } catch (error) {
    if (error.name === "AbortError") throw error;
  }
  if (response.status === 401 && session && state.session === session) {
    setSession(null);
    show("session-error", "登录已失效，请重新登录。");
  }
  if (!response.ok) throw new ApiError(response.status, payload, response.headers.get("Retry-After"));
  if (payload?.code !== "OK" || !Object.hasOwn(payload, "data")) {
    throw new Error("接口返回结构无法识别，请检查联调接口。");
  }
  return payload.data;
}

function errorText(error) {
  if (error.status === 404) return "记录不存在或当前身份无权查看。";
  if (error.code === "IDENTITY_REQUIRED") return "请先完成校园身份绑定。";
  if (!(error instanceof ApiError)) {
    return error instanceof TypeError ? "网络请求失败，请检查连接后再试。" : error.message;
  }
  const lines = [error.message];
  if (error.status === 409) lines.push("请刷新记录，查看最新状态。");
  if (error.status === 429 && /^\d+$/.test(error.retryAfter ?? "")) lines.push(`请在 ${error.retryAfter} 秒后再试。`);
  for (const [field, messages] of Object.entries(error.fields ?? {})) {
    if (Array.isArray(messages)) lines.push(`${FIELD_LABELS[field] ?? field}：${messages.join("；")}`);
  }
  return lines.join("\n");
}

function show(id, message = "") {
  const el = $(id);
  el.textContent = message;
  el.hidden = !message;
}

function node(tag, content = "", className = "") {
  const el = document.createElement(tag);
  el.textContent = content;
  if (className) el.className = className;
  return el;
}

function button(label, action, className = "secondary") {
  const el = node("button", label, className);
  el.type = "button";
  el.addEventListener("click", action);
  return el;
}

function date(value) {
  if (!value) return "";
  const time = new Date(value);
  return Number.isNaN(time.valueOf()) ? "" : beijingTime.format(time);
}

function invalidLength(value, min, max) {
  const length = Array.from(value).length;
  return length < min || length > max;
}

function sessionControls() {
  const session = state.session;
  const user = session?.user;
  const name = user?.nickname || user?.username || "已登录";
  const verification = user?.is_campus_verified
    ? (user.verification_mode === "demo" ? "校园身份已绑定（演示认证）" : "已绑定校园身份")
    : "未绑定校园身份";
  $("session-info").textContent = user
    ? `${name} · ${session.demo ? "演示会话 · " : ""}${verification}`
    : "访客 · 可浏览公开信息";
  $("login-form").hidden = !!session;
  $("logout").hidden = !session;
  $("demo-form").hidden = !state.demoAvailable || (!!session && !session.demo);
  $("demo-form").querySelector("button").textContent = session?.demo ? "切换演示身份" : "进入演示";
  for (const control of all(".session-card input, .session-card select, .session-card button")) control.disabled = state.authBusy;
}

function setSession(session, reload = true) {
  state.session?.controller.abort();
  state.session = session;
  show("session-error");
  show("notice");
  clearApplication();
  clearMatch();
  closeDetail();
  for (const pager of Object.values(pagers)) resetPager(pager);
  setRole("applicant");
  sessionControls();
  if (reload) loadActiveView();
}

function revoke(session) {
  return request(session.demo ? "/demo/logout" : "/auth/logout", { method: "POST", session: null, token: session.token });
}

async function signIn(path, body, demo) {
  if (state.authBusy) return;
  state.authBusy = true;
  const previous = state.session;
  setSession(null, false);
  try {
    if (previous) {
      try {
        await revoke(previous);
      } catch (error) {
        if (error.status !== 401) throw error;
      }
    }
    const data = await request(path, { method: "POST", body, session: null });
    if (typeof data?.access_token !== "string" || !data.access_token || typeof data.user?.id !== "string" || !data.user.id) {
      throw new Error("登录响应缺少访问令牌或用户摘要。");
    }
    setSession({ token: data.access_token, user: data.user, demo, controller: new AbortController() });
  } catch (error) {
    show("session-error", errorText(error));
    loadActiveView();
  } finally {
    state.authBusy = false;
    sessionControls();
  }
}

async function signOut() {
  const previous = state.session;
  if (!previous || state.authBusy) return;
  state.authBusy = true;
  setSession(null);
  try {
    await revoke(previous);
  } catch (error) {
    if (error.status !== 401) show("session-error", `已退出本页。服务端登出失败：${errorText(error)}`);
  } finally {
    state.authBusy = false;
    sessionControls();
  }
}

function resetPager(pager) {
  pager.controller?.abort();
  pager.controller = null;
  pager.page = 1;
  pager.nav.hidden = true;
  pager.list.replaceChildren();
  pager.status.textContent = "";
}

function pagePath(key, page) {
  const paging = `page=${page}&page_size=${PAGE_SIZE}`;
  if (key === "claims") return `/users/me/claims?role=${state.role}&${paging}`;
  const mine = key === "sources";
  const demo = state.session?.demo || (!state.session && state.demoAvailable);
  if (demo) return `/demo/posts?mine=${mine}&${paging}`;
  return `${mine ? "/users/me/posts" : "/posts"}?status=open&${paging}`;
}

async function loadPage(key, page = pagers[key].page) {
  const pager = pagers[key];
  const session = state.session;
  pager.controller?.abort();
  pager.list.replaceChildren();
  pager.nav.hidden = true;
  if (!session && key !== "posts") {
    pager.status.textContent = "请先登录。";
    return;
  }
  const controller = new AbortController();
  pager.controller = controller;
  pager.status.textContent = "正在加载…";
  try {
    const data = await request(pagePath(key, page), { session, signal: controller.signal });
    if (controller.signal.aborted) return;
    if (!Array.isArray(data?.items) || !Number.isInteger(data.total_pages) || !Number.isInteger(data.total)) {
      throw new Error("列表响应缺少分页数据。");
    }
    pager.page = page;
    pager.status.textContent = data.total ? `共 ${data.total} 条` : "暂无记录。";
    const render = key === "claims" ? claimCard : (post) => postCard(post, key === "sources");
    pager.list.replaceChildren(...data.items.map(render));
    pager.nav.hidden = data.total_pages <= 1 && page === 1;
    pager.nav.querySelector("[data-page]").textContent = `第 ${page} 页，共 ${data.total_pages} 页`;
    pager.nav.querySelector("[data-step='-1']").disabled = page <= 1;
    pager.nav.querySelector("[data-step='1']").disabled = page >= data.total_pages;
  } catch (error) {
    if (!controller.signal.aborted) pager.status.textContent = errorText(error);
  }
}

function postMeta(post) {
  const publisher = post.publisher?.nickname ? `发布者 ${post.publisher.nickname}` : "";
  return [POST_LABELS[post.post_type], POST_LABELS[post.status], post.category?.name, post.campus?.name, post.location?.name,
    date(post.occurred_at), publisher].filter(Boolean).join(" · ");
}

function postCard(post, source = false) {
  const card = node("li");
  if (source && post.status !== "open") {
    card.append(node("strong", post.title), node("p", "仅开放信息可以查找匹配。", "muted"));
  } else {
    card.append(button(post.title || "查看信息", () => source ? findMatches(post) : openApplication(post), "item-title"));
  }
  card.append(node("p", postMeta(post), "muted"));
  return card;
}

function claimCard(claim) {
  const card = node("li");
  card.append(button(claim.post?.title || "查看认领", () => openDetail(claim.id), "item-title"),
    node("p", [CLAIM_LABELS[claim.status], date(claim.created_at)].filter(Boolean).join(" · "), "muted"));
  return card;
}

function clearApplication() {
  state.application?.controller.abort();
  state.application = null;
  $("application").hidden = true;
  $("application-form").reset();
  $("application-form").querySelector("button").disabled = false;
  show("application-error");
  show("application-hint");
  for (const id of ["application-title", "application-meta", "application-permission"]) $(id).textContent = "";
}

function openApplication(post) {
  clearApplication();
  const user = state.session?.user;
  state.application = { post, controller: new AbortController() };
  $("application").hidden = false;
  $("application-title").textContent = post.title;
  $("application-meta").textContent = postMeta(post);
  show("application-hint", post.post_type === "lost" && !post.publisher?.is_deleted && post.publisher?.is_campus_verified === false ? HANDOVER_HINT : "");
  let permission = "";
  if (post.publisher?.is_deleted) permission = "信息发布者已注销，无法申请认领";
  else if (post.status !== "open") permission = "这条信息当前不接受新的认领申请。";
  else if (!user) permission = "登录并绑定校园身份后可以提交认领申请。";
  else if (user.id === post.publisher?.id) permission = "你不能认领自己发布的信息。";
  else if (!user.is_campus_verified) permission = "请先完成校园身份绑定。";
  $("application-permission").textContent = permission;
  $("application-form").hidden = !!permission;
}

async function applyForPost(event) {
  event.preventDefault();
  const application = state.application;
  if (!application || !state.session || event.currentTarget.hidden) return;
  const submit = event.currentTarget.querySelector("button");
  if (submit.disabled) return;
  const proof = $("verification-text").value.trim();
  show("application-error");
  if (invalidLength(proof, 10, 1000)) {
    show("application-error", "私有认领证明需要 10–1000 字。");
    return;
  }
  submit.disabled = true;
  try {
    const claim = await request("/claims", {
      method: "POST", body: { post_id: application.post.id, verification_text: proof }, signal: application.controller.signal
    });
    if (state.application !== application) return;
    setRole("applicant");
    resetPager(pagers.claims);
    switchView("claims");
    show("notice", "认领申请已提交。");
    void openDetail(claim.id);
  } catch (error) {
    if (state.application === application) show("application-error", errorText(error));
  } finally {
    if (state.application === application) submit.disabled = false;
  }
}

function clearMatch() {
  state.match?.abort();
  state.match = null;
  $("match-results").hidden = true;
  $("match-list").replaceChildren();
  $("match-status").textContent = "";
  $("match-title").textContent = "匹配结果";
}

async function findMatches(post) {
  clearMatch();
  const controller = new AbortController();
  state.match = controller;
  $("match-results").hidden = false;
  $("match-title").textContent = `匹配结果 · ${post.title}`;
  $("match-status").textContent = "正在查找…";
  try {
    const data = await request(`/posts/${encodeURIComponent(post.id)}/matches`, { signal: controller.signal });
    if (controller.signal.aborted) return;
    if (data?.source_post_id !== post.id || !Array.isArray(data.items)) throw new Error("匹配结果与所选信息不符。");
    $("match-status").textContent = data.items.length ? `找到 ${data.items.length} 条候选。` : "暂无符合条件的候选。";
    for (const match of data.items) {
      const card = node("li");
      card.append(button(match.post.title, () => {
        switchView("posts");
        openApplication(match.post);
      }, "item-title"), node("p", postMeta(match.post), "muted"));
      const reasons = match.reasons.map((reason) => REASON_LABELS[reason] ?? reason).join("、");
      card.append(node("p", `${match.score} 分${reasons ? ` · ${reasons}` : ""}`));
      $("match-list").append(card);
    }
  } catch (error) {
    if (!controller.signal.aborted) $("match-status").textContent = errorText(error);
  }
}

function closeDetail() {
  const detail = state.detail;
  if (detail) {
    clearTimeout(detail.timer);
    detail.controller.abort();
  }
  state.detail = null;
  $("claim-detail").hidden = true;
  $("conversation").hidden = true;
  $("message-form").hidden = true;
  $("message-form").reset();
  $("message-form").querySelector("button").disabled = false;
  $("decision-label").hidden = true;
  $("decision-note").value = "";
  for (const id of ["claim-facts", "claim-buttons", "messages-list"]) $(id).replaceChildren();
  for (const id of ["claim-title", "claim-status", "messages-status"]) $(id).textContent = "";
  for (const id of ["claim-error", "handover-hint", "messages-error"]) show(id);
}

function openDetail(id) {
  closeDetail();
  if (!state.session) return;
  const detail = {
    id, session: state.session, controller: new AbortController(), claim: null, reading: false, changing: false,
    sending: false, messages: new Set(), cursor: null, timer: null, messageRequest: null
  };
  state.detail = detail;
  $("claim-detail").hidden = false;
  $("claim-title").textContent = "认领详情";
  $("claim-title").focus({ preventScroll: true });
  return readDetail(detail);
}

function claimRole(claim, user) {
  if (user.id === claim.applicant?.id || user.id === claim.applicant_id) return "applicant";
  if (user.id === claim.publisher?.id) return "publisher";
  return null;
}

function forgetUnavailableDetail(error) {
  closeDetail();
  show("notice", errorText(error));
  void loadPage("claims");
}

async function readDetail(detail) {
  if (!detail || detail.reading || detail.changing) return;
  detail.reading = true;
  $("refresh-claim").disabled = true;
  for (const control of $("claim-buttons").querySelectorAll("button")) control.disabled = true;
  if (!detail.claim) $("claim-status").textContent = "正在加载详情…";
  show("claim-error");
  try {
    const claim = await request(`/claims/${encodeURIComponent(detail.id)}`, { signal: detail.controller.signal });
    if (state.detail !== detail) return;
    if (claim?.id !== detail.id || !claimRole(claim, detail.session.user)) throw new ApiError(404);
    const firstRead = !detail.claim;
    detail.claim = claim;
    renderDetail(detail);
    if (firstRead) void loadMessages(detail);
  } catch (error) {
    if (state.detail !== detail) return;
    if (error.status === 404 || error.status === 403) {
      forgetUnavailableDetail(error);
    } else {
      if (!detail.claim) $("claim-status").textContent = "详情加载失败。";
      show("claim-error", errorText(error));
    }
  } finally {
    detail.reading = false;
    if (state.detail === detail) {
      $("refresh-claim").disabled = false;
      for (const control of $("claim-buttons").querySelectorAll("button")) control.disabled = false;
    }
  }
}

function fact(label, value) {
  const row = node("div", "", "fact");
  row.append(node("dt", label), node("dd", value));
  return row;
}

function canMessage(claim) {
  return claim?.status === "pending" || claim?.status === "accepted";
}

function renderDetail(detail) {
  const claim = detail.claim;
  const role = claimRole(claim, detail.session.user);
  $("claim-title").textContent = claim.post?.title || "认领详情";
  $("claim-status").textContent = [CLAIM_LABELS[claim.status] || claim.status, role === "applicant" ? "我发起的" : "我收到的"].join(" · ");
  const facts = node("dl");
  facts.append(
    fact("私有证明", claim.verification_text),
    fact("申请时间", date(claim.created_at) || "—"),
    fact("申请者确认", date(claim.applicant_confirmed_at) || "未确认"),
    fact("发布者确认", date(claim.publisher_confirmed_at) || "未确认")
  );
  if (claim.decision_note) facts.append(fact("审核说明", claim.decision_note));
  if (claim.close_reason) facts.append(fact("关闭原因", CLOSE_LABELS[claim.close_reason] ?? claim.close_reason));
  $("claim-facts").replaceChildren(facts);
  show("handover-hint", role === "applicant" && claim.post?.post_type === "lost" && !claim.publisher?.is_deleted && claim.publisher?.is_campus_verified === false ? HANDOVER_HINT : "");
  renderClaimActions(detail, role);
  $("conversation").hidden = false;
  $("message-form").hidden = !canMessage(claim);
}

function renderClaimActions(detail, role) {
  const claim = detail.claim;
  const pending = claim.status === "pending";
  const accepted = claim.status === "accepted";
  const reviewing = pending && role === "publisher";
  const actions = [];
  if (reviewing) actions.push(["同意申请", "accept"], ["拒绝申请", "reject"]);
  const ownConfirmation = role === "applicant" ? claim.applicant_confirmed_at : claim.publisher_confirmed_at;
  if (accepted && !ownConfirmation) actions.push(["确认已交接", "confirm-handover"]);
  if ((pending && role === "applicant") || (accepted && !claim.applicant_confirmed_at && !claim.publisher_confirmed_at)) {
    actions.push(["取消申请", "cancel"]);
  }
  $("decision-label").hidden = !reviewing;
  if (!reviewing) $("decision-note").value = "";
  $("claim-buttons").replaceChildren(...actions.map(([label, action]) => {
    const control = button(label, () => changeClaim(detail, action));
    control.disabled = detail.changing || detail.reading;
    return control;
  }));
}

async function changeClaim(detail, action) {
  if (detail.changing || detail.reading) return;
  show("claim-error");
  const note = $("decision-note").value.trim();
  const reviewing = action === "accept" || action === "reject";
  if (reviewing && invalidLength(note, action === "reject" ? 1 : 0, 500)) {
    show("claim-error", action === "reject" ? "拒绝时需要填写 1–500 字的审核说明。" : "审核说明最多 500 字。");
    return;
  }
  detail.changing = true;
  for (const control of $("claim-buttons").querySelectorAll("button")) control.disabled = true;
  $("refresh-claim").disabled = true;
  let refresh = false;
  try {
    const claim = await request(`/claims/${encodeURIComponent(detail.id)}/${action}`, {
      method: "POST", body: reviewing && note ? { decision_note: note } : undefined, signal: detail.controller.signal
    });
    if (state.detail !== detail) return;
    if (claim?.id !== detail.id || !claimRole(claim, detail.session.user)) throw new ApiError(404);
    detail.claim = claim;
    renderDetail(detail);
    void loadPage("claims");
  } catch (error) {
    if (state.detail !== detail) return;
    if (error.status === 404 || error.status === 403) forgetUnavailableDetail(error);
    else show("claim-error", errorText(error));
    refresh = error.status === 409;
  } finally {
    detail.changing = false;
    if (state.detail === detail) {
      $("refresh-claim").disabled = false;
      renderClaimActions(detail, claimRole(detail.claim, detail.session.user));
    }
  }
  if (refresh && state.detail === detail) {
    const conflict = $("claim-error").textContent;
    await readDetail(detail);
    if (state.detail === detail && !$("claim-error").textContent) show("claim-error", conflict);
  }
}

function appendMessages(detail, messages) {
  const list = $("messages-list");
  const atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 24;
  for (const message of messages) {
    if (typeof message.id !== "string" || typeof message.content !== "string") throw new Error("消息字段不完整。");
    if (detail.messages.has(message.id)) continue;
    detail.messages.add(message.id);
    const mine = (message.sender_id ?? message.sender?.id) === detail.session.user.id;
    const row = node("li", "", mine ? "message mine" : "message");
    row.append(node("small", [mine ? "我" : "对方", date(message.created_at)].filter(Boolean).join(" · "), "muted"), node("p", message.content));
    list.append(row);
  }
  if (atBottom) list.scrollTop = list.scrollHeight;
  $("messages-status").textContent = detail.messages.size ? "" : "暂无消息。";
}

async function readMessageBatches(detail) {
  try {
    let hasMore;
    do {
      const previous = detail.cursor;
      const cursor = previous === null ? "" : `&after_id=${encodeURIComponent(previous)}`;
      const data = await request(`/claims/${encodeURIComponent(detail.id)}/messages?limit=${MESSAGE_PAGE_SIZE}${cursor}`, { signal: detail.controller.signal });
      if (state.detail !== detail) return false;
      if (!Array.isArray(data?.items) || typeof data.has_more !== "boolean" ||
          (data.next_after_id !== null && typeof data.next_after_id !== "string") ||
          (data.has_more && (!data.next_after_id || data.next_after_id === previous))) {
        throw new Error("消息列表响应或游标无法识别。");
      }
      appendMessages(detail, data.items);
      detail.cursor = data.next_after_id;
      hasMore = data.has_more;
    } while (hasMore);
    return true;
  } catch (error) {
    if (state.detail === detail) {
      if (error.status === 404 || error.status === 403) forgetUnavailableDetail(error);
      else $("messages-status").textContent = `消息刷新失败。${errorText(error)}`;
    }
    return false;
  }
}

function loadMessages(detail) {
  if (!detail?.claim || state.detail !== detail) return Promise.resolve(false);
  if (detail.messageRequest) return detail.messageRequest;
  clearTimeout(detail.timer);
  $("refresh-messages").disabled = true;
  if (!detail.messages.size) $("messages-status").textContent = "正在加载消息…";
  detail.messageRequest = readMessageBatches(detail).finally(() => {
    detail.messageRequest = null;
    if (state.detail === detail) {
      $("refresh-messages").disabled = false;
      detail.timer = setTimeout(() => loadMessages(detail), POLL_MS);
    }
  });
  return detail.messageRequest;
}

async function refreshAfterSending(detail) {
  if (detail.messageRequest) await detail.messageRequest;
  return loadMessages(detail);
}

async function sendMessage(event) {
  event.preventDefault();
  const detail = state.detail;
  if (!detail || detail.sending || !canMessage(detail.claim)) return;
  const input = $("message-content");
  const draft = input.value;
  const content = draft.trim();
  show("messages-error");
  if (invalidLength(content, 1, 1000)) {
    show("messages-error", "消息需要 1–1000 字。");
    return;
  }
  const submit = event.currentTarget.querySelector("button");
  detail.sending = true;
  submit.disabled = true;
  try {
    await request(`/claims/${encodeURIComponent(detail.id)}/messages`, {
      method: "POST", body: { content }, signal: detail.controller.signal
    });
    if (state.detail !== detail) return;
    if (input.value === draft) input.value = "";
    await refreshAfterSending(detail);
  } catch (error) {
    if (state.detail !== detail) return;
    if (error.status === 404 || error.status === 403) forgetUnavailableDetail(error);
    else if (!(error instanceof ApiError) || error.status >= 500) {
      const refreshed = await refreshAfterSending(detail);
      if (state.detail === detail) show("messages-error", refreshed
        ? "发送结果未能确认。消息列表已刷新，请核对后再决定是否重发。"
        : "发送结果未能确认，消息列表也未能刷新。请先刷新并核对记录，再决定是否重发。");
    } else {
      if (error.status === 409) await readDetail(detail);
      if (state.detail === detail) show("messages-error", errorText(error));
    }
  } finally {
    detail.sending = false;
    if (state.detail === detail) submit.disabled = false;
  }
}

function loadActiveView() {
  void loadPage(state.view === "matches" ? "sources" : state.view);
}

function switchView(view) {
  if (state.view === view) return;
  if (state.view === "posts") clearApplication();
  if (state.view === "matches") clearMatch();
  if (state.view === "claims") closeDetail();
  state.view = view;
  show("notice");
  for (const control of all("[data-view]")) {
    const active = control.dataset.view === view;
    control.setAttribute("aria-pressed", String(active));
    $(control.dataset.view).hidden = !active;
  }
  loadActiveView();
}

function setRole(role, reload = false) {
  if (state.role !== role) closeDetail();
  state.role = role;
  for (const control of all("[data-role]")) control.setAttribute("aria-pressed", String(control.dataset.role === role));
  if (reload) {
    show("notice");
    resetPager(pagers.claims);
    void loadPage("claims");
  }
}

$("login-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const body = { username: form.elements.username.value.trim(), password: form.elements.password.value };
  form.elements.password.value = "";
  void signIn("/auth/login", body, false);
});
$("demo-form").addEventListener("submit", (event) => {
  event.preventDefault();
  void signIn("/demo/token", { actor: event.currentTarget.elements.actor.value }, true);
});
$("logout").addEventListener("click", signOut);
$("application-form").addEventListener("submit", applyForPost);
$("message-form").addEventListener("submit", sendMessage);
$("refresh-claim").addEventListener("click", () => readDetail(state.detail));
$("refresh-messages").addEventListener("click", () => loadMessages(state.detail));
for (const control of all("[data-view]")) control.addEventListener("click", () => switchView(control.dataset.view));
for (const control of all("[data-role]")) control.addEventListener("click", () => setRole(control.dataset.role, true));
for (const control of all("[data-refresh]")) control.addEventListener("click", () => loadPage(control.dataset.refresh));
for (const control of all("[data-step]")) {
  control.addEventListener("click", () => {
    const key = control.closest("[data-pager]").dataset.pager;
    void loadPage(key, pagers[key].page + Number(control.dataset.step));
  });
}
window.addEventListener("pagehide", closeDetail);

async function start() {
  sessionControls();
  try {
    const response = await fetch("/health", { cache: "no-store", credentials: "omit", signal: AbortSignal.timeout(3000) });
    if (response.ok) state.demoAvailable = (await response.json()).demo_mode === true;
  } catch {
    // The shared API remains usable when health is unavailable.
  }
  sessionControls();
  loadActiveView();
}

void start();
