(() => {
  "use strict";

  const ALLOWED_ACTORS = new Set(["alice", "bob", "finder", "outsider"]);
  const PAGE_SIZE = 20;
  const MESSAGE_LIMIT = 2000;
  const MESSAGE_PAGE_SIZE = 200;
  const MAX_MESSAGE_PAGES = 20;
  const MAX_REASON_LENGTH = 500;
  const DEFAULT_COOLDOWN_SECONDS = 30;

  const STATUS_LABELS = Object.freeze({
    PENDING: "待审核",
    APPROVED: "已批准",
    REJECTED: "已驳回",
    WITHDRAWN: "已撤销",
    CLOSED_OTHER: "其他申请获批关闭",
    EXPIRED: "已过期",
    COMPLETED: "已完成",
    DISPUTED: "争议冻结"
  });

  const STATUS_TONES = Object.freeze({
    PENDING: "pending",
    APPROVED: "approved",
    REJECTED: "rejected",
    WITHDRAWN: "withdrawn",
    CLOSED_OTHER: "closed-other",
    EXPIRED: "expired",
    COMPLETED: "completed",
    DISPUTED: "disputed"
  });

  const LISTING_STATUS_LABELS = Object.freeze({
    published: "已发布",
    claimed: "已被认领"
  });

  const CLAIM_FILTER_ROLES = Object.freeze(["applicant", "finder"]);
  const CLAIM_FILTER_LABELS = Object.freeze({
    applicant: "我发起的",
    finder: "我收到的"
  });
  const CLAIM_FILTER_ROLE_LABELS = Object.freeze({
    applicant: "申请人",
    finder: "拾获者"
  });
  const DEFAULT_CLAIM_ROLE = "applicant";

  const FIELD_LABELS = Object.freeze({
    actor: "演示身份",
    item_id: "物品",
    item_number: "物品编号",
    evidence_text: "私有证据",
    reason: "原因",
    code: "确认码",
    text: "消息内容"
  });

  const DEFAULT_ERROR_MESSAGES = Object.freeze({
    400: "请求格式有误。",
    401: "令牌无效或已过期。",
    403: "当前演示身份无权执行此操作。",
    404: "未找到请求的资源。",
    409: "状态冲突或幂等键冲突，请刷新后重试。",
    410: "确认码已过期，请重新获取。",
    422: "提交内容未通过校验或隐私过滤。",
    429: "请求过于频繁，请稍后再试。",
    500: "服务端暂时不可用，请稍后重试。",
    502: "服务端返回了无法识别的响应。",
    503: "服务端暂时不可用，请稍后重试。"
  });

  const API_BASE = (() => {
    const meta = document.querySelector('meta[name="claim-api-base"]');
    const configured = meta && typeof meta.content === "string" ? meta.content.trim() : "";
    const value = configured || "/v1";
    return value.endsWith("/") ? value.slice(0, -1) : value;
  })();

  const dateTimeFormatter = new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  });

  function emptyClaimsState() {
    return {
      page: 1,
      items: [],
      total: null,
      role: DEFAULT_CLAIM_ROLE,
      counts: { applicant: null, finder: null },
      countStatus: { applicant: "idle", finder: "idle" }
    };
  }

  const state = {
    token: null,
    tokenExpiresAt: null,
    actor: null,
    epoch: 0,
    abort: new AbortController(),
    switching: false,
    found: {
      page: 1,
      items: [],
      total: null,
      selectedId: null,
      detail: null
    },
    lost: {
      items: [],
      selectedId: null
    },
    matches: {
      items: [],
      ruleVersion: "",
      threshold: null,
      lostId: null
    },
    claims: emptyClaimsState(),
    selectedClaimId: null,
    claim: null,
    messages: [],
    code: null,
    seq: {
      found: 0,
      foundDetail: 0,
      lost: 0,
      matches: 0,
      claims: 0,
      claimCounts: 0,
      claim: 0,
      messages: 0,
      code: 0
    },
    inFlight: new Set(),
    cooldownUntil: 0
  };

  const ui = {};
  const idempotencyKeys = new Map();
  const listingTitleCache = new Map();
  const listingTitleRequests = new Map();
  const LISTING_TITLE_CACHE_LIMIT = 200;
  const LISTING_TITLE_FETCH_CONCURRENCY = 3;
  let noticeTimer = null;
  let cooldownTimer = null;
  let dialogResolver = null;
  let actionDialogReasonIsRequired = false;
  let onlineRefreshInFlight = false;

  class ApiError extends Error {
    constructor(status, code, message, extra = {}) {
      super(message);
      this.name = "ApiError";
      this.status = status;
      this.code = code;
      this.field = extra.field || "";
      this.retryAfterSeconds = extra.retryAfterSeconds;
      this.aborted = Boolean(extra.aborted);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }

  function init() {
    cacheElements();
    bindEvents();
    resetPrivateForIdentityChange();
    updateCooldownDisplay();
    updateCharacterCount();
    void loadFound();
  }

  function cacheElements() {
    const get = (id) => document.getElementById(id);

    ui.identityActions = get("identity-actions");
    ui.actorButtons = Array.from(document.querySelectorAll(".actor-button[data-actor]"));
    ui.logoutButton = get("logout-button");
    ui.sessionStatus = get("session-status");

    ui.noticeRegion = get("notice-region");
    ui.cooldownBanner = get("cooldown-banner");
    ui.cooldownText = get("cooldown-text");
    ui.cooldownClear = get("cooldown-clear");

    ui.foundSection = get("found-section");
    ui.refreshFound = get("refresh-found");
    ui.foundList = get("found-list");
    ui.foundPrev = get("found-prev");
    ui.foundNext = get("found-next");
    ui.foundPageStatus = get("found-page-status");
    ui.foundDetail = get("found-detail");
    ui.claimGate = get("claim-gate");
    ui.claimForm = get("claim-form");
    ui.claimItemId = get("claim-item-id");
    ui.claimTarget = get("claim-target");
    ui.claimItemNumber = get("claim-item-number");
    ui.claimEvidenceInput = get("claim-evidence-input");
    ui.claimFormError = get("claim-form-error");
    ui.claimSubmit = get("claim-submit");

    ui.refreshLost = get("refresh-lost");
    ui.lostList = get("lost-list");
    ui.loadMatchesButton = get("load-matches");
    ui.matchContext = get("match-context");
    ui.matchesList = get("matches-list");

    ui.refreshClaims = get("refresh-claims");
    ui.claimsFilters = get("claims-filters");
    ui.claimsFilterApplicant = get("claims-filter-applicant");
    ui.claimsFilterFinder = get("claims-filter-finder");
    ui.claimsCountApplicant = get("claims-count-applicant");
    ui.claimsCountFinder = get("claims-count-finder");
    ui.claimsFilterNote = get("claims-filter-note");
    ui.claimsList = get("claims-list");
    ui.claimsPrev = get("claims-prev");
    ui.claimsNext = get("claims-next");
    ui.claimsPageStatus = get("claims-page-status");

    ui.claimWorkspace = get("claim-workspace");
    ui.claimDetailTitle = get("claim-detail-title");
    ui.claimBadges = get("claim-badges");
    ui.refreshClaim = get("refresh-claim");
    ui.closeClaim = get("close-claim");
    ui.claimLoadState = get("claim-load-state");
    ui.claimDetailContent = get("claim-detail-content");
    ui.claimMeta = get("claim-meta");
    ui.claimEvidence = get("claim-evidence");
    ui.claimRoleNote = get("claim-role-note");
    ui.claimActions = get("claim-actions");
    ui.claimActionsMessage = get("claim-actions-message");

    ui.handoverSection = get("handover-section");
    ui.fetchCodeButton = get("fetch-code-button");
    ui.codeStatus = get("code-status");
    ui.codeDisplay = get("code-display");
    ui.ownCode = get("own-code");
    ui.codeExpiry = get("code-expiry");
    ui.handoverConfirmForm = get("handover-confirm-form");
    ui.counterpartCode = get("counterpart-code");
    ui.handoverFormError = get("handover-form-error");
    ui.handoverConfirmSubmit = get("handover-confirm-submit");
    ui.handoverProgress = get("handover-progress");
    ui.handoverActionError = get("handover-action-error");
    ui.resetHandoverButton = get("reset-handover-button");

    ui.chatSection = get("chat-section");
    ui.refreshMessages = get("refresh-messages");
    ui.messageList = get("message-list");
    ui.messageForm = get("message-form");
    ui.messageText = get("message-text");
    ui.messageCount = get("message-count");
    ui.chatReadonlyNote = get("chat-readonly-note");
    ui.messageFormError = get("message-form-error");
    ui.messageSubmit = get("message-submit");

    ui.disputeSection = get("dispute-section");
    ui.disputeDescription = get("dispute-description");
    ui.disputeButton = get("dispute-button");
    ui.exportButton = get("export-button");
    ui.disputeNote = get("dispute-note");

    ui.actionDialog = get("action-dialog");
    ui.actionDialogForm = get("action-dialog-form");
    ui.actionDialogTitle = get("action-dialog-title");
    ui.actionDialogDescription = get("action-dialog-description");
    ui.actionDialogReasonWrap = get("action-dialog-reason-wrap");
    ui.actionDialogReasonLabel = get("action-dialog-reason-label");
    ui.actionDialogReason = get("action-dialog-reason");
    ui.actionDialogReasonHint = get("action-dialog-reason-hint");
    ui.actionDialogAckWrap = get("action-dialog-ack-wrap");
    ui.actionDialogAck = get("action-dialog-ack");
    ui.actionDialogAckText = get("action-dialog-ack-text");
    ui.actionDialogError = get("action-dialog-error");
    ui.actionDialogCancel = get("action-dialog-cancel");
    ui.actionDialogConfirm = get("action-dialog-confirm");
  }

  function bindEvents() {
    ui.actorButtons.forEach((button) => {
      button.addEventListener("click", () => {
        void switchIdentity(button.dataset.actor || "");
      });
    });
    ui.logoutButton.addEventListener("click", logoutDemo);

    ui.refreshFound.addEventListener("click", () => void loadFound());
    ui.foundPrev.addEventListener("click", () => changeFoundPage(-1));
    ui.foundNext.addEventListener("click", () => changeFoundPage(1));

    ui.claimForm.addEventListener("submit", (event) => {
      event.preventDefault();
      void submitClaim();
    });
    ui.claimItemNumber.addEventListener("input", () => clearInlineError(ui.claimFormError));
    ui.claimEvidenceInput.addEventListener("input", () => clearInlineError(ui.claimFormError));

    ui.refreshLost.addEventListener("click", () => void loadLost());
    ui.loadMatchesButton.addEventListener("click", () => void loadMatches());

    ui.refreshClaims.addEventListener("click", () => void loadClaims());
    ui.claimsFilterApplicant.addEventListener("click", () => switchClaimsRole("applicant"));
    ui.claimsFilterFinder.addEventListener("click", () => switchClaimsRole("finder"));
    ui.claimsPrev.addEventListener("click", () => changeClaimsPage(-1));
    ui.claimsNext.addEventListener("click", () => changeClaimsPage(1));

    ui.refreshClaim.addEventListener("click", () => {
      if (state.selectedClaimId !== null) {
        void loadClaimDetail(state.selectedClaimId);
      }
    });
    ui.closeClaim.addEventListener("click", closeClaimWorkspace);

    ui.fetchCodeButton.addEventListener("click", () => void fetchOwnCode());
    ui.handoverConfirmForm.addEventListener("submit", (event) => {
      event.preventDefault();
      void submitHandoverConfirm();
    });
    ui.counterpartCode.addEventListener("input", () => clearInlineError(ui.handoverFormError));
    ui.resetHandoverButton.addEventListener("click", () => void resetHandover());

    ui.refreshMessages.addEventListener("click", () => void refreshMessages());
    ui.messageForm.addEventListener("submit", (event) => {
      event.preventDefault();
      void sendMessage();
    });
    ui.messageText.addEventListener("input", () => {
      if (ui.messageText.value.length > MESSAGE_LIMIT) {
        ui.messageText.value = ui.messageText.value.slice(0, MESSAGE_LIMIT);
      }
      updateCharacterCount();
      clearInlineError(ui.messageFormError);
    });

    ui.disputeButton.addEventListener("click", () => void disputeClaim());
    ui.exportButton.addEventListener("click", () => void downloadDisputeExport());

    window.addEventListener("online", () => void refreshClaimsAfterOnline());
    ui.cooldownClear.addEventListener("click", clearLocalCooldown);

    ui.actionDialogCancel.addEventListener("click", () => finishActionDialog(false));
    ui.actionDialogForm.addEventListener("submit", handleActionDialogSubmit);
    ui.actionDialog.addEventListener("cancel", (event) => {
      event.preventDefault();
      finishActionDialog(false);
    });
    ui.actionDialog.addEventListener("close", () => {
      if (dialogResolver) {
        const resolve = dialogResolver;
        dialogResolver = null;
        resolve(false);
      }
    });
  }

  /* ----------------------------------------------------------------------- */
  /* Session and identity                                                    */
  /* ----------------------------------------------------------------------- */

  async function switchIdentity(actor) {
    if (!ALLOWED_ACTORS.has(actor) || state.switching) {
      return;
    }

    clearNotice();
    resetPrivateForIdentityChange();
    state.switching = true;
    updateIdentityUI(`正在获取演示身份 ${actor} 的令牌…`);

    const epoch = state.epoch;
    const slot = `demo-token:${actor}`;
    const signature = JSON.stringify({ actor });
    const idempotencyKey = getWriteKey(slot, signature);

    try {
      const raw = await requestJson("/demo/token", {
        method: "POST",
        body: { actor },
        auth: false,
        idempotencyKey
      });

      if (epoch !== state.epoch) {
        return;
      }

      const data = extractObject(raw, ["auth", "token"]);
      const token = typeof data === "string"
        ? data
        : safeText(data && data.token).trim();
      const returnedActor = safeText(data && data.actor).trim();
      const expiresAt = safeText(data && (data.expires_at || data.expiresAt)).trim();

      if (!token) {
        throw new ApiError(502, "BAD_TOKEN_RESPONSE", "演示令牌响应缺少 token。");
      }
      if (returnedActor && returnedActor !== actor) {
        throw new ApiError(502, "BAD_TOKEN_RESPONSE", "演示令牌响应中的 actor 与请求不一致。");
      }

      forgetWriteKey(slot);
      state.token = token;
      state.tokenExpiresAt = expiresAt || null;
      state.actor = returnedActor || actor;
      state.switching = false;
      updateIdentityUI();
      syncFoundClaimAccess();
      showNotice(`已切换到演示身份 ${state.actor}。这是合成演练身份，不是真实认证。`, "success");
      void loadFound();
      void loadLost();
      void loadClaims();
    } catch (error) {
      if (epoch !== state.epoch || isAbortError(error)) {
        return;
      }
      state.switching = false;
      updateIdentityUI("演示身份获取失败，请重新选择演示身份。");
      syncFoundClaimAccess();
      showNotice(formatError(error), "error", { sticky: true });
    }
  }

  function logoutDemo() {
    if (!state.token && !state.switching) {
      return;
    }

    clearNotice();
    resetPrivateForIdentityChange();
    state.switching = false;
    updateIdentityUI("已退出演示身份。上一身份的私有内容已从页面清除。");
    showNotice("已退出演示身份。演示令牌和已加载数据均已从页面清除，请重新选择演示身份。", "info");
    syncFoundClaimAccess();
  }

  function handleTokenExpired() {
    if (!state.token) {
      return;
    }

    const expiredActor = state.actor;
    resetPrivateForIdentityChange();
    state.switching = false;
    updateIdentityUI("演示身份令牌无效或已过期，私有内容已清除。请重新选择演示身份。");
    showNotice(
      `演示身份${expiredActor ? ` ${expiredActor} ` : ""}的令牌无效或已过期，私有内容已清除。请重新选择演示身份。`,
      "error",
      { sticky: true }
    );
    syncFoundClaimAccess();
  }

  function resetPrivateForIdentityChange() {
    state.epoch += 1;
    try {
      state.abort.abort();
    } catch (_error) {
      // Aborting an already completed controller is harmless.
    }
    state.abort = new AbortController();

    Object.keys(state.seq).forEach((key) => {
      state.seq[key] += 1;
    });

    state.token = null;
    state.tokenExpiresAt = null;
    state.actor = null;
    state.inFlight.clear();
    clearListingTitleCache();

    for (const key of Array.from(idempotencyKeys.keys())) {
      if (!key.startsWith("demo-token:")) {
        idempotencyKeys.delete(key);
      }
    }

    state.found = {
      page: 1,
      items: [],
      total: null,
      selectedId: null,
      detail: null
    };
    state.lost = { items: [], selectedId: null };
    state.matches = { items: [], ruleVersion: "", threshold: null, lostId: null };
    state.claims = emptyClaimsState();

    clearClaimWorkspaceDom();
    setPrivatePlaceholders();

    showState(ui.foundList, {
      kind: "info",
      message: "选择演示身份后加载公开失物。"
    });
    showState(ui.foundDetail, {
      kind: "info",
      message: "选择演示身份并从左侧选择一条失物，查看公开详情。"
    });
    updateFoundPagination();

    ui.claimForm.reset();
    clearInlineError(ui.claimFormError);
    ui.claimTarget.textContent = "尚未选择";
    ui.claimItemId.value = "";
    setButtonBusy(ui.claimSubmit, false);
    setButtonBusy(ui.loadMatchesButton, false);
    setButtonIdleLabel(ui.loadMatchesButton, "查看匹配解释（Top 3）");
    ui.loadMatchesButton.disabled = true;

    closeActionDialog();
    syncFoundClaimAccess();
    updateCharacterCount();
    updateIdentityUI();
  }

  function updateIdentityUI(statusOverride) {
    const switching = state.switching;
    ui.actorButtons.forEach((button) => {
      const active = button.dataset.actor === state.actor;
      button.setAttribute("aria-pressed", active ? "true" : "false");
      button.disabled = switching;
    });
    ui.logoutButton.disabled = switching || !state.token;

    if (typeof statusOverride === "string") {
      ui.sessionStatus.textContent = statusOverride;
      return;
    }

    if (switching) {
      ui.sessionStatus.textContent = "正在获取演示身份令牌…";
    } else if (state.token) {
      const expiryText = state.tokenExpiresAt
        ? `，令牌有效期至 ${formatDateTime(state.tokenExpiresAt)}`
        : "";
      ui.sessionStatus.textContent = `当前演示身份：${state.actor}${expiryText}。演示令牌仅保存在本页内存中，实际角色与权限以服务端返回为准。`;
    } else {
      ui.sessionStatus.textContent = "当前未选择演示身份。请选择演示身份以加载只读失物数据；此处的身份切换是合成演示，不是真实认证。";
    }
  }

  function syncFoundClaimAccess() {
    const detail = state.found.detail;
    if (!detail) {
      ui.claimForm.hidden = true;
      ui.claimGate.hidden = true;
      return;
    }

    const title = safeText(detail.title).trim() || "未命名失物";
    ui.claimTarget.textContent = title;

    if (!state.token) {
      ui.claimForm.hidden = true;
      ui.claimGate.hidden = false;
      ui.claimGate.textContent = "选择演示身份后，可查看公开详情并视认领状态发起认领申请。";
      return;
    }

    const status = safeText(detail.status).trim().toLowerCase();
    const isFound = !detail.kind || detail.kind === "found";
    const claimable = isFound && detail.claimable !== false && status !== "claimed";
    if (!claimable) {
      ui.claimForm.hidden = true;
      ui.claimGate.hidden = false;
      ui.claimGate.textContent = isFound
        ? "该拾获记录当前不可认领：已被认领、已有获批申请，或外部状态不是 published。"
        : "该记录不是拾获记录，不能发起认领申请。";
      return;
    }

    ui.claimGate.hidden = true;
    ui.claimForm.hidden = false;
    if (isIdPresent(detail.id)) {
      ui.claimItemId.value = String(detail.id);
    }
  }

  function setPrivatePlaceholders() {
    showState(ui.lostList, {
      kind: "info",
      message: "选择演示身份后查看本人丢失记录。"
    });
    ui.matchContext.textContent = "先选择一条本人丢失记录。";
    showState(ui.matchesList, {
      kind: "info",
      message: "匹配结果会显示分数、理由和规则版本。"
    });
    showState(ui.claimsList, {
      kind: "info",
      message: "选择演示身份后查看本人相关申请。"
    });
    ui.claimsPageStatus.textContent = "第 1 页";
    ui.claimsPrev.disabled = true;
    ui.claimsNext.disabled = true;
    ui.loadMatchesButton.disabled = true;
    renderClaimFilters();
  }

  /* ----------------------------------------------------------------------- */
  /* HTTP client                                                             */
  /* ----------------------------------------------------------------------- */

  function apiUrl(path) {
    return `${API_BASE}${path}`;
  }

  function claimPath(claimId) {
    return `/claims/${encodeURIComponent(String(claimId))}`;
  }

  async function requestJson(path, options = {}) {
    const response = await requestResponse(path, options);

    if (response.status === 204) {
      return null;
    }

    const text = await response.text();
    if (!text) {
      return null;
    }

    const contentType = response.headers.get("content-type") || "";
    const looksLikeJson = /^[\s]*[\[{]/.test(text);

    if (contentType.includes("application/json") || looksLikeJson) {
      try {
        return JSON.parse(text);
      } catch (_error) {
        throw new ApiError(502, "INVALID_JSON", "服务端返回了无法解析的 JSON。");
      }
    }

    return text;
  }

  async function requestResponse(path, options = {}) {
    const method = options.method || "GET";
    const headers = new Headers();
    headers.set("Accept", options.accept || "application/json");

    let body;
    if (options.body !== undefined) {
      headers.set("Content-Type", "application/json");
      body = JSON.stringify(options.body);
    }

    if (options.idempotencyKey) {
      headers.set("Idempotency-Key", options.idempotencyKey);
    }

    if (options.auth) {
      if (!state.token) {
        throw new ApiError(401, "UNAUTHENTICATED", "请先选择演示身份。");
      }
      headers.set("Authorization", `Bearer ${state.token}`);
    }

    let response;
    try {
      response = await fetch(apiUrl(path), {
        method,
        headers,
        body,
        credentials: "omit",
        cache: "no-store",
        signal: state.abort.signal
      });
    } catch (error) {
      if (error && (error.name === "AbortError" || error.code === 20)) {
        throw new ApiError(0, "ABORTED", "请求已取消。", { aborted: true });
      }
      throw new ApiError(0, "NETWORK_ERROR", "无法连接后端服务。请检查服务是否已启动，以及页面与 API 是否同源。");
    }

    if (!response.ok) {
      throw await buildApiError(response, Boolean(options.auth));
    }

    return response;
  }

  async function buildApiError(response, authRequest) {
    let text = "";
    try {
      text = await response.text();
    } catch (_error) {
      text = "";
    }

    let payload = null;
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch (_error) {
        payload = null;
      }
    }

    const envelope = isPlainObject(payload) ? payload : {};
    const source = isPlainObject(envelope.error) ? envelope.error : envelope;
    let message = safeText(source.message || envelope.message).trim();
    let field = safeText(source.field || envelope.field).trim();
    let code = safeText(source.code || envelope.code).trim();

    if (Array.isArray(envelope.detail) && envelope.detail.length > 0) {
      const first = envelope.detail[0];
      if (isPlainObject(first)) {
        if (!message) {
          message = safeText(first.msg || first.message).trim();
        }
        if (!field && Array.isArray(first.loc) && first.loc.length > 0) {
          field = safeText(first.loc[first.loc.length - 1]).trim();
        }
      }
    } else if (!message && typeof envelope.detail === "string") {
      message = envelope.detail.trim();
    }

    if (!message) {
      message = DEFAULT_ERROR_MESSAGES[response.status] || `请求失败（HTTP ${response.status}）。`;
    }
    if (!code) {
      code = `HTTP_${response.status}`;
    }
    if (field === "body") {
      field = "";
    }

    const retryAfterSeconds = parseRetryAfterSeconds(response, payload);
    const error = new ApiError(response.status, code, message, {
      field,
      retryAfterSeconds
    });

    if (response.status === 401 && authRequest) {
      handleTokenExpired();
    }
    if (response.status === 429) {
      startCooldown(retryAfterSeconds);
    }

    return error;
  }

  function parseRetryAfterSeconds(response, payload) {
    const source = isPlainObject(payload) && isPlainObject(payload.error) ? payload.error : payload;
    const candidates = [
      source && source.retry_after_seconds,
      source && source.retry_after,
      source && source.retryAfter,
      source && source.retryAfterSeconds,
      response.headers.get("Retry-After")
    ];

    for (const candidate of candidates) {
      if (candidate === null || candidate === undefined || candidate === "") {
        continue;
      }
      const numeric = Number(candidate);
      if (Number.isFinite(numeric) && numeric >= 0) {
        return clampCooldown(numeric);
      }
      if (typeof candidate === "string") {
        const parsedDate = Date.parse(candidate);
        if (!Number.isNaN(parsedDate)) {
          const seconds = Math.ceil((parsedDate - Date.now()) / 1000);
          if (seconds > 0) {
            return clampCooldown(seconds);
          }
        }
      }
    }

    return DEFAULT_COOLDOWN_SECONDS;
  }

  function clampCooldown(seconds) {
    return Math.min(3600, Math.max(1, Math.ceil(Number(seconds) || DEFAULT_COOLDOWN_SECONDS)));
  }

  /* ----------------------------------------------------------------------- */
  /* Public found listings                                                   */
  /* ----------------------------------------------------------------------- */

  async function loadFound() {
    if (!state.token) {
      showState(ui.foundList, {
        kind: "info",
        message: "选择演示身份后加载公开失物。"
      });
      updateFoundPagination();
      return;
    }

    const seq = ++state.seq.found;
    const requestedPage = state.found.page;

    showState(ui.foundList, {
      kind: "loading",
      message: "正在加载公开失物…"
    });

    try {
      const query = new URLSearchParams({
        kind: "found",
        page: String(requestedPage),
        page_size: String(PAGE_SIZE)
      });
      const payload = await requestJson(`/listings?${query.toString()}`, { auth: true });
      if (seq !== state.seq.found) {
        return;
      }

      const pageData = extractList(payload, ["listings", "items", "results"]);
      if (!pageData.recognized) {
        throw new ApiError(502, "UNEXPECTED_LIST_SHAPE", "失物列表响应结构无法识别，请核对接口契约。");
      }

      state.found.items = pageData.items;
      state.found.total = pageData.total;
      renderFoundList();
      updateFoundPagination();
    } catch (error) {
      if (seq !== state.seq.found || isAbortError(error)) {
        return;
      }
      state.found.items = [];
      state.found.total = null;
      showState(ui.foundList, {
        kind: "error",
        title: "公开失物加载失败",
        message: formatError(error),
        retry: () => void loadFound()
      });
      updateFoundPagination();
    }
  }

  function renderFoundList() {
    ui.foundList.setAttribute("aria-busy", "false");

    if (state.found.items.length === 0) {
      showState(ui.foundList, {
        kind: "empty",
        title: "暂无公开拾获记录",
        message: "后端尚未返回公开失物数据，或当前页为空。"
      });
      return;
    }

    const list = make("ul", { className: "item-list" });
    for (const raw of state.found.items) {
      if (!isPlainObject(raw)) {
        continue;
      }

      const itemId = raw.id;
      const title = safeText(raw.title).trim() || "未命名失物";
      const selected = isIdPresent(itemId) && String(itemId) === String(state.found.selectedId);
      const li = make("li", { className: "item-card" });
      const button = make("button", {
        className: "item-button",
        attrs: {
          type: "button",
          "aria-pressed": selected ? "true" : "false",
          "data-listing-id": isIdPresent(itemId) ? String(itemId) : false
        }
      });

      button.append(
        make("span", { className: "item-title", text: title }),
        make("span", { className: "item-meta", text: formatListingMeta(raw) })
      );

      const badges = make("span", { className: "item-badges" });
      if (safeText(raw.status).trim()) {
        badges.append(listingStatusBadge(raw));
      }
      if (badges.childNodes.length > 0) {
        button.append(badges);
      }

      if (isIdPresent(itemId)) {
        button.addEventListener("click", () => {
          void loadFoundDetail(itemId);
        });
      } else {
        button.disabled = true;
        button.title = "该记录缺少公开 id，无法加载详情。";
      }

      li.append(button);
      list.append(li);
    }

    if (list.childNodes.length === 0) {
      showState(ui.foundList, {
        kind: "error",
        title: "列表数据不可用",
        message: "公开失物记录缺少可用的公开 id。",
        retry: () => void loadFound()
      });
      return;
    }

    ui.foundList.replaceChildren(list);
  }

  async function loadFoundDetail(itemId) {
    if (!isIdPresent(itemId)) {
      return;
    }
    if (!state.token) {
      showNotice("请先选择演示身份，再查看失物详情。", "warning", { sticky: true });
      return;
    }

    const idText = String(itemId);
    const isNewSelection = String(state.found.selectedId) !== idText;
    state.found.selectedId = itemId;
    state.found.detail = null;
    const seq = ++state.seq.foundDetail;

    if (isNewSelection) {
      ui.claimForm.reset();
      clearInlineError(ui.claimFormError);
      ui.claimTarget.textContent = "尚未选择";
      ui.claimItemId.value = "";
    }

    ui.claimForm.hidden = true;
    ui.claimGate.hidden = true;
    renderFoundList();
    showState(ui.foundDetail, {
      kind: "loading",
      message: "正在加载失物详情…"
    });

    try {
      const payload = await requestJson(`/listings/${encodeURIComponent(idText)}`, { auth: true });
      if (seq !== state.seq.foundDetail || String(state.found.selectedId) !== idText) {
        return;
      }

      const detail = extractObject(payload, ["listing", "item"]);
      if (!isPlainObject(detail)) {
        throw new ApiError(502, "UNEXPECTED_ITEM_SHAPE", "失物详情响应结构无法识别，请核对接口契约。");
      }

      state.found.detail = detail;
      renderFoundDetail(detail);
    } catch (error) {
      if (seq !== state.seq.foundDetail || isAbortError(error) || String(state.found.selectedId) !== idText) {
        return;
      }
      state.found.detail = null;
      ui.claimForm.hidden = true;
      ui.claimGate.hidden = true;
      showState(ui.foundDetail, {
        kind: "error",
        title: "失物详情加载失败",
        message: formatError(error),
        retry: () => void loadFoundDetail(itemId)
      });
    }
  }

  function renderFoundDetail(detail) {
    ui.foundDetail.replaceChildren();

    const title = safeText(detail.title).trim() || "未命名失物";
    const heading = make("div", { className: "detail-heading" });
    const headingText = make("div");
    headingText.append(
      make("p", { className: "eyebrow", text: "公开详情" }),
      make("h3", { text: title })
    );

    const badgeRow = make("div", { className: "badge-row" });
    if (safeText(detail.status).trim()) {
      badgeRow.append(listingStatusBadge(detail));
    }

    heading.append(headingText, badgeRow);

    const meta = make("dl", { className: "meta-grid" });
    appendMeta(meta, "类别", safeText(detail.category).trim() || "未提供");
    appendMeta(meta, "发生时间", formatDateTime(detail.occurred_at));
    appendMeta(meta, "地点", safeText(detail.location).trim() || "未提供");
    if (!detail.kind || detail.kind === "found") {
      appendMeta(meta, "认领状态", detail.claimable === true ? "当前可认领" : "当前不可认领");
    }

    const description = safeText(detail.description).trim();
    const descriptionBlock = make("div");
    descriptionBlock.append(
      make("h4", { text: "物品描述" }),
      make("p", {
        className: "detail-description",
        text: description || "未提供描述。"
      })
    );

    ui.foundDetail.append(
      heading,
      meta,
      descriptionBlock,
      make("p", {
        className: "public-note",
        text: "公开详情不展示发布者账号、user_id 或真实身份映射。"
      })
    );

    syncFoundClaimAccess();
  }

  function updateFoundPagination() {
    if (!state.token) {
      ui.foundPrev.disabled = true;
      ui.foundNext.disabled = true;
      ui.foundPageStatus.textContent = "第 1 页";
      return;
    }

    ui.foundPrev.disabled = state.found.page <= 1;
    const total = state.found.total;
    const hasKnownTotal = Number.isFinite(total);
    const hasNext = hasKnownTotal
      ? state.found.page * PAGE_SIZE < total
      : state.found.items.length >= PAGE_SIZE;
    ui.foundNext.disabled = !hasNext;

    ui.foundPageStatus.textContent = hasKnownTotal
      ? `第 ${state.found.page} 页 · 共 ${total} 条`
      : `第 ${state.found.page} 页`;
  }

  function changeFoundPage(delta) {
    if (!state.token) {
      return;
    }
    const nextPage = state.found.page + delta;
    if (nextPage < 1) {
      return;
    }
    state.found.page = nextPage;
    void loadFound();
  }

  async function submitClaim() {
    if (!state.token) {
      showNotice("请先选择演示身份，再发起认领申请。", "warning", { sticky: true });
      return;
    }
    if (!state.found.detail || !isIdPresent(state.found.detail.id)) {
      showInlineError(ui.claimFormError, "请先选择一条带有公开 id 的失物。");
      return;
    }

    const itemNumber = ui.claimItemNumber.value.trim();
    const evidenceText = ui.claimEvidenceInput.value.trim();

    if (itemNumber.length > 64) {
      showInlineError(ui.claimFormError, "物品编号不能超过 64 个字符。");
      ui.claimItemNumber.focus();
      return;
    }
    if (!evidenceText) {
      showInlineError(ui.claimFormError, "请填写私有证据说明。");
      ui.claimEvidenceInput.focus();
      return;
    }
    if (evidenceText.length > 2000) {
      showInlineError(ui.claimFormError, "私有证据说明不能超过 2000 个字符。");
      ui.claimEvidenceInput.focus();
      return;
    }

    const body = {
      item_id: state.found.detail.id,
      evidence_text: evidenceText
    };
    if (itemNumber) {
      body.item_number = itemNumber;
    }
    const slot = `create-claim:${String(state.found.detail.id)}`;
    const signature = JSON.stringify(body);
    const epoch = state.epoch;

    await runWriteAction({
      slot,
      button: ui.claimSubmit,
      busyText: "提交中…",
      errorBox: ui.claimFormError,
      action: async () => {
        const key = getWriteKey(slot, signature);
        const payload = await requestJson("/claims", {
          method: "POST",
          auth: true,
          body,
          idempotencyKey: key
        });
        forgetWriteKey(slot);

        if (epoch !== state.epoch) {
          return;
        }

        const claim = extractObject(payload, ["claim", "application"]);
        const claimId = isPlainObject(claim) && isIdPresent(claim.id) ? claim.id : null;

        ui.claimForm.reset();
        clearInlineError(ui.claimFormError);
        syncFoundClaimAccess();
        showNotice("认领申请已提交。私有证据仅对申请双方可见。", "success");
        void loadClaims();
        if (claimId !== null) {
          openClaim(claimId, { focusHeading: true });
        }
      }
    });
  }

  /* ----------------------------------------------------------------------- */
  /* Lost records and explainable matches                                    */
  /* ----------------------------------------------------------------------- */

  async function loadLost() {
    if (!state.token) {
      showState(ui.lostList, {
        kind: "info",
        message: "选择演示身份后查看本人丢失记录。"
      });
      ui.loadMatchesButton.disabled = true;
      return;
    }

    const epoch = state.epoch;
    const seq = ++state.seq.lost;
    showState(ui.lostList, {
      kind: "loading",
      message: "正在加载本人丢失记录…"
    });

    try {
      const query = new URLSearchParams({
        kind: "lost",
        mine: "true",
        page: "1",
        page_size: String(PAGE_SIZE)
      });
      const payload = await requestJson(`/listings?${query.toString()}`, { auth: true });
      if (epoch !== state.epoch || seq !== state.seq.lost) {
        return;
      }

      const pageData = extractList(payload, ["listings", "items", "results"]);
      if (!pageData.recognized) {
        throw new ApiError(502, "UNEXPECTED_LIST_SHAPE", "丢失记录响应结构无法识别，请核对接口契约。");
      }

      state.lost.items = pageData.items;
      const selectedExists = state.lost.items.some(
        (item) => isPlainObject(item) && isIdPresent(item.id) && String(item.id) === String(state.lost.selectedId)
      );
      if (!selectedExists) {
        state.lost.selectedId = null;
        state.matches = { items: [], ruleVersion: "", threshold: null, lostId: null };
        ui.matchContext.textContent = "先选择一条本人丢失记录。";
        showState(ui.matchesList, {
          kind: "info",
          message: "点击“查看匹配解释（Top 3）”获取服务端解释。"
        });
      }

      renderLostList();
      ui.loadMatchesButton.disabled = !isIdPresent(state.lost.selectedId);
    } catch (error) {
      if (epoch !== state.epoch || seq !== state.seq.lost || isAbortError(error)) {
        return;
      }
      state.lost.items = [];
      state.lost.selectedId = null;
      ui.loadMatchesButton.disabled = true;
      showState(ui.lostList, {
        kind: "error",
        title: "本人丢失记录加载失败",
        message: formatError(error),
        retry: () => void loadLost()
      });
    }
  }

  function renderLostList() {
    if (state.lost.items.length === 0) {
      showState(ui.lostList, {
        kind: "empty",
        title: "没有可用的丢失记录",
        message: "当前身份未被服务端关联丢失记录，或接口暂未返回数据。"
      });
      return;
    }

    const list = make("ul", { className: "item-list" });
    for (const raw of state.lost.items) {
      if (!isPlainObject(raw)) {
        continue;
      }

      const itemId = raw.id;
      const title = safeText(raw.title).trim() || "未命名丢失记录";
      const selected = isIdPresent(itemId) && String(itemId) === String(state.lost.selectedId);
      const li = make("li", { className: "item-card" });
      const button = make("button", {
        className: "item-button",
        attrs: {
          type: "button",
          "aria-pressed": selected ? "true" : "false",
          "data-listing-id": isIdPresent(itemId) ? String(itemId) : false
        }
      });

      button.append(
        make("span", { className: "item-title", text: title }),
        make("span", { className: "item-meta", text: formatListingMeta(raw) })
      );

      const badges = make("span", { className: "item-badges" });
      if (safeText(raw.status).trim()) {
        badges.append(listingStatusBadge(raw));
      }
      if (badges.childNodes.length > 0) {
        button.append(badges);
      }

      if (isIdPresent(itemId)) {
        button.addEventListener("click", () => selectLost(itemId));
      } else {
        button.disabled = true;
      }

      li.append(button);
      list.append(li);
    }

    ui.lostList.replaceChildren(list);
  }

  function selectLost(itemId) {
    const item = state.lost.items.find(
      (candidate) => isPlainObject(candidate) && isIdPresent(candidate.id) && String(candidate.id) === String(itemId)
    );
    if (!item) {
      return;
    }

    if (String(state.lost.selectedId) === String(itemId)) {
      ui.loadMatchesButton.disabled = false;
      return;
    }

    state.seq.matches += 1;
    setButtonBusy(ui.loadMatchesButton, false);
    setButtonIdleLabel(ui.loadMatchesButton, "查看匹配解释（Top 3）");
    state.lost.selectedId = itemId;
    state.matches = { items: [], ruleVersion: "", threshold: null, lostId: null };
    const title = safeText(item.title).trim() || "该丢失记录";
    ui.matchContext.textContent = `已选择「${title}」。点击按钮请求服务端返回 Top 3 匹配解释。`;
    showState(ui.matchesList, {
      kind: "info",
      message: "尚未请求匹配解释。"
    });
    renderLostList();
    ui.loadMatchesButton.disabled = false;
  }

  async function loadMatches() {
    if (!state.token) {
      showNotice("请先选择演示身份。", "warning", { sticky: true });
      return;
    }
    if (!isIdPresent(state.lost.selectedId)) {
      showNotice("请先选择一条本人丢失记录。", "warning", { sticky: true });
      return;
    }

    const epoch = state.epoch;
    const lostId = state.lost.selectedId;
    const seq = ++state.seq.matches;

    setButtonBusy(ui.loadMatchesButton, true, "匹配中…");
    showState(ui.matchesList, {
      kind: "loading",
      message: "正在请求 Top 3 匹配解释…"
    });

    try {
      const query = new URLSearchParams({ item_id: String(lostId) });
      const payload = await requestJson(`/matches?${query.toString()}`, { auth: true });
      if (epoch !== state.epoch || seq !== state.seq.matches || String(state.lost.selectedId) !== String(lostId)) {
        return;
      }

      const pageData = extractList(payload, ["candidates", "matches", "items", "results"]);
      if (!pageData.recognized) {
        throw new ApiError(502, "UNEXPECTED_MATCH_SHAPE", "匹配解释响应结构无法识别，请核对接口契约。");
      }

      const threshold = isPlainObject(payload) && Number.isFinite(Number(payload.threshold))
        ? Number(payload.threshold)
        : null;
      state.matches = {
        items: pageData.items.filter(isPlainObject).slice(0, 3),
        ruleVersion: pageData.ruleVersion,
        threshold,
        lostId
      };

      const lost = state.lost.items.find(
        (item) => isPlainObject(item) && String(item.id) === String(lostId)
      );
      const lostTitle = lost ? safeText(lost.title).trim() || "该记录" : "该记录";
      ui.matchContext.textContent = `以「${lostTitle}」为查询，服务端返回 ${state.matches.items.length} 条候选解释。`;
      renderMatches();
    } catch (error) {
      if (
        epoch !== state.epoch ||
        seq !== state.seq.matches ||
        String(state.lost.selectedId) !== String(lostId) ||
        isAbortError(error)
      ) {
        return;
      }
      showState(ui.matchesList, {
        kind: "error",
        title: "匹配解释加载失败",
        message: formatError(error),
        retry: () => void loadMatches()
      });
    } finally {
      if (epoch === state.epoch) {
        setButtonBusy(ui.loadMatchesButton, false);
      }
    }
  }

  function renderMatches() {
    const matches = state.matches.items;
    if (matches.length === 0) {
      showState(ui.matchesList, {
        kind: "empty",
        title: "暂无候选匹配",
        message: "服务端未返回可解释的拾获物品候选。"
      });
      return;
    }

    const fragment = document.createDocumentFragment();
    const ruleLine = make("p", { className: "rule-version" });
    ruleLine.textContent = `规则版本：${state.matches.ruleVersion || "服务端未提供"}`
      + (state.matches.threshold !== null ? `；候选阈值：${state.matches.threshold}` : "");
    fragment.append(ruleLine);

    matches.forEach((candidate, index) => {
      const foundId = matchFoundId(candidate);
      const title = safeText(
        candidate.title ||
        candidate.found_title ||
        candidate.item_title ||
        (isPlainObject(candidate.item) && candidate.item.title) ||
        (isPlainObject(candidate.found_item) && candidate.found_item.title)
      ).trim() || lookupListingTitle(foundId) || `候选 ${index + 1}`;

      const card = make("article", { className: "match-card" });
      const head = make("div", { className: "match-card-head" });
      head.append(make("h4", { className: "match-title", text: title }));

      const scoreText = formatScore(candidate.score);
      if (scoreText) {
        head.append(make("span", { className: "score", text: `匹配分 ${scoreText}` }));
      }
      card.append(head);

      const metaText = matchMetaText(candidate);
      if (metaText) {
        card.append(make("p", { className: "match-meta", text: metaText }));
      }

      const reasons = matchReasons(candidate);
      if (reasons.length > 0) {
        const list = make("ul", { className: "reason-list" });
        reasons.forEach((reason) => list.append(make("li", { text: reason })));
        card.append(list);
      } else {
        card.append(make("p", { className: "hint", text: "服务端未返回可读的解释理由。" }));
      }

      const version = safeText(candidate.rule_version).trim() || state.matches.ruleVersion;
      if (version) {
        card.append(make("p", { className: "rule-version", text: `该结果规则版本：${version}` }));
      }

      if (isIdPresent(foundId)) {
        const actions = make("div", { className: "actions-row" });
        const viewButton = make("button", {
          className: "button button-small",
          text: "查看该失物详情",
          attrs: { type: "button" }
        });
        viewButton.addEventListener("click", () => {
          scrollToElement(ui.foundSection);
          void loadFoundDetail(foundId);
        });
        actions.append(viewButton);
        card.append(actions);
      }

      fragment.append(card);
    });

    ui.matchesList.replaceChildren(fragment);
    ui.matchesList.setAttribute("aria-busy", "false");
  }

  function matchReasons(candidate) {
    const raw = Array.isArray(candidate.reasons)
      ? candidate.reasons
      : candidate.reason !== undefined
        ? [candidate.reason]
        : [];

    return raw
      .map(reasonText)
      .map((text) => text.trim())
      .filter(Boolean);
  }

  function reasonText(reason) {
    if (typeof reason === "string" || typeof reason === "number") {
      return String(reason).slice(0, 500);
    }
    if (isPlainObject(reason)) {
      return safeText(reason.text || reason.reason || reason.description || reason.explanation || reason.detail)
        .trim()
        .slice(0, 500);
    }
    return "";
  }

  function matchMetaText(candidate) {
    const nested = isPlainObject(candidate.item)
      ? candidate.item
      : isPlainObject(candidate.found_item)
        ? candidate.found_item
        : isPlainObject(candidate.listing)
          ? candidate.listing
          : {};
    const parts = [];
    const category = safeText(candidate.category || nested.category).trim();
    const occurred = candidate.occurred_at || nested.occurred_at;
    const location = safeText(candidate.location || nested.location).trim();
    if (category) {
      parts.push(category);
    }
    if (occurred) {
      parts.push(formatDateTime(occurred));
    }
    if (location) {
      parts.push(location);
    }
    return parts.join(" · ");
  }

  function matchFoundId(candidate) {
    if (candidate.found_item_id !== undefined && candidate.found_item_id !== null) {
      return candidate.found_item_id;
    }
    if (candidate.listing_id !== undefined && candidate.listing_id !== null) {
      return candidate.listing_id;
    }
    if (candidate.found_listing_id !== undefined && candidate.found_listing_id !== null) {
      return candidate.found_listing_id;
    }
    if (candidate.item_id !== undefined && candidate.item_id !== null) {
      return candidate.item_id;
    }
    if (isPlainObject(candidate.found_item) && isIdPresent(candidate.found_item.id)) {
      return candidate.found_item.id;
    }
    if (isPlainObject(candidate.item) && isIdPresent(candidate.item.id)) {
      return candidate.item.id;
    }
    if (isPlainObject(candidate.listing) && isIdPresent(candidate.listing.id)) {
      return candidate.listing.id;
    }
    return null;
  }

  /* ----------------------------------------------------------------------- */
  /* Related claims                                                          */
  /* ----------------------------------------------------------------------- */

  function claimFilterButton(role) {
    return role === "applicant" ? ui.claimsFilterApplicant : ui.claimsFilterFinder;
  }

  function claimFilterCountElement(role) {
    return role === "applicant" ? ui.claimsCountApplicant : ui.claimsCountFinder;
  }

  function renderClaimFilters() {
    const enabled = Boolean(state.token) && !state.switching;
    let anyError = false;
    let anyLoading = false;

    for (const role of CLAIM_FILTER_ROLES) {
      const button = claimFilterButton(role);
      const countElement = claimFilterCountElement(role);
      const active = state.claims.role === role;
      const status = state.claims.countStatus[role];
      const count = state.claims.counts[role];
      let countText = "—";
      let countTitle = "总数暂不可用";
      let countState = "unavailable";

      if (status === "loading") {
        countText = "…";
        countTitle = "正在读取总数";
        countState = "loading";
        anyLoading = true;
      } else if (status === "ready" && Number.isFinite(count)) {
        countText = String(count);
        countTitle = `共 ${count} 条`;
        countState = "ready";
      } else if (status === "error") {
        anyError = true;
      }

      button.disabled = !enabled;
      button.setAttribute("aria-pressed", active ? "true" : "false");
      const countLabel = status === "ready" && Number.isFinite(count)
        ? `共 ${count} 条`
        : status === "loading"
          ? "正在读取总数"
          : "总数暂不可用";
      button.setAttribute(
        "aria-label",
        `${CLAIM_FILTER_LABELS[role]}，${CLAIM_FILTER_ROLE_LABELS[role]}，${countLabel}`
      );

      countElement.textContent = countText;
      countElement.title = countTitle;
      countElement.dataset.countState = countState;
    }

    ui.claimsFilters.setAttribute("aria-busy", anyLoading ? "true" : "false");

    let note;
    if (!state.token) {
      note = "选择演示身份后可按“我发起的/我收到的”分组查看申请。";
    } else if (state.claims.role === "applicant") {
      note = "当前显示我作为申请人的申请；可切换到“我收到的”查看拾获者视角。";
    } else {
      note = "当前显示我作为拾获者的申请；可切换到“我发起的”查看申请人视角。";
    }
    if (enabled && anyError) {
      note += " 分组总数暂不可用（显示 —），可刷新重试。";
    }
    ui.claimsFilterNote.textContent = note;
  }

  function switchClaimsRole(role) {
    if (!CLAIM_FILTER_ROLES.includes(role) || !state.token || state.switching) {
      return;
    }
    if (state.claims.role === role) {
      return;
    }

    state.claims.role = role;
    state.claims.page = 1;
    state.claims.items = [];
    state.claims.total = null;
    renderClaimFilters();
    void loadClaims();
  }

  async function loadClaimCounts(epoch) {
    if (!state.token || epoch !== state.epoch) {
      return;
    }

    const countSeq = ++state.seq.claimCounts;
    state.claims.counts = { applicant: null, finder: null };
    state.claims.countStatus = { applicant: "loading", finder: "loading" };
    renderClaimFilters();

    await Promise.all(CLAIM_FILTER_ROLES.map(async (role) => {
      try {
        const query = new URLSearchParams({
          role,
          page: "1",
          page_size: "1"
        });
        const payload = await requestJson(`/claims?${query.toString()}`, { auth: true });
        if (epoch !== state.epoch || countSeq !== state.seq.claimCounts) {
          return;
        }

        const pageData = extractList(payload, ["claims", "items", "results"]);
        if (!pageData.recognized || !Number.isFinite(pageData.total)) {
          throw new ApiError(502, "UNEXPECTED_LIST_SHAPE", "分组计数响应结构无法识别。");
        }

        state.claims.counts[role] = pageData.total;
        state.claims.countStatus[role] = "ready";
      } catch (error) {
        if (
          epoch !== state.epoch ||
          countSeq !== state.seq.claimCounts ||
          isAbortError(error)
        ) {
          return;
        }
        if (state.claims.countStatus[role] !== "ready") {
          state.claims.counts[role] = null;
          state.claims.countStatus[role] = "error";
        }
      } finally {
        if (epoch === state.epoch && countSeq === state.seq.claimCounts) {
          renderClaimFilters();
        }
      }
    }));
  }

  async function loadClaims(options = {}) {
    if (!state.token) {
      showState(ui.claimsList, {
        kind: "info",
        message: "选择演示身份后查看本人相关申请。"
      });
      updateClaimsPagination();
      renderClaimFilters();
      return;
    }

    const refreshCounts = options.refreshCounts !== false;
    const epoch = state.epoch;
    const role = state.claims.role;
    const seq = ++state.seq.claims;
    const roleFilterLabel = CLAIM_FILTER_LABELS[role];
    let countsPromise = null;

    if (refreshCounts) {
      countsPromise = loadClaimCounts(epoch);
    }
    renderClaimFilters();
    showState(ui.claimsList, {
      kind: "loading",
      message: `正在加载${roleFilterLabel}申请…`
    });

    try {
      const query = new URLSearchParams({
        role,
        page: String(state.claims.page),
        page_size: String(PAGE_SIZE)
      });
      const payload = await requestJson(`/claims?${query.toString()}`, { auth: true });
      if (
        epoch !== state.epoch ||
        seq !== state.seq.claims ||
        state.claims.role !== role
      ) {
        return;
      }

      const pageData = extractList(payload, ["claims", "items", "results"]);
      if (!pageData.recognized) {
        throw new ApiError(502, "UNEXPECTED_LIST_SHAPE", "申请列表响应结构无法识别，请核对接口契约。");
      }

      await prefetchClaimListingTitles(pageData.items, epoch);
      if (
        epoch !== state.epoch ||
        seq !== state.seq.claims ||
        state.claims.role !== role
      ) {
        return;
      }

      state.claims.items = pageData.items;
      state.claims.total = pageData.total;
      if (Number.isFinite(pageData.total)) {
        state.claims.counts[role] = pageData.total;
        state.claims.countStatus[role] = "ready";
      }
      renderClaimFilters();
      renderClaimsList();
      updateClaimsPagination();
    } catch (error) {
      if (
        epoch !== state.epoch ||
        seq !== state.seq.claims ||
        state.claims.role !== role ||
        isAbortError(error)
      ) {
        return;
      }
      state.claims.items = [];
      state.claims.total = null;
      showState(ui.claimsList, {
        kind: "error",
        title: `${roleFilterLabel}申请加载失败`,
        message: formatError(error),
        retry: () => void loadClaims()
      });
      updateClaimsPagination();
    } finally {
      if (countsPromise) {
        try {
          await countsPromise;
        } catch (_error) {
          // Count requests already resolve to a visible unavailable state.
        }
      }
    }
  }

  async function refreshClaimsAfterOnline() {
    if (!state.token || state.switching || onlineRefreshInFlight) {
      return;
    }

    onlineRefreshInFlight = true;
    try {
      await loadClaims();
    } finally {
      onlineRefreshInFlight = false;
    }
  }

  function renderClaimsList() {
    ui.claimsList.setAttribute("aria-busy", "false");

    if (state.claims.items.length === 0) {
      const role = state.claims.role;
      const title = state.claims.page > 1
        ? "当前页暂无申请"
        : role === "applicant"
          ? "暂无我发起的申请"
          : "暂无我收到的申请";
      const message = state.claims.page > 1
        ? "当前页为空，可返回上一页继续查看。"
        : role === "applicant"
          ? "当前身份还没有作为申请人发起的认领申请。"
          : "当前身份还没有作为拾获者收到的认领申请。";
      showState(ui.claimsList, {
        kind: "empty",
        title,
        message
      });
      return;
    }

    const list = make("ul", { className: "item-list" });
    for (const raw of state.claims.items) {
      if (!isPlainObject(raw)) {
        continue;
      }

      const claimId = raw.id;
      const title = claimTitle(raw);
      const role = getClaimRole(raw);
      const selected = isIdPresent(claimId) && String(claimId) === String(state.selectedClaimId);
      const li = make("li", { className: "item-card" });
      const button = make("button", {
        className: "item-button",
        attrs: {
          type: "button",
          "aria-pressed": selected ? "true" : "false",
          "data-claim-id": isIdPresent(claimId) ? String(claimId) : false,
          "data-item-id": isIdPresent(raw.item_id) ? String(raw.item_id) : false
        }
      });

      const metaParts = [];
      if (role !== "unknown") {
        metaParts.push(`本人角色：${roleLabel(role)}`);
      }
      if (raw.updated_at) {
        metaParts.push(`更新于 ${formatDateTime(raw.updated_at)}`);
      } else if (raw.created_at) {
        metaParts.push(`创建于 ${formatDateTime(raw.created_at)}`);
      }

      button.append(
        make("span", { className: "item-title", text: title }),
        make("span", {
          className: "item-meta",
          text: metaParts.length > 0 ? metaParts.join(" · ") : "未返回可显示的时间或角色信息"
        })
      );

      const badges = make("span", { className: "item-badges" });
      badges.append(statusBadge(raw.status));
      if (role !== "unknown") {
        badges.append(roleBadge(role));
      }
      button.append(badges);

      if (isIdPresent(claimId)) {
        button.addEventListener("click", () => openClaim(claimId, { focusHeading: true }));
      } else {
        button.disabled = true;
      }

      li.append(button);
      list.append(li);
    }

    ui.claimsList.replaceChildren(list);
  }

  function updateClaimsPagination() {
    const total = state.claims.total;
    const hasKnownTotal = Number.isFinite(total);
    const hasNext = hasKnownTotal
      ? state.claims.page * PAGE_SIZE < total
      : state.claims.items.length >= PAGE_SIZE;

    ui.claimsPrev.disabled = state.claims.page <= 1 || !state.token;
    ui.claimsNext.disabled = !hasNext || !state.token;
    ui.claimsPageStatus.textContent = hasKnownTotal
      ? `第 ${state.claims.page} 页 · 共 ${total} 条`
      : `第 ${state.claims.page} 页`;
  }

  function changeClaimsPage(delta) {
    if (!state.token) {
      return;
    }
    const nextPage = state.claims.page + delta;
    if (nextPage < 1) {
      return;
    }
    state.claims.page = nextPage;
    void loadClaims({ refreshCounts: false });
  }

  /* ----------------------------------------------------------------------- */
  /* Claim workspace                                                         */
  /* ----------------------------------------------------------------------- */

  function openClaim(claimId, options = {}) {
    if (!state.token) {
      showNotice("请先选择演示身份。", "warning", { sticky: true });
      return;
    }
    if (!isIdPresent(claimId)) {
      return;
    }

    const idText = String(claimId);
    const isNew = String(state.selectedClaimId) !== idText;
    state.selectedClaimId = claimId;

    if (isNew) {
      state.seq.messages += 1;
      state.seq.code += 1;
      state.messages = [];
      state.code = null;
      ui.messageForm.reset();
      updateCharacterCount();
      ui.handoverConfirmForm.reset();
      clearInlineError(ui.handoverFormError);
      clearInlineError(ui.handoverActionError);
      ui.codeStatus.textContent = "";
      ui.codeDisplay.hidden = true;
      ui.ownCode.textContent = "";
      ui.codeExpiry.textContent = "";
      ui.handoverProgress.textContent = "";
      ui.messageList.replaceChildren();
      setButtonBusy(ui.fetchCodeButton, false);
      setButtonIdleLabel(ui.fetchCodeButton, "获取本方确认码");
      setButtonBusy(ui.handoverConfirmSubmit, false);
      setButtonBusy(ui.refreshMessages, false);
      setButtonBusy(ui.exportButton, false);
    }

    ui.claimWorkspace.hidden = false;
    ui.claimDetailTitle.textContent = "申请详情";
    ui.claimBadges.replaceChildren();
    ui.claimDetailContent.hidden = true;
    ui.claimLoadState.hidden = false;
    showState(ui.claimLoadState, {
      kind: "loading",
      message: "正在加载申请详情…"
    });

    renderClaimsList();
    scrollToElement(ui.claimWorkspace);
    void loadClaimDetail(claimId, { focusHeading: Boolean(options.focusHeading) });
  }

  function closeClaimWorkspace() {
    if (!state.selectedClaimId) {
      return;
    }

    Object.keys(state.seq).forEach((key) => {
      if (key === "claim" || key === "messages" || key === "code") {
        state.seq[key] += 1;
      }
    });

    clearClaimWorkspaceDom();
    renderClaimsList();
    showNotice("已收起申请详情，私有证据、消息和确认码已从页面清除。", "info");
  }

  function clearClaimWorkspaceDom() {
    state.selectedClaimId = null;
    state.claim = null;
    state.messages = [];
    state.code = null;

    ui.claimWorkspace.hidden = true;
    ui.claimBadges.replaceChildren();
    ui.claimDetailTitle.textContent = "申请详情";
    ui.claimLoadState.hidden = true;
    ui.claimLoadState.replaceChildren();
    ui.claimDetailContent.hidden = true;

    ui.claimMeta.replaceChildren();
    ui.claimEvidence.replaceChildren();
    ui.claimRoleNote.textContent = "";
    ui.claimActions.replaceChildren();
    clearInlineError(ui.claimActionsMessage);

    ui.handoverSection.hidden = true;
    ui.handoverConfirmForm.reset();
    clearInlineError(ui.handoverFormError);
    clearInlineError(ui.handoverActionError);
    ui.handoverProgress.textContent = "";
    ui.codeStatus.textContent = "";
    ui.codeDisplay.hidden = true;
    ui.ownCode.textContent = "";
    ui.codeExpiry.textContent = "";
    setButtonBusy(ui.fetchCodeButton, false);
    setButtonIdleLabel(ui.fetchCodeButton, "获取本方确认码");
    setButtonBusy(ui.handoverConfirmSubmit, false);

    ui.chatSection.hidden = true;
    ui.messageList.replaceChildren();
    ui.messageList.setAttribute("aria-busy", "false");
    ui.messageForm.reset();
    updateCharacterCount();
    clearInlineError(ui.messageFormError);
    ui.chatReadonlyNote.textContent = "";
    ui.messageText.disabled = true;
    ui.messageSubmit.disabled = true;
    setButtonBusy(ui.refreshMessages, false);

    ui.disputeSection.hidden = true;
    ui.disputeButton.hidden = false;
    ui.exportButton.hidden = true;
    ui.disputeNote.textContent = "";
    setButtonBusy(ui.exportButton, false);
    setButtonBusy(ui.disputeButton, false);

    setButtonBusy(ui.claimSubmit, false);
  }

  async function loadClaimDetail(claimId, options = {}) {
    if (!state.token || !isIdPresent(claimId)) {
      return;
    }

    const idText = String(claimId);
    const epoch = state.epoch;
    const seq = ++state.seq.claim;

    clearClaimBodyForLoading();
    ui.claimLoadState.hidden = false;
    showState(ui.claimLoadState, {
      kind: "loading",
      message: "正在加载申请详情…"
    });

    try {
      const payload = await requestJson(claimPath(claimId), { auth: true });
      if (
        epoch !== state.epoch ||
        seq !== state.seq.claim ||
        String(state.selectedClaimId) !== idText
      ) {
        return;
      }

      const claim = extractObject(payload, ["claim", "application"]);
      if (!isPlainObject(claim)) {
        throw new ApiError(502, "UNEXPECTED_CLAIM_SHAPE", "申请详情响应结构无法识别，请核对接口契约。");
      }

      await prefetchClaimListingTitles([claim], epoch);
      if (
        epoch !== state.epoch ||
        seq !== state.seq.claim ||
        String(state.selectedClaimId) !== idText
      ) {
        return;
      }

      state.claim = claim;
      ui.claimLoadState.hidden = true;
      ui.claimLoadState.replaceChildren();
      renderClaimDetail(claim);

      if (options.focusHeading) {
        ui.claimDetailTitle.focus({ preventScroll: true });
      }

      void loadMessages(claimId);
    } catch (error) {
      if (epoch !== state.epoch || seq !== state.seq.claim || isAbortError(error)) {
        return;
      }
      if (String(state.selectedClaimId) !== idText) {
        return;
      }

      state.claim = null;
      ui.claimDetailContent.hidden = true;
      ui.claimLoadState.hidden = false;
      showState(ui.claimLoadState, {
        kind: "error",
        title: "申请详情加载失败",
        message: formatError(error),
        retry: () => void loadClaimDetail(claimId, { focusHeading: true })
      });
    }
  }

  function clearClaimBodyForLoading() {
    ui.claimDetailContent.hidden = true;
    ui.claimBadges.replaceChildren();
    ui.claimMeta.replaceChildren();
    ui.claimEvidence.replaceChildren();
    ui.claimRoleNote.textContent = "";
    ui.claimActions.replaceChildren();
    clearInlineError(ui.claimActionsMessage);
    ui.handoverSection.hidden = true;
    ui.chatSection.hidden = true;
    ui.disputeSection.hidden = true;
    ui.messageList.replaceChildren();
    ui.claimBadges.replaceChildren();
  }

  function renderClaimDetail(claim) {
    const status = getClaimStatus(claim);
    const role = getClaimRole(claim);
    const title = claimTitle(claim);

    ui.claimDetailTitle.textContent = `申请详情：${title}`;
    ui.claimDetailContent.hidden = false;
    renderClaimBadges(claim, status, role);
    renderClaimMeta(claim, role, status);
    renderClaimEvidence(claim);
    renderClaimActions(claim, status, role);
    renderHandover(claim, status);
    renderChatState(claim, status, role);
    renderDisputeSection(claim, status);
  }

  function renderClaimBadges(claim, status, role) {
    ui.claimBadges.replaceChildren();
    ui.claimBadges.append(statusBadge(status));
    if (role !== "unknown") {
      ui.claimBadges.append(roleBadge(role));
    } else {
      ui.claimBadges.append(make("span", { className: "badge", text: "本人角色未返回" }));
    }
    ui.claimBadges.append(make("span", { className: "privacy-chip", text: "仅申请双方可见" }));
  }

  function renderClaimMeta(claim, role, status) {
    ui.claimMeta.replaceChildren();
    appendClaimMeta("相关物品", claimTitle(claim));
    if (isIdPresent(claim.id)) {
      appendClaimMeta("申请编号", String(claim.id));
    }
    appendClaimMeta("本人角色", role === "unknown" ? "服务端未返回可识别角色" : roleLabel(role));
    if (claim.created_at) {
      appendClaimMeta("创建时间", formatDateTime(claim.created_at));
    }
    if (claim.updated_at) {
      appendClaimMeta("更新时间", formatDateTime(claim.updated_at));
    }
    if (claim.handover_deadline) {
      appendClaimMeta("交接期限", formatDateTime(claim.handover_deadline));
    }

    const reason = safeText(claim.reason).trim();
    if (reason) {
      const label = status === "REJECTED"
        ? "驳回原因"
        : status === "DISPUTED"
          ? "争议原因"
          : "状态说明";
      appendClaimMeta(label, reason, true);
    }
  }

  function appendClaimMeta(label, value, wide = false) {
    const item = make("div", {
      className: wide ? "claim-meta-item claim-meta-wide" : "claim-meta-item"
    });
    item.append(
      make("span", { className: "claim-meta-label", text: label }),
      make("span", { className: "claim-meta-value", text: value })
    );
    ui.claimMeta.append(item);
  }

  function renderClaimEvidence(claim) {
    ui.claimEvidence.replaceChildren();

    const evidenceText = safeText(
      claim.evidence_text !== undefined ? claim.evidence_text : claim.evidence
    ).trim();
    const itemNumber = safeText(claim.item_number).trim();

    if (!evidenceText && !itemNumber) {
      showState(ui.claimEvidence, {
        kind: "info",
        message: "服务端未返回可显示的私有证据。"
      });
      return;
    }

    if (itemNumber) {
      ui.claimEvidence.append(evidenceItem("物品编号 / 私有暗号", itemNumber, "mono"));
    }
    if (evidenceText) {
      ui.claimEvidence.append(evidenceItem("私有证据说明", evidenceText));
    }
  }

  function evidenceItem(label, value, extraClass) {
    const wrap = make("div", { className: "evidence-item" });
    const valueNode = make("p", {
      className: `evidence-value${extraClass ? ` ${extraClass}` : ""}`,
      text: value
    });
    wrap.append(
      make("span", { className: "evidence-label", text: label }),
      valueNode
    );
    return wrap;
  }

  function renderClaimActions(claim, status, role) {
    ui.claimActions.replaceChildren();
    clearInlineError(ui.claimActionsMessage);
    ui.claimRoleNote.textContent = "";

    if (!isIdPresent(claim.id)) {
      ui.claimRoleNote.textContent = "服务端未返回申请 id，无法执行状态操作。";
      return;
    }

    const statusKnown = Object.prototype.hasOwnProperty.call(STATUS_LABELS, status);
    if (!statusKnown) {
      ui.claimRoleNote.textContent = "无法识别服务端返回的申请状态，已隐藏状态操作。";
      return;
    }

    if (status === "PENDING") {
      const approvePermission = permissionFor(claim, "approve");
      const rejectPermission = permissionFor(claim, "reject");
      const withdrawPermission = permissionFor(claim, "withdraw");

      const canApprove = approvePermission === true || (approvePermission === null && role === "finder");
      const canReject = rejectPermission === true || (rejectPermission === null && role === "finder");
      const canWithdraw = withdrawPermission === true || (withdrawPermission === null && role === "claimant");
      let buttonCount = 0;

      if (canApprove) {
        appendClaimActionButton("批准申请", "button button-primary", (button) => {
          void handleApprove(claim, button);
        });
        buttonCount += 1;
      }
      if (canReject) {
        appendClaimActionButton("驳回申请", "button button-danger-outline", (button) => {
          void handleReject(claim, button);
        });
        buttonCount += 1;
      }
      if (canWithdraw) {
        appendClaimActionButton("撤销申请", "button button-danger-outline", (button) => {
          void handleWithdraw(claim, button);
        });
        buttonCount += 1;
      }

      if (buttonCount > 0) {
        ui.claimRoleNote.textContent = role === "finder"
          ? "你是拾获者：批准后进入交接确认；同一拾获物品的其他待审申请可能由服务端关闭。"
          : "你是申请人：可在审核前撤销。批准后请使用下方交接确认。";
      } else if (role === "unknown") {
        ui.claimRoleNote.textContent = "服务端未返回可识别的本人角色或操作权限，状态操作已隐藏。可刷新详情或重新选择演示身份。";
      } else {
        ui.claimRoleNote.textContent = "当前状态与本人角色下没有可执行的状态操作。";
      }
      return;
    }

    if (status === "APPROVED") {
      ui.claimRoleNote.textContent = "申请已批准。请使用下方交接确认：双方均确认后才完成。";
      return;
    }

    if (status === "DISPUTED") {
      ui.claimRoleNote.textContent = "申请已进入争议冻结：状态操作、匿名沟通和交接确认均已停止；当前仅可查看历史消息、私有证据并下载去身份导出。";
      return;
    }

    if (status === "COMPLETED") {
      ui.claimRoleNote.textContent = "交接已完成，当前为只读状态。";
      return;
    }

    if (status === "CLOSED_OTHER") {
      ui.claimRoleNote.textContent = "同一拾获物品的其他申请已获批，本申请被关闭；当前为只读状态。";
      return;
    }

    if (status === "EXPIRED") {
      ui.claimRoleNote.textContent = "申请已过期（待审核时限或交接期限已过），当前为只读状态。";
      return;
    }

    ui.claimRoleNote.textContent = `当前状态“${displayStatus(status)}”下没有可执行的状态操作，仅可查看。`;
  }

  function appendClaimActionButton(label, className, onClick) {
    const button = make("button", {
      className,
      text: label,
      attrs: { type: "button", "data-write-trigger": "true" }
    });
    button.addEventListener("click", () => onClick(button));
    ui.claimActions.append(button);
    return button;
  }

  function renderHandover(claim, status) {
    if (status !== "APPROVED") {
      ui.handoverSection.hidden = true;
      state.code = null;
      ui.codeDisplay.hidden = true;
      ui.ownCode.textContent = "";
      ui.codeExpiry.textContent = "";
      ui.codeStatus.textContent = "";
      ui.handoverConfirmForm.reset();
      clearInlineError(ui.handoverFormError);
      clearInlineError(ui.handoverActionError);
      ui.handoverProgress.textContent = "";
      return;
    }

    ui.handoverSection.hidden = false;
    renderCodeState();
    renderHandoverProgress(claim);
  }

  function renderHandoverProgress(claim) {
    const handover = getHandoverState(claim);
    const parts = [];

    if (handover.mine !== null) {
      parts.push(handover.mine ? "本人已确认" : "本人尚未确认");
    }
    if (handover.other !== null) {
      parts.push(handover.other ? "对方已确认" : "对方尚未确认");
    }

    if (handover.mine === true && handover.other === true) {
      ui.handoverProgress.textContent = "双方均已确认。最终状态以服务端响应为准。";
    } else if (parts.length > 0) {
      ui.handoverProgress.textContent = `${parts.join("；")}。双方均确认后才会完成交接。`;
    } else {
      ui.handoverProgress.textContent = "服务端未返回双方确认细节；双方均确认后状态才会变为已完成。";
    }
  }

  function renderCodeState() {
    if (!state.code || !state.code.code) {
      ui.codeDisplay.hidden = true;
      ui.ownCode.textContent = "";
      ui.codeExpiry.textContent = "";
      setButtonIdleLabel(ui.fetchCodeButton, "获取本方确认码");
      return;
    }

    ui.codeDisplay.hidden = false;
    ui.ownCode.textContent = state.code.code;
    ui.codeExpiry.textContent = state.code.expires_at
      ? `有效期至 ${formatDateTime(state.code.expires_at)}（以服务端时间为准）`
      : "服务端未返回过期时间。";
    setButtonIdleLabel(ui.fetchCodeButton, "刷新本方确认码");
  }

  function renderChatState(claim, status, role) {
    ui.chatSection.hidden = false;
    const active = status === "PENDING" || status === "APPROVED";
    const sendPermission = permissionFor(claim, "send_message");
    const canSend = active && sendPermission !== false;

    ui.messageText.disabled = !canSend;
    ui.messageSubmit.disabled = !canSend;

    if (status === "DISPUTED") {
      ui.messageText.placeholder = "争议冻结，仅可查看历史消息。";
      ui.chatReadonlyNote.textContent = "争议冻结：匿名沟通已停止，仅可查看历史消息并下载去身份导出。";
      return;
    }

    ui.messageText.placeholder = canSend
      ? "输入消息，不要包含手机号、邮箱或身份证号。"
      : "当前申请不可发送消息，仅可查看历史记录。";

    if (!active) {
      ui.chatReadonlyNote.textContent = "申请已结束，聊天只读。";
    } else if (sendPermission === false) {
      ui.chatReadonlyNote.textContent = "服务端权限显示当前不可发送消息。";
    } else {
      ui.chatReadonlyNote.textContent = "";
    }
  }

  function renderDisputeSection(claim, status) {
    ui.disputeSection.hidden = true;
    ui.disputeButton.hidden = false;
    ui.exportButton.hidden = true;
    ui.disputeNote.textContent = "";
    ui.exportButton.disabled = false;
    ui.disputeButton.disabled = false;

    if (status === "APPROVED") {
      ui.disputeSection.hidden = false;
      ui.disputeDescription.textContent = "发起争议会冻结本次申请的状态操作、匿名沟通与交接确认，并将申请转为只读；历史证据和消息仍可查看，去身份导出将开放。该操作在界面中不可撤销，请确认后再继续。";
      ui.disputeNote.textContent = "仅在确有严重分歧时使用。争议后不可再发送消息，仅可查看历史并下载去身份导出。";
      ui.exportButton.hidden = true;
      return;
    }

    if (status === "DISPUTED") {
      ui.disputeSection.hidden = false;
      ui.disputeButton.hidden = true;
      ui.exportButton.hidden = false;
      ui.disputeDescription.textContent = "该申请已进入争议冻结，当前为只读：状态操作、匿名沟通与交接确认均已停止。历史消息仍可查看，可下载去身份导出。";
      ui.disputeNote.textContent = "导出文件不包含真实身份映射；请仅在授权范围内使用。";
    }
  }

  /* ----------------------------------------------------------------------- */
  /* Claim state actions                                                     */
  /* ----------------------------------------------------------------------- */

  async function handleApprove(claim, button) {
    if (!ensureCooldown(ui.claimActionsMessage)) {
      return;
    }

    const result = await openActionDialog({
      title: "批准这项认领？",
      description: "批准后进入交接确认。同一拾获物品的其他待审申请可能由服务端关闭。",
      confirmLabel: "确认批准"
    });
    if (!result) {
      return;
    }
    if (String(state.selectedClaimId) !== String(claim.id)) {
      return;
    }

    await runClaimAction({
      claimId: claim.id,
      actionName: "approve",
      path: "/approve",
      button,
      successMessage: "已批准该认领申请，进入交接确认。"
    });
  }

  async function handleReject(claim, button) {
    if (!ensureCooldown(ui.claimActionsMessage)) {
      return;
    }

    const result = await openActionDialog({
      title: "驳回这项认领？",
      description: "请填写驳回原因。原因会对相关方可见，请勿填写真实身份信息。",
      reasonLabel: "驳回原因",
      reasonRequired: true,
      confirmLabel: "确认驳回",
      danger: true
    });
    if (!result) {
      return;
    }
    if (String(state.selectedClaimId) !== String(claim.id)) {
      return;
    }

    await runClaimAction({
      claimId: claim.id,
      actionName: "reject",
      path: "/reject",
      body: { reason: result.reason },
      button,
      successMessage: "已驳回该认领申请。"
    });
  }

  async function handleWithdraw(claim, button) {
    if (!ensureCooldown(ui.claimActionsMessage)) {
      return;
    }

    const result = await openActionDialog({
      title: "撤销这项申请？",
      description: "撤销后申请进入终态，不能继续匿名沟通或交接确认。",
      confirmLabel: "确认撤销",
      danger: true
    });
    if (!result) {
      return;
    }
    if (String(state.selectedClaimId) !== String(claim.id)) {
      return;
    }

    await runClaimAction({
      claimId: claim.id,
      actionName: "withdraw",
      path: "/withdraw",
      button,
      successMessage: "已撤销该认领申请。"
    });
  }

  async function runClaimAction(options) {
    const claimId = options.claimId;
    const epoch = state.epoch;
    const slot = `claim:${String(claimId)}:${options.actionName}`;
    const body = options.body;
    const signature = body === undefined ? "<empty-body>" : JSON.stringify(body);

    await runWriteAction({
      slot,
      button: options.button,
      busyText: "处理中…",
      errorBox: ui.claimActionsMessage,
      action: async () => {
        const key = getWriteKey(slot, signature);
        await requestJson(`${claimPath(claimId)}${options.path}`, {
          method: "POST",
          auth: true,
          body,
          idempotencyKey: key
        });
        forgetWriteKey(slot);

        if (epoch !== state.epoch) {
          return;
        }

        if (String(state.selectedClaimId) === String(claimId)) {
          showNotice(options.successMessage, "success");
        }
        await refreshClaimAfterMutation(claimId);
      },
      onError: (error) => {
        if (error.status === 409) {
          showNotice(formatError(error), "error", { sticky: true });
          void loadClaimDetail(claimId);
        }
      }
    });
  }

  async function refreshClaimAfterMutation(claimId) {
    const tasks = [
      loadClaimDetail(claimId),
      loadClaims(),
      loadFound()
    ];
    if (state.found.detail && isIdPresent(state.found.detail.id)) {
      tasks.push(loadFoundDetail(state.found.detail.id));
    }
    await Promise.allSettled(tasks);
  }

  /* ----------------------------------------------------------------------- */
  /* Anonymous messages                                                      */
  /* ----------------------------------------------------------------------- */

  async function loadMessages(claimId, options = {}) {
    if (!state.token || !isIdPresent(claimId) || String(state.selectedClaimId) !== String(claimId)) {
      return;
    }

    const epoch = state.epoch;
    const seq = ++state.seq.messages;
    const hadMessages = state.messages.length > 0;

    ui.messageList.setAttribute("aria-busy", "true");
    if (!hadMessages) {
      showState(ui.messageList, {
        kind: "loading",
        message: "正在加载匿名消息…"
      });
    }

    try {
      const allItems = [];
      let after = "";
      let truncated = false;

      for (let page = 0; page < MAX_MESSAGE_PAGES; page += 1) {
        const query = new URLSearchParams({ limit: String(MESSAGE_PAGE_SIZE) });
        if (after) {
          query.set("after", after);
        }
        const payload = await requestJson(`${claimPath(claimId)}/messages?${query.toString()}`, { auth: true });
        if (
          epoch !== state.epoch ||
          seq !== state.seq.messages ||
          String(state.selectedClaimId) !== String(claimId)
        ) {
          return;
        }

        if (!isPlainObject(payload) || !Array.isArray(payload.items)) {
          throw new ApiError(502, "UNEXPECTED_MESSAGE_SHAPE", "消息列表响应结构无法识别，请核对接口契约。");
        }

        allItems.push(...payload.items);
        const nextAfter = safeText(payload.next_after).trim();
        if (!nextAfter) {
          break;
        }
        if (nextAfter === after) {
          throw new ApiError(502, "UNEXPECTED_MESSAGE_SHAPE", "消息分页游标未推进，已停止加载。");
        }
        after = nextAfter;
        if (page === MAX_MESSAGE_PAGES - 1) {
          truncated = true;
        }
      }

      const role = state.claim ? getClaimRole(state.claim) : "unknown";
      const normalized = allItems
        .map((message) => normalizeMessage(message, role))
        .filter(Boolean);

      if (allItems.length > 0 && normalized.length === 0) {
        throw new ApiError(502, "UNEXPECTED_MESSAGE_SHAPE", "消息字段结构无法识别，请核对接口契约。");
      }

      state.messages = normalized;
      renderMessages();
      if (truncated) {
        showNotice("消息数量较多，当前仅展示已加载的部分历史。", "warning", { sticky: true });
      }
    } catch (error) {
      if (
        epoch !== state.epoch ||
        seq !== state.seq.messages ||
        String(state.selectedClaimId) !== String(claimId) ||
        isAbortError(error)
      ) {
        return;
      }
      if (hadMessages) {
        showNotice(`消息刷新失败：${formatError(error)}`, "error", { sticky: true });
      } else {
        showState(ui.messageList, {
          kind: "error",
          title: "消息加载失败",
          message: formatError(error),
          retry: () => void loadMessages(claimId)
        });
      }
    } finally {
      if (seq === state.seq.messages) {
        ui.messageList.setAttribute("aria-busy", "false");
      }
    }
  }

  function normalizeMessage(raw, role) {
    if (!isPlainObject(raw)) {
      return null;
    }

    const text = safeText(
      raw.text !== undefined ? raw.text : raw.content !== undefined ? raw.content : raw.message !== undefined ? raw.message : raw.body
    ).trim();
    if (!text) {
      return null;
    }

    return {
      text,
      mine: messageIsMine(raw, role),
      when: raw.created_at || raw.sent_at || raw.timestamp || raw.time || ""
    };
  }

  function messageIsMine(message, role) {
    for (const key of ["is_mine", "mine", "own", "outgoing"]) {
      if (typeof message[key] === "boolean") {
        return message[key];
      }
      if (message[key] === 1 || message[key] === 0) {
        return message[key] === 1;
      }
    }

    const direction = safeText(message.direction).trim().toLowerCase();
    if (["outgoing", "out", "sent", "mine", "self"].includes(direction)) {
      return true;
    }
    if (["incoming", "in", "received", "other", "counterparty"].includes(direction)) {
      return false;
    }

    const senderRole = normalizeRole(
      message.sender_role || message.author_role || message.role
    );
    if (senderRole !== "unknown" && role !== "unknown") {
      return senderRole === role;
    }

    const sender = safeText(message.sender).trim().toLowerCase();
    if (["me", "self", "mine"].includes(sender)) {
      return true;
    }
    if (["other", "counterparty", "peer"].includes(sender)) {
      return false;
    }

    return null;
  }

  function renderMessages() {
    ui.messageList.replaceChildren();

    if (state.messages.length === 0) {
      const status = state.claim ? getClaimStatus(state.claim) : "";
      const canSend = status === "PENDING" || status === "APPROVED";
      let title = "暂无消息";
      let message = "当前还没有匿名消息，可在下方发送。";

      if (status === "DISPUTED") {
        title = "暂无历史消息";
        message = "争议冻结后匿名沟通已停止，此处仅可查看历史消息并下载去身份导出。";
      } else if (status && !canSend) {
        title = "暂无历史消息";
        message = "当前申请为只读状态，没有可发送的新消息。";
      }

      showState(ui.messageList, {
        kind: "empty",
        title,
        message
      });
      return;
    }

    const fragment = document.createDocumentFragment();
    state.messages.forEach((message) => {
      const directionClass = message.mine === true
        ? "message-mine"
        : message.mine === false
          ? "message-other"
          : "message-unknown";
      const senderLabel = message.mine === true
        ? "我"
        : message.mine === false
          ? "对方"
          : "匿名消息";
      const when = message.when ? formatDateTime(message.when) : "";
      const meta = when ? `${senderLabel} · ${when}` : senderLabel;

      const bubble = make("article", { className: `message ${directionClass}` });
      bubble.append(
        make("div", { className: "message-meta", text: meta }),
        make("p", { className: "message-text", text: message.text })
      );
      fragment.append(bubble);
    });

    ui.messageList.append(fragment);
    ui.messageList.setAttribute("aria-busy", "false");
    ui.messageList.scrollTop = ui.messageList.scrollHeight;
  }

  async function sendMessage() {
    if (!state.token) {
      showNotice("请先选择演示身份。", "warning", { sticky: true });
      return;
    }
    if (!state.claim || !isIdPresent(state.selectedClaimId)) {
      showInlineError(ui.messageFormError, "请先打开一条申请。");
      return;
    }

    const status = getClaimStatus(state.claim);
    if (status !== "PENDING" && status !== "APPROVED") {
      showInlineError(
        ui.messageFormError,
        status === "DISPUTED"
          ? "争议已冻结，匿名沟通已停止，仅可查看历史消息。"
          : "当前申请为只读状态，不能发送消息。"
      );
      return;
    }

    const text = ui.messageText.value.trim();
    if (!text) {
      showInlineError(ui.messageFormError, "请输入消息内容。");
      ui.messageText.focus();
      return;
    }
    if (text.length > MESSAGE_LIMIT) {
      showInlineError(ui.messageFormError, `消息不能超过 ${MESSAGE_LIMIT} 个字符。`);
      ui.messageText.focus();
      return;
    }

    const piiLabels = detectPii(text);
    if (piiLabels.length > 0) {
      showInlineError(
        ui.messageFormError,
        `消息中疑似包含${piiLabels.join("、")}，已拦截发送。请勿在匿名聊天中发送身份信息；物品编号等请放入“私有证据”。`
      );
      ui.messageText.focus();
      return;
    }

    const claimId = state.selectedClaimId;
    const epoch = state.epoch;
    const slot = `message:${String(claimId)}`;
    const signature = JSON.stringify({ text });

    await runWriteAction({
      slot,
      button: ui.messageSubmit,
      busyText: "发送中…",
      errorBox: ui.messageFormError,
      action: async () => {
        const key = getWriteKey(slot, signature);
        await requestJson(`${claimPath(claimId)}/messages`, {
          method: "POST",
          auth: true,
          body: { text },
          idempotencyKey: key
        });
        forgetWriteKey(slot);

        if (epoch !== state.epoch || String(state.selectedClaimId) !== String(claimId)) {
          return;
        }

        ui.messageText.value = "";
        updateCharacterCount();
        await loadMessages(claimId);
        if (
          state.token &&
          String(state.selectedClaimId) === String(claimId)
        ) {
          ui.messageText.focus();
        }
      }
    });
  }

  async function refreshMessages() {
    if (!state.token || !isIdPresent(state.selectedClaimId)) {
      return;
    }

    setButtonBusy(ui.refreshMessages, true, "刷新中…");
    try {
      await loadMessages(state.selectedClaimId);
    } finally {
      if (state.token) {
        setButtonBusy(ui.refreshMessages, false);
      }
    }
  }

  function detectPii(text) {
    const labels = [];
    const value = String(text);
    const compact = value.replace(/[\s\-()]/g, "");

    if (/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i.test(value)) {
      labels.push("邮箱");
    }
    if (/(?:^|[^\d])(?:\+?86)?1[3-9]\d{9}(?:[^\d]|$)/.test(compact)) {
      labels.push("手机号");
    }
    if (/(?:^|[^\d])\d{17}[\dXx](?:[^\d]|$)/.test(compact) || /(?:^|[^\d])\d{15}(?:[^\d]|$)/.test(compact)) {
      labels.push("身份证号");
    }

    return Array.from(new Set(labels));
  }

  function updateCharacterCount() {
    const length = ui.messageText.value.length;
    ui.messageCount.textContent = `${length} / ${MESSAGE_LIMIT}`;
  }

  /* ----------------------------------------------------------------------- */
  /* Handover code, reset, dispute and export                                */
  /* ----------------------------------------------------------------------- */

  async function fetchOwnCode() {
    if (!state.token || !state.claim || !isIdPresent(state.selectedClaimId)) {
      return;
    }
    const status = getClaimStatus(state.claim);
    if (status !== "APPROVED") {
      ui.codeStatus.textContent = "只有在已批准状态下才能获取本方确认码。";
      return;
    }
    if (isCoolingDown()) {
      ui.codeStatus.textContent = cooldownMessage();
      return;
    }

    const claimId = state.selectedClaimId;
    const epoch = state.epoch;
    const seq = ++state.seq.code;

    clearInlineError(ui.handoverActionError);
    ui.codeStatus.textContent = "正在获取本方确认码…";
    setButtonBusy(ui.fetchCodeButton, true, "获取中…");

    try {
      const payload = await requestJson(`${claimPath(claimId)}/code`, { auth: true });
      if (
        epoch !== state.epoch ||
        seq !== state.seq.code ||
        String(state.selectedClaimId) !== String(claimId) ||
        !state.claim ||
        getClaimStatus(state.claim) !== "APPROVED"
      ) {
        return;
      }

      const data = extractObject(payload, ["data"]);
      const code = safeText(data && data.code).trim();
      if (!code) {
        throw new ApiError(502, "BAD_CODE_RESPONSE", "确认码响应缺少 code。");
      }

      state.code = {
        code,
        expires_at: data.expires_at || data.expiresAt || ""
      };
      renderCodeState();
      ui.codeStatus.textContent = "已获取本方确认码。确认码仅用于交接核对，不是身份凭证。";
    } catch (error) {
      if (
        epoch !== state.epoch ||
        seq !== state.seq.code ||
        String(state.selectedClaimId) !== String(claimId) ||
        isAbortError(error)
      ) {
        return;
      }

      if (error.status === 410) {
        state.code = null;
        renderCodeState();
        ui.codeStatus.textContent = "本方确认码已过期，请按重置条件申请重置，或等待冷却结束。";
        showNotice("确认码已过期。按照契约，只有冷却结束或码到期后才能重置交接。", "warning", { sticky: true });
      } else {
        ui.codeStatus.textContent = formatError(error);
      }
    } finally {
      if (
        epoch === state.epoch &&
        String(state.selectedClaimId) === String(claimId)
      ) {
        setButtonBusy(ui.fetchCodeButton, false);
        renderCodeState();
      }
    }
  }

  async function submitHandoverConfirm() {
    if (!state.token || !state.claim || !isIdPresent(state.selectedClaimId)) {
      return;
    }
    if (getClaimStatus(state.claim) !== "APPROVED") {
      showInlineError(ui.handoverFormError, "当前申请不在可交接状态。");
      return;
    }

    const code = ui.counterpartCode.value.trim();
    if (!code) {
      showInlineError(ui.handoverFormError, "请输入对方提供的确认码。");
      ui.counterpartCode.focus();
      return;
    }
    if (code.length < 4 || code.length > 32) {
      showInlineError(ui.handoverFormError, "确认码长度应为 4 到 32 个字符。");
      ui.counterpartCode.focus();
      return;
    }

    const claimId = state.selectedClaimId;
    const epoch = state.epoch;
    const slot = `handover-confirm:${String(claimId)}`;
    const signature = JSON.stringify({ code });

    await runWriteAction({
      slot,
      button: ui.handoverConfirmSubmit,
      busyText: "提交中…",
      errorBox: ui.handoverFormError,
      action: async () => {
        const key = getWriteKey(slot, signature);
        await requestJson(`${claimPath(claimId)}/handover/confirm`, {
          method: "POST",
          auth: true,
          body: { code },
          idempotencyKey: key
        });
        forgetWriteKey(slot);

        if (epoch !== state.epoch || String(state.selectedClaimId) !== String(claimId)) {
          return;
        }

        ui.handoverConfirmForm.reset();
        clearInlineError(ui.handoverFormError);
        showNotice("对方确认码已提交。双方都确认后，交接才会完成。", "success");
        await refreshClaimAfterMutation(claimId);
      },
      onError: (error) => {
        if (error.status === 410 || error.status === 409) {
          showNotice(formatError(error), "error", { sticky: true });
          void loadClaimDetail(claimId);
        }
      }
    });
  }

  async function resetHandover() {
    if (!state.token || !state.claim || !isIdPresent(state.selectedClaimId)) {
      return;
    }
    if (getClaimStatus(state.claim) !== "APPROVED") {
      showNotice("当前申请不在可重置交接的状态。", "warning", { sticky: true });
      return;
    }
    if (!ensureCooldown(ui.handoverActionError)) {
      return;
    }

    const result = await openActionDialog({
      title: "重置交接确认？",
      description: "已提交的交接确认会被清除，需要重新获取确认码并完成双方确认。申请和聊天记录不会被删除。服务端只允许在冷却结束或确认码到期后重置，每申请最多 2 次。",
      reasonLabel: "重置原因（可选）",
      reasonRequired: false,
      ackText: "我理解重置后需要重新完成双方确认。",
      confirmLabel: "确认重置",
      danger: true
    });
    if (!result) {
      return;
    }

    const claimId = state.selectedClaimId;
    const epoch = state.epoch;
    const slot = `handover-reset:${String(claimId)}`;
    const body = { reason: result.reason || "" };

    await runWriteAction({
      slot,
      button: ui.resetHandoverButton,
      busyText: "重置中…",
      errorBox: ui.handoverActionError,
      action: async () => {
        const key = getWriteKey(slot, JSON.stringify(body));
        const payload = await requestJson(`${claimPath(claimId)}/handover/reset`, {
          method: "POST",
          auth: true,
          body,
          idempotencyKey: key
        });
        forgetWriteKey(slot);

        if (epoch !== state.epoch || String(state.selectedClaimId) !== String(claimId)) {
          return;
        }

        state.code = null;
        renderCodeState();
        ui.codeStatus.textContent = "";
        ui.handoverConfirmForm.reset();
        clearInlineError(ui.handoverFormError);
        const resetCount = isPlainObject(payload) && Number.isFinite(Number(payload.reset_count))
          ? Number(payload.reset_count)
          : null;
        const countText = resetCount !== null ? `（第 ${resetCount} 次）` : "";
        showNotice(`交接确认已重置${countText}。双方旧确认已清空，请重新获取确认码并完成双方确认。`, "success");
        await refreshClaimAfterMutation(claimId);
      },
      onError: (error) => {
        if (error.status === 410) {
          showNotice(formatError(error), "error", { sticky: true });
          void loadClaimDetail(claimId);
        }
      }
    });
  }

  async function disputeClaim() {
    if (!state.token || !state.claim || !isIdPresent(state.selectedClaimId)) {
      return;
    }
    if (getClaimStatus(state.claim) !== "APPROVED") {
      showNotice("只有已批准的申请才能发起争议冻结。", "warning", { sticky: true });
      return;
    }
    if (!ensureCooldown(ui.claimActionsMessage)) {
      return;
    }

    const result = await openActionDialog({
      title: "发起争议并冻结？",
      description: "争议会将申请转为只读：状态操作、匿名沟通与交接确认全部停止，历史消息仍可查看，并开放去身份导出。界面不提供撤销，请确认后再继续。",
      reasonLabel: "争议原因",
      reasonRequired: true,
      ackText: "我理解争议将冻结申请与匿名沟通，且无法在界面中撤销。",
      acknowledgeRequired: true,
      confirmLabel: "确认发起争议",
      danger: true
    });
    if (!result) {
      return;
    }

    const claimId = state.selectedClaimId;
    const epoch = state.epoch;
    const slot = `dispute:${String(claimId)}`;
    const body = { reason: result.reason };

    await runWriteAction({
      slot,
      button: ui.disputeButton,
      busyText: "发起中…",
      errorBox: null,
      action: async () => {
        const key = getWriteKey(slot, JSON.stringify(body));
        await requestJson(`${claimPath(claimId)}/dispute`, {
          method: "POST",
          auth: true,
          body,
          idempotencyKey: key
        });
        forgetWriteKey(slot);

        if (epoch !== state.epoch || String(state.selectedClaimId) !== String(claimId)) {
          return;
        }

        state.code = null;
        showNotice("争议已发起：申请已冻结为只读，匿名沟通和交接确认均已停止。历史消息仍可查看，可下载去身份导出。", "warning", { sticky: true });
        await refreshClaimAfterMutation(claimId);
      },
      onError: (error) => {
        if (error.status === 409) {
          showNotice(formatError(error), "error", { sticky: true });
          void loadClaimDetail(claimId);
        }
      }
    });
  }

  async function downloadDisputeExport() {
    if (!state.token || !state.claim || !isIdPresent(state.selectedClaimId)) {
      return;
    }
    if (getClaimStatus(state.claim) !== "DISPUTED") {
      showNotice("只有争议冻结的申请才能下载去身份导出。", "warning", { sticky: true });
      return;
    }
    if (isCoolingDown()) {
      showNotice(cooldownMessage(), "warning", { sticky: true });
      return;
    }

    const claimId = state.selectedClaimId;
    const epoch = state.epoch;
    setButtonBusy(ui.exportButton, true, "准备导出…");

    try {
      const response = await requestResponse(`${claimPath(claimId)}/dispute-export`, {
        auth: true,
        accept: "application/json, text/csv, text/plain, application/octet-stream"
      });
      if (epoch !== state.epoch || String(state.selectedClaimId) !== String(claimId)) {
        return;
      }

      const blob = await response.blob();
      if (!blob || blob.size === 0) {
        throw new ApiError(502, "EMPTY_EXPORT", "导出的文件为空。");
      }
      if (String(state.selectedClaimId) !== String(claimId)) {
        return;
      }

      const filename = exportFilename(response, claimId);
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = filename;
      link.hidden = true;
      link.rel = "noopener";
      document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 10000);

      showNotice("已开始下载去身份导出。文件不包含真实身份映射。", "success");
    } catch (error) {
      if (
        epoch !== state.epoch ||
        String(state.selectedClaimId) !== String(claimId) ||
        isAbortError(error)
      ) {
        return;
      }
      showNotice(`去身份导出失败：${formatError(error)}`, "error", { sticky: true });
    } finally {
      if (epoch === state.epoch && String(state.selectedClaimId) === String(claimId)) {
        setButtonBusy(ui.exportButton, false);
      }
    }
  }

  function exportFilename(response, claimId) {
    const disposition = response.headers.get("content-disposition") || "";
    const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
    const quoted = /filename="?([^";]+)"?/i.exec(disposition);
    let name = "";

    if (encoded && encoded[1]) {
      try {
        name = decodeURIComponent(encoded[1].trim());
      } catch (_error) {
        name = encoded[1].trim();
      }
    } else if (quoted && quoted[1]) {
      name = quoted[1].trim();
    }

    const contentType = (response.headers.get("content-type") || "").toLowerCase();
    const extension = contentType.includes("json")
      ? ".json"
      : contentType.includes("csv")
        ? ".csv"
        : contentType.includes("text/plain")
          ? ".txt"
          : ".json";

    const safeClaimId = String(claimId).replace(/[^a-zA-Z0-9_-]/g, "_").slice(0, 48);
    if (!name) {
      name = `dispute-export-${safeClaimId || "claim"}`;
    }

    name = name
      .replace(/[\\/:*?"<>|\u0000-\u001f]/g, "_")
      .replace(/^\.+/, "")
      .trim()
      .slice(0, 120);

    if (!name) {
      name = `dispute-export-${safeClaimId || "claim"}`;
    }
    if (!/\.[a-zA-Z0-9]{1,8}$/.test(name)) {
      name += extension;
    }

    return name;
  }

  /* ----------------------------------------------------------------------- */
  /* Dialog, cooldown, notices and shared UI helpers                         */
  /* ----------------------------------------------------------------------- */

  function openActionDialog(options) {
    if (!ui.actionDialog || typeof ui.actionDialog.showModal !== "function") {
      return Promise.resolve(false);
    }

    if (ui.actionDialog.open) {
      finishActionDialog(false);
    }

    const reasonVisible = Boolean(options.reasonLabel);
    const reasonRequired = options.reasonRequired !== undefined
      ? Boolean(options.reasonRequired)
      : reasonVisible;
    const acknowledgeRequired = Boolean(options.ackText);
    actionDialogReasonIsRequired = reasonVisible && reasonRequired;

    ui.actionDialogTitle.textContent = options.title || "确认操作";
    ui.actionDialogDescription.textContent = options.description || "";
    ui.actionDialogReasonWrap.hidden = !reasonVisible;
    ui.actionDialogReasonLabel.textContent = options.reasonLabel || "原因";
    ui.actionDialogReason.value = "";
    ui.actionDialogReason.required = actionDialogReasonIsRequired;
    ui.actionDialogReasonHint.textContent = options.reasonHint || "原因会对相关方可见，请勿填写真实身份信息。";
    ui.actionDialogAckWrap.hidden = !acknowledgeRequired;
    ui.actionDialogAck.checked = false;
    ui.actionDialogAck.required = acknowledgeRequired;
    ui.actionDialogAckText.textContent = options.ackText || "我理解此操作的后果。";
    ui.actionDialogError.hidden = true;
    ui.actionDialogError.textContent = "";
    ui.actionDialogConfirm.textContent = options.confirmLabel || "确认";
    ui.actionDialogConfirm.className = options.danger ? "button button-danger" : "button button-primary";

    return new Promise((resolve) => {
      dialogResolver = resolve;
      ui.actionDialog.showModal();

      window.requestAnimationFrame(() => {
        if (reasonVisible) {
          ui.actionDialogReason.focus();
        } else if (acknowledgeRequired) {
          ui.actionDialogAck.focus();
        } else {
          ui.actionDialogConfirm.focus();
        }
      });
    });
  }

  function handleActionDialogSubmit(event) {
    event.preventDefault();
    if (!dialogResolver) {
      return;
    }

    clearInlineError(ui.actionDialogError);
    const reasonVisible = !ui.actionDialogReasonWrap.hidden;
    const acknowledgeRequired = !ui.actionDialogAckWrap.hidden;
    const reason = ui.actionDialogReason.value.trim();

    if (reasonVisible && actionDialogReasonIsRequired && !reason) {
      showInlineError(ui.actionDialogError, "请填写原因。");
      ui.actionDialogReason.focus();
      return;
    }
    if (reason.length > MAX_REASON_LENGTH) {
      showInlineError(ui.actionDialogError, `原因不能超过 ${MAX_REASON_LENGTH} 个字符。`);
      ui.actionDialogReason.focus();
      return;
    }
    if (acknowledgeRequired && !ui.actionDialogAck.checked) {
      showInlineError(ui.actionDialogError, "请勾选确认框后再继续。");
      ui.actionDialogAck.focus();
      return;
    }

    finishActionDialog({
      reason,
      acknowledged: acknowledgeRequired ? ui.actionDialogAck.checked : false
    });
  }

  function finishActionDialog(result) {
    const resolve = dialogResolver;
    dialogResolver = null;
    if (ui.actionDialog && ui.actionDialog.open) {
      ui.actionDialog.close();
    }
    if (resolve) {
      resolve(result || false);
    }
  }

  function closeActionDialog() {
    const resolve = dialogResolver;
    dialogResolver = null;
    if (ui.actionDialog && ui.actionDialog.open) {
      ui.actionDialog.close();
    }
    if (resolve) {
      resolve(false);
    }
  }

  function startCooldown(seconds) {
    const duration = clampCooldown(seconds);
    const until = Date.now() + duration * 1000;
    if (until > state.cooldownUntil) {
      state.cooldownUntil = until;
    }

    ui.cooldownBanner.hidden = false;
    updateCooldownDisplay();
    if (cooldownTimer !== null) {
      window.clearInterval(cooldownTimer);
    }
    cooldownTimer = window.setInterval(updateCooldownDisplay, 500);
  }

  function updateCooldownDisplay() {
    const remainingMs = state.cooldownUntil - Date.now();
    if (remainingMs <= 0) {
      state.cooldownUntil = 0;
      ui.cooldownBanner.hidden = true;
      ui.cooldownText.textContent = "";
      if (cooldownTimer !== null) {
        window.clearInterval(cooldownTimer);
        cooldownTimer = null;
      }
      return;
    }

    const seconds = Math.ceil(remainingMs / 1000);
    ui.cooldownBanner.hidden = false;
    ui.cooldownText.textContent = `服务端返回访问频率限制，剩余约 ${seconds} 秒。此处仅显示本地倒计时，服务端限制仍然有效。`;
  }

  function clearLocalCooldown() {
    state.cooldownUntil = 0;
    if (cooldownTimer !== null) {
      window.clearInterval(cooldownTimer);
      cooldownTimer = null;
    }
    ui.cooldownBanner.hidden = true;
    ui.cooldownText.textContent = "";
    showNotice("已清除本地冷却倒计时显示，但不会绕过服务端限流。", "info");
  }

  function isCoolingDown() {
    return state.cooldownUntil > Date.now();
  }

  function cooldownMessage() {
    const seconds = Math.max(1, Math.ceil((state.cooldownUntil - Date.now()) / 1000));
    return `请求冷却中，请等待约 ${seconds} 秒后再试。`;
  }

  function ensureCooldown(errorBox) {
    if (!isCoolingDown()) {
      return true;
    }
    showInlineError(errorBox, cooldownMessage());
    return false;
  }

  async function runWriteAction(options) {
    const slot = options.slot;
    if (state.inFlight.has(slot)) {
      return false;
    }
    if (isCoolingDown()) {
      showInlineError(options.errorBox, cooldownMessage());
      return false;
    }

    const epoch = state.epoch;
    state.inFlight.add(slot);
    clearInlineError(options.errorBox);
    setButtonBusy(options.button, true, options.busyText || "处理中…");

    try {
      await options.action();
      return true;
    } catch (error) {
      if (epoch !== state.epoch || isAbortError(error)) {
        return false;
      }
      if (typeof options.onError === "function") {
        try {
          options.onError(error);
        } catch (_callbackError) {
          // A secondary refresh must not hide the original error.
        }
      }
      if (options.errorBox) {
        showInlineError(options.errorBox, formatError(error));
      } else {
        showNotice(formatError(error), "error", { sticky: true });
      }
      return false;
    } finally {
      state.inFlight.delete(slot);
      setButtonBusy(options.button, false);
    }
  }

  function showNotice(message, kind = "info", options = {}) {
    if (!ui.noticeRegion) {
      return;
    }

    if (noticeTimer !== null) {
      window.clearTimeout(noticeTimer);
      noticeTimer = null;
    }

    const box = make("div", {
      className: `notice notice-${kind}`,
      attrs: { role: kind === "error" ? "alert" : "status" }
    });
    const text = make("p", { className: "notice-message", text: message });
    const close = make("button", {
      className: "notice-close",
      text: "关闭",
      attrs: { type: "button", "aria-label": "关闭提示" }
    });
    close.addEventListener("click", () => {
      if (noticeTimer !== null) {
        window.clearTimeout(noticeTimer);
        noticeTimer = null;
      }
      box.remove();
    });
    box.append(text, close);
    ui.noticeRegion.replaceChildren(box);

    const sticky = options.sticky === true || kind === "error" || kind === "warning";
    if (!sticky) {
      noticeTimer = window.setTimeout(() => {
        if (box.isConnected) {
          box.remove();
        }
        noticeTimer = null;
      }, 7000);
    }
  }

  function clearNotice() {
    if (noticeTimer !== null) {
      window.clearTimeout(noticeTimer);
      noticeTimer = null;
    }
    if (ui.noticeRegion) {
      ui.noticeRegion.replaceChildren();
    }
  }

  function showInlineError(element, message) {
    if (!element) {
      return;
    }
    element.textContent = message;
    element.hidden = false;
  }

  function clearInlineError(element) {
    if (!element) {
      return;
    }
    element.textContent = "";
    element.hidden = true;
  }

  function showState(container, options) {
    if (!container) {
      return;
    }

    const kind = options.kind || "info";
    const box = make("div", {
      className: `state state-${kind}`,
      attrs: { role: kind === "error" ? "alert" : "status" }
    });

    if (options.title) {
      box.append(make("strong", { className: "state-title", text: options.title }));
    }
    if (options.message) {
      box.append(make("p", { className: "state-message", text: options.message }));
    }
    if (typeof options.retry === "function") {
      const retry = make("button", {
        className: "button button-small",
        text: options.retryLabel || "重试",
        attrs: { type: "button" }
      });
      retry.addEventListener("click", options.retry);
      box.append(retry);
    }

    container.setAttribute("aria-busy", kind === "loading" ? "true" : "false");
    container.replaceChildren(box);
  }

  /* ----------------------------------------------------------------------- */
  /* Rendering and formatting helpers                                        */
  /* ----------------------------------------------------------------------- */

  function make(tag, options = {}, children = []) {
    const node = document.createElement(tag);
    if (options.className) {
      node.className = options.className;
    }
    if (options.text !== undefined && options.text !== null) {
      node.textContent = String(options.text);
    }
    if (options.attrs) {
      Object.entries(options.attrs).forEach(([key, value]) => {
        if (value === false || value === null || value === undefined) {
          return;
        }
        node.setAttribute(key, value === true ? "" : String(value));
      });
    }
    for (const child of children) {
      if (child) {
        node.append(child);
      }
    }
    return node;
  }

  function appendMeta(dl, label, value) {
    dl.append(make("dt", { text: label }), make("dd", { text: value }));
  }

  function safeText(value) {
    if (value === null || value === undefined) {
      return "";
    }
    if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
      return String(value);
    }
    return "";
  }

  function isPlainObject(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function isIdPresent(value) {
    return value !== null && value !== undefined && String(value).trim() !== "";
  }

  function formatDateTime(value) {
    if (value === null || value === undefined || value === "") {
      return "未提供";
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return "时间格式无法识别";
    }
    return dateTimeFormatter.format(date);
  }

  function formatScore(value) {
    if (typeof value === "number" && Number.isFinite(value)) {
      return String(value);
    }
    if (typeof value === "string") {
      return value.trim().slice(0, 40);
    }
    return "";
  }

  function formatListingMeta(item) {
    const parts = [];
    const category = safeText(item.category).trim();
    const location = safeText(item.location).trim();
    if (category) {
      parts.push(category);
    }
    if (item.occurred_at) {
      parts.push(formatDateTime(item.occurred_at));
    }
    if (location) {
      parts.push(location);
    }
    return parts.length > 0 ? parts.join(" · ") : "未提供分类、时间与地点";
  }

  function normalizeRole(value) {
    const raw = safeText(value).trim().toLowerCase();
    if (!raw) {
      return "unknown";
    }
    if (["claimant", "claimer", "applicant", "applicant_side", "claimant_side", "申请人"].some((entry) => raw === entry || raw.includes(entry))) {
      return "claimant";
    }
    if (["finder", "owner", "holder", "publisher", "founder", "拾获者", "发布者"].some((entry) => raw === entry || raw.includes(entry))) {
      return "finder";
    }
    return "unknown";
  }

  function getClaimRole(claim) {
    const candidates = [
      claim.my_role,
      claim.role,
      claim.viewer_role,
      claim.current_role,
      claim.party_role,
      isPlainObject(claim.viewer) ? claim.viewer.role : ""
    ];
    for (const candidate of candidates) {
      const role = normalizeRole(candidate);
      if (role !== "unknown") {
        return role;
      }
    }

    if (claim.is_claimant === true || claim.viewer_is_claimant === true) {
      return "claimant";
    }
    if (claim.is_finder === true || claim.viewer_is_finder === true) {
      return "finder";
    }
    return "unknown";
  }

  function roleLabel(role) {
    return role === "claimant" ? "申请人" : role === "finder" ? "拾获者" : "角色未确认";
  }

  function getClaimStatus(claim) {
    return safeText(claim && claim.status).trim().toUpperCase();
  }

  function displayStatus(status) {
    const raw = safeText(status).trim();
    if (!raw) {
      return "状态未知";
    }
    const key = raw.toUpperCase();
    return STATUS_LABELS[key] || raw.slice(0, 40);
  }

  function statusTone(status) {
    const key = safeText(status).trim().toUpperCase();
    return STATUS_TONES[key] || "unknown";
  }

  function statusBadge(status) {
    const tone = statusTone(status);
    const classes = tone === "unknown" ? "badge" : `badge status-${tone}`;
    return make("span", {
      className: classes,
      text: displayStatus(status)
    });
  }

  function listingStatusBadge(item) {
    const status = safeText(item && item.status).trim().toLowerCase();
    const isFound = !item || !item.kind || item.kind === "found";
    let label = LISTING_STATUS_LABELS[status] || (status ? status.slice(0, 30) : "状态未知");
    let tone = status === "claimed" ? "claimed" : status === "published" ? "published" : "unknown";

    if (isFound && item && item.claimable === true) {
      label = "可认领";
      tone = "claimable";
    } else if (isFound && item && item.claimable === false && status !== "claimed") {
      label = "不可认领";
      tone = "unclaimable";
    }

    return make("span", {
      className: `badge status-${tone}`,
      text: label
    });
  }

  function roleBadge(role) {
    return make("span", {
      className: "badge role-badge",
      text: `本人角色：${roleLabel(role)}`
    });
  }

  function permissionFor(claim, action) {
    const aliases = {
      approve: ["approve", "approve_claim", "can_approve"],
      reject: ["reject", "reject_claim", "can_reject"],
      withdraw: ["withdraw", "withdraw_claim", "can_withdraw"],
      send_message: ["send_message", "message", "can_message", "can_send_message"],
      dispute: ["dispute", "create_dispute", "can_dispute"]
    }[action] || [action];

    const booleanKeys = {
      approve: ["can_approve"],
      reject: ["can_reject"],
      withdraw: ["can_withdraw"],
      send_message: ["can_send_message", "can_message"],
      dispute: ["can_dispute"]
    }[action] || [];

    for (const key of booleanKeys) {
      if (typeof claim[key] === "boolean") {
        return claim[key];
      }
    }

    const containers = [
      claim.permissions,
      claim.allowed_actions,
      isPlainObject(claim.permissions) ? claim.permissions.actions : null
    ].filter((entry) => Array.isArray(entry) || isPlainObject(entry));

    let sawCollection = false;
    for (const container of containers) {
      if (Array.isArray(container)) {
        sawCollection = true;
        const values = container.map((entry) => safeText(entry).trim().toLowerCase());
        if (values.includes("*") || values.some((value) => aliases.includes(value))) {
          return true;
        }
        continue;
      }

      for (const alias of aliases) {
        if (typeof container[alias] === "boolean") {
          sawCollection = true;
          if (container[alias]) {
            return true;
          }
        }
      }
    }

    if (sawCollection) {
      // A permission collection exists but does not grant this action.
      return false;
    }
    return null;
  }

  function getHandoverState(claim) {
    const sources = [
      isPlainObject(claim.handover) ? claim.handover : null,
      isPlainObject(claim.handover_state) ? claim.handover_state : null,
      claim
    ].filter(Boolean);

    const findBoolean = (keys) => {
      for (const source of sources) {
        for (const key of keys) {
          if (typeof source[key] === "boolean") {
            return source[key];
          }
        }
      }
      return null;
    };

    let mine = findBoolean([
      "my_confirmed",
      "self_confirmed",
      "confirmed_by_me",
      "mine_confirmed"
    ]);
    let other = findBoolean([
      "confirmed_by_counterpart",
      "counterparty_confirmed",
      "other_confirmed",
      "confirmed_by_other",
      "other_side_confirmed"
    ]);

    const role = getClaimRole(claim);
    if (role === "claimant") {
      if (mine === null) {
        mine = findBoolean(["claimant_confirmed"]);
      }
      if (other === null) {
        other = findBoolean(["finder_confirmed"]);
      }
    } else if (role === "finder") {
      if (mine === null) {
        mine = findBoolean(["finder_confirmed"]);
      }
      if (other === null) {
        other = findBoolean(["claimant_confirmed"]);
      }
    }

    return { mine, other };
  }

  function clearListingTitleCache() {
    listingTitleCache.clear();
    listingTitleRequests.clear();
  }

  function rememberListingTitle(itemId, title) {
    const key = safeText(itemId).trim();
    const safeTitle = safeText(title).trim();
    if (!key || !safeTitle) {
      return;
    }

    if (listingTitleCache.has(key)) {
      listingTitleCache.delete(key);
    }
    listingTitleCache.set(key, safeTitle);
    while (listingTitleCache.size > LISTING_TITLE_CACHE_LIMIT) {
      const oldestKey = listingTitleCache.keys().next().value;
      if (oldestKey === undefined) {
        break;
      }
      listingTitleCache.delete(oldestKey);
    }
  }

  function fetchListingTitle(itemId) {
    const key = safeText(itemId).trim();
    if (!key || !state.token) {
      return Promise.resolve("");
    }
    if (listingTitleCache.has(key)) {
      return Promise.resolve(listingTitleCache.get(key));
    }
    if (listingTitleRequests.has(key)) {
      return listingTitleRequests.get(key);
    }

    const epoch = state.epoch;
    let requestPromise = null;
    requestPromise = (async () => {
      try {
        const payload = await requestJson(`/listings/${encodeURIComponent(key)}`, { auth: true });
        if (epoch !== state.epoch || !state.token) {
          return "";
        }
        const item = extractObject(payload, ["listing", "item"]);
        if (!isPlainObject(item) || !isIdPresent(item.id) || String(item.id) !== key) {
          return "";
        }
        const title = safeText(item.title).trim();
        if (!title) {
          return "";
        }
        rememberListingTitle(key, title);
        return title;
      } catch (_error) {
        return "";
      } finally {
        if (listingTitleRequests.get(key) === requestPromise) {
          listingTitleRequests.delete(key);
        }
      }
    })();

    listingTitleRequests.set(key, requestPromise);
    return requestPromise;
  }

  async function prefetchClaimListingTitles(claims, epoch) {
    if (!state.token) {
      return;
    }

    const itemIds = [];
    const seen = new Set();
    for (const claim of claims) {
      if (!isPlainObject(claim)) {
        continue;
      }
      const nested = isPlainObject(claim.item)
        ? claim.item
        : isPlainObject(claim.listing)
          ? claim.listing
          : isPlainObject(claim.found_item)
            ? claim.found_item
            : null;
      const itemId = claim.item_id || (nested && nested.id);
      if (!isIdPresent(itemId)) {
        continue;
      }
      const key = String(itemId);
      if (seen.has(key) || lookupListingTitle(key)) {
        continue;
      }
      seen.add(key);
      itemIds.push(key);
    }

    if (itemIds.length === 0) {
      return;
    }

    let cursor = 0;
    const workerCount = Math.min(LISTING_TITLE_FETCH_CONCURRENCY, itemIds.length);
    const workers = Array.from({ length: workerCount }, async () => {
      while (cursor < itemIds.length) {
        if (epoch !== state.epoch) {
          return;
        }
        const itemId = itemIds[cursor];
        cursor += 1;
        await fetchListingTitle(itemId);
      }
    });
    await Promise.all(workers);
  }

  function claimTitle(claim) {
    const nested = isPlainObject(claim.item)
      ? claim.item
      : isPlainObject(claim.listing)
        ? claim.listing
        : isPlainObject(claim.found_item)
          ? claim.found_item
          : null;

    const candidates = [
      nested && nested.title,
      claim.item_title,
      claim.listing_title,
      claim.found_title,
      claim.title
    ];

    for (const value of candidates) {
      const title = safeText(value).trim();
      if (title) {
        return title;
      }
    }

    const itemId = claim.item_id || (nested && nested.id);
    const cachedTitle = lookupListingTitle(itemId);
    if (cachedTitle) {
      return cachedTitle;
    }
    return isIdPresent(itemId) ? `物品 ${safeText(itemId).trim()}` : "未命名物品";
  }

  function lookupListingTitle(itemId) {
    if (!isIdPresent(itemId)) {
      return "";
    }

    const cacheKey = String(itemId);
    if (listingTitleCache.has(cacheKey)) {
      return listingTitleCache.get(cacheKey);
    }

    const collections = [state.found.items, state.lost.items];
    for (const collection of collections) {
      for (const item of collection) {
        if (isPlainObject(item) && isIdPresent(item.id) && String(item.id) === String(itemId)) {
          return safeText(item.title).trim();
        }
      }
    }

    for (const candidate of state.matches.items) {
      const nested = isPlainObject(candidate.item)
        ? candidate.item
        : isPlainObject(candidate.found_item)
          ? candidate.found_item
          : null;
      if (nested && isIdPresent(nested.id) && String(nested.id) === String(itemId)) {
        return safeText(nested.title).trim();
      }
      if (matchFoundId(candidate) !== null && String(matchFoundId(candidate)) === String(itemId)) {
        return safeText(candidate.title || candidate.found_title).trim();
      }
    }

    if (isPlainObject(state.found.detail) && isIdPresent(state.found.detail.id) && String(state.found.detail.id) === String(itemId)) {
      return safeText(state.found.detail.title).trim();
    }

    return "";
  }

  function extractObject(payload, preferredKeys = []) {
    let node = payload;
    for (let depth = 0; depth < 4; depth += 1) {
      if (!isPlainObject(node)) {
        break;
      }

      let next = null;
      for (const key of preferredKeys) {
        if (isPlainObject(node[key])) {
          next = node[key];
          break;
        }
      }
      if (!next && isPlainObject(node.data)) {
        next = node.data;
      }
      if (!next || next === node) {
        break;
      }
      node = next;
    }
    return node;
  }

  function extractList(payload, preferredKeys = []) {
    let node = payload;

    if (isPlainObject(payload) && Object.prototype.hasOwnProperty.call(payload, "data")) {
      if (Array.isArray(payload.data) || isPlainObject(payload.data)) {
        node = payload.data;
      }
    }

    let items = null;
    if (Array.isArray(node)) {
      items = node;
    } else if (isPlainObject(node)) {
      if (isPlainObject(node.data)) {
        for (const key of preferredKeys) {
          if (Array.isArray(node.data[key])) {
            items = node.data[key];
            break;
          }
        }
        if (!items && Array.isArray(node.data.items)) {
          items = node.data.items;
        }
      }
      if (!items) {
        for (const key of preferredKeys) {
          if (Array.isArray(node[key])) {
            items = node[key];
            break;
          }
        }
      }
      if (!items && Array.isArray(node.items)) {
        items = node.items;
      }
    }

    const metaNode = isPlainObject(node) ? node : {};
    const total = firstFiniteInteger([
      metaNode.total,
      metaNode.total_count,
      metaNode.count,
      isPlainObject(payload) ? payload.total : null,
      isPlainObject(payload) ? payload.total_count : null
    ]);
    const ruleVersion = safeText(
      metaNode.rule_version ||
      (isPlainObject(payload) && payload.rule_version) ||
      (Array.isArray(items) && items.length > 0 && isPlainObject(items[0]) ? items[0].rule_version : "")
    ).trim();

    return {
      recognized: Array.isArray(items),
      items: Array.isArray(items) ? items : [],
      total,
      ruleVersion
    };
  }

  function firstFiniteInteger(values) {
    for (const value of values) {
      if (value === null || value === undefined || value === "") {
        continue;
      }
      const number = Number(value);
      if (Number.isFinite(number) && number >= 0) {
        return Math.floor(number);
      }
    }
    return null;
  }

  function formatError(error) {
    if (!(error instanceof ApiError)) {
      return "发生未知错误，请刷新后重试。";
    }
    if (error.aborted) {
      return "请求已取消。";
    }

    let text = safeText(error.message).trim() || "请求失败。";
    if (text.length > 500) {
      text = `${text.slice(0, 500)}…`;
    }

    const details = [];
    if (error.field) {
      const fieldName = FIELD_LABELS[error.field] || safeText(error.field);
      details.push(`字段：${fieldName}`);
    }
    if (error.code) {
      details.push(`错误码：${error.code}`);
    }
    if (error.status === 429 && error.retryAfterSeconds) {
      details.push(`约 ${error.retryAfterSeconds} 秒后可重试`);
    }
    if (details.length > 0) {
      return `${text}（${details.join("；")}）`;
    }
    return text;
  }

  function isAbortError(error) {
    return Boolean(error && (error.aborted || error.name === "AbortError" || error.code === "ABORTED"));
  }

  function setButtonBusy(button, busy, busyText = "处理中…") {
    if (!button) {
      return;
    }

    if (busy) {
      if (button.dataset.busy === "true") {
        return;
      }
      if (button.dataset.idleLabel === undefined) {
        button.dataset.idleLabel = button.textContent;
      }
      button.dataset.busy = "true";
      button.disabled = true;
      button.setAttribute("aria-busy", "true");
      button.textContent = busyText;
      return;
    }

    if (button.dataset.idleLabel !== undefined) {
      button.textContent = button.dataset.idleLabel;
    }
    delete button.dataset.busy;
    button.disabled = false;
    button.setAttribute("aria-busy", "false");
  }

  function setButtonIdleLabel(button, label) {
    if (!button) {
      return;
    }
    button.dataset.idleLabel = label;
    if (button.dataset.busy !== "true") {
      button.textContent = label;
    }
  }

  function getWriteKey(slot, signature) {
    const existing = idempotencyKeys.get(slot);
    if (existing && existing.signature === signature) {
      return existing.key;
    }

    const key = createIdempotencyKey();
    idempotencyKeys.set(slot, { key, signature });
    return key;
  }

  function forgetWriteKey(slot) {
    idempotencyKeys.delete(slot);
  }

  function createIdempotencyKey() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return window.crypto.randomUUID();
    }
    if (window.crypto && typeof window.crypto.getRandomValues === "function") {
      const bytes = new Uint8Array(16);
      window.crypto.getRandomValues(bytes);
      return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
    }
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`;
  }

  function scrollToElement(element) {
    if (!element) {
      return;
    }
    const reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    element.scrollIntoView({
      behavior: reduceMotion ? "auto" : "smooth",
      block: "start"
    });
  }
})();
