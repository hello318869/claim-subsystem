<script setup>
defineProps({
  tone: { type: String, default: 'error' }, // error | warn | info | success
  title: { type: String, default: '' },
  message: { type: String, default: '' },
  details: { type: Array, default: () => [] },
  hint: { type: String, default: '' },
})
</script>

<template>
  <div class="notice" :class="`notice--${tone}`" role="alert">
    <div class="notice__body">
      <p v-if="title" class="notice__title">{{ title }}</p>
      <p v-if="message" class="notice__message">{{ message }}</p>
      <ul v-if="details.length" class="notice__details">
        <li v-for="(item, index) in details" :key="index">{{ item }}</li>
      </ul>
      <p v-if="hint" class="notice__hint">{{ hint }}</p>
    </div>
    <div v-if="$slots.actions" class="notice__actions">
      <slot name="actions"></slot>
    </div>
  </div>
</template>

<style scoped>
.notice {
  display: flex;
  gap: 14px;
  align-items: flex-start;
  justify-content: space-between;
  padding: 12px 14px;
  border-radius: 10px;
  border: 1px solid;
  font-size: 14px;
  line-height: 1.6;
}

.notice__body {
  min-width: 0;
}

.notice__title {
  margin: 0 0 2px;
  font-weight: 650;
}

.notice__message {
  margin: 0;
  word-break: break-word;
}

.notice__details {
  margin: 6px 0 0;
  padding-left: 18px;
  color: inherit;
}

.notice__hint {
  margin: 6px 0 0;
  font-size: 13px;
  opacity: 0.85;
}

.notice__actions {
  flex: none;
  display: flex;
  gap: 8px;
}

.notice--error {
  background: #fef2f2;
  border-color: #f6cccc;
  color: #991b1b;
}

.notice--warn {
  background: #fffbeb;
  border-color: #f3e2b4;
  color: #92400e;
}

.notice--info {
  background: #eff6ff;
  border-color: #c7dbfa;
  color: #1e40af;
}

.notice--success {
  background: #ecfdf5;
  border-color: #bfe9d6;
  color: #065f46;
}
</style>
