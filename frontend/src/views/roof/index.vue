<template>
  <section class="page" data-module="roof">
    <header class="page-head">
      <div>
        <h2>顶板管理管理</h2>
        <p class="page-desc">维护顶板监测，围绕监测编号、所在工作面、离层量、锚杆受力做登记、筛选与状态流转。</p>
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

    <section class="panel">
      <header class="panel-head">
        <h3>离层量逐时监测</h3>
        <p class="panel-desc">缺测时段明示「暂无数据」并列出缺口，不以零值顶替；离层量达到 {{ warnLimit }}mm 即超出预警区间。</p>
      </header>
      <form class="filter-bar" @submit.prevent="loadSeries">
        <label class="filter-item">
          <span>工作面</span>
          <select v-model="seriesFace">
            <option v-for="face in faces" :key="face.工作面" :value="face.工作面">{{ face.工作面 }}</option>
          </select>
        </label>
        <label class="filter-item">
          <span>监测日期</span>
          <input v-model="seriesDate" type="date" />
        </label>
        <button class="btn" type="submit">查询</button>
      </form>

      <table class="data-table">
        <thead>
          <tr><th>时刻</th><th>离层量(mm)</th><th>状态</th><th>数据来源</th></tr>
        </thead>
        <tbody>
          <tr v-for="slot in slots" :key="slot.时刻" :class="{ 'missing-row': slot.状态 === '暂无数据' }">
            <td>{{ formatHour(slot.时刻) }}</td>
            <td>
              <span v-if="slot.状态 === '暂无数据'" class="missing-text">暂无数据</span>
              <template v-else>{{ slot.离层量 }}</template>
            </td>
            <td>
              <span :class="['tag', slot.状态 === '超限' ? 'tag-danger' : slot.状态 === '暂无数据' ? 'tag-muted' : 'tag-ok']">
                {{ slot.状态 }}
              </span>
            </td>
            <td>
              <template v-if="slot.状态 === '暂无数据'">—</template>
              <template v-else>
                {{ slot.补采 ? '补采回填' : '实时上报' }}<template v-if="slot.版本 > 1">（第{{ slot.版本 }}版）</template>
              </template>
            </td>
          </tr>
          <tr v-if="!slots.length">
            <td colspan="4" class="empty-state">请选择工作面与监测日期后查询</td>
          </tr>
        </tbody>
      </table>

      <div v-if="gaps.length" class="gap-panel">
        <strong>缺口时段（{{ gaps.length }} 段，共 {{ gapHours }} 小时）</strong>
        <ul>
          <li v-for="gap in gaps" :key="gap.开始">
            {{ formatHour(gap.开始) }} ~ {{ formatHour(gap.结束) }}，缺测 {{ gap.缺测小时 }} 小时
          </li>
        </ul>
      </div>

      <div v-if="verdicts.length" class="verdict-panel">
        <strong>超限判定（连续超出预警区间）</strong>
        <ul>
          <li v-for="verdict in verdicts" :key="`${verdict.开始}-${verdict.结束}`">
            <span :class="['tag', verdict.原因 === '离层加速' ? 'tag-danger' : verdict.原因 === '数据中断' ? 'tag-warn' : 'tag-info']">
              {{ verdict.原因 }}
            </span>
            {{ formatHour(verdict.开始) }} ~ {{ formatHour(verdict.结束) }}（连续 {{ verdict.连续小时 }} 小时，峰值 {{ verdict.峰值 }}mm）：
            {{ verdict.结论 }}；处置：{{ verdict.处置 }}
          </li>
        </ul>
      </div>
    </section>

    <section class="panel">
      <header class="panel-head">
        <h3>补采登记</h3>
        <p class="panel-desc">数据中断后补采的数据按采集时刻续接原序列，同一小时只保留最新一版，缺口统计随之下调。</p>
      </header>
      <form class="filter-bar" @submit.prevent="submitBackfill">
        <label class="filter-item">
          <span>工作面</span>
          <select v-model="backfillFace">
            <option v-for="face in faces" :key="face.工作面" :value="face.工作面">{{ face.工作面 }}</option>
          </select>
        </label>
        <label class="filter-item">
          <span>采集时刻</span>
          <input v-model="backfillMoment" type="datetime-local" step="3600" />
        </label>
        <label class="filter-item">
          <span>离层量(mm)</span>
          <input v-model="backfillValue" type="number" min="0" step="0.1" placeholder="实测离层量" />
        </label>
        <button class="btn primary" type="submit">提交补采</button>
      </form>
      <p v-if="backfillMessage" class="panel-note">{{ backfillMessage }}</p>
    </section>

    <section class="panel">
      <header class="panel-head">
        <h3>顶板日报</h3>
        <p class="panel-desc">缺口时段与判定结论随逐时数据实时汇总，补采回填后缺口统计跟着一起变。</p>
      </header>
      <form class="filter-bar" @submit.prevent="loadReport">
        <label class="filter-item">
          <span>日报日期</span>
          <input v-model="reportDate" type="date" />
        </label>
        <button class="btn" type="submit">生成日报</button>
      </form>

      <div v-if="report" class="stat-row">
        <article v-for="(value, label) in report.summary" :key="label" class="stat-card">
          <span class="stat-label">{{ label }}</span>
          <strong class="stat-value">{{ value }}</strong>
        </article>
      </div>

      <table v-if="report" class="data-table">
        <thead>
          <tr><th>工作面</th><th>实到/应到</th><th>缺测小时</th><th>缺口时段</th><th>判定结论</th></tr>
        </thead>
        <tbody>
          <tr v-for="face in report.faces" :key="face.工作面">
            <td>{{ face.工作面 }}</td>
            <td>{{ face.实到小时 }}/{{ face.应到小时 }}</td>
            <td>{{ face.缺测小时 }}</td>
            <td>
              <template v-if="face.缺口时段.length">
                <div v-for="gap in face.缺口时段" :key="gap.开始">
                  {{ formatHour(gap.开始) }} ~ {{ formatHour(gap.结束) }}（{{ gap.缺测小时 }}小时）
                </div>
              </template>
              <span v-else class="muted-text">无缺口</span>
            </td>
            <td>
              <template v-if="face.判定结论.length">
                <div v-for="verdict in face.判定结论" :key="`${verdict.开始}-${verdict.结束}`">
                  <span :class="['tag', verdict.原因 === '离层加速' ? 'tag-danger' : verdict.原因 === '数据中断' ? 'tag-warn' : 'tag-info']">
                    {{ verdict.原因 }}
                  </span>
                  {{ verdict.结论 }}；处置：{{ verdict.处置 }}
                </div>
              </template>
              <span v-else class="muted-text">无超限判定</span>
            </td>
          </tr>
          <tr v-if="!report.faces.length">
            <td colspan="5" class="empty-state">该日期没有工作面监测记录</td>
          </tr>
        </tbody>
      </table>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

