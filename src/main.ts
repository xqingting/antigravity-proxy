// Antigravity Proxy 桌面控制台前端核心逻辑 (含输入/输出/缓存命中监控、真流式打字机测试、历史调用看板)
let isTauri = false
let invokeFn: any = null

try {
  // @ts-ignore
  if (window.__TAURI_INTERNALS__) {
    isTauri = true
    // @ts-ignore
    import('@tauri-apps/api/core').then((mod) => {
      invokeFn = mod.invoke
      initApp()
    })
  } else {
    initApp()
  }
} catch (e) {
  initApp()
}

interface ProxyStatus {
  running: boolean
  port: number
  model: string
  effort: string
  agy_version: string
  pid?: number
  message?: string
}

interface RequestRecord {
  id: string
  timestamp: string
  date: string
  model: string
  is_stream: boolean
  duration: number
  prompt_tokens: number
  completion_tokens: number
  cached_tokens: number
  cache_hit_rate: number
  total_tokens: number
  tps: number
  status: 'success' | 'error' | 'timeout'
  error?: string | null
}

interface StatsSnapshot {
  total_requests: number
  successful_requests: number
  failed_requests: number
  success_rate: number
  active_requests: number
  max_concurrency: number
  total_prompt_tokens: number
  total_completion_tokens: number
  total_cached_tokens: number
  cache_hit_rate: number
  total_tokens: number
  avg_duration: number
  avg_tps: number
  recent_history: RequestRecord[]
}

let currentRunning = false

