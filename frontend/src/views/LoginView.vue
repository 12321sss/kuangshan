<template>
  <div class="login-page">
    <!-- 背景装饰 -->
    <div class="bg-grid"></div>
    <div class="bg-glow glow-1"></div>
    <div class="bg-glow glow-2"></div>

    <div class="login-panel">
      <!-- 左侧品牌区 -->
      <div class="intro">
        <div class="intro-logo">
          <svg viewBox="0 0 32 32" width="34" height="34">
            <rect width="32" height="32" rx="7" fill="#14b8a6" />
            <path d="M6 22 L13 11 L18 17 L21 12 L26 22 Z" fill="#fff" />
          </svg>
        </div>
        <h1>智慧矿山</h1>
        <p class="slogan">遥感解译 · 物联感知 · 三维监测预警一体化平台</p>
        <ul class="features">
          <li><i class="bullet"></i>七类地物智能解译，采坑/排土场/水体自动提取</li>
          <li><i class="bullet"></i>多时相变化追踪与采坑扩张趋势预测</li>
          <li><i class="bullet"></i>边坡位移物联感知，三级阈值实时预警</li>
        </ul>
        <div class="intro-foot">DEMO v0.1 · 演示环境数据均为模拟</div>
      </div>

      <!-- 右侧表单区 -->
      <div class="form-side">
        <h2>欢迎登录</h2>
        <p class="form-sub">请使用演示账号进入平台</p>
        <el-form :model="form" @submit.prevent="onLogin">
          <el-form-item>
            <el-input v-model="form.username" placeholder="用户名" size="large" :prefix-icon="User" />
          </el-form-item>
          <el-form-item>
            <el-input
              v-model="form.password"
              type="password"
              placeholder="密码"
              size="large"
              show-password
              :prefix-icon="Lock"
              @keyup.enter="onLogin"
            />
          </el-form-item>
          <el-button type="primary" size="large" class="login-btn" :loading="loading" @click="onLogin">
            登 录
          </el-button>
        </el-form>

        <el-collapse class="accounts">
          <el-collapse-item title="演示账号" name="1">
            <div class="account-row" v-for="a in demoAccounts" :key="a.u" @click="fill(a)">
              <code>{{ a.u }} / {{ a.p }}</code>
              <span>{{ a.role }}</span>
            </div>
          </el-collapse-item>
        </el-collapse>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const form = reactive({ username: '', password: '' })
const loading = ref(false)

const demoAccounts = [
  { u: 'admin', p: 'admin123', role: '系统管理员' },
  { u: 'manager', p: 'manager123', role: '项目管理员' },
  { u: 'analyst', p: 'analyst123', role: '解译分析师' },
  { u: 'viewer', p: 'viewer123', role: '观察员' }
]

function fill(a: { u: string; p: string }) {
  form.username = a.u
  form.password = a.p
}

async function onLogin() {
  if (!form.username || !form.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    await auth.login(form.username, form.password)
    ElMessage.success(`欢迎，${auth.user?.displayName}`)
    router.push((route.query.redirect as string) || '/')
  } catch (e: any) {
    ElMessage.error(e.message || '登录失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  position: relative;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  background: linear-gradient(150deg, #06121f 0%, #0a2033 45%, #0d3b3f 100%);
}

/* 网格背景 */
.bg-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(45, 212, 191, 0.05) 1px, transparent 1px),
    linear-gradient(90deg, rgba(45, 212, 191, 0.05) 1px, transparent 1px);
  background-size: 44px 44px;
  mask-image: radial-gradient(ellipse 80% 70% at 50% 45%, #000 30%, transparent 75%);
}

/* 冷色光晕 */
.bg-glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(90px);
  opacity: 0.35;
}

.glow-1 { width: 480px; height: 480px; background: #0d9488; top: -160px; right: -120px; }
.glow-2 { width: 380px; height: 380px; background: #1d4ed8; bottom: -140px; left: -100px; }

/* 登录面板：左右双栏玻璃拟态 */
.login-panel {
  position: relative;
  display: flex;
  width: 780px;
  min-height: 460px;
  border-radius: 16px;
  overflow: hidden;
  background: rgba(13, 27, 42, 0.6);
  border: 1px solid rgba(45, 212, 191, 0.18);
  backdrop-filter: blur(14px);
  box-shadow: 0 30px 80px rgba(0, 0, 0, 0.5);
}

/* 左侧品牌区 */
.intro {
  width: 46%;
  padding: 44px 36px;
  display: flex;
  flex-direction: column;
  background: linear-gradient(160deg, rgba(13, 148, 136, 0.16), rgba(13, 148, 136, 0.04));
  border-right: 1px solid rgba(45, 212, 191, 0.12);
}

.intro-logo { margin-bottom: 18px; }

.intro h1 {
  font-size: 30px;
  letter-spacing: 10px;
  color: #f0fdfa;
  margin-bottom: 10px;
}

.slogan { font-size: 13px; color: #5eead4; margin-bottom: 30px; letter-spacing: 1px; }

.features { list-style: none; display: flex; flex-direction: column; gap: 14px; flex: 1; }

.features li {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  font-size: 13px;
  color: #94b8b3;
  line-height: 1.6;
}

.bullet {
  flex-shrink: 0;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #2dd4bf;
  margin-top: 7px;
  box-shadow: 0 0 8px #2dd4bf;
}

.intro-foot { font-size: 11px; color: #3f5a63; letter-spacing: 1px; }

/* 右侧表单区 */
.form-side { flex: 1; padding: 44px 40px; }

.form-side h2 { font-size: 22px; color: #f0fdfa; margin-bottom: 6px; }
.form-sub { font-size: 13px; color: #64748b; margin-bottom: 28px; }

/* 深色表单控件适配 */
.form-side :deep(.el-input__wrapper) {
  background: rgba(2, 12, 20, 0.55);
  box-shadow: 0 0 0 1px rgba(45, 212, 191, 0.22) inset;
}

.form-side :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px #2dd4bf inset;
}

.form-side :deep(.el-input__inner) { color: #e2e8f0; }
.form-side :deep(.el-input__inner::placeholder) { color: #475569; }
.form-side :deep(.el-input__prefix) { color: #2dd4bf; }

.login-btn {
  width: 100%;
  margin-top: 6px;
  letter-spacing: 10px;
  font-weight: 600;
  background: linear-gradient(90deg, #0d9488, #14b8a6);
  border: none;
}

.login-btn:hover { background: linear-gradient(90deg, #0f766e, #0d9488); }

.accounts { margin-top: 24px; border-top: none; --el-collapse-header-bg-color: transparent; }

.accounts :deep(.el-collapse-item__header) {
  background: transparent;
  color: #64748b;
  font-size: 12px;
  border-bottom: none;
  height: 34px;
}

.accounts :deep(.el-collapse-item__wrap) { background: transparent; border-bottom: none; }
.accounts :deep(.el-collapse-item__content) { padding-bottom: 4px; }

.account-row {
  display: flex;
  justify-content: space-between;
  padding: 5px 8px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 12px;
  color: #94b8b3;
}

.account-row:hover { background: rgba(45, 212, 191, 0.08); }
.account-row code { color: #5eead4; font-family: monospace; }
</style>
