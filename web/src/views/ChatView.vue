<template>
  <div class="chat-view">
    <!-- Main Chat Container -->
    <div class="chat-container">
      <!-- Chat Header -->
      <div class="chat-header">
        <div class="header-left">
          <h2>智能问答</h2>
          <span class="session-badge" v-if="chatStore.sessionId">
            {{ chatStore.sessionId.substring(0, 8) }}
          </span>
        </div>
        <div class="header-actions">
          <button class="btn-icon" @click="toggleStreamMode" :title="useStream ? '流式输出已开启' : '流式输出已关闭'">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
            </svg>
            <span class="stream-indicator" :class="{ active: useStream }"></span>
          </button>
          <button class="btn-icon" @click="handleNewSession" title="新建会话">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M12 5v14M5 12h14"/>
            </svg>
          </button>
        </div>
      </div>

      <!-- Messages Area -->
      <div class="messages-area" ref="messagesRef">
        <!-- Welcome Message -->
        <div v-if="chatStore.messages.length === 0" class="welcome-message">
          <div class="welcome-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <path d="M12 2L2 7L12 12L22 7L12 2Z"/>
              <path d="M2 17L12 22L22 17"/>
              <path d="M2 12L12 17L22 12"/>
            </svg>
          </div>
          <h3>欢迎使用航空排故智能问答系统</h3>
          <p>基于航空知识库的智能检索与故障诊断问答，支持多种文档格式。</p>
          <div class="quick-actions">
            <button class="quick-btn" @click="askQuestion('发动机振动异常如何排查？')">发动机振动排查</button>
            <button class="quick-btn" @click="askQuestion('液压系统压力低的排故流程是什么？')">液压系统排故</button>
            <button class="quick-btn" @click="askQuestion('航电系统故障代码如何查询？')">故障代码查询</button>
          </div>
        </div>

        <!-- Message List -->
        <div
          v-for="(msg, index) in chatStore.messages"
          :key="index"
          :class="['message', msg.role]"
        >
          <div class="message-avatar">
            <div class="avatar-icon" :class="msg.role">
              <svg v-if="msg.role === 'user'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
                <circle cx="12" cy="7" r="4"/>
              </svg>
              <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 2L2 7L12 12L22 7L12 2Z"/>
                <path d="M2 17L12 22L22 17"/>
                <path d="M2 12L12 17L22 12"/>
              </svg>
            </div>
          </div>
          <div class="message-body">
            <div class="message-header">
              <span class="message-role">{{ msg.role === 'user' ? '用户' : 'AI助手' }}</span>
              <span class="message-time" v-if="msg.timestamp">{{ formatTime(msg.timestamp) }}</span>
            </div>
            <div class="message-content markdown-content" v-html="renderMarkdown(msg.content)"></div>
            <div
              v-if="msg.role === 'assistant' && shouldShowModeCard(msg)"
              class="mode-card"
            >
              <p v-if="getIntentLabel(msg.intent)"><strong>对话类型：</strong>{{ getIntentLabel(msg.intent) }}</p>
              <p v-if="getProfileLabel(msg.metadata?.prompt_profile)"><strong>回答模式：</strong>{{ getProfileLabel(msg.metadata?.prompt_profile) }}</p>
              <p v-if="msg.metadata?.force_rag" class="mode-note">
                检测到 PHM 技术问题，已自动切换到知识库诊断模式。
              </p>
              <button
                v-if="msg.sources && msg.sources.length > 0"
                class="source-toggle-btn"
                @click="openSources(msg.sources)"
              >
                查看依据来源 ({{ msg.sources.length }})
              </button>
            </div>
            <div
              v-if="msg.role === 'assistant' && hasDiagnosis(msg)"
              class="diagnosis-card"
            >
              <h4>PHM 诊断结构</h4>
              <p v-if="msg.diagnosis?.conclusion"><strong>诊断结论：</strong>{{ msg.diagnosis?.conclusion }}</p>
              <p v-if="msg.diagnosis?.safety_risks"><strong>风险提示：</strong>{{ msg.diagnosis?.safety_risks }}</p>
              <p v-if="msg.diagnosis?.info_gaps"><strong>信息缺口：</strong>{{ msg.diagnosis?.info_gaps }}</p>
            </div>
            <div class="message-footer" v-if="msg.role === 'assistant' && msg.processingTime">
              <span class="processing-time">{{ msg.processingTime.toFixed(0) }}ms</span>
            </div>
          </div>
        </div>

        <!-- Typing Indicator -->
        <div v-if="chatStore.isLoading || chatStore.isStreaming" class="message assistant typing">
          <div class="message-avatar">
            <div class="avatar-icon assistant">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 2L2 7L12 12L22 7L12 2Z"/>
                <path d="M2 17L12 22L22 17"/>
                <path d="M2 12L12 17L22 12"/>
              </svg>
            </div>
          </div>
          <div class="message-body">
            <div class="typing-indicator" v-if="!chatStore.isStreaming">
              <span></span><span></span><span></span>
            </div>
            <div class="stream-status" v-else>
              <div class="status-dot"></div>
              <span>{{ getStatusText() }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Input Area -->
      <div class="input-area">
        <div class="input-wrapper">
          <textarea
            v-model="inputText"
            @keydown.enter.exact.prevent="handleSend"
            placeholder="输入您的问题，按 Enter 发送..."
            rows="1"
            ref="textareaRef"
            :disabled="chatStore.isLoading || chatStore.isStreaming"
          ></textarea>
          <div class="input-actions">
            <div class="left-actions">
              <span class="char-count">{{ inputText.length }} / 2000</span>
            </div>
            <div class="right-actions">
              <button
                class="btn-send"
                @click="handleSend"
                :disabled="!inputText.trim() || chatStore.isLoading || chatStore.isStreaming"
              >
                <span>发送</span>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/>
                </svg>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Sources Panel -->
    <transition name="slide">
      <div v-if="showSources && sources.length > 0" class="sources-panel">
        <div class="sources-header">
          <h3>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
              <polyline points="14 2 14 8 20 8"/>
            </svg>
            参考来源
          </h3>
          <button class="btn-close" @click="showSources = false">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M18 6L6 18M6 6l12 12"/>
            </svg>
          </button>
        </div>
        <div class="source-list">
          <div v-for="(source, i) in sources" :key="i" class="source-item">
            <div class="source-header">
              <span class="source-number">{{ i + 1 }}</span>
              <span class="source-title">{{ source.title || '知识库文档' }}</span>
            </div>
            <div class="source-content">{{ truncateText(source.content, 150) }}</div>
            <div class="source-meta" v-if="source.score">
              <span class="relevance-score">相关度: {{ (source.score * 100).toFixed(1) }}%</span>
            </div>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, watch, onMounted } from 'vue'
