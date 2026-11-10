import { computed } from 'vue'
import { session } from '../../../shared/session.js'

export const tokenRef = computed(() => session.token || '')
export const hasToken = () => Boolean(tokenRef.value)
