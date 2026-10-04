<template>
  <section class="page" data-module="roof">
    <header class="page-head">
      <div>
        <h2>顶板管理</h2>
        <p class="page-desc">离层量按小时上报，缺测时段如实标注缺口、绝不拿零值顶替；补采接续原记录，判定分清数据中断与离层加速。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记顶板监测</button>
        <button class="btn" type="button" @click="exportRows">导出顶板管理清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <section class="panel">
      <h3 class="panel-title">离层量监测（按小时上报）</h3>
      <form class="filter-bar" @submit.prevent="reloadReadings">
        <label class="filter-item">
          <span>所在工作面</span>
          <input v-model="query.workface" list="roof-workfaces" placeholder="选择或输入工作面" />
          <datalist id="roof-workfaces">
            <option v-for="name in workfaces" :key="name" :value="name" />
          </datalist>
        </label>
        <label class="filter-item">
          <span>时段开始</span>
          <input v-model="query.start" type="datetime-local" step="3600" />
        </label>
        <label class="filter-item">
          <span>时段结束</span>
          <input v-model="query.end" type="datetime-local" step="3600" />
        </label>
        <button class="btn" type="submit">查询</button>
      </form>

      <div v-if="assessment" class="assess-card" :data-conclusion="assessment.结论">
        <strong>判定结论：{{ assessment.结论 }}</strong>
        <p>{{ assessment.依据 }}</p>
        <p class="assess-suggestion">处置建议：{{ assessment.处置建议 }}</p>
      </div>

      <p v-if="readingMessage" class="notice-bar">{{ readingMessage }}</p>
      <ul v-if="readingGaps.length" class="gap-list">
        <li v-for="gap in readingGaps" :key="`${gap.缺口开始}-${gap.缺口结束}`">
          缺测时段：{{ gap.缺口开始 }} ~ {{ gap.缺口结束 }}（{{ gap.缺口小时数 }} 小时）
        </li>
      </ul>

      <table class="data-table">
        <thead>
          <tr>
            <th>采集时刻</th>
            <th>离层量(mm)</th>
            <th>上报方式</th>
            <th>版本</th>
            <th>更新时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in readings" :key="String(row.id)">
            <td>{{ row.采集时刻 }}</td>
            <td>{{ row.离层量 }}</td>
            <td>{{ row.上报方式 }}</td>
            <td>第 {{ row.版本 }} 版</td>
            <td>{{ row.更新时间 }}</td>
          </tr>
          <tr v-if="!readings.length">
            <td colspan="5" class="empty-state">暂无数据：该时段内没有任何上报，缺口时段见上方列表</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="panel">
      <h3 class="panel-title">补采登记</h3>
      <p class="panel-desc">数据中断恢复后在此补录：同一工作面同一采集时刻重复上报会接续原记录，只保留最新一版，缺口按采集时间自动回填。</p>
      <form class="filter-bar" @submit.prevent="submitReading">
        <label class="filter-item">
          <span>所在工作面</span>
          <input v-model="ingest.workface" list="roof-workfaces" placeholder="工作面" />
        </label>
        <label class="filter-item">
          <span>采集时刻</span>
          <input v-model="ingest.hour" type="datetime-local" step="3600" />
        </label>
        <label class="filter-item">
          <span>离层量(mm)</span>
          <input v-model="ingest.value" type="number" step="0.1" placeholder="缺测请留空时段，勿填 0" />
        </label>
        <label class="filter-item">
          <span>上报方式</span>
          <select v-model="ingest.mode">
            <option>实时上报</option>
            <option>补采回填</option>
          </select>
        </label>
        <button class="btn primary" type="submit">提交上报</button>
      </form>
      <p v-if="ingestMessage" class="notice-bar">{{ ingestMessage }}</p>
    </section>

    <section class="panel">
      <h3 class="panel-title">缺口记录</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th>所在工作面</th>
            <th>缺口开始</th>
            <th>缺口结束</th>
            <th>缺口小时数</th>
            <th>状态</th>
            <th>回填时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="gap in gaps" :key="String(gap.id)">
            <td>{{ gap.所在工作面 }}</td>
            <td>{{ gap.缺口开始 }}</td>
            <td>{{ gap.缺口结束 }}</td>
            <td>{{ gap.缺口小时数 }}</td>
            <td><span class="tag" :data-status="gap.状态">{{ gap.状态 }}</span></td>
            <td>{{ gap.回填时间 || '—' }}</td>
          </tr>
          <tr v-if="!gaps.length">
            <td colspan="6" class="empty-state">暂无缺口记录</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="panel">
      <h3 class="panel-title">顶板日报</h3>
      <form class="filter-bar" @submit.prevent="reloadReport">
        <label class="filter-item">
          <span>日报日期</span>
          <input v-model="reportDate" type="date" />
        </label>
        <button class="btn" type="submit">生成日报</button>
      </form>
      <template v-if="report">
        <div class="stat-row">
          <article class="stat-card">
            <span class="stat-label">待回填缺口</span>
            <strong class="stat-value">{{ report.缺口统计.待回填条数 }} 段 / {{ report.缺口统计.待回填小时 }} 小时</strong>
          </article>
          <article class="stat-card">
            <span class="stat-label">已回填缺口</span>
            <strong class="stat-value">{{ report.缺口统计.已回填条数 }} 段 / {{ report.缺口统计.已回填小时 }} 小时</strong>
          </article>
          <article class="stat-card">
            <span class="stat-label">生成时间</span>
            <strong class="stat-value">{{ report.生成时间 }}</strong>
          </article>
        </div>
        <table class="data-table">
          <thead>
            <tr>
              <th>所在工作面</th>
              <th>判定窗口</th>
              <th>结论</th>
              <th>处置建议</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in report.判定结论" :key="item.所在工作面">
              <td>{{ item.所在工作面 }}</td>
              <td>{{ item.判定窗口 || '—' }}</td>
              <td><span class="tag" :data-status="item.结论">{{ item.结论 }}</span></td>
              <td>{{ item.处置建议 }}</td>
            </tr>
          </tbody>
        </table>
      </template>
    </section>

    <section class="panel">
      <h3 class="panel-title">监测台账</h3>
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
            <td :colspan="columns.length + 1" class="empty-state">暂无顶板管理数据，可先登记顶板监测</td>
          </tr>
        </tbody>
      </table>

      <footer class="page-foot">
        <span>共 {{ total }} 条顶板管理记录</span>
        <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      </footer>
    </section>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, any>

