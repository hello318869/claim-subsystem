import { describe, expect, it } from 'vitest'
import { availableActions } from '../constants.js'

const claim = { status: 'pending', applicant_id: '1', publisher: { id: '2' }, applicant_confirmed_at: null, publisher_confirmed_at: null }
describe('认领操作权限与状态', () => {
  it('待审时申请者可以取消，发布者可以审核', () => {
    expect(availableActions(claim, '1')).toEqual(['cancel'])
    expect(availableActions(claim, '2')).toEqual(['accept', 'reject'])
  })
  it('非参与者和未登录用户没有操作', () => {
    expect(availableActions(claim, '3')).toEqual([])
    expect(availableActions(claim, null)).toEqual([])
  })
  it('双方未确认时均可确认或取消', () => {
    expect(availableActions({ ...claim, status: 'accepted' }, '1')).toEqual(['confirm-handover', 'cancel'])
    expect(availableActions({ ...claim, status: 'accepted' }, '2')).toEqual(['confirm-handover', 'cancel'])
  })
  it('单方确认后取消消失，已确认方不能重复操作', () => {
    const accepted = { ...claim, status: 'accepted', applicant_confirmed_at: '2026-10-10T00:00:00Z' }
    expect(availableActions(accepted, '1')).toEqual([])
    expect(availableActions(accepted, '2')).toEqual(['confirm-handover'])
  })
  it.each(['closed', 'completed', 'cancelled', 'rejected'])('终态 %s 没有写操作', status => {
    expect(availableActions({ ...claim, status }, '1')).toEqual([])
    expect(availableActions({ ...claim, status }, '2')).toEqual([])
  })
})
