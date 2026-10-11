/*
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
*/

import { defineComponent, h } from 'vue'
import { createRouter, createWebHistory, RouterLink } from 'vue-router'
import type { RouteLocationNormalized, NavigationGuardNext } from 'vue-router'
import { userService } from '@/services/user'
import { classifySetupFailure, getSetupStatus, privateBootstrap } from '@/services/organization'
import { canAccessMatchedPaths } from '@/router/routePermissions'
import { getApiUrl } from '@/config/api'
import HumanAgentView from '@/views/HumanAgentView.vue'
import OrganizationSettings from '@/views/settings/OrganizationSettings.vue'
import AIConfigSettings from '@/views/settings/AIConfigSettings.vue'
import IntegrationsSettings from '@/views/settings/IntegrationsSettings.vue'
import WidgetAppsSettings from '@/views/settings/WidgetAppsSettings.vue'
import UserSettingsView from '@/views/UserSettingsView.vue'
import { useEnterpriseFeatures } from '@/composables/useEnterpriseFeatures'

// Initialize enterprise features
const { hasEnterpriseModule, loadModule, moduleImports, NotAvailableComponent } =
  useEnterpriseFeatures()

// Router-only user-facing states. These do not replace the native Agent workflow
// editor or change RBAC; the separate /workflow editor route never existed.
const routeNotice = (
  name: string,
  section: string,
  heading: string,
  description: string,
  primaryPath: string,
  primaryLabel: string,
) => defineComponent({
  name,
  setup: () => () => h('main', {
    style: {
      minHeight: '100dvh', boxSizing: 'border-box', padding: 'clamp(24px, 7vw, 70px)',
      background: 'var(--bg, #141722)', color: 'var(--text, #f5f1eb)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontFamily: 'var(--font-sans, sans-serif)',
    },
  }, [
    h('section', {
      style: {
        width: '100%', maxWidth: '560px', padding: '28px',
        background: 'var(--surface, #1c2030)', border: '1px solid var(--o12, #45404d)',
        borderRadius: '16px', boxSizing: 'border-box',
      },
    }, [
      h('p', { style: { color: 'var(--accent-ink, #cba768)', margin: '0 0 12px' } }, `言策 · ${section}`),
      h('h1', { style: { fontSize: '24px', lineHeight: '1.3', margin: '0 0 12px' } }, heading),
      h('p', { style: { fontSize: '14px', lineHeight: '1.7', margin: '0 0 24px', color: 'var(--muted, #c8c2c9)' } }, description),
      h('nav', { 'aria-label': '言策页面导航', style: { display: 'flex', flexWrap: 'wrap', gap: '16px', alignItems: 'center' } }, [
        h(RouterLink, {
          to: primaryPath,
          style: { color: 'var(--accent-ink, #e3c28d)', fontWeight: '600', textDecoration: 'underline' },
        }, { default: () => primaryLabel }),
        h(RouterLink, {
          to: '/yance',
          style: { color: 'var(--text, #f5f1eb)', textDecoration: 'underline' },
        }, { default: () => '返回言策' }),
      ]),
    ]),
  ]),
})

const WorkflowRouteEntry = routeNotice(
  'YanceWorkflowEntry', '原生工作流', '工作流在 AI Agent 中管理',
  '当前没有独立的工作流编辑页。请进入 AI Agent，选择 Agent 后查看工作流标签。实际编辑能力取决于原生功能资格和账号权限。',
  '/ai-agents', '前往 AI Agent',
)

const ForbiddenYanceRoute = routeNotice(
  'YanceForbidden', '访问权限', '无权访问此页面',
  '当前账号没有访问这个功能的权限。言策保留 ChatterMate 的原生权限校验，不会自动提升权限。',
  '/settings/user', '查看我的账号',
)

