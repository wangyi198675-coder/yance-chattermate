<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import YanceGlobalGirlfriend from './YanceGlobalGirlfriend.vue'
import YanceNativeCapabilityHub from './YanceNativeCapabilityHub.vue'

const props = withDefaults(defineProps<{ caption?: string; connectionSummary?: string }>(), { caption: '', connectionSummary: '平台状态请在账号页核对' })
const router = useRouter()
const currentPath = computed(() => router.currentRoute?.value?.path || window.location.pathname)
const girlfriend = ref(false)

const links = [
  { path: '/yance/home', label: '首页', mark: '⌂' },
  { path: '/yance', label: '对话', mark: '☰' },
  { path: '/yance/relationship', label: '关系世界', mark: '♡' },
  { path: '/yance/people', label: '人物', mark: '♙' },
  { path: '/yance/settings', label: '设置', mark: '⚙' },
]
const selected = (path: string) =>
  path === '/yance/relationship' ? currentPath.value.startsWith(path)
    : path === '/yance' ? currentPath.value === '/yance' : currentPath.value === path
</script>

<template>
  <section class="yance-web-shell" data-yance-rev34-shell data-design-version="REV3.4-P1R1">
    <aside class="yance-web-nav" aria-label="言策导航">
      <router-link to="/yance/home" class="yance-web-brand" aria-label="言策首页">
        <strong>言策</strong><span>YANCE · DESKTOP</span>
      </router-link>
      <nav class="yance-web-routes" aria-label="主要页面">
        <router-link
          v-for="link in links" :key="link.path" :to="link.path"
          class="yance-web-route" :class="{ selected: selected(link.path) }"
          :aria-current="selected(link.path) ? 'page' : undefined"
        ><span aria-hidden="true">{{ link.mark }}</span> {{ link.label }}</router-link>
      </nav>
      <YanceNativeCapabilityHub />
      <div class="yance-web-nav-bottom">
        <button type="button" class="yance-web-task" data-yance-global-girlfriend-launcher
          aria-keyshortcuts="Control+Shift+G" @click="girlfriend = true">✦ 闺蜜大脑 · 任务</button>
        <button type="button" class="yance-web-connection" data-yance-live-channel-status
          @click="router.push('/yance/platform-accounts')">{{ props.connectionSummary }}</button>
        <small>同一会话 · 一条时间线<br>唯一输入框 · 不自动发送</small>
      </div>
    </aside>
    <div class="yance-web-content" data-yance-real-content>
      <slot />
    </div>
    <YanceGlobalGirlfriend v-model:open="girlfriend" />
  </section>
</template>

