/**
 * API module for RAG Platform
 */

import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 60000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Request interceptor
api.interceptors.request.use(
  (config) => {
    // Add trace ID for debugging
    config.headers['X-Trace-ID'] = generateTraceId()
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// Response interceptor
api.interceptors.response.use(
  (response) => {
    return response.data
  },
  (error) => {
    console.error('API Error:', error)
    return Promise.reject(error)
  }
)

function generateTraceId(): string {
  return Math.random().toString(36).substring(2, 10)
}

// Chat API
export const chatApi = {
  sendMessage: (message: string, sessionId?: string) =>
    api.post('/chat', { message, session_id: sessionId }),

  getHistory: (sessionId: string, limit = 20) =>
    api.get(`/chat/history/${sessionId}`, { params: { limit } }),

  clearSession: (sessionId: string) =>
    api.delete(`/chat/session/${sessionId}`),
}

// Documents API
export const documentsApi = {
  list: (skip = 0, limit = 20) =>
    api.get('/documents', { params: { skip, limit } }),

  upload: (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.post('/documents/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },

  get: (docId: string) =>
    api.get(`/documents/${docId}`),

  delete: (docId: string) =>
    api.delete(`/documents/${docId}`),
}

// Sessions API
export const sessionsApi = {
  create: () => api.post('/sessions'),

  list: (skip = 0, limit = 20) =>
    api.get('/sessions', { params: { skip, limit } }),

  get: (sessionId: string) =>
    api.get(`/sessions/${sessionId}`),

  delete: (sessionId: string) =>
    api.delete(`/sessions/${sessionId}`),
}

// Admin API
export const adminApi = {
  health: () => api.get('/admin/health'),

  metrics: () => api.get('/admin/metrics'),

  getCircuitBreakers: () => api.get('/admin/circuit-breakers'),

  resetCircuitBreaker: (name: string) =>
    api.post(`/admin/circuit-breakers/${name}/reset`),

  getDegradation: () => api.get('/admin/degradation'),

  setDegradationMode: (mode: string) =>
    api.post(`/admin/degradation/mode/${mode}`),
}

export default api