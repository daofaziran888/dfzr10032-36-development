<template>
  <section class="page" data-module="monitor">
    <header class="page-head">
      <div>
        <h2>采集监控管理</h2>
        <p class="page-desc">维护监控面板，围绕面板编号、采集源总数、今日采集量、成功率做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记监控面板</button>
        <button class="btn" type="button" @click="exportRows">导出采集监控清单</button>
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
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
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
          <td :colspan="columns.length + 1" class="empty-state">暂无采集监控数据，可先登记监控面板</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条采集监控记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <section class="panel">
      <header class="panel-head">
        <h3>报告快照来源对账</h3>
        <div class="panel-actions">
          <button class="btn" type="button" @click="openConsume('snapshot')">消费报告快照</button>
          <button class="btn" type="button" @click="openConsume('corrections')">消费更正回执</button>
        </div>
      </header>
      <p class="panel-hint">
        消费已确认的报告快照及其更正后写入来源对账记录，可追查原统计周期与更正批次。
      </p>
      <form class="filter-bar" @submit.prevent="loadReconciliation">
        <label class="filter-item">
          <span>下载标识</span>
          <input v-model="reconciliationFilter" placeholder="按原下载标识回查" />
        </label>
        <button class="btn" type="submit">查询</button>
        <button class="btn ghost" type="button" @click="resetReconciliationFilter">重置</button>
      </form>
      <table class="data-table">
        <thead>
          <tr>
            <th>对账编号</th>
            <th>类型</th>
            <th>下载标识</th>
            <th>原统计周期</th>
            <th>采集源</th>
            <th>记录数</th>
            <th>成功量</th>
            <th>失败量</th>
            <th>更正批次</th>
            <th>回执编号</th>
            <th>核对一致</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in reconciliation" :key="String(row.id)">
            <td>{{ row.对账编号 }}</td>
            <td>{{ row.类型 }}</td>
            <td>{{ row.下载标识 || '—' }}</td>
            <td>{{ row.原统计周期 }}</td>
            <td>{{ row.采集源 }}</td>
            <td>{{ row.记录数 }}</td>
            <td>{{ row.成功量 === '' ? '—' : row.成功量 }}</td>
            <td>{{ row.失败量 === '' ? '—' : row.失败量 }}</td>
            <td>{{ row.更正批次 || '—' }}</td>
            <td>{{ row.回执编号 || '—' }}</td>
            <td>{{ row.核对一致 ? '是' : '否' }}</td>
          </tr>
          <tr v-if="!reconciliation.length">
            <td colspan="11" class="empty-state">暂无来源对账记录，可先消费一份报告快照</td>
          </tr>
        </tbody>
      </table>
    </section>

    <Teleport to="body">
      <div v-if="showCreateModal" class="modal-overlay" @click.self="showCreateModal = false">
        <div class="modal-card">
          <header class="modal-head">
            <h3>登记监控面板</h3>
            <button class="btn ghost" type="button" @click="showCreateModal = false">&times;</button>
          </header>
          <form class="modal-body" @submit.prevent="submitCreate">
            <label v-for="field in columns.slice(0, 3)" :key="field" class="modal-field">
              <span>{{ field }}</span>
              <input v-model="createFields[field]" :placeholder="`请输入${field}`" required />
            </label>
            <footer class="modal-foot">
              <button class="btn" type="button" @click="showCreateModal = false">取消</button>
              <button class="btn primary" type="submit">提交登记</button>
            </footer>
          </form>
        </div>
      </div>

      <div v-if="showConsumeModal" class="modal-overlay" @click.self="showConsumeModal = false">
        <div class="modal-card">
          <header class="modal-head">
            <h3>{{ consumeMode === 'snapshot' ? '消费报告快照' : '消费更正回执' }}</h3>
            <button class="btn ghost" type="button" @click="showConsumeModal = false">&times;</button>
          </header>
          <form class="modal-body" @submit.prevent="submitConsume">
            <label v-if="consumeMode === 'snapshot'" class="modal-field">
              <span>下载标识</span>
              <input v-model="consumeFields['下载标识']" placeholder="例如 SNPS-20261120-0001" required />
            </label>
            <template v-else>
              <label class="modal-field">
                <span>统计周期</span>
                <input v-model="consumeFields['统计周期']" placeholder="例如 2026-W47" required />
              </label>
              <label class="modal-field">
                <span>更正批次（可选）</span>
                <input v-model="consumeFields['更正批次']" placeholder="留空则消费该周期全部更正" />
              </label>
            </template>
            <label class="modal-field">
              <span>消费人</span>
              <input v-model="consumeFields['消费人']" placeholder="例如 采集监控" />
            </label>
            <footer class="modal-foot">
              <button class="btn" type="button" @click="showConsumeModal = false">取消</button>
              <button class="btn primary" type="submit">确认消费</button>
            </footer>
          </form>
        </div>
      </div>
    </Teleport>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/monitor'
