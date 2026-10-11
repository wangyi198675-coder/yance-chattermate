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
import DashboardLayout from '@/layouts/DashboardLayout.vue'
import AnalyticsDashboard from '@/components/analytics/AnalyticsDashboard.vue'
</script>

<template>
  <DashboardLayout>
    <header class="native-page-intro">
      <h1>数据分析</h1>
      <p>按时间范围查看会话、智能体表现与客户反馈；数据以实际服务返回为准。</p>
    </header>
    <AnalyticsDashboard />
  </DashboardLayout>
</template>

<style scoped>
.native-page-intro { padding: 14px 22px 0; }
.native-page-intro h1 { margin: 0; color: var(--text); font-size: 19px; }
.native-page-intro p { margin: 5px 0 12px; color: var(--muted); font-size: 12px; }
</style>