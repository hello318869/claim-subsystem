<script setup>
import { claimLabels } from '../constants.js'
defineProps({ claim: Object })
</script>

<template>
  <ol class="steps" aria-label="认领进度">
    <li class="done"><span>1</span>提交申请</li>
    <li :class="{ done: ['accepted', 'completed'].includes(claim.status), current: claim.status === 'pending' }"><span>2</span>发布者核实</li>
    <li :class="{ done: claim.status === 'completed', current: claim.status === 'accepted' }"><span>3</span>双方确认交接</li>
    <li :class="{ done: claim.status === 'completed' }"><span>4</span>{{ ['rejected', 'cancelled', 'closed'].includes(claim.status) ? claimLabels[claim.status] : '认领完成' }}</li>
  </ol>
</template>
