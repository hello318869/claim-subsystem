<script setup>
import { computed } from 'vue'
import { STATUS_HINT, STATUS_TEXT } from '../config.js'

const props = defineProps({
  status: { type: String, default: 'open' },
  showHint: { type: Boolean, default: false },
})

const label = computed(() => STATUS_TEXT[props.status] || props.status || '未知状态')
const hint = computed(() => STATUS_HINT[props.status] || '')
</script>

<template>
  <span class="status-badge" :class="`status-badge--${status}`" :title="hint || label">
    <span class="status-badge__dot" aria-hidden="true"></span>
    <span class="status-badge__text">{{ label }}</span>
    <span v-if="showHint && hint" class="status-badge__hint">（{{ hint }}）</span>
  </span>
</template>

<style scoped>
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 9px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  line-height: 1.5;
  white-space: nowrap;
}

.status-badge__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

.status-badge--open {
  color: #0f766e;
  background: #e6f6f3;
}

.status-badge--in_handover {
  color: #b45309;
  background: #fdf1de;
}

.status-badge--completed {
  color: #1e40af;
  background: #e7edfd;
}

.status-badge--withdrawn {
  color: #64748b;
  background: #eef1f5;
}

.status-badge__hint {
  font-weight: 400;
  color: var(--muted);
}
</style>