// Base routes
const baseRoutes = [
  {
    path: '/',
    // A function, not a string: permissions live in localStorage and are not
    // readable when this module is first evaluated. Also the landing spot for
    // an installed PWA (manifest start_url) and for pushes with no session.
    //
    // Only resolve with a session in hand. Resolving for a signed-out visitor
    // yields the no-permission floor, which the guard then carries into
    // ?redirect= and honours after login — landing an admin on User Settings.
    redirect: '/yance',
  },
  {
    path: '/login',
    name: 'login',
    redirect: '/yance',
    meta: { requiresAuth: false },
  },
  {
    path: '/setup',
    name: 'setup',
    redirect: '/yance',
    meta: { requiresAuth: false },
  },
  {
    // Workflow is managed on each native AI Agent's Workflow tab. This
    // entry explains that scope instead of silently falling back to /yance.
    path: '/workflow',
    name: 'workflow-entry',
    component: WorkflowRouteEntry,
    meta: { requiresAuth: true },
  },
  {
    path: '/ai-agents',
    name: 'ai-agents',
    component: () => import('@/views/AIAgentView.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/analytics',
    name: 'analytics',
    component: () => import('@/views/AnalyticsView.vue'),
    meta: {
      requiresAuth: true,
      layout: 'dashboard',
      title: 'Analytics Dashboard',
    },
  },
  {
    path: '/knowledge',
    name: 'knowledge',
    component: () => import('@/views/KnowledgeView.vue'),
    meta: {
      requiresAuth: true,
      layout: 'dashboard',
      title: 'Knowledge Base',
    },
  },
  {
    path: '/faq',
    name: 'faq',
    component: () => import('@/views/FaqView.vue'),
    meta: {
      requiresAuth: true,
      layout: 'dashboard',
      title: 'FAQ & Help Center',
    },
  },
  {
    path: '/tickets',
    name: 'tickets',
    component: () => import('@/views/TicketsView.vue'),
    meta: {
      requiresAuth: true,
      layout: 'dashboard',
      title: 'Tickets',
    },
  },
  {
    path: '/tickets/:id',
    name: 'ticket-detail',
    component: () => import('@/views/TicketDetailView.vue'),
    meta: {
      requiresAuth: true,
      layout: 'dashboard',
      title: 'Ticket',
    },
  },
  {
    path: '/settings/ticketing',
    name: 'ticketing-settings',
    component: () => import('@/views/settings/TicketingSettings.vue'),
    meta: {
      requiresAuth: true,
      layout: 'dashboard',
      title: 'Ticketing Settings',
    },
  },
  {
    path: '/widget/:id',
    name: 'widget',
    component: () => import('@/webclient/WidgetBuilder.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/conversations',
    name: 'conversations',
    component: () => import('../views/ConversationsView.vue'),
    // Any inbox grant — own/group chats, the unclaimed queue, or everything
    meta: {
      requiresAuth: true,
    },
  },
  {
    path: '/people',
    name: 'people',
    // Without meta the page rendered and then 403'd on every request; the
    // guard sends users who can't read the directory to /403 instead.
    component: () => import('../views/PeopleView.vue'),
    meta: {
      requiresAuth: true,
    },
  },
  {
    path: '/human-agents',
    name: 'human-agents',
    component: HumanAgentView,
    meta: { requiresAuth: true },
  },
  {
    path: '/settings/organization',
    name: 'organization-settings',
    component: OrganizationSettings,
    meta: {
      requiresAuth: true,
      layout: 'dashboard',
    },
  },
  {
    path: '/settings/ai-config',
    name: 'ai-config-settings',
    component: AIConfigSettings,
    meta: {
      requiresAuth: true,
      layout: 'dashboard',
    },
  },
  {
    path: '/settings/integrations',
    name: 'integrations-settings',
    component: IntegrationsSettings,
    meta: {
      requiresAuth: true,
      layout: 'dashboard',
    },
  },
  {
    path: '/settings/widget-apps',
    name: 'widget-apps',
    component: WidgetAppsSettings,
    meta: {
      requiresAuth: true,
      layout: 'dashboard',
    },
  },
  {
    path: '/settings/user',
    name: 'user-settings',
    component: UserSettingsView,
    meta: {
      requiresAuth: true,
      layout: 'dashboard',
    },
  },
  {
    path: '/yance/home',
    name: 'yance-home',
    component: () => import('@/yance/YanceHomeNativeComposition.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/yance/settings',
    name: 'yance-settings',
    component: () => import('@/yance/YanceSettingsNativeComposition.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/yance/people',
    name: 'yance-people-directory',
    component: () => import('@/yance/YancePeopleDirectory.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/yance/platform-accounts',
    name: 'yance-platform-accounts',
    component: () => import('@/yance/YancePlatformAccounts.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/yance/manage/:tool(ai|user|organization)',
    name: 'yance-native-settings-tool',
    component: () => import('@/yance/YanceNativeSettingsTool.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/yance/relationship/:customerId?',
    name: 'yance-relationship-world',
    component: () => import('@/yance/YanceRelationshipWorld.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/yance/startup',
    name: 'yance-startup-state',
    component: () => import('@/yance/YanceStartupStateView.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/yance',
    name: 'yance',
    component: () => import('@/yance/YanceNativeHostView.vue'),
    meta: { requiresAuth: true },
  },  {
    // Registered, and reachable: the guard used to send denials to /403 with
    // no such route, so they fell through this catch-all onto /ai-agents —
    // which had no meta.permissions and therefore always rendered. A user was
    // silently dropped on a page they had just been refused.
    path: '/403',
    name: 'forbidden',
    component: ForbiddenYanceRoute,
    // The display is Chinese; the existing RBAC guard remains authoritative.
    meta: { requiresAuth: true },
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/yance',
  },
]

// Helper function to load enterprise component
const loadEnterpriseComponent = (path: string) => {
  if (!hasEnterpriseModule) {
    return NotAvailableComponent
  }
  return async () => {
    const module = await loadModule(path)
    return module?.default || NotAvailableComponent
  }
}

// Combine routes based on module availability
const allRoutes = hasEnterpriseModule
  ? [
      ...baseRoutes,
      {
        path: '/signup',
        name: 'signup',
        component: loadEnterpriseComponent(moduleImports.signupView),
        meta: { requiresAuth: false },
      },
      {
        path: '/explore',
        name: 'explore',
        component: loadEnterpriseComponent(moduleImports.exploreView),
        meta: { requiresAuth: false },
      },
      {
        path: '/settings/subscription',
        name: 'subscription',
        component: loadEnterpriseComponent(moduleImports.subscriptionView),
        meta: {
          requiresAuth: true,
          layout: 'dashboard',
          title: 'Subscription Plans',
        },
      },
      {
        path: '/settings/subscription/setup/:planId',
        name: 'billing-setup',
        component: loadEnterpriseComponent(moduleImports.billingSetupView),
        meta: { requiresAuth: true },
      },
      {
        path: '/shopify/session-token-bounce',
        name: 'shopify-session-token-bounce',
        component: loadEnterpriseComponent(moduleImports.shopifySessionTokenBounce),
        meta: { requiresAuth: false },
      },
      {
        path: '/shopify/connect',
        name: 'shopify-connect',
        component: loadEnterpriseComponent(moduleImports.shopifyConnect),
        meta: { requiresAuth: false }, // Session token auth instead
      },
      {
        path: '/shopify/auth-complete',
        name: 'shopify-auth-complete',
        component: loadEnterpriseComponent(moduleImports.shopifyAuthComplete),
        meta: { requiresAuth: false },
      },
      {
        path: '/shopify/agent-selection',
        name: 'shopify-agent-selection',
        component: loadEnterpriseComponent(moduleImports.shopifyAgentSelection),
        meta: { requiresAuth: false }, // Session token auth instead
      },
      {
        path: '/shopify/agent-management',
        name: 'shopify-agent-management',
        component: loadEnterpriseComponent(moduleImports.shopifyAgentManagement),
        meta: { requiresAuth: false }, // Session token auth instead
      },
      {
        path: '/shopify/inbox',
        name: 'shopify-inbox',
        component: loadEnterpriseComponent(moduleImports.shopifyInbox),
        meta: { requiresAuth: false },
      },
      {
        path: '/shopify/pricing',
        name: 'shopify-pricing',
        component: loadEnterpriseComponent(moduleImports.shopifyPricing),
        meta: { requiresAuth: false },
      },
    ]
  : baseRoutes

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: allRoutes,
})

// Keep browser/WebView titles grounded in the requested product even while
// native upstream CRUD screens await a separately authorized layout bridge.
const nativeBrowserTitles: Record<string, string> = {
  '/workflow': '言策 · 原生工作流',
  '/403': '言策 · 无权访问',
  '/ai-agents': '言策 · AI 智能体',
  '/knowledge': '言策 · 知识库',
  '/tickets': '言策 · 工单',
  '/analytics': '言策 · 数据分析',
  '/faq': '言策 · 帮助中心',
  '/settings/ai-config': '言策 · AI 模型配置',
  '/settings/widget-apps': '言策 · 小组件',
}
router.afterEach((to) => {
  if (to.path === '/yance' || to.path.startsWith('/yance/')) {
    document.title = '言策'
  } else if (nativeBrowserTitles[to.path]) {
    document.title = nativeBrowserTitles[to.path]
  }
})
// Add subscription guard only if enterprise module is available
if (hasEnterpriseModule) {
  const loadGuard = async () => {
    try {
      const guardModule = await loadModule(moduleImports.subscriptionGuard)
      const subscriptionGuard = guardModule?.subscriptionGuard
      if (subscriptionGuard) {
        router.beforeEach((to, from, next) => {
          if (to.path === '/' || to.path.startsWith('/yance')) {
            return next()
          }
          return subscriptionGuard(to, from, next)
        })
      }
    } catch (error) {
      console.warn('Enterprise subscription guard not available:', error)
    }
  }
  loadGuard()
}

// Navigation guard
router.beforeEach(async (to, from, next) => {
  if (to.path.startsWith('/shopify/')) {
    return next()
  }

  if (to.name === 'yance-startup-state') {
    return next()
  }

  const setupState = await getSetupStatus()

  if (setupState === 'BACKEND_UNAVAILABLE' || setupState === 'NETWORK_ERROR') {
    return next({
      name: 'yance-startup-state',
      query: { state: setupState },
    })
  }

  if (setupState === 'SETUP_INCOMPLETE' || !userService.isAuthenticated()) {
    try {
      await privateBootstrap()
    } catch (error) {
      return next({
        name: 'yance-startup-state',
        query: { state: classifySetupFailure(error) },
      })
    }
  }

  if (to.path === '/login' || to.path === '/setup') {
    return next('/yance')
  }

  const requiresAuth = to.matched.some((record) => record.meta.requiresAuth)
  if (requiresAuth && !userService.isAuthenticated()) {
    return next('/yance')
  }

  // /workflow is a native AI Agent entry point, not an unguarded shortcut.
  // Reuse the same permissions as the actual /ai-agents CRUD destination.
  if (to.name === 'workflow-entry' && !canAccessMatchedPaths(['/ai-agents'])) {
    return next({ name: 'forbidden' })
  }

  if (!canAccessMatchedPaths(to.matched.map((record) => record.path))) {
    return next({ name: 'forbidden' })
  }

  return next()
})
export default router