const ENDPOINT = '/api/roof'
const columns = ["监测编号", "所在工作面", "离层量", "锚杆受力", "收敛变形", "监测日期", "监测人员", "顶板状态"]
const actions = ["离层预警", "变形报警", "加固完成"]

const stats = ref([
  { label: '监测工作面', value: 0 },
  { label: '待回填缺口', value: 0 },
  { label: '已回填缺口', value: 0 },
  { label: '离层加速工作面', value: 0 },
])

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

// 离层量监测查询：默认时段覆盖示例数据，打开页面即可看到内容。
const workfaces = ref<string[]>([])
const query = reactive({
  workface: '1301综采面',
  start: '2026-10-03T08:00',
  end: '2026-10-04T08:00',
})
const readings = ref<Row[]>([])
const readingGaps = ref<Row[]>([])
const readingMessage = ref('')
const assessment = ref<Row | null>(null)

// 补采登记表单。
const ingest = reactive({
  workface: '1302运输巷',
  hour: '2026-10-04T02:00',
  value: '',
  mode: '补采回填',
})
const ingestMessage = ref('')

const gaps = ref<Row[]>([])
const reportDate = ref('2026-10-04')
const report = ref<Row | null>(null)

function toHourText(local: string): string {
  return local.replace('T', ' ')
}

async function fetchJsonOrThrow(path: string, fallback: string): Promise<any> {
  const response = await request(path)
  if (!response.ok) {
    const detail = await response.json().catch(() => null)
    throw new Error(detail?.detail ?? fallback)
  }
  return response.json()
}

async function reloadReadings() {
  errorMessage.value = ''
  readingMessage.value = ''
  try {
    const params = new URLSearchParams({
      workface: query.workface,
      start: toHourText(query.start),
      end: toHourText(query.end),
    })
    const payload = await fetchJsonOrThrow(`${ENDPOINT}/readings?${params}`, '离层量查询失败')
    readings.value = payload.items ?? []
    readingGaps.value = payload.gaps ?? []
    readingMessage.value = payload.message ?? ''
    const verdict = await fetchJsonOrThrow(
      `${ENDPOINT}/assessment?workface=${encodeURIComponent(query.workface)}`,
      '判定结论读取失败',
    )
    assessment.value = verdict.items?.[0] ?? null
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '离层量查询失败'
  }
}

async function submitReading() {
  errorMessage.value = ''
  ingestMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/readings`, {
      method: 'POST',
      body: JSON.stringify({
        values: {
          所在工作面: ingest.workface,
          采集时刻: toHourText(ingest.hour),
          离层量: ingest.value,
          上报方式: ingest.mode,
        },
      }),
    })
    const payload = await response.json()
    ingestMessage.value = payload.message ?? ''
    if (!payload.ok) {
      return
    }
    // 补采会回填缺口、翻转判定，相关联的区块一起刷新。
    await Promise.all([reloadGaps(), reloadReport(), reloadWorkfaces()])
    if (ingest.workface === query.workface) {
      await reloadReadings()
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '上报失败'
  }
}

async function reloadGaps() {
  const payload = await fetchJsonOrThrow(`${ENDPOINT}/gaps`, '缺口记录读取失败')
  gaps.value = payload.items ?? []
  stats.value[1].value = gaps.value.filter((gap) => gap.状态 === '待回填').length
  stats.value[2].value = gaps.value.filter((gap) => gap.状态 === '已回填').length
}

async function reloadWorkfaces() {
  const payload = await fetchJsonOrThrow(`${ENDPOINT}/workfaces`, '工作面清单读取失败')
  workfaces.value = payload.items ?? []
  stats.value[0].value = workfaces.value.length
  const verdicts = await fetchJsonOrThrow(`${ENDPOINT}/assessment`, '判定结论读取失败')
  stats.value[3].value = (verdicts.items ?? []).filter((item: Row) => item.结论 === '离层加速').length
}

async function reloadReport() {
  errorMessage.value = ''
  try {
    report.value = await fetchJsonOrThrow(`${ENDPOINT}/daily-report?date=${reportDate.value}`, '顶板日报生成失败')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '顶板日报生成失败'
  }
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '顶板监测登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('顶板管理动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '顶板管理操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${params}`)
    if (!response.ok) {
      throw new Error('顶板监测列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '顶板管理列表读取失败'
  }
}

onMounted(async () => {
  await Promise.all([reload(), reloadWorkfaces(), reloadGaps(), reloadReport()])
  await reloadReadings()
})
</script>
