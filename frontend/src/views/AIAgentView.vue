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
import { ref, defineAsyncComponent } from 'vue'
import DashboardLayout from '@/layouts/DashboardLayout.vue'

// Lazy load the AIAgentSetup component
const AIAgentSetup = defineAsyncComponent(() => 
  import('@/components/aiagent/AIAgentSetup.vue')
)

const selectedModel = ref('openai')
const isWorkflowFullscreen = ref(false)

// Handle fullscreen toggle from workflow editor
const handleWorkflowFullscreenToggle = (isFullscreen: boolean) => {
    isWorkflowFullscreen.value = isFullscreen
}
</script>

<template>
    <DashboardLayout :hide-sidebar="isWorkflowFullscreen" :hide-header="isWorkflowFullscreen">
        <div class="dashboard-container">
            <!-- Main Chat Area -->
            <div class="chat-section">
                <header v-if="!isWorkflowFullscreen" class="native-page-intro">
                    <h1>AI 智能体</h1>
                    <p>创建和管理智能体，查看真实配置及运行状态。</p>
                </header>
                <AIAgentSetup :model="selectedModel" @toggle-fullscreen="handleWorkflowFullscreenToggle" />
            </div>
        </div>
    </DashboardLayout>
</template>

<style scoped>
.dashboard-container {
    display: flex;
    min-height: 100%;
    position: relative;
}

.chat-section {
    flex: 1;
    min-width: 0;
}
.native-page-intro { padding: 14px 20px 0; }
.native-page-intro h1 { margin: 0; font-size: 19px; color: var(--text); }
.native-page-intro p { margin: 5px 0 12px; color: var(--muted); font-size: 12px; }
</style>