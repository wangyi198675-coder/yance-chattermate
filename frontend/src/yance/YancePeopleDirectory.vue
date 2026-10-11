<script setup lang="ts">
import YanceWebShell from './components/YanceWebShell.vue'
import { onMounted, ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import CustomerAvatar from '@/components/people/CustomerAvatar.vue'
import { peopleService } from '@/services/people'
import type { PersonListItem } from '@/types/people'
import { personProfileLine } from '@/utils/personProfile'

const router = useRouter()
const search = ref('')
const submittedSearch = ref('')
const view = ref<'identified' | 'anonymous'>('identified')
const people = ref<PersonListItem[]>([])
const page = ref(1)
const pageSize = 20
const total = ref(0)
const loading = ref(true)
const error = ref('')
let request = 0
const pages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))
const nameOf = (person: PersonListItem) => person.name || person.email || person.phone || '未命名人物'
const stageOf = (person: PersonListItem) => ({
  visitor: '访客', lead: '潜在联系人', customer: '联系人',
}[person.lead_stage] ?? '人物')

async function loadPeople() {
  const requestId = ++request
  loading.value = true
  error.value = ''
  try {
    const result = await peopleService.listPeople({
      page: page.value, page_size: pageSize, search: submittedSearch.value || undefined, view: view.value,
    })
    if (requestId !== request) return
    people.value = result.items
    total.value = result.total
  } catch {
    if (requestId !== request) return
    people.value = []
    total.value = 0
    error.value = '人物目录读取失败，请检查连接后重试。'
  } finally {
    if (requestId === request) loading.value = false
  }
}
function changeView(next: 'identified' | 'anonymous') {
  view.value = next
  page.value = 1
  void loadPeople()
}
function submitSearch() {
  submittedSearch.value = search.value.trim()
  page.value = 1
  void loadPeople()
}
function turnPage(next: number) {
  if (next < 1 || next > pages.value || loading.value) return
  page.value = next
  void loadPeople()
}
onMounted(() => { void loadPeople() })
</script>

<template>
  <DashboardLayout>
    <YanceWebShell>
    <main class="yance-directory" data-yance-people-directory>
      <header class="directory-head">
        <div><p>言策 Yance</p><h1>人物目录</h1><span>读取已有联系人资料，不创建另一套客户数据库。</span></div>
        <nav aria-label="人物目录导航">
          <button type="button" @click="router.push('/yance/home')">首页</button>
          <button type="button" @click="router.push('/yance/relationship')">关系世界</button>
          <button type="button" @click="router.push('/yance')">对话</button>
        </nav>
      </header>
      <form class="directory-search" @submit.prevent="submitSearch">
        <label for="yance-people-search">查找人物</label>
        <input id="yance-people-search" v-model="search" type="search" placeholder="姓名、邮箱或电话" />
        <button type="submit">搜索</button>
      </form>
      <div class="directory-tabs" role="group" aria-label="人物范围">
        <button type="button" :aria-pressed="view === 'identified'" @click="changeView('identified')">已识别人物</button>
        <button type="button" :aria-pressed="view === 'anonymous'" @click="changeView('anonymous')">匿名访客</button>
      </div>
      <p v-if="loading" class="directory-state" role="status">正在读取真实人物资料…</p>
      <div v-else-if="error" class="directory-state" role="alert">{{ error }} <button type="button" @click="loadPeople">重试</button></div>
      <p v-else-if="!people.length" class="directory-state" data-empty-directory>暂无符合条件的人物。尚未连接平台时，这也可能是正常的空目录。</p>
      <ul v-else class="directory-list">
        <li v-for="person in people" :key="person.id">
          <button type="button" class="person-row" @click="router.push('/yance/relationship/' + encodeURIComponent(person.id))">
            <CustomerAvatar :profile="person.profile" :display-name="nameOf(person)" :anonymous="person.is_anonymous" :size="40" />
            <span class="person-name"><strong>{{ nameOf(person) }}</strong><small>{{ personProfileLine(person.profile, 'zh-CN') || person.email || person.phone || '暂无更多资料' }}</small></span>
            <span class="person-stage">{{ stageOf(person) }}</span>
            <span aria-hidden="true">›</span>
          </button>
        </li>
      </ul>
      <footer v-if="!loading && !error && total > 0" class="directory-pagination">
        <span>共 {{ total }} 人 · 第 {{ page }} / {{ pages }} 页</span>
        <button type="button" :disabled="page <= 1" @click="turnPage(page - 1)">上一页</button>
        <button type="button" :disabled="page >= pages" @click="turnPage(page + 1)">下一页</button>
      </footer>
    </main>
      </YanceWebShell>
  </DashboardLayout>
</template>

<style scoped>
.yance-directory { width: min(980px, calc(100% - 28px)); margin: 0 auto; padding: 22px 0 35px; color: var(--text); }
.directory-head { display:flex; justify-content:space-between; align-items:start; gap:12px; flex-wrap:wrap; }
.directory-head h1 { margin:0 0 7px; font-size:25px; }
.directory-head p,.directory-head span {color:var(--muted); font-size:12px; margin:0 0 4px;}
.directory-head nav,.directory-tabs,.directory-search,.directory-pagination { display:flex; align-items:center; flex-wrap:wrap; gap:8px; }
button {background:var(--bg2);border:1px solid var(--o14);color:var(--text);border-radius:8px;padding:8px 11px;cursor:pointer;}
button:disabled{opacity:.45;cursor:default;}
.directory-search { margin:20px 0 12px; }
.directory-search label {font-size:13px;}
.directory-search input{flex:1;min-width:160px;background:var(--bg);color:var(--text);border:1px solid var(--o14);border-radius:8px;padding:9px;}
.directory-tabs button[aria-pressed="true"]{background:var(--accent-bg-12);border-color:var(--accent-border);}
.directory-state{padding:25px 12px;color:var(--muted);background:var(--bg2);border-radius:12px;}
.directory-list{list-style:none;padding:0;margin:14px 0;}
.directory-list li{border-bottom:1px solid var(--o10);}
.person-row{width:100%;display:flex;align-items:center;gap:12px;text-align:left;border:0;border-radius:0;background:transparent;padding:12px 3px;}
.person-name{display:flex;flex:1;min-width:0;flex-direction:column;gap:3px;}
.person-name strong,.person-name small{overflow:hidden;white-space:nowrap;text-overflow:ellipsis;}
.person-name small,.person-stage,.directory-pagination{color:var(--muted);font-size:12px;}
.directory-pagination{justify-content:flex-end;}
@media(max-width:550px){.directory-head nav{width:100%;}.person-stage{display:none;}}
</style>