import { useChatStore, type SourceDocument, type ChatMessage } from '@/stores/chat'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

const chatStore = useChatStore()

const inputText = ref('')
const messagesRef = ref<HTMLElement | null>(null)
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const showSources = ref(false)
const sources = ref<SourceDocument[]>([])
const useStream = ref(true)

// Configure marked
marked.setOptions({
  breaks: true,
  gfm: true,
})

onMounted(() => {
  autoResizeTextarea()
})

function renderMarkdown(text: string): string {
  if (!text) return ''
  try {
    // Parse markdown and sanitize HTML to prevent XSS attacks
    const rawHtml = marked.parse(text) as string
    return DOMPurify.sanitize(rawHtml, {
      ALLOWED_TAGS: [
        'p', 'br', 'strong', 'em', 'u', 's', 'code', 'pre',
        'ul', 'ol', 'li', 'a', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'blockquote', 'table', 'thead', 'tbody', 'tr', 'th', 'td',
        'span', 'div', 'hr'
      ],
      ALLOWED_ATTR: ['href', 'title', 'class', 'id', 'target', 'rel']
    })
  } catch {
    return text
  }
}

function formatTime(timestamp: number): string {
  return new Date(timestamp).toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  })
}

function truncateText(text: string, maxLength: number): string {
  if (!text) return ''
  return text.length > maxLength ? text.substring(0, maxLength) + '...' : text
}

function getStatusText(): string {
  const node = chatStore.currentNode
  const intent = chatStore.currentIntent

  if (node === 'agent') return '正在分析问题...'
  if (node === 'retrieve') return '正在检索知识库...'
  if (node === 'rewrite') return '正在优化查询...'
  if (node === 'generate') return '正在生成回答...'
  if (intent === 'general_chat') return '正在思考...'
  return '处理中...'
}

function autoResizeTextarea() {
  if (textareaRef.value) {
    textareaRef.value.style.height = 'auto'
    textareaRef.value.style.height = Math.min(textareaRef.value.scrollHeight, 150) + 'px'
  }
}

