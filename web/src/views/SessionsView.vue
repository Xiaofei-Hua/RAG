<template>
  <div class="sessions-view">
    <!-- Page Header -->
    <div class="page-header">
      <div class="header-content">
        <h1>会话历史</h1>
        <p>查看和管理历史对话记录</p>
      </div>
      <div class="header-actions">
        <button class="btn-secondary" @click="loadSessions">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M23 4v6h-6"/>
            <path d="M1 20v-6h6"/>
            <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
          </svg>
          刷新
        </button>
      </div>
    </div>

    <!-- Sessions Grid -->
    <div v-if="sessions.length === 0" class="empty-state">
      <div class="empty-icon">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <circle cx="12" cy="12" r="10"/>
          <polyline points="12 6 12 12 16 14"/>
        </svg>
      </div>
      <h3>暂无历史会话</h3>
      <p>开始新对话后，会话记录将显示在这里</p>
      <router-link to="/" class="btn-primary">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 5v14M5 12h14"/>
        </svg>
        开始对话
      </router-link>
    </div>

    <div v-else class="sessions-grid">
      <div
        v-for="session in sessions"
        :key="session.session_id"
        class="session-card"
        @click="openSession(session.session_id)"
      >
        <div class="session-header">
          <div class="session-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
            </svg>
          </div>
          <div class="session-id">
            {{ session.session_id?.substring(0, 12) }}...
          </div>
          <button class="btn-delete" @click.stop="deleteSession(session.session_id)">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="3 6 5 6 21 6"/>
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
            </svg>
          </button>
        </div>

        <div class="session-body">
          <div class="session-stats">
            <div class="stat">
              <span class="stat-value">{{ session.message_count || 0 }}</span>
              <span class="stat-label">消息数</span>
            </div>
            <div class="stat">
              <span class="stat-value">{{ formatTTL(session.ttl_seconds) }}</span>
              <span class="stat-label">剩余时间</span>
            </div>
          </div>
        </div>

        <div class="session-footer">
          <span class="session-time">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10"/>
              <polyline points="12 6 12 12 16 14"/>
            </svg>
            {{ formatDate(session.created_at) }}
          </span>
          <span class="open-btn">
            打开
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M5 12h14M12 5l7 7-7 7"/>
            </svg>
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useChatStore } from '@/stores/chat'

const router = useRouter()
const chatStore = useChatStore()
const sessions = ref<any[]>([])

onMounted(async () => {
  await loadSessions()
})

async function loadSessions() {
  try {
    const response = await fetch('/api/sessions')
    const data = await response.json()
    sessions.value = data.sessions || []
  } catch (e) {
    console.error('Load sessions error:', e)
  }
}

async function openSession(sessionId: string) {
  await chatStore.loadHistory(sessionId)
  router.push('/')
}

async function deleteSession(sessionId: string) {
  if (!confirm('确定删除此会话？此操作不可撤销。')) return

  try {
    await fetch(`/api/sessions/${sessionId}`, { method: 'DELETE' })
    await loadSessions()
  } catch (e) {
    console.error('Delete session error:', e)
  }
}

function formatTTL(seconds: number): string {
  if (!seconds || seconds < 0) return '已过期'
  const hours = Math.floor(seconds / 3600)
  if (hours > 24) {
    const days = Math.floor(hours / 24)
    return `${days}天`
  }
  if (hours > 0) return `${hours}小时`
  const minutes = Math.floor(seconds / 60)
  if (minutes > 0) return `${minutes}分钟`
  return '即将过期'
}

function formatDate(date: string): string {
  if (!date) return ''
  return new Date(date).toLocaleDateString('zh-CN', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}
</script>

<style scoped>
.sessions-view {
  padding: var(--spacing-lg);
  max-width: 1200px;
  margin: 0 auto;
  overflow-y: auto;
}

/* Page Header */
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: var(--spacing-xl);
}

.header-content h1 {
  font-size: 28px;
  font-weight: 700;
  margin: 0 0 var(--spacing-xs) 0;
}

