<template>
  <section class="page" data-module="report">
    <header class="page-head">
      <div>
        <h2>采集报告管理</h2>
        <p class="page-desc">
          维护采集报告，按统计周期下载包含来源明细的快照包，并处理更正回执与核销领取。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记采集报告</button>
        <button class="btn" type="button" @click="openDownload">下载快照包</button>
        <button class="btn" type="button" @click="exportRows">导出采集报告清单</button>
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
          <td :colspan="columns.length + 1" class="empty-state">暂无采集报告数据，可先登记采集报告</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条采集报告记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <section class="panel">
      <header class="panel-head">
        <h3>报告快照留档</h3>
        <span class="panel-hint">按原下载标识可回查当时出包的内容</span>
      </header>
      <table class="data-table">
        <thead>
          <tr>
            <th>下载标识</th>
            <th>统计周期</th>
            <th>生成时间</th>
            <th>明细条数</th>
            <th>成功量</th>
            <th>失败量</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="snapshot in snapshots" :key="snapshot.下载标识">
            <td>{{ snapshot.下载标识 }}</td>
            <td>{{ snapshot.统计周期 }}</td>
            <td>{{ snapshot.生成时间 }}</td>
            <td>{{ snapshot.明细条数 }}</td>
            <td>{{ snapshot.成功量 }}</td>
            <td>{{ snapshot.失败量 }}</td>
            <td>{{ snapshot.状态 }}</td>
            <td class="row-actions">
              <button class="link" type="button" @click="viewSnapshot(snapshot)">查看核对</button>
              <a class="link" :href="`${ENDPOINT}/snapshots/${snapshot.下载标识}/file`">下载原包</a>
            </td>
          </tr>
          <tr v-if="!snapshots.length">
            <td colspan="8" class="empty-state">还没有留档的快照，可先按周期下载一次</td>
          </tr>
        </tbody>
      </table>
      <div v-if="selectedPackage" class="package-preview">
        <h4>{{ selectedPackage.统计周期 }} · {{ selectedPackage.快照标识 }}</h4>
        <p class="panel-hint">
          包内明细 {{ selectedPackage.明细.length }} 条，汇总成功 {{ selectedPackage.合计.成功量 }}、失败
          {{ selectedPackage.合计.失败量 }}，逐笔核对
          <strong>{{ selectedPackage.核对.一致 ? '一致' : '不一致' }}</strong>。
        </p>
        <table class="data-table">
          <thead>
            <tr><th>采集源</th><th>汇总记录数</th><th>明细记录数</th><th>成功量</th><th>失败量</th><th>一致</th></tr>
          </thead>
          <tbody>
            <tr v-for="check in selectedPackage.核对.来源核对" :key="check.采集源">
              <td>{{ check.采集源 }}</td>
              <td>{{ check.汇总记录数 }}</td>
              <td>{{ check.明细记录数 }}</td>
              <td>{{ check.汇总成功量 }}</td>
              <td>{{ check.汇总失败量 }}</td>
              <td>{{ check.一致 ? '是' : '否' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="panel">
      <header class="panel-head">
        <h3>更正回执</h3>
        <div class="panel-actions">
          <button class="btn" type="button" @click="openCorrection">登记更正</button>
          <button class="btn" type="button" @click="openClaim('核销')">核销已记旧数</button>
          <button class="btn" type="button" @click="openClaim('入账')">按周期领取入账</button>
        </div>
      </header>
      <table class="data-table">
        <thead>
          <tr>
            <th>回执编号</th>
            <th>更正批次</th>
            <th>统计周期</th>
            <th>采集源</th>
            <th>关联下载标识</th>
            <th>基础失败量</th>
            <th>更正后</th>
            <th>应补差额</th>
            <th>已核销</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="receipt in corrections" :key="receipt.回执编号">
            <td>{{ receipt.回执编号 }}</td>
            <td>{{ receipt.更正批次 }}</td>
            <td>{{ receipt.统计周期 }}</td>
            <td>{{ receipt.采集源 }}</td>
            <td>{{ receipt.关联下载标识 || '—' }}</td>
            <td>{{ receipt.基础失败量 }}</td>
            <td>{{ receipt.更正后失败量 }}</td>
            <td>{{ receipt.应补差额 }}</td>
            <td>{{ receipt.已核销条数 }} 条 {{ receipt.核销批次.join('、') }}</td>
            <td>{{ receipt.状态 }}</td>
          </tr>
          <tr v-if="!corrections.length">
            <td colspan="10" class="empty-state">没有更正回执</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section v-if="claimResult" class="panel">
      <header class="panel-head">
        <h3>领取结果</h3>
        <span class="panel-hint">{{ claimResult.领取人 }} · {{ claimResult.模式 }} · {{ claimResult.统计周期 }}</span>
      </header>
      <p class="panel-hint">{{ claimResult.message }}</p>
      <table v-if="claimResult.报告.length" class="data-table">
        <thead>
          <tr><th>报告编号</th><th>采集源</th><th>基础失败量</th><th>可入账失败量</th><th>应补差额</th></tr>
        </thead>
        <tbody>
          <tr v-for="report in claimResult.报告" :key="report.报告编号">
            <td>{{ report.报告编号 }}</td>
            <td>{{ report.采集源 }}</td>
            <td>{{ report.基础失败量 }}</td>
            <td>{{ report.可入账失败量 }}</td>
            <td>{{ report.应补差额 }}</td>
          </tr>
        </tbody>
      </table>
      <table class="data-table">
        <thead>
          <tr><th>类型</th><th>回执编号</th><th>报告编号</th><th>核销批次</th><th>数量</th><th>差额</th></tr>
        </thead>
        <tbody>
          <tr v-for="entry in claimResult.台账" :key="entry.编号">
            <td>{{ entry.类型 }}</td>
            <td>{{ entry.回执编号 || '—' }}</td>
            <td>{{ entry.报告编号 || '—' }}</td>
            <td>{{ entry.核销批次 || '—' }}</td>
            <td>{{ entry.数量 }}</td>
            <td>{{ entry.差额 }}</td>
          </tr>
          <tr v-if="!claimResult.台账.length">
            <td colspan="6" class="empty-state">本次没有新增台账</td>
          </tr>
        </tbody>
      </table>
    </section>

    <Teleport to="body">
      <div v-if="showCreateModal" class="modal-overlay" @click.self="showCreateModal = false">
        <div class="modal-card">
          <header class="modal-head">
            <h3>登记采集报告</h3>
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

      <div v-if="showDownloadModal" class="modal-overlay" @click.self="showDownloadModal = false">
        <div class="modal-card">
          <header class="modal-head">
            <h3>按统计周期下载快照包</h3>
            <button class="btn ghost" type="button" @click="showDownloadModal = false">&times;</button>
          </header>
          <form class="modal-body" @submit.prevent="submitDownload">
            <label class="modal-field">
              <span>统计周期</span>
              <input v-model="downloadPeriod" placeholder="例如 2026-W47" required />
            </label>
            <p class="panel-hint">只聚合已确认的采集结果；下载后会留档，之后按原下载标识仍可回查。</p>
            <footer class="modal-foot">
              <button class="btn" type="button" @click="showDownloadModal = false">取消</button>
              <button class="btn primary" type="submit">下载</button>
            </footer>
          </form>
        </div>
      </div>

      <div v-if="showCorrectionModal" class="modal-overlay" @click.self="showCorrectionModal = false">
        <div class="modal-card">
          <header class="modal-head">
            <h3>登记更正</h3>
            <button class="btn ghost" type="button" @click="showCorrectionModal = false">&times;</button>
          </header>
          <form class="modal-body" @submit.prevent="submitCorrection">
            <label class="modal-field">
              <span>统计周期</span>
              <input v-model="correctionFields['统计周期']" placeholder="例如 2026-W47" required />
            </label>
            <label class="modal-field">
              <span>采集源</span>
              <input v-model="correctionFields['采集源']" placeholder="例如 北区" required />
            </label>
            <label class="modal-field">
              <span>更正前失败量</span>
              <input v-model="correctionFields['更正前失败量']" inputmode="numeric" required />
            </label>
            <label class="modal-field">
              <span>更正后失败量</span>
              <input v-model="correctionFields['更正后失败量']" inputmode="numeric" required />
            </label>
            <label class="modal-field">
              <span>原下载标识（可选）</span>
              <input v-model="correctionFields['下载标识']" placeholder="例如 SNPS-20261120-0001" />
            </label>
            <p class="panel-hint">同一来源同一周期的同一次变化只计入一次，重复提交会返回原回执。</p>
            <footer class="modal-foot">
              <button class="btn" type="button" @click="showCorrectionModal = false">取消</button>
              <button class="btn primary" type="submit">提交更正</button>
            </footer>
          </form>
        </div>
      </div>

      <div v-if="showClaimModal" class="modal-overlay" @click.self="showClaimModal = false">
        <div class="modal-card">
          <header class="modal-head">
            <h3>{{ claimMode === '核销' ? '核销已记旧数' : '按周期领取入账' }}</h3>
            <button class="btn ghost" type="button" @click="showClaimModal = false">&times;</button>
          </header>
          <form class="modal-body" @submit.prevent="submitClaim">
            <label class="modal-field">
              <span>统计周期</span>
              <input v-model="claimFields['统计周期']" placeholder="例如 2026-W47" required />
            </label>
            <label class="modal-field">
              <span>领取人</span>
              <input v-model="claimFields['领取人']" placeholder="结算员姓名" required />
            </label>
            <p class="panel-hint">
              {{ claimMode === '核销'
                ? '按更正回执逐条核销旧数，同一个回执只会核销一次。'
                : '领取该周期可入账的报告，同时带出基础数、应补差额和已核销批次。' }}
            </p>
            <footer class="modal-foot">
              <button class="btn" type="button" @click="showClaimModal = false">取消</button>
              <button class="btn primary" type="submit">确认{{ claimMode }}</button>
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

type Snapshot = {
  下载标识: string
  统计周期: string
  生成时间: string
  明细条数: number
  成功量: number
  失败量: number
  状态: string
}

type SourceCheck = {
  采集源: string
  汇总记录数: number
  明细记录数: number
  汇总成功量: number
  汇总失败量: number
  一致: boolean
}

type Package = {
  快照标识: string
  统计周期: string
  合计: { 成功量: number; 失败量: number }
  来源汇总: { 采集源: string; 成功量: number; 失败量: number }[]
  明细: unknown[]
  核对: { 一致: boolean; 来源核对: SourceCheck[] }
}

type Receipt = {
  回执编号: string
  更正批次: string
  统计周期: string
  采集源: string
  关联下载标识: string
  基础失败量: number
  更正后失败量: number
  应补差额: number
  已核销条数: number
  核销批次: string[]
  状态: string
}

type ClaimResult = {
  ok: boolean
  message: string
  领取人: string
  统计周期: string
  模式: string
  报告: { 报告编号: string; 采集源: string; 基础失败量: number; 可入账失败量: number; 应补差额: number }[]
  台账: { 编号: string; 类型: string; 回执编号: string; 报告编号: string; 核销批次: string; 数量: number; 差额: number }[]
}

const ENDPOINT = '/api/report'
const columns = ["报告编号", "采集源", "统计周期", "总采集量", "成功量", "失败量", "平均耗秒", "生成时间"]
const actions = ["重新生成"]
const statuses = ["生成中", "已生成", "已发送"]
const stats = [{"label": "本周采集量", "value": 0}, {"label": "成功率", "value": 0}, {"label": "平均延迟", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const showCreateModal = ref(false)
const createFields = ref<Record<string, string>>({})

const snapshots = ref<Snapshot[]>([])
const selectedPackage = ref<Package | null>(null)
const showDownloadModal = ref(false)
const downloadPeriod = ref('')

const corrections = ref<Receipt[]>([])
const showCorrectionModal = ref(false)
const correctionFields = ref<Record<string, string>>({})
const showClaimModal = ref(false)
const claimMode = ref<'核销' | '入账'>('核销')
const claimFields = ref<Record<string, string>>({})
const claimResult = ref<ClaimResult | null>(null)

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

function openDownload() {
  errorMessage.value = ''
  downloadPeriod.value = rows.value[0]?.统计周期 ? String(rows.value[0].统计周期) : ''
  showDownloadModal.value = true
}

function submitDownload() {
  const period = downloadPeriod.value.trim()
  if (!period) {
    errorMessage.value = '请填写统计周期'
    return
  }
  showDownloadModal.value = false
  window.open(`${ENDPOINT}/snapshots/download?period=${encodeURIComponent(period)}`, '_blank')
  window.setTimeout(() => {
    void loadSnapshots()
    void loadCorrections()
  }, 800)
}

function openCorrection() {
  errorMessage.value = ''
  correctionFields.value = {
    统计周期: snapshots.value[0]?.统计周期 ?? '',
    下载标识: snapshots.value[0]?.下载标识 ?? '',
  }
  showCorrectionModal.value = true
}

function openClaim(mode: '核销' | '入账') {
  errorMessage.value = ''
  claimMode.value = mode
  claimFields.value = { 统计周期: snapshots.value[0]?.统计周期 ?? '', 领取人: '' }
  claimResult.value = null
  showClaimModal.value = true
}

async function viewSnapshot(snapshot: Snapshot) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/snapshots/${encodeURIComponent(snapshot.下载标识)}`)
    if (!response.ok) {
      throw new Error('快照读取失败')
    }
    selectedPackage.value = (await response.json()) as Package
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '快照读取失败'
  }
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

async function submitCorrection() {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/corrections`, {
      method: 'POST',
      body: JSON.stringify({ values: correctionFields.value }),
    })
    const data = await response.json()
    if (!data.ok) {
      throw new Error(data.message || '更正登记失败')
    }
    showCorrectionModal.value = false
    errorMessage.value = data.message
    await Promise.all([loadCorrections(), loadSnapshots()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '更正登记失败'
  }
}

async function submitClaim() {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/claims`, {
      method: 'POST',
      body: JSON.stringify({ values: { ...claimFields.value, 模式: claimMode.value } }),
    })
    const data = (await response.json()) as ClaimResult
    if (!data.ok) {
      throw new Error(data.message || '领取失败')
    }
    claimResult.value = data
    showClaimModal.value = false
    await loadCorrections()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '领取失败'
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
      throw new Error('采集报告动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '采集报告操作失败'
  }
}

async function loadSnapshots() {
  try {
    const response = await request(`${ENDPOINT}/snapshots`)
    if (!response.ok) {
      return
    }
    const payload = await response.json()
    snapshots.value = payload.items ?? []
  } catch {
    snapshots.value = []
  }
}

async function loadCorrections() {
  try {
    const response = await request(`${ENDPOINT}/corrections`)
    if (!response.ok) {
      return
    }
    const payload = await response.json()
    corrections.value = payload.items ?? []
  } catch {
    corrections.value = []
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('采集报告列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    updateStats()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '采集报告列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadSnapshots()
  void loadCorrections()
})
</script>
