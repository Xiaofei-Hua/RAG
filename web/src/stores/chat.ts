import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp?: number
  isStreaming?: boolean
  sources?: SourceDocument[]
  intent?: string
  processingTime?: number
  metadata?: Record<string, any>
  diagnosis?: PHMDiagnosis | null
}

export interface SourceDocument {
  content: string
  source?: string
  title?: string
  score: number
}

export interface ChatResponse {
  response: string
  session_id: string
  intent: string
  sources: SourceDocument[]
  processing_time_ms: number
  metadata: Record<string, any>
}

export interface PHMDiagnosis {
  conclusion: string
  possible_causes: string[]
  troubleshooting_steps: string[]
  safety_risks: string
  evidence_sources: string[]
  info_gaps: string
}

export interface StreamEvent {
  type: 'session' | 'status' | 'intent' | 'node' | 'token' | 'done' | 'error'
  session_id?: string
  message?: string
  intent?: string
  confidence?: number
  route?: string
  force_rag?: boolean
  name?: string
  content?: string
  full_response?: string
  sources?: SourceDocument[]
  processing_time_ms?: number
  metadata?: Record<string, any>
}

export const useChatStore = defineStore('chat', () => {
  // State
  const messages = ref<ChatMessage[]>([])
  const sessionId = ref<string>('')
  const isLoading = ref(false)
  const isStreaming = ref(false)
  const error = ref<string | null>(null)
  const currentIntent = ref<string>('')
  const currentNode = ref<string>('')

  // Getters
  const messageCount = computed(() => messages.value.length)
  const lastMessage = computed(() => messages.value[messages.value.length - 1])

  // Actions
  async function initSession() {
    if (!sessionId.value) {
      sessionId.value = generateSessionId()
    }
  }

  async function sendMessage(content: string): Promise<ChatResponse | null> {
    if (!content.trim()) return null

    // Add user message
    const userMessage: ChatMessage = {
      role: 'user',
      content: content.trim(),
      timestamp: Date.now(),
    }
    messages.value.push(userMessage)

    isLoading.value = true
    error.value = null

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          message: content.trim(),
          session_id: sessionId.value,
          stream: false,
        }),
      })

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }

      const data: ChatResponse = await response.json()

      // Add assistant message
      const assistantMessage: ChatMessage = {
        role: 'assistant',
        content: data.response,
        timestamp: Date.now(),
        sources: data.sources,
        intent: data.intent,
        processingTime: data.processing_time_ms,
        metadata: data.metadata,
        diagnosis: data.metadata?.diagnosis || null,
      }
      messages.value.push(assistantMessage)

      // Update session ID if new
      if (data.session_id !== sessionId.value) {
        sessionId.value = data.session_id
      }

      return data
    } catch (e: any) {
      error.value = e.message || '发送消息失败'
      console.error('Send message error:', e)

      // Add error message
      messages.value.push({
        role: 'assistant',
        content: '抱歉，发生了错误。请稍后重试。',
        timestamp: Date.now(),
      })

      throw e
    } finally {
      isLoading.value = false
    }
  }

  async function sendMessageStream(content: string): Promise<void> {
    if (!content.trim()) return

    // Add user message
    const userMessage: ChatMessage = {
      role: 'user',
      content: content.trim(),
      timestamp: Date.now(),
    }
    messages.value.push(userMessage)

    // Add placeholder for assistant message
    const assistantIndex = messages.value.length
    messages.value.push({
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
      isStreaming: true,
    })

    isStreaming.value = true
    error.value = null
    currentIntent.value = ''
    currentNode.value = ''

    try {
      const response = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          message: content.trim(),
          session_id: sessionId.value,
          stream: true,
        }),
      })

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }

      const reader = response.body?.getReader()
      if (!reader) {
        throw new Error('No reader available')
      }

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const event: StreamEvent = JSON.parse(line.slice(6))
              handleStreamEvent(event, assistantIndex)
            } catch (e) {
              console.error('Failed to parse event:', line, e)
            }
          }
        }
      }

      // Mark streaming as complete
      if (messages.value[assistantIndex]) {
        messages.value[assistantIndex].isStreaming = false
      }
    } catch (e: any) {
      error.value = e.message || '流式输出失败'
      console.error('Stream error:', e)

      // Update assistant message with error
      if (messages.value[assistantIndex]) {
        messages.value[assistantIndex].content = '抱歉，发生了错误。请稍后重试。'
        messages.value[assistantIndex].isStreaming = false
      }
    } finally {
      isStreaming.value = false
      currentIntent.value = ''
      currentNode.value = ''
    }
  }

  function handleStreamEvent(event: StreamEvent, messageIndex: number) {
    switch (event.type) {
      case 'session':
        if (event.session_id && event.session_id !== sessionId.value) {
          sessionId.value = event.session_id
        }
        break

      case 'status':
        // Status message (e.g., "正在分析意图...")
        console.log('Status:', event.message)
        break

      case 'intent':
        currentIntent.value = event.intent || ''
        if (messages.value[messageIndex]) {
          messages.value[messageIndex].intent = event.intent || ''
          messages.value[messageIndex].metadata = {
            ...(messages.value[messageIndex].metadata || {}),
            route: event.route || '',
            force_rag: event.force_rag || false,
          }
        }
        break

      case 'node':
        currentNode.value = event.name || ''
        break

      case 'token':
        if (event.content && messages.value[messageIndex]) {
          messages.value[messageIndex].content += event.content
        }
        break

      case 'done':
        if (messages.value[messageIndex]) {
          messages.value[messageIndex].isStreaming = false
          if (event.full_response) {
            messages.value[messageIndex].content = event.full_response
          }
          if (event.sources) {
            messages.value[messageIndex].sources = event.sources
          }
          if (event.processing_time_ms !== undefined) {
            messages.value[messageIndex].processingTime = event.processing_time_ms
          }
          if (event.metadata) {
            messages.value[messageIndex].metadata = event.metadata
            messages.value[messageIndex].diagnosis = event.metadata?.diagnosis || null
          }
        }
        break

      case 'error':
        error.value = event.message || '未知错误'
        if (messages.value[messageIndex]) {
          messages.value[messageIndex].content = `错误: ${event.message || '未知错误'}`
          messages.value[messageIndex].isStreaming = false
        }
        break
    }
  }

  async function loadHistory(sid: string) {
    try {
      const response = await fetch(`/api/chat/history/${sid}?limit=50`)
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }

      const data = await response.json()
      messages.value = data.messages || []
      sessionId.value = sid
    } catch (e) {
      console.error('Load history error:', e)
    }
  }

  function clearMessages() {
    messages.value = []
  }

  function newSession() {
    messages.value = []
    sessionId.value = generateSessionId()
    error.value = null
    currentIntent.value = ''
    currentNode.value = ''
  }

  return {
    // State
    messages,
    sessionId,
    isLoading,
    isStreaming,
    error,
    currentIntent,
    currentNode,
    // Getters
    messageCount,
    lastMessage,
    // Actions
    initSession,
    sendMessage,
    sendMessageStream,
    loadHistory,
    clearMessages,
    newSession,
  }
})

function generateSessionId(): string {
  return 'session_' + Math.random().toString(36).substring(2, 15) + '_' + Date.now().toString(36)
}
