<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  busy: Boolean,
  campuses: { type: Array, default: () => [] },
  fallback: Boolean,
  fieldErrors: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['submit'])

const campusId = ref(props.fallback ? 'main' : '')
const studentNo = ref('')
const bindingCode = ref('')
const localErrors = ref({})

// 校区字典异步返回后，默认选中第一个校区。
watch(() => props.campuses, list => {
  if (!props.fallback && !campusId.value && list.length) campusId.value = list[0].id
}, { immediate: true })

const errors = computed(() => ({
  campus_id: localErrors.value.campus_id || props.fieldErrors.campus_id || '',
  student_no: localErrors.value.student_no || props.fieldErrors.student_no || '',
  binding_code: localErrors.value.binding_code || props.fieldErrors.binding_code || '',
}))

function submit() {
  if (props.busy) return
  const problems = {}
  const campus = campusId.value.trim()
  if (!campus) problems.campus_id = props.fallback ? '请输入校区标识' : '请选择校区'
  // 学号：6～20 位字母或数字；绑定码：长度 6～64（与后端校验一致，不裁剪）。
  if (!/^[A-Za-z0-9]{6,20}$/.test(studentNo.value.trim())) problems.student_no = '学号需为 6～20 位字母或数字'
  if (bindingCode.value.length < 6 || bindingCode.value.length > 64) problems.binding_code = '绑定码长度需为 6～64 个字符'
  localErrors.value = problems
  if (Object.keys(problems).length) return
  emit('submit', { campus_id: campus, student_no: studentNo.value.trim(), binding_code: bindingCode.value })
}
</script>

<template>
  <form class="binding-form" novalidate @submit.prevent="submit">
    <label for="binding-campus">校区</label>
    <select v-if="!fallback" id="binding-campus" v-model="campusId" name="campus_id" :disabled="busy">
      <option value="">请选择校区</option>
      <option v-for="campus in campuses" :key="campus.id" :value="campus.id">{{ campus.name }}</option>
    </select>
    <input v-else id="binding-campus" v-model="campusId" name="campus_id" :disabled="busy" placeholder="请输入校区标识，例如 main">
    <p v-if="fallback" class="notice">暂时无法读取校区选项。可以手动输入校区标识，演示环境主校区使用 main。</p>
    <p v-if="errors.campus_id" class="field-error">{{ errors.campus_id }}</p>
    <label for="binding-student-no">学号</label>
    <input id="binding-student-no" v-model="studentNo" name="student_no" :disabled="busy" placeholder="6～20 位字母或数字，例如 20260004">
    <p v-if="errors.student_no" class="field-error">{{ errors.student_no }}</p>
    <label for="binding-code">绑定码</label>
    <input id="binding-code" v-model="bindingCode" name="binding_code" autocomplete="off" :disabled="busy" placeholder="由初始化命令输出的一次性绑定码">
    <p v-if="errors.binding_code" class="field-error">{{ errors.binding_code }}</p>
    <button type="submit" :disabled="busy">{{ busy ? '绑定中…' : '提交绑定' }}</button>
    <p class="muted">演示绑定码由初始化命令输出；每个校园身份只能绑定一次，绑定后不可解绑。</p>
  </form>
</template>

<style scoped>
.binding-form button { width: 100%; margin: 20px 0 12px; }
.field-error { color: #994529; font-size: 13px; margin: 6px 0 0; }
.notice { margin-top: 10px; }
</style>