const columns = ["面板编号", "采集源总数", "今日采集量", "成功率", "平均延迟", "失败重试", "异常告警", "更新时间"]
const actions = ["查看详情"]
const statuses = ["正常", "预警", "告警"]
const stats = [{"label": "今日采集量", "value": 0}, {"label": "成功率", "value": 0}, {"label": "异常告警数", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const showCreateModal = ref(false)
const createFields = ref<Record<string, string>>({})

type ReconciliationRow = Record<string, string | number | boolean>

const reconciliation = ref<ReconciliationRow[]>([])
const reconciliationFilter = ref('')
const showConsumeModal = ref(false)
const consumeMode = ref<'snapshot' | 'corrections'>('snapshot')
const consumeFields = ref<Record<string, string>>({})

function openConsume(mode: 'snapshot' | 'corrections') {
  errorMessage.value = ''
  consumeMode.value = mode
  consumeFields.value = { 消费人: '采集监控' }
  showConsumeModal.value = true
}

async function submitConsume() {
  errorMessage.value = ''
  const path = consumeMode.value === 'snapshot'
    ? `${ENDPOINT}/reconciliation/snapshot`
    : `${ENDPOINT}/reconciliation/corrections`
  try {
    const response = await request(path, {
      method: 'POST',
      body: JSON.stringify({ values: consumeFields.value }),
    })
    const data = await response.json()
    if (!data.ok) {
      throw new Error(data.message || '消费失败')
    }
    showConsumeModal.value = false
    errorMessage.value = data.message
    await loadReconciliation()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '消费失败'
  }
}

function resetReconciliationFilter() {
  reconciliationFilter.value = ''
  void loadReconciliation()
}

async function loadReconciliation() {
  const query = reconciliationFilter.value.trim()
    ? `?download_id=${encodeURIComponent(reconciliationFilter.value.trim())}`
    : ''
  try {
    const response = await request(`${ENDPOINT}/reconciliation${query}`)
    if (!response.ok) {
      return
    }
    const payload = await response.json()
    reconciliation.value = payload.items ?? []
  } catch {
    reconciliation.value = []
  }
}

function updateStats() {
  const data = rows.value
  stats.length > 0 && (stats[0].value = data.filter((r: Row) => r.status === statuses[1] || r.pending).length)
  stats.length > 1 && (stats[1].value = data.filter((r: Row) => r.status && !r.pending && !r.abnormal).length)
  stats.length > 2 && (stats[2].value = data.filter((r: Row) => r.abnormal).length)
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = ''
  createFields.value = {}
  showCreateModal.value = true
}

async function submitCreate() {
  errorMessage.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: createFields.value }),
    })
    if (!response.ok) {
      const data = await response.json()
      throw new Error(data.message || '登记失败')
    }
    showCreateModal.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    if (!response.ok) {
      throw new Error('采集监控动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '采集监控操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('监控面板列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    updateStats()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '采集监控列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadReconciliation()
})
</script>
