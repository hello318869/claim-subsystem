<script setup>
import { computed, ref } from 'vue'
const props = defineProps({ busy: Boolean })
const emit = defineEmits(['submit'])
const text = ref('')
const length = computed(() => Array.from(text.value.trim()).length)
const remaining = computed(() => Math.max(0, 10 - length.value))
const tooShort = computed(() => length.value > 0 && length.value < 10)
const allowed = computed(() => !props.busy && length.value >= 10 && length.value <= 1000)
function submit() {
  if (allowed.value) emit('submit', text.value.trim())
}
</script>

<template>
  <form @submit.prevent="submit">
    <label for="verification">私有认领证明</label>
    <p class="muted">描述未公开的细节，例如钥匙数量或挂件特征。仅你和发布者可见，提交后可在会话中补充。</p>
    <textarea id="verification" v-model="text" rows="6" required placeholder="请输入至少 10 个字的认领证明" :disabled="busy" />
    <p v-if="tooShort" class="field-error" role="status">认领证明至少需要 10 个字，当前 {{ length }} 个字，还差 {{ remaining }} 个字。</p>
    <div class="form-bottom">
      <span class="muted">{{ length }} / 1000 字<span v-if="tooShort" class="hint-error">（至少 10 字）</span></span>
      <button :disabled="!allowed" :title="length < 10 ? '认领证明至少 10 个字' : ''">{{ busy ? '提交中…' : '提交认领申请' }}</button>
    </div>
  </form>
</template>

<style scoped>
.field-error { color: #994529; font-size: 13px; margin: 6px 0 0; }
.hint-error { color: #b45309; margin-left: 4px; }
</style>
