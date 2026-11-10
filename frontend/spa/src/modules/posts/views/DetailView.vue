<script setup>
import { deletedPublisherMessage } from '../../claims/constants.js'
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import NoticeBar from '../components/NoticeBar.vue'
import PostImage from '../components/PostImage.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { describeError } from '../api/http.js'
import { getPost, resolvePost, restorePost, withdrawPost } from '../api/posts.js'
import { hasToken } from '../api/session.js'
import { session } from '../../../shared/session.js'
import { LIMITS, POST_TYPE_TEXT, STATUS_TEXT } from '../config.js'
import { charLength, formatBeijingDateTime } from '../utils/format.js'
import { isImageReadable } from '../utils/image.js'
import { validateResolveNote } from '../utils/validate.js'

/*
 * 详情（契约 §5.1 GET /posts/{id}，PostDetail 结构见 §3.9）。
 * 撤回信息只有发布者能读到；其他人会拿到 404，页面按“不存在或不可见”处理。
 * 状态操作 withdraw / restore / resolve 由发布者执行，409 时提示当前状态（§5.4）。
 */
const route = useRoute()

const post = ref(null)
const loading = ref(true)
const error = ref(null)

const actionLoading = ref('')
const actionError = ref('')
const actionNotice = ref('')

const resolveOpen = ref(false)
const resolveNote = ref('')
const resolveError = ref('')

const postId = computed(() => String(route.params.id || ''))

const canManage = computed(() => Boolean(session.user) && post.value?.publisher?.id === session.user.id)

const typeLabel = computed(() => POST_TYPE_TEXT[post.value?.post_type] || post.value?.post_type || '')
const statusLabel = computed(() => STATUS_TEXT[post.value?.status] || post.value?.status || '')
const isWithdrawn = computed(() => post.value?.status === 'withdrawn')
const canEdit = computed(
  () => canManage.value && ['open', 'withdrawn'].includes(post.value?.status),
)
const canWithdraw = computed(() => canManage.value && post.value?.status === 'open')
const canRestore = computed(() => canManage.value && post.value?.status === 'withdrawn')
const canResolve = computed(
  () => canManage.value && post.value?.post_type === 'lost' && post.value?.status === 'open',
)

const images = computed(() => (Array.isArray(post.value?.images) ? post.value.images : []))
const readonlyImages = computed(() =>
  images.value.map((image) => ({
    image,
    readable: isImageReadable(image, {
      postStatus: post.value?.status,
      isOwner: canManage.value,
    }),
  })),
)

const publisherVerified = computed(() => post.value?.publisher?.is_campus_verified === true)
const publisherDemo = computed(() => post.value?.publisher?.verification_mode === 'demo')
const publisherDeleted = computed(() => post.value?.publisher?.is_deleted === true)

const resolveLength = computed(() => charLength(resolveNote.value))

const pageHeading = computed(() => (post.value ? post.value.title : '信息详情'))

async function load() {
  loading.value = true
  error.value = null
  try {
    post.value = await getPost(postId.value)
  } catch (err) {
    error.value = err
    post.value = null
  } finally {
    loading.value = false
  }
}

function resetActionMessages() {
  actionError.value = ''
  actionNotice.value = ''
}

async function runAction(kind) {
  if (actionLoading.value) return
  resetActionMessages()

  if (kind === 'resolve') {
    resolveError.value = ''
    const localErrors = validateResolveNote(resolveNote.value)
    if (Object.keys(localErrors).length) {
      resolveError.value = localErrors.resolve_note?.[0] || '请检查办结说明'
      return
    }
  }

  actionLoading.value = kind
  try {
    let data = null
    if (kind === 'withdraw') data = await withdrawPost(postId.value)
    else if (kind === 'restore') data = await restorePost(postId.value)
    else if (kind === 'resolve') data = await resolvePost(postId.value, resolveNote.value.trim())

    if (data && typeof data === 'object') post.value = data
    actionNotice.value =
      kind === 'withdraw'
        ? '已撤回。该信息已从公开列表与详情中隐藏，相关待处理认领由 C 关闭。'
        : kind === 'restore'
          ? '已恢复为“进行中”，重新出现在公开列表中；历史认领申请不会恢复。'
          : '已标记为“已完成”（自行找回）。'
    resolveOpen.value = false
    resolveNote.value = ''
  } catch (err) {
    if (err?.status === 409) {
      // 先刷新，再按服务端返回的最新状态提示（契约 5.4：状态已变化时返回 409）
      await load()
      const current = STATUS_TEXT[post.value?.status] || post.value?.status || '未知状态'
      actionError.value = `操作与当前状态冲突：${describeError(err)}。这条信息现在是「${current}」。`
    } else if (err?.status === 403) {
      actionError.value = `你没有执行该操作的权限（${describeError(err)}）。只有发布者本人可以撤回、恢复或办结。`
    } else if (err?.status === 401) {
      actionError.value = `登录已失效，请先在 A 的登录页重新登录（${describeError(err)}）。`
    } else {
      actionError.value = describeError(err)
    }
  } finally {
    actionLoading.value = ''
  }
}