function initApp() {
  const statusIndicator = document.getElementById('statusIndicator')!
  const statusText = document.getElementById('statusText')!
  const toggleBtn = document.getElementById('toggleBtn')! as HTMLButtonElement
  const restartBtn = document.getElementById('restartBtn')! as HTMLButtonElement
  const agyVersionEl = document.getElementById('agyVersion')!

  // 6 联监控卡片 DOM
  const statTotalPromptTokens = document.getElementById('statTotalPromptTokens')!
  const statTotalCompletionTokens = document.getElementById('statTotalCompletionTokens')!
  const statTotalTokens = document.getElementById('statTotalTokens')!
  const statTotalRequests = document.getElementById('statTotalRequests')!
  const statSuccessRate = document.getElementById('statSuccessRate')!
  const statReqDetail = document.getElementById('statReqDetail')!
  const statAvgTps = document.getElementById('statAvgTps')!
  const statAvgDuration = document.getElementById('statAvgDuration')!
  const activeRequestsHint = document.getElementById('activeRequestsHint')!
  const resetStatsBtn = document.getElementById('resetStatsBtn')! as HTMLButtonElement

  // 历史明细 DOM
  const historyCount = document.getElementById('historyCount')!
  const historyTableBody = document.getElementById('historyTableBody')!

  // 复制按钮组
  const copyBaseUrlBtn = document.getElementById('copyBaseUrlBtn')!
  const copyApiKeyBtn = document.getElementById('copyApiKeyBtn')!
  const copyModelBtn = document.getElementById('copyModelBtn')!
  const copyAllConfigBtn = document.getElementById('copyAllConfigBtn')!
  const copyCurlBtn = document.getElementById('copyCurlBtn')!

  // 测试区 DOM
  const sendTestBtn = document.getElementById('sendTestBtn')! as HTMLButtonElement
  const testPromptInput = document.getElementById('testPromptInput')! as HTMLInputElement
  const streamToggle = document.getElementById('streamToggle')! as HTMLInputElement
  const testResultBox = document.getElementById('testResultBox')!
  const resultContent = document.getElementById('resultContent')!
  const resultMeta = document.getElementById('resultMeta')!
  const testDuration = document.getElementById('testDuration')!

  // 日志 DOM
  const refreshLogsBtn = document.getElementById('refreshLogsBtn')!
  const logViewport = document.getElementById('logViewport')!

  // 复制辅助函数
  function setupCopy(btn: HTMLElement, textToCopy: string, label: string = '已复制 ✓') {
    btn.addEventListener('click', async () => {
      await navigator.clipboard.writeText(textToCopy)
      const orig = btn.innerText
      btn.innerText = label
      btn.classList.add('copied')
      setTimeout(() => {
        btn.innerText = orig
        btn.classList.remove('copied')
      }, 1500)
    })
  }

  setupCopy(copyBaseUrlBtn, 'http://127.0.0.1:8765/v1')
  if (copyApiKeyBtn) setupCopy(copyApiKeyBtn, 'sk-antigravity-local')
  if (copyModelBtn) setupCopy(copyModelBtn, 'gemini-3.8-flash')
  if (copyAllConfigBtn) {
    setupCopy(
      copyAllConfigBtn,
      `API Base URL: http://127.0.0.1:8765/v1\nAPI Key: sk-antigravity-local\nModel: gemini-3.8-flash`,
      '全套配置已复制 ✓'
    )
  }
  setupCopy(
    copyCurlBtn,
    `curl http://127.0.0.1:8765/v1/chat/completions \\\n  -H "Content-Type: application/json" \\\n  -d '{"model": "gemini-3.8-flash", "messages": [{"role": "user", "content": "你好"}]}'`,
    'cURL 已复制'
  )

  // 检查状态
  async function checkStatus() {
    try {
      if (invokeFn) {
        const status: ProxyStatus = await invokeFn('get_proxy_status')
        updateUI(status)
      } else {
        const res = await fetch('http://127.0.0.1:8765/health')
        if (res.ok) {
          const data = await res.json()
          updateUI({
            running: true,
            port: 8765,
            model: data.default_model || 'gemini-3.8-flash',
            effort: data.default_effort || 'high',
            agy_version: data.agy_version || '已连接',
          })
        } else {
          updateUI({ running: false, port: 8765, model: 'gemini-3.8-flash', effort: 'high', agy_version: '未检测' })
        }
      }
    } catch (e) {
      updateUI({ running: false, port: 8765, model: 'gemini-3.8-flash', effort: 'high', agy_version: '未检测' })
    }
  }

  function updateUI(status: ProxyStatus) {
    currentRunning = status.running
    if (status.running) {
      statusIndicator.className = 'status-indicator is-running'
      statusText.innerText = `服务正常运行于 http://127.0.0.1:${status.port}/v1 (并发上限: 5，主流模型别名自动映射)`
      toggleBtn.innerText = '停止服务'
      toggleBtn.className = 'btn btn-danger'
      restartBtn.disabled = false
    } else {
      statusIndicator.className = 'status-indicator is-stopped'
      statusText.innerText = '代理服务已停止 (可点击右侧按钮启动)'
      toggleBtn.innerText = '启动服务'
      toggleBtn.className = 'btn btn-primary'
      restartBtn.disabled = true
    }
    agyVersionEl.innerText = status.agy_version || '正常'
  }

  // 格式化 Token 计数
  function formatTokens(n: number): string {
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(2) + 'M'
    if (n >= 10_000) return (n / 1_000).toFixed(1) + 'K'
    return n.toLocaleString()
  }

  // 刷新统计指标
  async function fetchStats() {
    try {
      const res = await fetch('http://127.0.0.1:8765/v1/stats')
      if (!res.ok) return
      const stats: StatsSnapshot = await res.json()

      // 1. 输入 Token 总数
      statTotalPromptTokens.innerText = formatTokens(stats.total_prompt_tokens || 0)

      // 2. 输出 Token 总数
      statTotalCompletionTokens.innerText = formatTokens(stats.total_completion_tokens || 0)

      // 3. 累计消耗 Token 总量
      statTotalTokens.innerText = formatTokens(stats.total_tokens || 0)

      // 4. 总调用次数 & 成功率
      statTotalRequests.innerText = stats.total_requests.toString()
      statSuccessRate.innerText = `${stats.success_rate}% 成功`
      statReqDetail.innerText = `成功 ${stats.successful_requests} · 失败 ${stats.failed_requests}`

      // 5. 平均生成速率 (TPS)
      statAvgTps.innerText = stats.avg_tps.toFixed(1)

      // 6. 平均响应耗时
      statAvgDuration.innerText = stats.avg_duration.toFixed(2)
      activeRequestsHint.innerText = `当前排队: ${stats.active_requests} / 并发上限: ${stats.max_concurrency || 5}`

      // 更新最近明细表格
      const history = stats.recent_history || []
      historyCount.innerText = `显示最近 ${history.length} 条调用`

      if (history.length === 0) {
        historyTableBody.innerHTML = `<tr><td colspan="7" class="empty-hint">暂无调用记录，发起任意请求即可实时呈现。</td></tr>`
      } else {
        const rowsHtml = history.map((rec) => {
          const typeBadge = rec.is_stream
            ? `<span class="badge-tag badge-stream">流式 SSE</span>`
            : `<span class="badge-tag badge-block">阻塞调用</span>`

          let statusBadge = `<span class="badge-tag badge-success">成功 200</span>`
          if (rec.status === 'timeout') {
            statusBadge = `<span class="badge-tag badge-timeout">超时 504</span>`
          } else if (rec.status === 'error') {
            statusBadge = `<span class="badge-tag badge-error" title="${rec.error || ''}">失败 500</span>`
          }

          const tpsText = rec.tps > 0 ? `${rec.tps} tps` : '-'
          const tokensDetail = `${rec.prompt_tokens} / ${rec.completion_tokens} / <strong>${rec.total_tokens}</strong>`

          return `
            <tr>
              <td>${rec.timestamp}</td>
              <td>${rec.model}</td>
              <td>${typeBadge}</td>
              <td>${rec.duration}s</td>
              <td>${tokensDetail}</td>
              <td><strong style="color: var(--accent-color);">${tpsText}</strong></td>
              <td>${statusBadge}</td>
            </tr>
          `
        }).join('')
        historyTableBody.innerHTML = rowsHtml
      }
    } catch (e) {
      // 代理可能未启动，静默忽略
    }
  }

  // 重置统计数据
  resetStatsBtn.addEventListener('click', async () => {
    if (!confirm('确定要清空当前的累计 Token、缓存命中率与调用统计记录吗？')) return
    try {
      const res = await fetch('http://127.0.0.1:8765/v1/stats/reset', { method: 'POST' })
      if (res.ok) {
        await fetchStats()
      }
    } catch (e: any) {
      alert(`重置失败: ${e}`)
    }
  })

  // 启停控制
  toggleBtn.addEventListener('click', async () => {
    toggleBtn.disabled = true
    try {
      if (invokeFn) {
        if (currentRunning) {
          await invokeFn('stop_proxy')
        } else {
          await invokeFn('start_proxy')
        }
      }
    } catch (e: any) {
      alert(`操作失败: ${e}`)
    } finally {
      toggleBtn.disabled = false
      await checkStatus()
      await fetchStats()
      await refreshLogs()
    }
  })

  restartBtn.addEventListener('click', async () => {
    restartBtn.disabled = true
    try {
      if (invokeFn) {
        await invokeFn('restart_proxy')
      }
    } catch (e: any) {
      alert(`重启失败: ${e}`)
    } finally {
      restartBtn.disabled = false
      await checkStatus()
      await fetchStats()
      await refreshLogs()
    }
  })

  // 连通性测试（支持真流式 SSE 逐字打字机与阻塞模式）
  sendTestBtn.addEventListener('click', async () => {
    const prompt = testPromptInput.value.trim()
    if (!prompt) return

    const isStream = streamToggle.checked
    sendTestBtn.disabled = true
    sendTestBtn.innerText = '思考中...'
    testResultBox.style.display = 'block'
    testResultBox.classList.add('is-loading')
    resultContent.innerText = isStream ? '⚡ 正在连接 SSE 流式数据...' : '🚀 正在唤醒本地 Antigravity 引擎...'
    resultMeta.innerText = ''
    testDuration.innerText = '0.0s'

    const startTime = performance.now()
    let timerTicker = setInterval(() => {
      const sec = ((performance.now() - startTime) / 1000).toFixed(1)
      testDuration.innerText = `耗时: ${sec}s`
    }, 100)

    try {
      if (isStream) {
        // 真流式 SSE 读取
        const res = await fetch('http://127.0.0.1:8765/v1/chat/completions', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            model: 'gemini-3.8-flash',
            messages: [{ role: 'user', content: prompt }],
            stream: true,
          }),
        })

        if (!res.ok || !res.body) {
          throw new Error(`HTTP ${res.status}: ${await res.text()}`)
        }

        const reader = res.body.getReader()
        const decoder = new TextDecoder('utf-8')
        let fullText = ''
        let receivedFirstChunk = false
        let firstChunkTime = 0
        let buffer = ''

        let isStreamFinished = false
        while (!isStreamFinished) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''

          for (const line of lines) {
            const trimmed = line.trim()
            if (!trimmed || !trimmed.startsWith('data:')) continue
            const dataStr = trimmed.slice(5).trim()
            if (dataStr === '[DONE]') {
              isStreamFinished = true
              break
            }

            try {
              const chunk = jsonParseSafe(dataStr)
              if (chunk?.choices?.[0]?.delta?.content) {
                if (!receivedFirstChunk) {
                  receivedFirstChunk = true
                  firstChunkTime = ((performance.now() - startTime) / 1000)
                  resultContent.innerText = ''
                  testResultBox.classList.remove('is-loading')
                }
                const tokenPiece = chunk.choices[0].delta.content
                fullText += tokenPiece
                resultContent.innerText = fullText
              }
            } catch (e) {
              // 忽略解析单行错误
            }
          }
        }

        try {
          await reader.cancel()
        } catch (e) {}

        clearInterval(timerTicker)
        testResultBox.classList.remove('is-loading')
        const totalElapsed = ((performance.now() - startTime) / 1000).toFixed(2)
        const estTokens = Math.max(1, Math.round(fullText.length / 2))
        const tps = (estTokens / parseFloat(totalElapsed)).toFixed(1)

        resultMeta.innerText = `首字: ${firstChunkTime ? firstChunkTime.toFixed(2) + 's' : '-'} | 估计 Tokens: ${estTokens} | 速率: ${tps} tps`
        testDuration.innerText = `流式总耗时: ${totalElapsed}s`

      } else {
        // 阻塞模式
        const res = await fetch('http://127.0.0.1:8765/v1/chat/completions', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            model: 'gemini-3.8-flash',
            messages: [{ role: 'user', content: prompt }],
            stream: false,
          }),
        })
        const data = await res.json()
        clearInterval(timerTicker)
        testResultBox.classList.remove('is-loading')

        if (data.error) {
          throw new Error(data.error.message || '请求失败')
        }

        const totalElapsed = ((performance.now() - startTime) / 1000).toFixed(2)
        const content = data.choices[0].message.content
        resultContent.innerText = content
        const usage = data.usage || {}
        const compTokens = usage.completion_tokens || 0
        const tps = compTokens > 0 ? (compTokens / parseFloat(totalElapsed)).toFixed(1) : '-'
        resultMeta.innerText = `入: ${usage.prompt_tokens || 0} | 出: ${compTokens} | 总量: ${usage.total_tokens || 0} | 速率: ${tps} tps`
        testDuration.innerText = `总响应耗时: ${totalElapsed}s`
      }
    } catch (e: any) {
      clearInterval(timerTicker)
      testResultBox.classList.remove('is-loading')
      resultContent.innerText = `请求失败: ${e.message || e}`
      testDuration.innerText = '请求失败'
    } finally {
      clearInterval(timerTicker)
      sendTestBtn.disabled = false
      sendTestBtn.innerText = '测试调用'
      await fetchStats()
      await refreshLogs()
    }
  })

  function jsonParseSafe(str: string): any {
    try {
      return JSON.parse(str)
    } catch {
      return null
    }
  }

  // 刷新日志
  async function refreshLogs() {
    try {
      if (invokeFn) {
        const logs: string = await invokeFn('get_proxy_logs')
        logViewport.innerText = logs || '暂无日志记录。'
      } else {
        logViewport.innerText = '服务在线 (http://127.0.0.1:8765)'
      }
      logViewport.scrollTop = logViewport.scrollHeight
    } catch (e) {
      logViewport.innerText = '读取日志失败。'
    }
  }

  refreshLogsBtn.addEventListener('click', refreshLogs)

  // 启动定时轮询
  checkStatus()
  fetchStats()
  refreshLogs()
  setInterval(checkStatus, 3000)
  setInterval(fetchStats, 2000)
  setInterval(refreshLogs, 5000)
}