interface FaceItem {
  工作面: string
  最新采集时刻: string
}

interface Slot {
  时刻: string
  离层量: number | null
  状态: string
  补采: boolean
  版本: number
}

interface Gap {
  开始: string
  结束: string
  缺测小时: number
}

interface Verdict {
  工作面: string
  开始: string
  结束: string
  连续小时: number
  缺测小时: number
  峰值: number
  原因: string
  结论: string
  处置: string
}

interface FaceReport {
  工作面: string
  应到小时: number
  实到小时: number
  缺测小时: number
  缺口时段: Gap[]
  判定结论: Verdict[]
}

interface DailyReport {
  日期: string
  预警上限: number
  summary: Record<string, number>
  faces: FaceReport[]
}

const ENDPOINT = '/api/roof'
const columns = ["监测编号", "所在工作面", "离层量", "锚杆受力", "收敛变形", "监测日期", "监测人员", "顶板状态"]
const actions = ["离层预警", "变形报警", "加固完成"]
const statuses = ["稳定", "离层预警", "变形超标", "已加固"]
const stats = [{"label": "稳定区域", "value": 0}, {"label": "预警区域", "value": 0}, {"label": "报警区域", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const faces = ref<FaceItem[]>([])
const seriesFace = ref('')
const seriesDate = ref('')
const slots = ref<Slot[]>([])
const gaps = ref<Gap[]>([])
const verdicts = ref<Verdict[]>([])
const warnLimit = ref(100)

const backfillFace = ref('')
const backfillMoment = ref('')
const backfillValue = ref('')
const backfillMessage = ref('')

const reportDate = ref('')
const report = ref<DailyReport | null>(null)

const gapHours = computed(() => gaps.value.reduce((sum, gap) => sum + gap.缺测小时, 0))

function formatHour(text: string) {
  return text.replace('T', ' ')
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
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
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

async function loadFaces() {
  try {
    const response = await request(`${ENDPOINT}/faces`)
    if (!response.ok) {
      throw new Error('工作面清单读取失败')
    }
    const payload = await response.json()
    faces.value = payload.items ?? []
    if (faces.value.length && !seriesFace.value) {
      seriesFace.value = faces.value[0].工作面
      backfillFace.value = faces.value[0].工作面
      const latest = faces.value[0].最新采集时刻.slice(0, 10)
      seriesDate.value = latest
      reportDate.value = latest
      backfillMoment.value = `${latest}T00:00`
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '工作面清单读取失败'
  }
}

async function loadSeries() {
  if (!seriesFace.value || !seriesDate.value) {
    return
  }
  try {
    const query = new URLSearchParams({ face: seriesFace.value, date: seriesDate.value }).toString()
    const response = await request(`${ENDPOINT}/readings?${query}`)
    if (!response.ok) {
      throw new Error('逐时序列读取失败')
    }
    const payload = await response.json()
    slots.value = payload.slots ?? []
    gaps.value = payload.gaps ?? []
    verdicts.value = payload.verdicts ?? []
    warnLimit.value = payload.预警上限 ?? warnLimit.value
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '逐时序列读取失败'
  }
}

async function submitBackfill() {
  backfillMessage.value = ''
  if (!backfillFace.value || !backfillMoment.value || backfillValue.value === '') {
    backfillMessage.value = '工作面、采集时刻、离层量都要填，缺一项不入库'
    return
  }
  try {
    const response = await request(`${ENDPOINT}/readings`, {
      method: 'POST',
      body: JSON.stringify({
        items: [{ 工作面: backfillFace.value, 采集时刻: backfillMoment.value, 离层量: Number(backfillValue.value) }],
      }),
    })
    const payload = await response.json()
    backfillMessage.value = payload.message ?? '补采结果未返回'
    if (payload.ok) {
      backfillValue.value = ''
      await Promise.all([loadSeries(), loadReport(), loadFaces()])
    }
  } catch (error) {
    backfillMessage.value = error instanceof Error ? error.message : '补采提交失败'
  }
}

async function loadReport() {
  if (!reportDate.value) {
    return
  }
  try {
    const response = await request(`${ENDPOINT}/daily-report?date=${reportDate.value}`)
    if (!response.ok) {
      throw new Error('顶板日报读取失败')
    }
    report.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '顶板日报读取失败'
  }
}

onMounted(async () => {
  await reload()
  await loadFaces()
  await Promise.all([loadSeries(), loadReport()])
})
</script>