watch(inputText, () => {
  autoResizeTextarea()
})

async function handleSend() {
  const text = inputText.value.trim()
  if (!text || chatStore.isLoading || chatStore.isStreaming) return

  inputText.value = ''
  autoResizeTextarea()
  sources.value = []
  showSources.value = false

  try {
    if (useStream.value) {
      await chatStore.sendMessageStream(text)
      syncSourcesFromLatestAssistant()
    } else {
      const response = await chatStore.sendMessage(text)
      if (response?.sources?.length) {
        sources.value = response.sources
        showSources.value = true
      }
    }
  } catch (e) {
    console.error('Send failed:', e)
  }

  await nextTick()
  scrollToBottom()
}

function askQuestion(question: string) {
  inputText.value = question
  handleSend()
}

function hasDiagnosis(msg: ChatMessage): boolean {
  return Boolean(
    msg.diagnosis &&
    (
      msg.diagnosis.conclusion ||
      msg.diagnosis.possible_causes?.length ||
      msg.diagnosis.troubleshooting_steps?.length ||
      msg.diagnosis.safety_risks ||
      msg.diagnosis.evidence_sources?.length ||
      msg.diagnosis.info_gaps
    )
  )
}

function getIntentLabel(intent?: string): string {
  if (!intent) return ''
  if (intent === 'general_chat') return '普通咨询'
  if (intent === 'rag_query') return '知识库问答'
  if (intent === 'degraded') return '降级服务'
  return ''
}

function getProfileLabel(profile?: string): string {
  if (!profile) return ''
  if (profile === 'phm_identity_v1') return 'PHM 平台身份介绍'
  if (profile === 'phm_general_v1') return 'PHM 通用咨询'
  if (profile === 'phm_diagnosis_v1') return 'PHM 故障诊断'
  return ''
}

function shouldShowModeCard(msg: ChatMessage): boolean {
  return Boolean(
    getIntentLabel(msg.intent) ||
    getProfileLabel(msg.metadata?.prompt_profile) ||
    msg.metadata?.force_rag ||
    (msg.sources && msg.sources.length > 0)
  )
}

function openSources(list: SourceDocument[]) {
  sources.value = list
  showSources.value = true
}

function syncSourcesFromLatestAssistant() {
  const reversed = [...chatStore.messages].reverse()
  const lastAssistant = reversed.find((m) => m.role === 'assistant')
  if (lastAssistant?.sources?.length) {
    sources.value = lastAssistant.sources
    showSources.value = true
  }
}

function handleNewSession() {
  chatStore.newSession()
  sources.value = []
  showSources.value = false
}

function toggleStreamMode() {
  useStream.value = !useStream.value
}

function scrollToBottom() {
  if (messagesRef.value) {
    messagesRef.value.scrollTop = messagesRef.value.scrollHeight
  }
}

// Auto scroll when messages change
watch(
  () => chatStore.messages.length,
  () => {
    nextTick(scrollToBottom)
  }
)

// Auto scroll during streaming
watch(
  () => chatStore.messages[chatStore.messages.length - 1]?.content,
  () => {
    nextTick(scrollToBottom)
  }
)
</script>

<style scoped>
.chat-view {
  display: flex;
  height: 100%;
  gap: 0;
}

/* Chat Container */
.chat-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: white;
  overflow: hidden;
}

/* Chat Header */
.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--spacing-md) var(--spacing-lg);
  border-bottom: 1px solid var(--neutral-200);
  background: var(--neutral-50);
}

.header-left {
  display: flex;
  align-items: center;
  gap: var(--spacing-md);
}

.chat-header h2 {
  font-size: 18px;
  font-weight: 600;
  margin: 0;
}

.session-badge {
  font-size: 12px;
  padding: 2px 8px;
  background: var(--neutral-100);
  border-radius: var(--radius-full);
  color: var(--neutral-500);
  font-family: var(--font-mono);
}

.header-actions {
  display: flex;
  gap: var(--spacing-sm);
}

.btn-icon {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--neutral-600);
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  transition: all var(--transition-fast);
}

.btn-icon:hover {
  background: var(--neutral-100);
  color: var(--neutral-900);
}

.btn-icon svg {
  width: 20px;
  height: 20px;
}

.stream-indicator {
  position: absolute;
  bottom: 4px;
  right: 4px;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--neutral-400);
  transition: background var(--transition-fast);
}

.stream-indicator.active {
  background: var(--success-500);
  box-shadow: 0 0 6px var(--success-500);
}

