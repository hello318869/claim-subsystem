<script setup>
import { computed } from 'vue'
import PostImage from './PostImage.vue'
import StatusBadge from './StatusBadge.vue'
import { POST_TYPE_TEXT, STATUS_TEXT } from '../config.js'
import { formatBeijingDateTime } from '../utils/format.js'
import { isImageReadable } from '../utils/image.js'

const props = defineProps({
  post: { type: Object, required: true },
})

const typeLabel = computed(() => POST_TYPE_TEXT[props.post.post_type] || props.post.post_type)
const statusLabel = computed(() => STATUS_TEXT[props.post.status] || props.post.status || '未知状态')
const coverReadable = computed(() =>
  isImageReadable(props.post.cover_image, { postStatus: props.post.status }),
)

const placeText = computed(() => {
  const campus = props.post.campus?.name || ''
  const location = props.post.location?.name || ''
  const detail = props.post.location_detail || ''
  const base = [campus, location].filter(Boolean).join(' · ')
  return [base, detail].filter(Boolean).join(' · ') || '地点未填写'
})

const publisherName = computed(() => props.post.publisher?.nickname || '匿名用户')
const publisherVerified = computed(() => props.post.publisher?.is_campus_verified === true)
const publisherDemo = computed(() => props.post.publisher?.verification_mode === 'demo')
</script>

<template>
  <RouterLink
    class="post-card"
    :to="{ name: 'post-detail', params: { id: post.id } }"
    :aria-label="`查看${typeLabel}信息：${post.title}，状态：${statusLabel}`"
  >
    <div class="post-card__media">
      <PostImage
        v-if="post.cover_image"
        :image="post.cover_image"
        :readable="coverReadable"
        :post-status="post.status"
        variant="card"
      />
      <div v-else class="post-card__no-image" aria-hidden="true">
        <span>暂无图片</span>
      </div>
      <span class="post-card__type" :class="`post-card__type--${post.post_type}`">
        {{ typeLabel }}
      </span>
    </div>

    <div class="post-card__body">
      <div class="post-card__head">
        <h3 class="post-card__title">{{ post.title }}</h3>
        <StatusBadge :status="post.status" />
      </div>

      <p class="post-card__meta">
        <span v-if="post.category?.name" class="post-card__chip">{{ post.category.name }}</span>
        <span class="post-card__place" :title="placeText">{{ placeText }}</span>
      </p>

      <p class="post-card__time">
        发生时间：{{ formatBeijingDateTime(post.occurred_at) }}
      </p>

      <div class="post-card__foot">
        <span class="post-card__publisher">
          {{ publisherName }}
          <span
            v-if="publisherVerified"
            class="badge badge--verified"
            :title="publisherDemo ? '演示认证：第一版未接入真实学校认证服务' : '已认证'"
          >
            {{ publisherDemo ? '演示认证' : '已认证' }}
          </span>
        </span>
        <span class="post-card__created">
          发布 {{ formatBeijingDateTime(post.created_at) }}
        </span>
      </div>
    </div>
  </RouterLink>
</template>

<style scoped>
.post-card {
  display: flex;
  flex-direction: column;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  overflow: hidden;
  text-decoration: none;
  color: inherit;
  transition: box-shadow 0.18s ease, transform 0.18s ease, border-color 0.18s ease;
  height: 100%;
}

.post-card:hover {
  box-shadow: var(--shadow);
  transform: translateY(-2px);
  border-color: var(--line-strong);
}

.post-card:focus-visible {
  outline: 3px solid var(--focus);
  outline-offset: 2px;
}

.post-card__media {
  position: relative;
  background: var(--surface-soft);
}

.post-card__no-image {
  aspect-ratio: 4 / 3;
  display: grid;
  place-items: center;
  color: var(--muted);
  font-size: 13px;
  background: repeating-linear-gradient(
    135deg,
    #f1f4fa,
    #f1f4fa 10px,
    #e9edf6 10px,
    #e9edf6 20px
  );
}

.post-card__type {
  position: absolute;
  top: 10px;
  left: 10px;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.02em;
  background: #ffffffee;
  border: 1px solid var(--line);
  color: var(--text);
  backdrop-filter: blur(2px);
}

.post-card__type--lost {
  color: #b91c1c;
  border-color: #f3c6c6;
  background: #fff5f5f0;
}

.post-card__type--found {
  color: #065f46;
  border-color: #bfe7d8;
  background: #f2fbf7f0;
}

.post-card__body {
  padding: 12px 14px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex: 1;
}

.post-card__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.post-card__title {
  margin: 0;
  font-size: 16px;
  line-height: 1.45;
  font-weight: 650;
  color: var(--text);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  word-break: break-word;
}

.post-card__meta {
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 13px;
  color: var(--text-soft);
}

.post-card__chip {
  background: var(--primary-soft);
  color: var(--primary-dark);
  border-radius: 6px;
  padding: 1px 7px;
  font-size: 12px;
}

.post-card__place {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}

.post-card__time {
  margin: 0;
  font-size: 12.5px;
  color: var(--muted);
}

.post-card__foot {
  margin-top: auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--line);
  font-size: 12.5px;
  color: var(--muted);
}

.post-card__publisher {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--text-soft);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.post-card__created {
  flex: none;
}
</style>