function openResolve() {
  resetActionMessages()
  resolveError.value = ''
  resolveOpen.value = true
}

onMounted(load)
</script>

<template>
  <div class="view">
    <nav class="breadcrumb" aria-label="位置">
      <RouterLink :to="{ name: 'post-list' }">← 返回信息列表</RouterLink>
      <span aria-hidden="true">/</span>
      <span>{{ typeLabel ? `${typeLabel}信息` : '信息详情' }}</span>
    </nav>

    <div v-if="loading" class="detail-skeleton" aria-busy="true">
      <div class="detail-skeleton__title"></div>
      <div class="detail-skeleton__media"></div>
      <div class="detail-skeleton__line"></div>
      <div class="detail-skeleton__line skeleton-card__line--short"></div>
    </div>

    <NoticeBar
      v-else-if="error"
      tone="error"
      :title="error.status === 404 ? '信息不存在或不可见' : '加载详情失败'"
      :message="
        error.status === 404
          ? '这条信息可能已被撤回、已删除，或者你没有查看权限（契约：撤回信息仅发布者可见）。'
          : describeError(error)
      "
      :hint="error.status === 404 ? '如果你就是发布者，请从 A 的“我的发布”进入，并确认登录状态。' : ''"
    >
      <template #actions>
        <button v-if="error.status !== 404" type="button" class="btn btn--ghost btn--sm" @click="load">
          重试
        </button>
      </template>
    </NoticeBar>

    <template v-else-if="post">
      <NoticeBar
        v-if="isWithdrawn"
        tone="warn"
        title="此信息已撤回"
        message="撤回后该信息不再出现在公开列表与公开详情中，其他人访问会得到 404；所有图片对其他用户也不可读。"
        :hint="
          canManage
            ? '你可以在这里恢复信息，或继续编辑后恢复。'
            : '只有发布者本人能看到这条已撤回信息。'
        "
      />

      <header class="detail-head">
        <div class="detail-head__top">
          <span class="type-chip" :class="`type-chip--${post.post_type}`">{{ typeLabel }}</span>
          <StatusBadge :status="post.status" />
          <span v-if="post.category?.name" class="chip">{{ post.category.name }}</span>
          <span v-if="!isWithdrawn && post.status === 'completed'" class="chip chip--muted">
            已完成，不再参与默认匹配
          </span>
        </div>
        <h1 class="detail-title">{{ pageHeading }}</h1>
        <p class="detail-meta">
          <span>发布者：{{ post.publisher?.nickname || '匿名用户' }}</span>
          <span v-if="publisherVerified" class="badge badge--verified">
            {{ publisherDemo ? '演示认证' : '校园已认证' }}
          </span>
          <span v-else-if="!publisherDeleted" class="badge">未认证校园身份</span>
          <span class="detail-meta__sep" aria-hidden="true">·</span>
          <span>发布 {{ formatBeijingDateTime(post.created_at) }}</span>
          <span class="detail-meta__sep" aria-hidden="true">·</span>
          <span>更新 {{ formatBeijingDateTime(post.updated_at) }}</span>
        </p>
      </header>

      <div v-if="post.status === 'open'" class="manage-actions">
        <p v-if="publisherDeleted" class="muted">{{ deletedPublisherMessage }}</p>
        <RouterLink
          v-else-if="canManage"
          class="btn btn--primary"
          :to="{ name: 'post-matches', params: { id: post.id } }"
        >查找匹配</RouterLink>
        <RouterLink
          v-else
          class="btn btn--primary"
          :to="{ path: '/claims/new', query: { post_id: post.id } }"
        >申请认领</RouterLink>
      </div>

      <div class="detail-layout">
        <div class="detail-main">
          <section class="card" aria-labelledby="detail-images-title">
            <h2 id="detail-images-title" class="card__title">
              图片（{{ images.length }}）
              <span v-if="!hasToken()" class="card__title-hint">未登录：仅登录可见的图片显示替代文字</span>
            </h2>
            <ul v-if="images.length" class="gallery">
              <li v-for="entry in readonlyImages" :key="entry.image.id" class="gallery__item">
                <PostImage
                  :image="entry.image"
                  :readable="entry.readable"
                  :requires-auth="isWithdrawn"
                  :post-status="post.status"
                  variant="hero"
                />
              </li>
            </ul>
            <p v-else class="card__empty">这条信息没有上传图片。</p>
          </section>

          <section class="card" aria-labelledby="detail-desc-title">
            <h2 id="detail-desc-title" class="card__title">物品描述</h2>
            <p class="detail-description">{{ post.description }}</p>
            <p class="detail-privacy">
              描述为纯文本；请不要在公开信息中填写完整证件号码、家庭住址或认领核验答案。
            </p>
          </section>

          <section v-if="post.post_type === 'found' && post.handover_note" class="card">
            <h2 class="card__title">保管 / 交接说明</h2>
            <p class="detail-description">{{ post.handover_note }}</p>
          </section>

          <section v-if="canManage" class="card card--manage" aria-labelledby="detail-manage-title">
            <h2 id="detail-manage-title" class="card__title">
              发布者操作
              <span class="badge badge--ok">你是发布者</span>
            </h2>
            <p class="card__hint">
              状态由服务端校验：重复执行已达到目标状态的操作会返回当前对象；状态已变化时返回 409。
            </p>

            <NoticeBar v-if="actionNotice" tone="success" :message="actionNotice" />
            <NoticeBar v-if="actionError" tone="error" title="操作失败" :message="actionError" />

            <div class="manage-actions">
              <RouterLink
                v-if="canEdit"
                class="btn btn--primary btn--sm"
                :to="{ name: 'post-edit', params: { id: post.id } }"
              >
                编辑信息
              </RouterLink>
              <button
                v-if="canWithdraw"
                type="button"
                class="btn btn--outline btn--sm"
                :disabled="!!actionLoading"
                @click="runAction('withdraw')"
              >
                {{ actionLoading === 'withdraw' ? '处理中…' : '撤回信息' }}
              </button>
              <button
                v-if="canRestore"
                type="button"
                class="btn btn--outline btn--sm"
                :disabled="!!actionLoading"
                @click="runAction('restore')"
              >
                {{ actionLoading === 'restore' ? '处理中…' : '恢复信息' }}
              </button>
              <button
                v-if="canResolve"
                type="button"
                class="btn btn--outline btn--sm"
                :disabled="!!actionLoading"
                @click="openResolve"
              >
                我已通过其他方式找回（办结）
              </button>
            </div>

            <div v-if="resolveOpen" class="resolve-form">
              <label class="field" for="resolve-note">
                <span class="field__label">
                  办结说明（必填，{{ LIMITS.resolve_note.min }}～{{ LIMITS.resolve_note.max }} 字）
                </span>
                <textarea
                  id="resolve-note"
                  v-model="resolveNote"
                  class="input resolve-form__textarea"
                  rows="3"
                  :maxlength="LIMITS.resolve_note.max"
                  placeholder="例如：在保卫处认领到了同款水杯，确认是本人物品。"
                ></textarea>
                <span class="field__counter" :class="{ 'is-over': resolveLength > LIMITS.resolve_note.max }">
                  {{ resolveLength }} / {{ LIMITS.resolve_note.max }}
                </span>
              </label>
              <p v-if="resolveError" class="field__error">{{ resolveError }}</p>
              <div class="resolve-form__actions">
                <button
                  type="button"
                  class="btn btn--primary btn--sm"
                  :disabled="!!actionLoading"
                  @click="runAction('resolve')"
                >
                  {{ actionLoading === 'resolve' ? '提交中…' : '确认办结' }}
                </button>
                <button
                  type="button"
                  class="btn btn--ghost btn--sm"
                  :disabled="!!actionLoading"
                  @click="resolveOpen = false"
                >
                  取消
                </button>
              </div>
              <p class="card__hint">
                办结只用于失物信息“自己找回了”，招领信息不能通过这个操作绕过双方确认。
              </p>
            </div>
          </section>
        </div>

        <aside class="detail-side">
          <section class="card">
            <h2 class="card__title">信息属性</h2>
            <dl class="attr-list">
              <div class="attr">
                <dt>信息 ID</dt>
                <dd>{{ post.id }}</dd>
              </div>
              <div class="attr">
                <dt>类型</dt>
                <dd>{{ typeLabel }}</dd>
              </div>
              <div class="attr">
                <dt>状态</dt>
                <dd>{{ statusLabel }}</dd>
              </div>
              <div class="attr">
                <dt>类别</dt>
                <dd>{{ post.category?.name || '—' }}</dd>
              </div>
              <div class="attr">
                <dt>校区</dt>
                <dd>{{ post.campus?.name || '—' }}</dd>
              </div>
              <div class="attr">
                <dt>地点</dt>
                <dd>{{ post.location?.name || '—' }}</dd>
              </div>
              <div class="attr">
                <dt>详细地点</dt>
                <dd>{{ post.location_detail || '—' }}</dd>
              </div>
              <div class="attr">
                <dt>发生时间</dt>
                <dd>{{ formatBeijingDateTime(post.occurred_at) }}</dd>
              </div>
              <div class="attr">
                <dt>完成时间</dt>
                <dd>{{ post.completed_at ? formatBeijingDateTime(post.completed_at) : '—' }}</dd>
              </div>
            </dl>
            <p class="card__hint">
              时间统一按北京时间显示（接口返回 UTC，例如 {{ post.occurred_at }}）。
            </p>
          </section>

          <section class="card">
            <h2 class="card__title">发布者</h2>
            <p class="publisher-line">
              <strong>{{ post.publisher?.nickname || '匿名用户' }}</strong>
              <span v-if="publisherVerified" class="badge badge--verified">
                {{ publisherDemo ? '演示认证' : '校园已认证' }}
              </span>
              <span v-else class="badge">未认证</span>
            </p>
            <p class="card__hint">
              第一版只公开昵称与认证状态，不公开账号、学号、真实姓名或手机号；联系通过认领申请内的站内消息进行（归 C）。
            </p>
            <p v-if="publisherDemo" class="card__hint">
              “演示认证”来自第一版的预置测试校园身份，不是真实校园认证结果。
            </p>
          </section>

          <section class="card">
            <h2 class="card__title">图片可见性</h2>
            <p class="card__hint">
              每张图的“未登录可见 / 仅登录用户可见”由发布人在上传时逐张选择；信息撤回后全部图片不可读（仅发布者可见）。
              当前页面上不可读的图片只会显示替代文字，不会请求原图。
            </p>
          </section>
        </aside>
      </div>
    </template>
  </div>