<style>
.yance-web-shell {
  --bg:#151622;--bg2:#211e2a;--bg3:#2b2230;--text:#efe8ee;--text2:#d3c8d3;
  --text3:#ad9fae;--muted:#a69cae;--o05:#ffffff0a;--o08:#ffffff14;--o10:#ffffff19;
  --o14:#ffffff26;--accent:#bd93d2;--accent-bg-12:#79518f33;--accent-border:#9671a7;
  --warning:#efb58e;--space-xs:6px;--space-sm:10px;
  width:min(920px,100vw);height:min(620px,100dvh);padding:16px;display:flex;gap:12px;
  background:radial-gradient(ellipse at 6% 4%,#462c2940,transparent 52%),
  radial-gradient(ellipse at 95% 95%,#51346555,transparent 47%),#0e101b;
  color:var(--text);font-family:'Noto Sans CJK SC','Microsoft YaHei',Inter,sans-serif;
  font-size:12px;line-height:1.45;overflow:hidden;box-sizing:border-box;
  border-radius:13px;margin:0 auto;
}
.yance-web-shell *, .yance-web-shell *::before, .yance-web-shell *::after{box-sizing:border-box}
.yance-web-shell button,.yance-web-shell input,.yance-web-shell textarea,.yance-web-shell select{
  font:inherit;color:inherit}
.yance-web-shell button{cursor:pointer}
.yance-web-shell button:disabled{cursor:not-allowed;opacity:.5}
.yance-web-shell :is(button,a,input,select,textarea):focus-visible{outline:2px solid #edc089;outline-offset:2px}
.yance-web-nav{flex:0 0 137px;width:137px;min-width:0;display:flex;flex-direction:column;gap:7px;
  border:1px solid #74523f;border-radius:13px;background:linear-gradient(165deg,#1d1b27,#121621);
  padding:13px 8px;color:#c2bcca;overflow:hidden}
.yance-web-brand{text-decoration:none;color:#e7c594;padding:3px 6px 12px;border-bottom:1px solid #4e434a;
  display:block;margin-bottom:5px}
.yance-web-brand strong{display:block;font-size:21px;line-height:1.24}
.yance-web-brand span{font-size:9px;letter-spacing:1px;color:#9a8c9f}
.yance-web-routes{display:flex;flex-direction:column;gap:3px}
.yance-web-route{display:block;color:#c2bcca;text-decoration:none;border-radius:8px;
  border:1px solid transparent;padding:8px 7px;font-size:12px}
.yance-web-route span{display:inline-block;width:15px;text-align:center;color:#9e869c;margin-right:2px}
.yance-web-route.selected{background:#3d2d30;border-color:#7d5b3e;color:#f1d6aa}
.yance-web-route:hover{background:#35293c}
.yance-web-advanced{color:#cbb3df;border-color:#5b4272;margin-top:7px}
.yance-web-nav-bottom{margin-top:auto;display:flex;flex-direction:column;gap:7px;min-width:0}
.yance-web-task{width:100%;text-align:left;border:1px solid #ac7ed1;
  background:linear-gradient(110deg,#56346b,#32233d);border-radius:8px;
  color:#f7dafd;padding:8px 6px;font-weight:600;min-height:31px}
.yance-web-connection{border:1px solid #655569;border-radius:7px;color:#d4c5da;
  background:#221e2d;text-align:left;font-size:10px;padding:7px 5px;overflow-wrap:anywhere}
.yance-web-nav-bottom small{color:#b1a2ad;border-top:1px solid #54434d;
  padding-top:9px;font-size:9px;line-height:1.6}
.yance-web-content{display:flex;flex:1;flex-direction:column;min-width:0;min-height:0;overflow:hidden}
.yance-web-content > main,.yance-web-content > section{width:100%;height:100%;min-height:0;overflow:auto;margin:0;color:var(--text)}
.yance-web-content :is(h1,h2,h3,h4){color:#f3e7dc}
.yance-web-content h1{font-size:20px}
.yance-web-content h2{font-size:15px}
.yance-web-content .home-heading,.yance-web-content .directory-head,.yance-web-content .platform-head{
  min-height:52px;padding:3px 5px 7px;margin:0 0 9px;border:0}
.yance-web-content :is(.home-heading-actions,.directory-head nav,.platform-head nav){display:none}
.yance-web-content :is(.home-section,.platform-section,.relationship-card,.settings-panel){
  background:linear-gradient(148deg,#24202d,#171b28);border:1px solid #5a4451;border-radius:11px;color:#efe8ee}
.yance-web-content :is(.home-state,.directory-state,.platform-note){color:#c4b6c5}
.yance-web-content :is(.primary-action,.primary-button){background:#695034;border:1px solid #b48b58;color:#fff5e1}
.yance-web-content :is(button,input,select){border-radius:7px}
.yance-web-content :is(input,textarea,select){background:#161522;color:#ede4ef;border:1px solid #76617c}
.yance-web-shell .yance-home-native,.yance-web-shell .yance-relationship-world,
.yance-web-shell .yance-directory,.yance-web-shell .platform-manager,
.yance-web-shell .yance-settings-native{padding:8px 5px 12px;margin:0;width:100%;max-width:100%;height:100%;overflow-y:auto;scrollbar-width:thin}
.yance-web-shell .yance-directory .directory-list{max-height:310px;overflow:auto}
.yance-web-shell .platform-manager .platform-section{display:inline-block;vertical-align:top;
  width:calc(25% - 9px);min-height:136px;margin:4px;padding:9px}
.yance-web-shell .platform-manager .platform-section header{display:block}
.yance-web-shell .platform-manager .platform-section h2{font-size:13px;margin:0 0 7px}
.yance-web-shell .platform-manager .platform-section header button{font-size:11px;padding:5px}
.yance-web-shell .platform-manager .platform-section p{font-size:10px;line-height:1.4}
.yance-web-shell .platform-manager .platform-section ul{padding:0}
.yance-web-shell .platform-manager .platform-section li{gap:3px}
.yance-web-shell .platform-manager .platform-section li button{font-size:10px}
.yance-web-shell .yance-home-native .home-section{padding:12px}
.yance-web-shell .yance-home-native .home-lower-grid{gap:9px}
.yance-web-shell .yance-home-native .continue-grid{gap:8px}
.yance-web-shell .yance-home-native .home-heading h1{margin:2px 0}
.yance-web-shell .yance-home-native .home-subtitle{font-size:11px}
.yance-web-shell .yance-home-native .home-heading,.yance-web-shell .yance-home-native .home-section{max-width:100%}
.yance-web-shell .yance-home-native :is(.home-state,.exception-card){min-height:46px}
.yance-web-shell .yance-home-native .home-section h2{margin:0 0 5px}
.yance-web-shell .yance-home-native .home-section p{font-size:11px}
.yance-web-shell .yance-home-native .attention-grid{gap:6px}
.yance-web-shell .yance-home-native .attention-item{padding:7px}
@media(max-width:700px){.yance-web-shell{width:100vw;height:100dvh;padding:8px;gap:7px;border-radius:0}
 .yance-web-nav{flex-basis:99px;width:99px;padding:8px 4px}
 .yance-web-route{padding:7px 3px;font-size:10px}.yance-web-brand strong{font-size:17px}
 .yance-web-task{font-size:10px}.yance-web-shell .platform-manager .platform-section{width:calc(50% - 9px)}
}

/* W371 REV3.4-P1R1 P1 visual corrections: exact 920x620 shared frame. */
.yance-web-shell{padding:8px;gap:12px}
.yance-web-nav{flex:0 0 118px;width:118px;padding:12px 9px}
.yance-web-brand strong{font-size:18px}
.yance-web-routes{gap:9px}
.yance-web-route{padding:9px 7px}
.yance-web-content{padding-top:3px}
.yance-web-shell .yance-home-native .home-heading{min-height:52px;padding:1px 7px 5px;margin-bottom:5px}
.yance-web-shell .yance-home-native .home-heading h1{font-size:20px;line-height:1.1}
.yance-web-shell .yance-home-native .home-heading .eyebrow{font-size:10px;color:#ac8a58}
.yance-web-shell .platform-manager{padding:1px 3px 10px}
.yance-web-shell .platform-manager .platform-head{min-height:52px;padding:1px 7px 5px;margin-bottom:0}
.yance-web-shell .platform-manager .platform-head p{margin:0;font-size:10px;color:#b19362}
.yance-web-shell .platform-manager .platform-head h1{font-size:20px;margin:0;color:#f2e3e8}
.yance-web-shell .platform-manager [data-platform-empty]{font-size:0;line-height:0;height:0;min-height:0;overflow:hidden;margin:0;padding:0}
.yance-web-shell .platform-manager .w371-platform-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;width:100%;margin:0}
.yance-web-shell .platform-manager .w371-platform-grid .platform-section{display:flex;flex-direction:column;
  gap:3px;width:100%;height:165px;min-height:0;overflow:hidden;min-width:0;margin:0;padding:10px;
  border-radius:11px;background:#151923;border:1px solid #4b3c51}
.yance-web-shell .platform-manager .w371-platform-card-heading{display:flex;flex-direction:column;align-items:start;gap:8px;flex:none}
.yance-web-shell .platform-manager .w371-platform-icon{display:grid;place-items:center;width:31px;height:31px;
  background:#36291f;border:1px solid #6e4a30;border-radius:9px;color:#e9b679;font-size:18px}
.yance-web-shell .platform-manager .w371-platform-card-heading h2{font-size:12px;line-height:1.2;
  font-weight:650;color:#f3e8ed;margin:0!important}
.yance-web-shell .platform-manager .w371-platform-description{font-size:10px;line-height:1.3;min-height:0;
  color:#ad9fac;margin:0;max-height:28px;overflow:hidden}
.yance-web-shell .platform-manager .w371-platform-status{font-size:10px;color:#aa9ba9;
  padding:3px 8px;border:1px solid #53455b;border-radius:30px;background:#252333;max-width:max-content;margin:0}
.yance-web-shell .platform-manager .w371-platform-grid .platform-section ul{overflow:auto;scrollbar-width:thin;margin:0}
.yance-web-shell .platform-manager .w371-platform-grid .platform-section ul li{padding:2px 0}
.yance-web-shell .platform-manager .w371-platform-grid .platform-section ul li button{padding:2px 4px}
.yance-web-shell .platform-manager .w371-platform-action{margin-top:auto;max-width:max-content;
  padding:5px 9px;background:#242333;border:1px solid #524760;border-radius:7px;font-size:10px;color:#e4d6e8}
.yance-web-shell .platform-manager .w371-platform-explainer{
  border:1px solid #84633c;border-radius:10px;background:#221d25;min-height:78px;margin:10px 0 0;padding:14px;color:#f0e3e5}
.yance-web-shell .platform-manager .w371-platform-explainer h2{font-size:12px;margin:0 0 8px}
.yance-web-shell .platform-manager .w371-platform-explainer p{font-size:10px;margin:0;line-height:1.65;color:#e0d2dc}
.yance-web-shell .platform-manager [data-personal-whatsapp-truth]{font-size:10px;margin-top:5px}
@media(max-width:700px){.yance-web-shell .platform-manager .w371-platform-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
.yance-web-shell .yance-web-nav{flex-basis:99px;width:99px}}
</style>