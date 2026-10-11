<!--
Copyright 2024-2026 ChatterMate

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
-->
<script setup lang="ts">
import { computed } from 'vue'
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import KnowledgeExplorer from '@/components/knowledge/KnowledgeExplorer.vue'
import { userService } from '@/services/user'

const organizationId = computed(() => userService.getCurrentUser()?.organization_id ?? '')

const description = '管理智能体使用的知识来源、页面和内容。可以检查抓取结果、编辑页面，并决定哪些内容保留在知识库。'
</script>

<template>
  <DashboardLayout>
    <div class="knowledge-view">
      <KnowledgeExplorer
        v-if="organizationId"
        mode="org"
        variant="page"
        title="知识库"
        :description="description"
        :organization-id="organizationId"
        :show-plan-meters="true"
      />
      <p v-else class="organization-warning" role="status">当前组织信息不可用，无法读取知识库。请检查当前账号的组织权限。</p>
    </div>
  </DashboardLayout>
</template>

<style scoped>
.organization-warning { color: var(--muted); padding: 20px; background: var(--surface); border: 1px solid var(--o08); border-radius: 12px; }
.knowledge-view {
  max-width: 1240px;
  margin: 0 auto;
  padding: 32px 24px 60px;
}
</style>
