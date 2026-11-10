<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { fetchImageBlob, imageContentUrl } from '../api/posts.js'
import { imageAltText } from '../utils/image.js'

/*
 * 统一的图片展示组件。
 * - 可读：公开图直接作为 img src；受登录保护的图带令牌取 Blob 后预览（令牌不进 URL）。
 * - 不可读：整块替换为 alt_text 占位，不请求原图，布局不塌陷（E3 US-11 / US-14）。
 * - 加载失败（如刚撤回返回 404）：也落到 alt_text 占位，不显示破图。
 */
const props = defineProps({
  image: { type: Object, default: null },
  /** 是否可读，由调用方按可见性规则算好传入 */
  readable: { type: Boolean, default: true },
  /** 未绑定图片 / 编辑页缩略图：即使 is_public=true 也必须带令牌请求 */
  requiresAuth: { type: Boolean, default: false },
  variant: { type: String, default: 'card' }, // card | thumb | hero
  postStatus: { type: String, default: 'open' },
})

const blobUrl = ref('')
const loading = ref(false)
const failed = ref(false)

const altText = computed(() => imageAltText(props.image))
const isPublicImage = computed(() => props.image?.is_public === true)

const useDirectSrc = computed(() => {
  if (!props.image || props.requiresAuth) return false
  return isPublicImage.value
})

const src = computed(() => (useDirectSrc.value ? imageContentUrl(props.image.id) : blobUrl.value))

const showPlaceholder = computed(() => !props.image || !props.readable || failed.value)

const placeholderReason = computed(() => {
  if (!props.image) return '暂无图片'
  if (!props.readable) {
    if (props.postStatus === 'withdrawn') return '信息已撤回，图片不可读'
    return isPublicImage.value ? '图片不可读' : '需登录后查看'
  }
  return '图片暂时无法加载'
})

let controller

function resetBlob() {
  controller?.abort()
  if (blobUrl.value) URL.revokeObjectURL(blobUrl.value)
  blobUrl.value = ''
}

async function loadBlob(imageId) {
  controller = new AbortController()
  const { signal } = controller
  failed.value = false
  loading.value = true
  try {
    const url = await fetchImageBlob(imageId, signal)
    if (signal.aborted) URL.revokeObjectURL(url)
    else blobUrl.value = url
  } catch (err) {
    if (!signal.aborted && err.name !== 'AbortError') failed.value = true
  } finally {
    if (!signal.aborted) loading.value = false
  }
}

watch(
  () => [props.image?.id, props.readable, props.requiresAuth, useDirectSrc.value],
  ([imageId, readable, , direct]) => {
    resetBlob()
    failed.value = false
    if (!imageId || !readable || direct) {
      loading.value = false
      return
    }
    loadBlob(imageId)
  },
  { immediate: true },
)

onBeforeUnmount(resetBlob)

function onImageError() {
  failed.value = true
}
</script>

<template>
  <figure class="post-image" :class="`post-image--${variant}`">
    <img
      v-if="src && !showPlaceholder"
      :src="src"
      :alt="altText"
      class="post-image__img"
      loading="lazy"
      decoding="async"
      @error="onImageError"
    />
    <div v-else-if="loading" class="post-image__skeleton" aria-hidden="true">
      <span>图片加载中…</span>
    </div>
    <div
      v-else
      class="post-image__placeholder"
      role="img"
      :aria-label="`图片不可查看，替代文字：${altText}`"
    >
      <span class="post-image__placeholder-icon" aria-hidden="true">🖼</span>
      <span class="post-image__alt">{{ altText }}</span>
      <span class="post-image__tag">{{ placeholderReason }}</span>
    </div>
    <figcaption v-if="variant !== 'thumb'" class="post-image__caption">
      <span class="post-image__caption-alt">{{ altText }}</span>
      <span v-if="image" class="post-image__caption-visibility">
        {{ image.is_public ? '未登录可见' : '仅登录用户可见' }}
      </span>
    </figcaption>
  </figure>
</template>

<style scoped>
.post-image {
  margin: 0;
  position: relative;
  background: var(--surface-soft);
  border-radius: 10px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  min-height: 120px;
}

.post-image__img {
  width: 100%;
  height: 100%;
  display: block;
  object-fit: cover;
  aspect-ratio: 4 / 3;
}

.post-image--hero .post-image__img {
  aspect-ratio: 16 / 10;
  object-fit: contain;
  background: #0f172a0a;
}

.post-image__skeleton {
  aspect-ratio: 4 / 3;
  display: grid;
  place-items: center;
  color: var(--muted);
  font-size: 13px;
  background: linear-gradient(100deg, #eef1f7 30%, #f7f9fc 50%, #eef1f7 70%);
  background-size: 300% 100%;
  animation: shimmer 1.4s infinite linear;
}

@keyframes shimmer {
  from {
    background-position: 150% 0;
  }
  to {
    background-position: -150% 0;
  }
}

.post-image__placeholder {
  aspect-ratio: 4 / 3;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 14px;
  text-align: center;
  color: var(--muted);
  background: repeating-linear-gradient(
    135deg,
    #f1f4fa,
    #f1f4fa 10px,
    #e9edf6 10px,
    #e9edf6 20px
  );
  border: 1px dashed var(--line-strong);
  border-radius: 10px;
  box-sizing: border-box;
}

.post-image__placeholder-icon {
  font-size: 20px;
  opacity: 0.6;
}

.post-image__alt {
  font-size: 13px;
  line-height: 1.5;
  color: var(--text-soft);
  word-break: break-word;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.post-image__tag {
  font-size: 12px;
  color: var(--muted);
  background: #ffffffcc;
  padding: 2px 8px;
  border-radius: 999px;
}

.post-image__caption {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 10px;
  font-size: 12px;
  color: var(--muted);
  border-top: 1px solid var(--line);
  background: var(--surface);
}

.post-image__caption-alt {
  word-break: break-word;
}

.post-image__caption-visibility {
  flex: none;
  color: var(--text-soft);
}

.post-image--thumb {
  min-height: 72px;
  width: 96px;
  height: 72px;
  border-radius: 8px;
}

.post-image--thumb .post-image__img,
.post-image--thumb .post-image__placeholder,
.post-image--thumb .post-image__skeleton {
  aspect-ratio: auto;
  width: 96px;
  height: 72px;
}

.post-image--thumb .post-image__alt {
  -webkit-line-clamp: 2;
  font-size: 11px;
}

.post-image--thumb .post-image__tag,
.post-image--thumb .post-image__placeholder-icon {
  display: none;
}
</style>