</template>

<style scoped>
.breadcrumb {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--muted);
}

.breadcrumb a {
  color: var(--primary-dark);
  text-decoration: none;
}

.breadcrumb a:hover {
  text-decoration: underline;
}

.detail-head {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.detail-head__top {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.type-chip {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--text);
}

.type-chip--lost {
  color: #b91c1c;
  border-color: #f3c6c6;
  background: #fff5f5;
}

.type-chip--found {
  color: #065f46;
  border-color: #bfe7d8;
  background: #f2fbf7;
}

.detail-title {
  margin: 0;
  font-size: clamp(21px, 3vw, 27px);
  line-height: 1.35;
  letter-spacing: -0.01em;
  word-break: break-word;
}

.detail-meta {
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 13px;
  color: var(--muted);
}

.detail-meta__sep {
  opacity: 0.5;
}

.detail-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 16px;
}

.detail-main,
.detail-side {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.gallery {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}

.gallery__item {
  min-width: 0;
}

.detail-description {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 15px;
  line-height: 1.85;
  color: var(--text);
}

.detail-privacy {
  margin: 12px 0 0;
  font-size: 12.5px;
  color: var(--muted);
}

.attr-list {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.attr {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 13px;
  border-bottom: 1px dashed var(--line);
  padding-bottom: 6px;
}

.attr:last-child {
  border-bottom: 0;
  padding-bottom: 0;
}

.attr dt {
  color: var(--muted);
  flex: none;
}

.attr dd {
  margin: 0;
  text-align: right;
  word-break: break-word;
  color: var(--text);
}

.publisher-line {
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 14px;
}

.card--manage {
  border-color: #c7dbfa;
  background: linear-gradient(180deg, #f8fbff, #ffffff 60%);
}

.manage-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 4px;
}

.resolve-form {
  margin-top: 8px;
  padding-top: 12px;
  border-top: 1px dashed var(--line-strong);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.resolve-form__textarea {
  resize: vertical;
  min-height: 78px;
}

.resolve-form__actions {
  display: flex;
  gap: 8px;
}

.detail-skeleton {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.detail-skeleton__title {
  height: 30px;
  width: 60%;
  border-radius: 8px;
  background: #eef1f7;
}

.detail-skeleton__media {
  height: 240px;
  border-radius: var(--radius);
  background: #eef1f7;
}

.detail-skeleton__line {
  height: 14px;
  border-radius: 6px;
  background: #eef1f7;
}

@media (min-width: 960px) {
  .detail-layout {
    grid-template-columns: minmax(0, 1fr) 320px;
    align-items: start;
  }

  .detail-side {
    position: sticky;
    top: 84px;
  }
}
</style>