.header-content p {
  color: var(--neutral-500);
  margin: 0;
}

.btn-secondary {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  padding: var(--spacing-sm) var(--spacing-md);
  background: white;
  border: 1px solid var(--neutral-200);
  border-radius: var(--radius-md);
  color: var(--neutral-700);
  font-weight: 500;
  transition: all var(--transition-fast);
}

.btn-secondary:hover {
  background: var(--neutral-50);
  border-color: var(--neutral-300);
}

.btn-secondary svg {
  width: 18px;
  height: 18px;
}

/* Empty State */
.empty-state {
  text-align: center;
  padding: var(--spacing-2xl);
  background: white;
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-sm);
}

.empty-icon {
  width: 80px;
  height: 80px;
  margin: 0 auto var(--spacing-md);
  background: var(--neutral-100);
  border-radius: var(--radius-lg);
  display: flex;
  align-items: center;
  justify-content: center;
}

.empty-icon svg {
  width: 40px;
  height: 40px;
  color: var(--neutral-400);
}

.empty-state h3 {
  font-size: 18px;
  font-weight: 600;
  margin: 0 0 var(--spacing-xs) 0;
}

.empty-state p {
  color: var(--neutral-500);
  margin: 0 0 var(--spacing-lg) 0;
}

.btn-primary {
  display: inline-flex;
  align-items: center;
  gap: var(--spacing-sm);
  padding: var(--spacing-sm) var(--spacing-lg);
  background: linear-gradient(135deg, var(--primary-500), var(--primary-600));
  color: white;
  border-radius: var(--radius-md);
  font-weight: 500;
  text-decoration: none;
  transition: all var(--transition-fast);
}

.btn-primary:hover {
  transform: translateY(-1px);
  box-shadow: var(--shadow-md);
}

.btn-primary svg {
  width: 18px;
  height: 18px;
}

/* Sessions Grid */
.sessions-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: var(--spacing-md);
}

.session-card {
  background: white;
  border-radius: var(--radius-lg);
  padding: var(--spacing-md);
  border: 1px solid var(--neutral-200);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.session-card:hover {
  border-color: var(--primary-200);
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}

.session-header {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  margin-bottom: var(--spacing-md);
}

.session-icon {
  width: 36px;
  height: 36px;
  background: var(--primary-100);
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--primary-500);
}

.session-icon svg {
  width: 18px;
  height: 18px;
}

.session-id {
  flex: 1;
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--neutral-600);
  background: var(--neutral-100);
  padding: var(--spacing-xs) var(--spacing-sm);
  border-radius: var(--radius-sm);
}

.btn-delete {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--neutral-400);
  transition: all var(--transition-fast);
}

.btn-delete:hover {
  background: var(--error-100);
  color: var(--error-500);
}

.btn-delete svg {
  width: 16px;
  height: 16px;
}

.session-body {
  margin-bottom: var(--spacing-md);
}

.session-stats {
  display: flex;
  gap: var(--spacing-lg);
}

.stat {
  display: flex;
  flex-direction: column;
}

.stat-value {
  font-size: 20px;
  font-weight: 600;
  color: var(--neutral-800);
}

.stat-label {
  font-size: 12px;
  color: var(--neutral-500);
}

.session-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: var(--spacing-sm);
  border-top: 1px solid var(--neutral-200);
}

.session-time {
  display: flex;
  align-items: center;
  gap: var(--spacing-xs);
  font-size: 12px;
  color: var(--neutral-500);
}

.session-time svg {
  width: 14px;
  height: 14px;
}

.open-btn {
  display: flex;
  align-items: center;
  gap: var(--spacing-xs);
  font-size: 13px;
  font-weight: 500;
  color: var(--primary-500);
}

.open-btn svg {
  width: 14px;
  height: 14px;
}

/* Responsive */
@media (max-width: 768px) {
  .page-header {
    flex-direction: column;
    gap: var(--spacing-md);
  }

  .sessions-grid {
    grid-template-columns: 1fr;
  }
}
</style>