/* Messages Area */
.messages-area {
  flex: 1;
  overflow-y: auto;
  padding: var(--spacing-lg);
}

/* Welcome Message */
.welcome-message {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  text-align: center;
  padding: var(--spacing-2xl);
}

.welcome-icon {
  width: 80px;
  height: 80px;
  background: linear-gradient(135deg, var(--primary-100), var(--primary-200));
  border-radius: var(--radius-xl);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: var(--spacing-lg);
}

.welcome-icon svg {
  width: 40px;
  height: 40px;
  color: var(--primary-500);
}

.welcome-message h3 {
  font-size: 24px;
  font-weight: 600;
  margin-bottom: var(--spacing-sm);
}

.welcome-message p {
  color: var(--neutral-500);
  margin-bottom: var(--spacing-xl);
}

.quick-actions {
  display: flex;
  gap: var(--spacing-sm);
  flex-wrap: wrap;
  justify-content: center;
}

.quick-btn {
  padding: var(--spacing-sm) var(--spacing-md);
  background: var(--neutral-100);
  border: 1px solid var(--neutral-200);
  border-radius: var(--radius-full);
  color: var(--neutral-700);
  font-size: 13px;
  transition: all var(--transition-fast);
}

.quick-btn:hover {
  background: var(--primary-50);
  border-color: var(--primary-200);
  color: var(--primary-600);
}

/* Message */
.message {
  display: flex;
  gap: 8px;
  margin-bottom: 10px;
  animation: fadeIn 0.3s ease;
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.message.user {
  flex-direction: row-reverse;
}

.message-avatar {
  flex-shrink: 0;
}

.avatar-icon {
  width: 28px;
  height: 28px;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
}

.avatar-icon.user {
  background: linear-gradient(135deg, var(--primary-400), var(--primary-600));
  color: white;
}

.avatar-icon.assistant {
  background: linear-gradient(135deg, var(--neutral-100), var(--neutral-200));
  color: var(--neutral-600);
}

.avatar-icon svg {
  width: 14px;
  height: 14px;
}

.message-body {
  max-width: 75%;
}

.message.user .message-body {
  align-items: flex-end;
}

.message-header {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  margin-bottom: var(--spacing-xs);
}

.message.user .message-header {
  flex-direction: row-reverse;
}

.message-role {
  font-size: 13px;
  font-weight: 500;
  color: var(--neutral-600);
}

.message-time {
  font-size: 12px;
  color: var(--neutral-400);
}

.message-content {
  padding: 8px 12px;
  border-radius: var(--radius-lg);
  background: var(--neutral-100);
  font-size: 14px;
  line-height: 1.5;
}

.message.user .message-content {
  background: linear-gradient(135deg, var(--primary-500), var(--primary-600));
  color: white;
  border-bottom-right-radius: var(--radius-sm);
}

.message.assistant .message-content {
  border-bottom-left-radius: var(--radius-sm);
}

.message-footer {
  margin-top: var(--spacing-xs);
  text-align: right;
}

.mode-card {
  margin-top: 8px;
  padding: 10px 12px;
  border-radius: var(--radius-md);
  border: 1px solid #e5e7eb;
  background: #f9fafb;
}

.mode-card p {
  margin: 4px 0;
  font-size: 12px;
  color: #374151;
}

.mode-note {
  color: #92400e !important;
}

.source-toggle-btn {
  margin-top: 6px;
  font-size: 11px;
  line-height: 1;
  padding: 6px 9px;
  border-radius: 999px;
  background: var(--primary-50);
  color: var(--primary-700);
  border: 1px solid var(--primary-200);
}

.source-toggle-btn:hover {
  background: var(--primary-100);
}

.diagnosis-card {
  margin-top: 8px;
  padding: 10px 12px;
  border-radius: var(--radius-md);
  border: 1px solid #bfdbfe;
  background: #eff6ff;
}

.diagnosis-card h4 {
  margin: 0 0 6px;
  font-size: 12px;
  color: #1e40af;
}

.diagnosis-card p {
  margin: 4px 0;
  font-size: 12px;
  color: #1f2937;
}

.processing-time {
  font-size: 11px;
  color: var(--neutral-400);
}

/* Typing Indicator */
.typing-indicator {
  display: flex;
  gap: 4px;
  padding: var(--spacing-md);
}

.typing-indicator span {
  width: 8px;
  height: 8px;
  background: var(--neutral-400);
  border-radius: 50%;
  animation: bounce 1.4s infinite ease-in-out;
}

.typing-indicator span:nth-child(1) { animation-delay: 0s; }
.typing-indicator span:nth-child(2) { animation-delay: 0.2s; }
.typing-indicator span:nth-child(3) { animation-delay: 0.4s; }

@keyframes bounce {
  0%, 80%, 100% {
    transform: scale(0.8);
    opacity: 0.5;
  }
  40% {
    transform: scale(1);
    opacity: 1;
  }
}

.stream-status {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  padding: var(--spacing-sm) var(--spacing-md);
  background: var(--primary-50);
  border-radius: var(--radius-md);
  font-size: 13px;
  color: var(--primary-600);
}

.status-dot {
  width: 8px;
  height: 8px;
  background: var(--primary-500);
  border-radius: 50%;
  animation: pulse 1.5s infinite;
}

/* Input Area */
.input-area {
  padding: var(--spacing-md) var(--spacing-lg) var(--spacing-lg);
  border-top: 1px solid var(--neutral-200);
  background: var(--neutral-50);
}

.input-wrapper {
  background: white;
  border: 1px solid var(--neutral-200);
  border-radius: var(--radius-lg);
  overflow: hidden;
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
}

.input-wrapper:focus-within {
  border-color: var(--primary-400);
  box-shadow: 0 0 0 3px var(--primary-100);
}

textarea {
  width: 100%;
  padding: var(--spacing-md);
  border: none;
  background: transparent;
  resize: none;
  font-size: 14px;
  line-height: 1.6;
  outline: none;
  min-height: 24px;
  max-height: 150px;
}

.input-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--spacing-sm) var(--spacing-md);
  border-top: 1px solid var(--neutral-100);
}

