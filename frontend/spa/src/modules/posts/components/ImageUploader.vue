<script setup>
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'
import PostImage from './PostImage.vue'
import { uploadPostImage } from '../api/posts.js'
import { describeError } from '../api/http.js'
import {
  ALLOWED_IMAGE_EXT_TEXT,
  ALLOWED_IMAGE_TYPES,
  ALT_TEXT_MAX,
  ALT_TEXT_MIN,
  IMAGE_ALT_TEXT_HINT,
  IMAGE_RESPONSIBILITY_NOTE,
  MAX_IMAGES,
} from '../config.js'
import { charLength, formatFileSize } from '../utils/format.js'
import { validateImageFile } from '../utils/validate.js'
import { imageVisibilityLabel } from '../utils/image.js'

/*
 * 图片上传区（契约 §3.6 / §5.1 POST /post-images）：
 *   1. 先逐张上传拿 PostImageView（含 id / url / alt_text / is_public），
 *   2. 发布或编辑时只提交 image_ids（顺序即展示顺序）。
 * alt_text 与 is_public 都在上传时确定，创建/修改接口不接收，所以这里的
 * 已上传图片只允许调整顺序和移除，改替代文字需移除后重新上传。
 */
const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  max: { type: Number, default: MAX_IMAGES },
  disabled: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'uploaded', 'error'])

const pending = ref([])
const fileInput = ref(null)
const batchUploading = ref(false)
let pendingSeed = 0

const totalCount = computed(() => props.modelValue.length + pending.value.length)
const canAddMore = computed(() => totalCount.value < props.max)
const isBusy = computed(() => props.disabled || batchUploading.value)

function openPicker() {
  if (!canAddMore.value || isBusy.value) return
  fileInput.value?.click()
}

function onFilesPicked(event) {
  const files = Array.from(event.target.files || [])
  event.target.value = ''
  if (!files.length) return

  const room = props.max - totalCount.value
  if (room <= 0) {
    emit('error', `最多 ${props.max} 张图片，请先移除已选图片。`)
    return
  }
  const accepted = files.slice(0, room)
  if (files.length > room) {
    emit('error', `最多 ${props.max} 张图片，本次只加入前 ${room} 张。`)
  }

  for (const file of accepted) {
    const localError = validateImageFile(file)
    pendingSeed += 1
    pending.value.push({
      key: `pending-${pendingSeed}`,
      file,
      alt_text: '',
      is_public: true,
      previewUrl: URL.createObjectURL(file),
      status: 'pending',
      error: localError,
    })
  }
}

function altLength(item) {
  return charLength(item.alt_text)
}

function altError(item) {
  const length = altLength(item)
  if (length === 0) return `请填写 ${ALT_TEXT_MIN}～${ALT_TEXT_MAX} 字的替代文字`
  if (length < ALT_TEXT_MIN) return `至少 ${ALT_TEXT_MIN} 字（当前 ${length} 字）`
  if (length > ALT_TEXT_MAX) return `最多 ${ALT_TEXT_MAX} 字（当前 ${length} 字）`
  return ''
}

async function uploadOne(item) {
  if (item.status === 'uploading') return
  const localError = validateImageFile(item.file)
  if (localError) {
    item.error = localError
    return
  }
  const textError = altError(item)
  if (textError) {
    item.error = textError
    return
  }
  item.status = 'uploading'
  item.error = ''
  try {
    const image = await uploadPostImage({
      file: item.file,
      altText: item.alt_text.trim(),
      isPublic: item.is_public,
    })
    emit('update:modelValue', [...props.modelValue, image])
    emit('uploaded', image)
    removePending(item)
    // 等父组件把新的 modelValue 传回来，避免连续上传时后一张覆盖前一张
    await nextTick()
  } catch (err) {
    item.status = 'pending'
    item.error = describeError(err)
    emit('error', `图片「${item.file.name}」上传失败：${describeError(err)}`)
  }
}

async function uploadAll() {
  if (isBusy.value) return
  const queue = pending.value.filter((item) => item.status !== 'uploading' && !item.error)
  if (!queue.length) {
    emit('error', '没有可上传的图片：请先填写合法的替代文字并确认格式与大小。')
    return
  }
  batchUploading.value = true
  try {
    for (const item of queue) {
      // 逐张上传，避免并发争抢导致部分成功难排查；失败项保留在列表里可重试
      await uploadOne(item)
    }
  } finally {
    batchUploading.value = false
  }
}

