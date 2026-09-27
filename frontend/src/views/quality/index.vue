<template>
  <section class="page" data-module="quality">
    <header class="page-head">
      <div>
        <h2>数据质控管理</h2>
        <p class="page-desc">维护质控任务，围绕质控编号、质控时段、涉及站点、质控规则做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记质控任务</button>
        <button class="btn" type="button" @click="exportRows">导出数据质控清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <label class="filter-item">
        <span>疑误率判定</span>
        <select v-model="verdict">
          <option value="">全部</option>
          <option v-for="option in verdictOptions" :key="option" :value="option">{{ option }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <span v-if="column === '疑误率判定'" class="verdict-tag" :class="verdictClass(row)">
              {{ row[column] ?? '未判定' }}
            </span>
            <template v-else>{{ formatCell(column, row) }}</template>
          </td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无数据质控数据，可先登记质控任务</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条数据质控记录</span>
      <span>疑误率偏高 {{ summary['偏高'] ?? 0 }} 条 · 偏低 {{ summary['偏低'] ?? 0 }} 条</span>
      <span v-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/quality'
const columns = ["质控编号", "质控时段", "涉及站点", "质控规则", "检出疑误数", "质控人员", "质控日期", "质控状态", "疑误率", "疑误率判定"]
const actions = ["启动质控", "确认完成", "退回重做"]
const statuses = ["待执行", "执行中", "已完成", "已退回"]
const verdictOptions = ["偏高", "偏低", "正常", "未判定"]
const stats = [{"label": "待执行质控", "value": 0}, {"label": "本月质控轮次", "value": 0}, {"label": "检出疑误数", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const summary = ref<Record<string, number>>({})
const errorMessage = ref('')
const noticeMessage = ref('')
const filters = ref<Record<string, string>>({})
const verdict = ref('')
const filterFields = columns.slice(0, 3)

function resetFilters() {
  filters.value = {}
  verdict.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '质控任务登记入口尚未接入审批流'
}

function verdictClass(row: Row) {
  const value = row['疑误率判定']
  if (value === '偏高') return 'is-high'
  if (value === '偏低') return 'is-low'
  if (value === '正常') return 'is-normal'
  return ''
}

function formatCell(column: string, row: Row) {
  const value = row[column]
  if (value === null || value === undefined || value === '') return '—'
  if (column === '疑误率' && typeof value === 'number') return `${(value * 100).toFixed(1)}%`
  return value
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message ?? payload.detail ?? '数据质控动作未生效，请稍后重试')
    }
    noticeMessage.value = payload.message ?? ''
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据质控操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>)
  const keyword = (filters.value['质控编号'] ?? '').trim()
  if (keyword) query.set('keyword', keyword)
  if (verdict.value) query.set('verdict', verdict.value)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('质控任务列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    summary.value = payload.summary ?? {}
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据质控列表读取失败'
  }
}

onMounted(reload)
</script>