.char-count {
  font-size: 12px;
  color: var(--neutral-400);
}

.btn-send {
  display: flex;
  align-items: center;
  gap: var(--spacing-xs);
  padding: var(--spacing-sm) var(--spacing-md);
  background: linear-gradient(135deg, var(--primary-500), var(--primary-600));
  color: white;
  border-radius: var(--radius-md);
  font-weight: 500;
  transition: all var(--transition-fast);
}

.btn-send:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: var(--shadow-md);
}

.btn-send:disabled {
  opacity: 0.5;
}

.btn-send svg {
  width: 16px;
  height: 16px;
}

/* Sources Panel */
.sources-panel {
  width: 320px;
  background: white;
  border-left: 1px solid var(--neutral-200);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.sources-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--spacing-md) var(--spacing-lg);
  border-bottom: 1px solid var(--neutral-200);
}

.sources-header h3 {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  font-size: 14px;
  font-weight: 600;
  margin: 0;
}

.sources-header h3 svg {
  width: 18px;
  height: 18px;
  color: var(--neutral-500);
}

.btn-close {
  width: 28px;
  height: 28px;
  border-radius: var(--radius-sm);
  color: var(--neutral-500);
  display: flex;
  align-items: center;
  justify-content: center;
}

.btn-close:hover {
  background: var(--neutral-100);
}

.btn-close svg {
  width: 16px;
  height: 16px;
}

.source-list {
  flex: 1;
  overflow-y: auto;
  padding: var(--spacing-md);
}

.source-item {
  padding: var(--spacing-md);
  background: var(--neutral-50);
  border-radius: var(--radius-md);
  margin-bottom: var(--spacing-sm);
  border: 1px solid var(--neutral-100);
}

.source-header {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  margin-bottom: var(--spacing-sm);
}

.source-number {
  width: 20px;
  height: 20px;
  background: var(--primary-100);
  color: var(--primary-600);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
}

.source-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--neutral-700);
}

.source-content {
  font-size: 12px;
  color: var(--neutral-600);
  line-height: 1.6;
  margin-bottom: var(--spacing-sm);
}

.source-meta {
  display: flex;
  align-items: center;
}

.relevance-score {
  font-size: 11px;
  color: var(--neutral-500);
}

/* Transitions */
.slide-enter-active,
.slide-leave-active {
  transition: all var(--transition-normal);
}

.slide-enter-from,
.slide-leave-to {
  transform: translateX(100%);
  opacity: 0;
}

/* Responsive */
@media (max-width: 768px) {
  .sources-panel {
    position: fixed;
    right: 0;
    top: 0;
    bottom: 0;
    z-index: 50;
    box-shadow: var(--shadow-xl);
  }
}
</style>