function removePending(item) {
  if (item.previewUrl) URL.revokeObjectURL(item.previewUrl)
  pending.value = pending.value.filter((entry) => entry.key !== item.key)
}

function removeImage(index) {
  const next = props.modelValue.filter((_, i) => i !== index)
  emit('update:modelValue', next)
}

function moveImage(index, offset) {
  const target = index + offset
  if (target < 0 || target >= props.modelValue.length) return
  const next = [...props.modelValue]
  const [item] = next.splice(index, 1)
  next.splice(target, 0, item)
  emit('update:modelValue', next)
}

onBeforeUnmount(() => {
  for (const item of pending.value) {
    if (item.previewUrl) URL.revokeObjectURL(item.previewUrl)
  }
  pending.value = []
})
</script>

<template>
  <section class="uploader" :class="{ 'is-disabled': disabled }" aria-label="图片上传">
    <div class="uploader__head">
      <h2 class="uploader__title">图片（{{ totalCount }} / {{ max }}）</h2>
      <p class="uploader__hint">{{ ALLOWED_IMAGE_EXT_TEXT }}</p>
    </div>

    <p class="uploader__note">{{ IMAGE_ALT_TEXT_HINT }}</p>
    <p class="uploader__note uploader__note--warn">{{ IMAGE_RESPONSIBILITY_NOTE }}</p>

    <div class="uploader__drop">
      <input
        ref="fileInput"
        class="visually-hidden"
        type="file"
        :accept="ALLOWED_IMAGE_TYPES.join(',')"
        multiple
        :disabled="!canAddMore || isBusy"
        @change="onFilesPicked"
      />
      <button
        type="button"
        class="btn btn--outline"
        :disabled="!canAddMore || isBusy"
        @click="openPicker"
      >
        选择图片
      </button>
      <span class="uploader__drop-hint">
        {{ canAddMore ? '支持多选；选好后逐张填写替代文字再上传' : `已达上限 ${max} 张` }}
      </span>
    </div>

    <!-- 待上传队列：本地预览 + 替代文字 + 是否允许未登录查看 -->
    <ul v-if="pending.length" class="uploader__list uploader__list--pending">
      <li v-for="item in pending" :key="item.key" class="uploader__item">
        <img
          class="uploader__preview"
          :src="item.previewUrl"
          :alt="item.alt_text || `待上传图片 ${item.file.name}`"
        />
        <div class="uploader__fields">
          <p class="uploader__filename">
            {{ item.file.name }}
            <span class="uploader__filesize">{{ formatFileSize(item.file.size) }}</span>
            <span class="uploader__state" :class="`is-${item.status}`">
              {{ item.status === 'uploading' ? '上传中…' : '待上传' }}
            </span>
          </p>
          <label class="field">
            <span class="field__label">
              替代文字（必填，{{ ALT_TEXT_MIN }}～{{ ALT_TEXT_MAX }} 字，供读屏与图片不可见时使用）
            </span>
            <textarea
              v-model="item.alt_text"
              class="input uploader__alt"
              rows="2"
              :maxlength="ALT_TEXT_MAX"
              :disabled="item.status === 'uploading'"
              :aria-invalid="!!altError(item)"
              placeholder="例如：深蓝色保温杯，杯身有白色校徽贴纸，杯盖边缘有一处磕碰"
            ></textarea>
            <span class="field__counter" :class="{ 'is-over': altLength(item) > ALT_TEXT_MAX }">
              {{ altLength(item) }} / {{ ALT_TEXT_MAX }}
            </span>
          </label>
          <p v-if="item.error" class="field__error">{{ item.error }}</p>
          <label class="check">
            <input v-model="item.is_public" type="checkbox" :disabled="item.status === 'uploading'" />
            <span>允许未登录查看这张图（默认勾选；不勾选则仅登录用户可看）</span>
          </label>
          <div class="uploader__item-actions">
            <button
              type="button"
              class="btn btn--primary btn--sm"
              :disabled="item.status === 'uploading' || isBusy"
              @click="uploadOne(item)"
            >
              {{ item.status === 'uploading' ? '上传中…' : '上传这张' }}
            </button>
            <button
              type="button"
              class="btn btn--ghost btn--sm"
              :disabled="item.status === 'uploading'"
              @click="removePending(item)"
            >
              移除
            </button>
          </div>
        </div>
      </li>
    </ul>

    <div v-if="pending.length > 1" class="uploader__bulk">
      <button type="button" class="btn btn--primary btn--sm" :disabled="isBusy" @click="uploadAll">
        {{ batchUploading ? '上传中…' : `全部上传（${pending.length} 张）` }}
      </button>
    </div>

    <!-- 已上传图片：顺序即 image_ids 顺序 -->
    <ul v-if="modelValue.length" class="uploader__list">
      <li v-for="(image, index) in modelValue" :key="image.id" class="uploader__item">
        <PostImage :image="image" :readable="true" :requires-auth="true" variant="thumb" />
        <div class="uploader__fields">
          <p class="uploader__filename">
            第 {{ index + 1 }} 张
            <span class="uploader__filesize">{{ formatFileSize(image.size_bytes) }}</span>
            <span class="uploader__state is-done">已上传</span>
          </p>
          <p class="uploader__alt-readonly">替代文字：{{ image.alt_text }}</p>
          <p class="uploader__visibility">{{ imageVisibilityLabel(image) }}</p>
          <div class="uploader__item-actions">
            <button
              type="button"
              class="btn btn--ghost btn--sm"
              :disabled="index === 0 || isBusy"
              @click="moveImage(index, -1)"
            >
              上移
            </button>
            <button
              type="button"
              class="btn btn--ghost btn--sm"
              :disabled="index === modelValue.length - 1 || isBusy"
              @click="moveImage(index, 1)"
            >
              下移
            </button>
            <button type="button" class="btn btn--ghost btn--sm" :disabled="isBusy" @click="removeImage(index)">
              移除
            </button>
          </div>
        </div>
      </li>
    </ul>

    <p v-if="!totalCount" class="uploader__empty">还没有图片。图片为选填（0～{{ max }} 张）。</p>
  </section>
