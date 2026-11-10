<script setup>
defineProps({ page: Number, totalPages: Number, total: Number, disabled: Boolean })
defineEmits(['change'])
</script>

<template>
  <div class="pagination">
    <span>共 {{ total }} 条 · 第 {{ page }} / {{ Math.max(1, totalPages) }} 页</span>
    <div class="actions">
      <button class="secondary" :disabled="disabled || page <= 1" @click="$emit('change', page - 1)">上一页</button>
      <button class="secondary" :disabled="disabled || page >= totalPages" @click="$emit('change', page + 1)">下一页</button>
    </div>
  </div>
</template>
