export const claimLabels = { pending: '待核实', accepted: '等待交接', rejected: '已拒绝', cancelled: '已取消', completed: '已完成', closed: '已关闭' }
export const postLabels = { open: '进行中', in_handover: '交接中', completed: '已完成', withdrawn: '已撤回' }
export const closeLabels = { post_withdrawn: '发布者已撤回信息', another_claim_accepted: '发布者选择了其他申请' }
export const reasonLabels = { category_same: '类别相同 +40', location_same: '地点相同 +30', time_near: '72 小时内 +20', keyword_overlap: '标题相似 +10' }
export const handoverHint = '对方为校外人员，建议在失物招领处交接'
export const deletedPublisherMessage = '信息发布者已注销，无法申请认领'

export function availableActions(claim, userId) {
  if (!claim || !userId) return []
  const applicant = claim.applicant_id === userId
  const publisher = claim.publisher.id === userId
  if (!applicant && !publisher) return []
  if (claim.status === 'pending') return publisher ? ['accept', 'reject'] : ['cancel']
  if (claim.status !== 'accepted') return []
  const confirmed = applicant ? claim.applicant_confirmed_at : claim.publisher_confirmed_at
  const result = confirmed ? [] : ['confirm-handover']
  if (!claim.applicant_confirmed_at && !claim.publisher_confirmed_at) result.push('cancel')
  return result
}