</template>

<style scoped>
.uploader {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.uploader__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.uploader__title {
  margin: 0;
  font-size: 15px;
  font-weight: 650;
}

.uploader__hint {
  margin: 0;
  font-size: 12.5px;
  color: var(--muted);
}

.uploader__note {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.65;
  color: var(--text-soft);
  background: var(--surface-soft);
  border-left: 3px solid var(--line-strong);
  padding: 7px 10px;
  border-radius: 6px;
}

.uploader__note--warn {
  background: #fffbeb;
  border-left-color: #f0c674;
  color: #7c4a03;
}

.uploader__drop {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px;
  border: 1px dashed var(--line-strong);
  border-radius: 10px;
  background: var(--surface-soft);
}

.uploader__drop-hint {
  font-size: 12.5px;
  color: var(--muted);
}

.uploader__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.uploader__item {
  display: flex;
  gap: 12px;
  padding: 10px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface);
}

.uploader__preview {
  width: 96px;
  height: 96px;
  object-fit: cover;
  border-radius: 8px;
  flex: none;
  background: var(--surface-soft);
}

.uploader__fields {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
  flex: 1;
}

.uploader__filename {
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 13px;
  color: var(--text);
  word-break: break-all;
}

.uploader__filesize {
  color: var(--muted);
  font-size: 12px;
}

.uploader__state {
  font-size: 11.5px;
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--surface-soft);
  color: var(--muted);
}

.uploader__state.is-done {
  background: #e6f6f3;
  color: #0f766e;
}

.uploader__state.is-uploading {
  background: #eff6ff;
  color: #1e40af;
}

.uploader__alt {
  resize: vertical;
  min-height: 56px;
}

.uploader__alt-readonly,
.uploader__visibility {
  margin: 0;
  font-size: 12.5px;
  color: var(--text-soft);
  word-break: break-word;
}

.uploader__visibility {
  color: var(--muted);
}

.uploader__item-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.uploader__bulk {
  display: flex;
  justify-content: flex-end;
}

.uploader__empty {
  margin: 0;
  font-size: 13px;
  color: var(--muted);
}

.field__counter {
  align-self: flex-end;
  font-size: 11.5px;
  color: var(--muted);
}

.field__counter.is-over {
  color: #b91c1c;
}
</style>
