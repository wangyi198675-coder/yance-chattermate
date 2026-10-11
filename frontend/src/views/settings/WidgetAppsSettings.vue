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
import WidgetAppList from '@/components/widget-app/WidgetAppList.vue'
</script>

<template>
  <DashboardLayout>
    <div class="dashboard-container">
      <div class="settings-section">
        <header class="native-page-intro">
          <h1>网页组件管理</h1>
          <p>查看已创建的组件应用，管理配置与密钥。权限及可用状态由真实服务决定。</p>
        </header>
        <WidgetAppList />
      </div>
    </div>
  </DashboardLayout>
</template>

<style scoped>
.dashboard-container {
  display: flex;
  height: 100%;
  position: relative;
}

.settings-section {
  flex: 1;
  padding: var(--space-lg);
}
.native-page-intro h1 { margin: 0; font-size: 19px; color: var(--text); }
.native-page-intro p { margin: 5px 0 14px; color: var(--muted); font-size: 12px; }
</style>
