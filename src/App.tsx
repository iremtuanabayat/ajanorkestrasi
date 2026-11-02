import { FormEvent, useEffect, useState } from "react"

type Agent = { id: string; name: string; description: string; model_name?: string; is_active: boolean; capabilities?: string[] }
type Health = { status?: string; ollama?: { connected?: boolean; model?: string }; model?: string }
type Delivery = { project_id: string; project_name: string; project_type: string; technology_stack: string[]; generated_files: string[]; status: string; test_status: string; preview_url?: string | null; workspace_path: string; test_results: { checks?: { name: string; passed: boolean; details: string }[] } }
type Message = { role: "user" | "assistant"; content: string; delivery?: Delivery }
const API = import.meta.env.VITE_API_URL || "http://localhost:8000/api"

const icons: Record<string, string> = { home: "⌂", models: "▤", flow: "⌘", agents: "♙", chat: "▢", settings: "⚙", plus: "+", send: "↗", spark: "✦" }
function Icon({ name }: { name: string }) { return <span className="icon" aria-hidden="true">{icons[name]}</span> }
function Robot({ small = false }: { small?: boolean }) { return <div className={`robot ${small ? "robot-small" : ""}`} aria-hidden="true"><i/><i/><b/></div> }

export default function App() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [health, setHealth] = useState<Health | null>(null)
  const [models, setModels] = useState<string[]>([])
  const [messages, setMessages] = useState<Message[]>([{ role: "assistant", content: "Merhaba! Ben Orkestra Yöneticisi. Bir ajan seçin ya da görevinizi yazın; yerel modeliniz hazır olduğunda birlikte çalışmaya başlayalım." }])
  const [input, setInput] = useState("")
  const [selectedAgent, setSelectedAgent] = useState("")
  const [mode, setMode] = useState<"single" | "multi">("multi")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [dialog, setDialog] = useState(false)
  const [agentName, setAgentName] = useState("")
  const [agentDescription, setAgentDescription] = useState("")
  const [agentPrompt, setAgentPrompt] = useState("")
  const [activeMenu, setActiveMenu] = useState(0)
  const [conversationId, setConversationId] = useState("")
  const [taskId, setTaskId] = useState("")
  const [taskStatus, setTaskStatus] = useState("")
  const [activity, setActivity] = useState("")
  const [conversations, setConversations] = useState<{ id: string; title: string }[]>([])
  const [fileViews, setFileViews] = useState<Record<string, { path: string; content: string }[]>>({})

  const refresh = async () => {
    try {
      const [h, a, m] = await Promise.all([fetch(`${API}/health`), fetch(`${API}/agents`), fetch(`${API}/models`)] )
      if (!h.ok || !a.ok || !m.ok) throw new Error("API yanıt vermedi")
      const healthData = await h.json(), agentData = await a.json(), modelData = await m.json()
      setHealth(healthData); setAgents(Array.isArray(agentData) ? agentData : agentData.agents || [])
      setModels(Array.isArray(modelData) ? modelData.map((x: any) => typeof x === "string" ? x : x.name) : modelData.models?.map((x: any) => typeof x === "string" ? x : x.name) || [])
      setError("")
    } catch { setHealth(null); setError("Backend bağlantısı yok · API http://localhost:8000 üzerinde bekleniyor") }
  }
  useEffect(() => { void refresh(); const timer = window.setInterval(() => void refresh(), 15000); return () => window.clearInterval(timer) }, [])
  useEffect(() => { void fetch(`${API}/conversations`).then(response => response.ok ? response.json() : []).then(rows => setConversations(rows)).catch(() => setConversations([])) }, [])
  useEffect(() => { if (!selectedAgent && agents.length) setSelectedAgent(agents[0].id) }, [agents, selectedAgent])

  const createAgent = async (event: FormEvent) => {
    event.preventDefault(); setError("")
    try {
      const response = await fetch(`${API}/agents`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: agentName, description: agentDescription, system_prompt: agentPrompt, model_name: models[0] || undefined, capabilities: ["analysis"], is_active: true }) })
      if (!response.ok) throw new Error((await response.json()).detail || "Ajan oluşturulamadı")
      const created = await response.json(); setAgents(current => [...current, created]); setSelectedAgent(created.id); setDialog(false); setAgentName(""); setAgentDescription(""); setAgentPrompt("")
    } catch (e) { setError(e instanceof Error ? e.message : "Ajan oluşturulamadı") }
  }
  const sendMessage = async (event: FormEvent) => {
    event.preventDefault(); const prompt = input.trim(); if (!prompt || busy) return
    setInput(""); setError(""); setMessages(current => [...current, { role: "user", content: prompt }]); setBusy(true)
    try {
      const response = await fetch(`${API}/${mode === "multi" ? "orchestrate" : "chat"}?stream=true`, { method: "POST", headers: { "Content-Type": "application/json", "Accept": "text/event-stream" }, body: JSON.stringify({ message: prompt, user_input: prompt, agent_id: selectedAgent || undefined, execution_mode: mode, conversation_id: conversationId || undefined }) })
      if (!response.ok) throw new Error((await response.json()).detail || "Görev tamamlanamadı")
      if (!response.body) throw new Error("Streaming yanıtı alınamadı")
      const reader = response.body.getReader(), decoder = new TextDecoder(); let buffer = "", answer = "", assistantAdded = false, projectDelivery: Delivery | undefined
      const updateAssistant = (content: string) => setMessages(current => {
        if (!assistantAdded) { assistantAdded = true; return [...current, { role: "assistant", content }] }
        return current.map((message, index) => index === current.length - 1 && message.role === "assistant" ? { ...message, content } : message)
      })
      while (true) {
        const { value, done } = await reader.read(); if (done) break
        buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n"); const frames = buffer.split("\n\n"); buffer = frames.pop() || ""
        for (const frame of frames) {
          const event = frame.match(/^event: (.+)$/m)?.[1], raw = frame.match(/^data: (.+)$/m)?.[1]
          if (!raw) continue
          const data = JSON.parse(raw)
          if (event === "task") { setTaskId(data.task_id); setTaskStatus(data.status); if (data.conversation_id) setConversationId(data.conversation_id) }
          if (event === "step") { setActivity(data.agent_name ? `${data.agent_name} · ${data.status}` : data.label || "Ajan çalışıyor"); setTaskStatus(data.status); if (data.output) { answer += `${answer ? "\n\n" : ""}## ${data.agent_name || "Ajan"}\n${data.output}`; updateAssistant(answer) } }
          if (event === "token") { answer += data.text; updateAssistant(answer) }
          if (event === "done") { answer = data.response || answer; projectDelivery = data.project_delivery; updateAssistant(answer); if (projectDelivery) setMessages(current => current.map((message, index) => index === current.length - 1 && message.role === "assistant" ? { ...message, delivery: projectDelivery } : message)); setConversationId(data.conversation_id || conversationId); setTaskStatus(data.status); setTaskId(""); setActivity("") }
          if (event === "error") throw new Error(data.message || "Görev tamamlanamadı")
          if (event === "cancelled") { setTaskStatus("cancelled"); setTaskId(""); setActivity("") }
        }
      }
      void refresh(); void fetch(`${API}/conversations`).then(response => response.ok ? response.json() : []).then(rows => setConversations(rows)).catch(() => undefined)
    } catch (e) { const message = e instanceof Error ? e.message : "İstek gönderilemedi"; setError(message); setMessages(current => [...current, { role: "assistant", content: `İstek tamamlanamadı: ${message}` }]) }
    finally { setBusy(false) }
  }
  const cancelTask = async () => { if (!taskId) return; try { await fetch(`${API}/tasks/${taskId}/cancel`, { method: "POST" }); setTaskStatus("cancelled") } catch { setError("Görev iptal isteği gönderilemedi") } }
  const openConversation = async (id: string) => { try { const response = await fetch(`${API}/conversations/${id}`); if (!response.ok) throw new Error("Sohbet yüklenemedi"); const data = await response.json(); setConversationId(id); setMessages(data.messages.map((item: Message) => ({ role: item.role, content: item.content }))) } catch (e) { setError(e instanceof Error ? e.message : "Sohbet yüklenemedi") } }
  const newConversation = async () => { try { const response = await fetch(`${API}/conversations`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: "Yeni sohbet" }) }); if (!response.ok) throw new Error("Yeni sohbet oluşturulamadı"); const row = await response.json(); setConversationId(row.id); setConversations(current => [row, ...current]); setMessages([]) } catch (e) { setError(e instanceof Error ? e.message : "Yeni sohbet oluşturulamadı") } }
  const toggleFiles = async (projectId: string) => { if (fileViews[projectId]) { setFileViews(current => { const next = { ...current }; delete next[projectId]; return next }); return } try { const response = await fetch(`${API}/projects/${projectId}/files`); if (!response.ok) throw new Error("Proje dosyaları yüklenemedi"); const files = await response.json(); setFileViews(current => ({ ...current, [projectId]: files })) } catch (e) { setError(e instanceof Error ? e.message : "Proje dosyaları yüklenemedi") } }

  const nav = ["home", "models", "flow", "agents", "chat", "settings"]
  const activeAgents = agents.filter(agent => agent.is_active)
  return <main className="app-shell">
    <header className="topbar">
      <a className="brand" href="#"><span className="brand-orbit"><Robot small/></span><span>AI<br/><b>ORCHESTRA</b></span></a>
      <div className="crumb"><span>Çalışma alanı</span><b>/</b><strong>{["Genel Bakış", "Modeller", "Orkestrasyon", "Ajanlar", "Sohbet", "Ayarlar"][activeMenu]}</strong></div>
      <div className="top-actions"><span className={`connection ${health ? "online" : "offline"}`}><i/>{health ? "Yerel sistem bağlı" : "Bağlantı bekleniyor"}</span><button className="avatar">AO</button></div>
    </header>
    <div className="workspace">
      <aside className="sidebar" aria-label="Ana menü">{nav.map((item, index) => <button key={item} className={activeMenu === index ? "active" : ""} onClick={() => setActiveMenu(index)} aria-label={item}><Icon name={item}/></button>)}<div className="sidebar-bottom"><button aria-label="Yeni sohbet" onClick={newConversation}><Icon name="plus"/></button></div></aside>
      <section className="main-content">
        <div className="welcome"><div><div className="eyebrow"><span className="eyebrow-line"/> YEREL AJAN ÇALIŞMA ALANI</div><h1>Orkestranız hazır mı?</h1><p>Ajanlarınızı yönetin, modellerinizi bağlayın ve görevlerinizi tek merkezden yürütün.</p></div><button className="primary-button" onClick={() => setDialog(true)}><Icon name="plus"/> Yeni ajan oluştur</button></div>
        {error && <div className="connection-banner"><span>{error}</span><button onClick={() => void refresh()}>Yeniden dene</button></div>}
        <div className="stats-grid">
          <article className="stat-card"><div className="stat-heading"><span>OLLAMA DURUMU</span><span className="stat-icon teal">◉</span></div><strong className="stat-value">{health?.ollama?.connected ? "Bağlı" : "Çevrimdışı"}</strong><div className="stat-foot"><i className={health?.ollama?.connected ? "pulse" : "muted-dot"}/>{health?.ollama?.connected ? "Yerel sunucu erişilebilir" : "localhost:11434 yanıt vermiyor"}</div></article>
          <article className="stat-card"><div className="stat-heading"><span>AKTİF MODEL</span><span className="stat-icon violet"><Icon name="spark"/></span></div><strong className="stat-value model-value">{health?.ollama?.model || health?.model || models[0] || "—"}</strong><div className="stat-foot">{models.length} model algılandı</div></article>
          <article className="stat-card"><div className="stat-heading"><span>KAYITLI AJANLAR</span><span className="stat-icon blue"><Icon name="agents"/></span></div><strong className="stat-value">{agents.length.toString().padStart(2, "0")}</strong><div className="stat-foot"><i className="pulse"/>{activeAgents.length} ajan kullanılabilir</div></article>
          <article className="stat-card"><div className="stat-heading"><span>ÇALIŞAN GÖREVLER</span><span className="stat-icon amber">↗</span></div><strong className="stat-value">{busy ? "01" : "00"}</strong><div className="stat-foot">Gerçek zamanlı görev durumu</div></article>
        </div>
        <div className="content-grid">
          <section className="panel agents-panel"><div className="panel-heading"><div><span className="section-kicker">EKİBİN</span><h2>Ajanlar <span className="count-pill">{agents.length}</span></h2></div><button className="text-button" onClick={() => setActiveMenu(3)}>Tümünü gör <span>→</span></button></div>
            {agents.length ? <div className="agent-list">{agents.slice(0, 5).map((agent, i) => <button className={`agent-card ${selectedAgent === agent.id ? "selected" : ""}`} key={agent.id} onClick={() => setSelectedAgent(agent.id)}><span className={`agent-avatar tone-${i % 4}`}><Robot small/></span><span className="agent-info"><strong>{agent.name}</strong><small>{agent.description || "Genel amaçlı asistan"}</small></span><span className={`agent-state ${agent.is_active ? "ready" : "paused"}`}><i/>{agent.is_active ? "Hazır" : "Pasif"}</span><span className="agent-chevron">›</span></button>)}</div> : <div className="agents-empty"><div className="empty-orbit"><Robot/></div><strong>Ekibiniz yeni görevini bekliyor</strong><p>İhtiyacınıza uygun ilk ajanı oluşturun.</p><button className="outline-button" onClick={() => setDialog(true)}><Icon name="plus"/> İlk ajanı oluştur</button></div>}
          </section>
          <section className="panel model-panel"><div className="panel-heading"><div><span className="section-kicker">YEREL ALTYAPI</span><h2>Model servisi</h2></div><span className={`service-badge ${health?.ollama?.connected ? "service-up" : "service-down"}`}><i/>{health?.ollama?.connected ? "Çalışıyor" : "Bekleniyor"}</span></div><div className="model-visual"><div className="model-ring ring-one"/><div className="model-ring ring-two"/><div className="model-core"><Icon name="spark"/></div><span className="orbit-point point-a"/><span className="orbit-point point-b"/><span className="orbit-point point-c"/></div><div className="model-summary"><strong>{health?.ollama?.model || health?.model || "Ollama bağlantısı gerekli"}</strong><span>{health?.ollama?.connected ? "Aktif model · Ollama" : "Yerel model sunucusuna bağlanın"}</span></div><div className="model-footer"><span><i className={health?.ollama?.connected ? "pulse" : "muted-dot"}/>{health?.ollama?.connected ? "localhost:11434" : "Sunucuya erişilemiyor"}</span><button onClick={() => void refresh()}>Kontrol et ↗</button></div></section>
        </div>
        <section className="panel activity-panel"><div className="panel-heading"><div><span className="section-kicker">CANLI GÖZLEM</span><h2>Son aktiviteler</h2></div><button className="text-button" onClick={() => setActiveMenu(2)}>İzleyiciyi aç <span>→</span></button></div>{busy ? <div className="activity-row"><span className="activity-symbol running">↻</span><div><strong>{activity || "Yeni görev yürütülüyor"}</strong><p>{selectedAgent ? agents.find(a => a.id === selectedAgent)?.name : "Orkestra"} · {taskStatus || "Görev başlatılıyor"}</p></div><time>şimdi</time><span className="running-label">{taskStatus || "Çalışıyor"}</span></div> : <div className="activity-empty"><span className="activity-symbol">◷</span><div><strong>{taskStatus === "cancelled" ? "Görev iptal edildi" : "Henüz görev etkinliği yok"}</strong><p>Görevler başlatıldığında gerçek durumları burada görünür.</p></div><span className="activity-wait">GÖREV BEKLENİYOR</span></div>}</section>
      </section>
      <aside className="orchestrator-panel"><div className="orchestrator-head"><div><span className="section-kicker">AI ORCHESTRA</span><h2>Orkestra Şefi</h2></div><button className="more-button" onClick={newConversation}>＋</button></div><div className="conductor-card"><div className="conductor-visual"><div className="conductor-halo"/><Robot/></div><strong>Orkestratör</strong><span>Görevleri ajanlara yönlendirir</span><div className="orchestrator-status"><i className={health?.ollama?.connected ? "pulse" : "muted-dot"}/>{health?.ollama?.connected ? "Sistem hazır" : "Bağlantı bekleniyor"}</div></div><div className="quick-chat"><div className="quick-chat-heading"><span>HIZLI GÖREV</span><span className="secure-tag">⌑ YEREL</span></div>{conversations.length > 0 && <select className="agent-select" aria-label="Sohbet geçmişi" value={conversationId} onChange={e => void openConversation(e.target.value)}><option value="">Sohbet geçmişi</option>{conversations.map(row => <option key={row.id} value={row.id}>{row.title}</option>)}</select>}<div className="mode-switch"><button className={mode === "single" ? "selected" : ""} onClick={() => setMode("single")}>Tek ajan</button><button className={mode === "multi" ? "selected" : ""} onClick={() => setMode("multi")}>Çoklu ajan</button></div>{mode === "single" && <select className="agent-select" value={selectedAgent} onChange={e => setSelectedAgent(e.target.value)}><option value="">Ajan seçin</option>{agents.map(agent => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select>}<div className="quick-messages">{messages.map((message, index) => <div className={`quick-message ${message.role}`} key={`${index}-${message.content.slice(0, 8)}`}>{message.role === "assistant" && <Robot small/>}<p>{message.content}</p>{message.delivery && <div className="delivery-card"><div className="delivery-title"><span>PROJE TESLİMİ</span><i className={message.delivery.test_status === "passed" ? "delivery-ok" : "delivery-warn"}>{message.delivery.test_status === "passed" ? "QA BAŞARILI" : "QA UYARISI"}</i></div><strong>{message.delivery.project_name}</strong><small>{message.delivery.technology_stack.join(" · ")} · {message.delivery.generated_files.length} dosya</small>{message.delivery.preview_url && <a className="delivery-preview" href={message.delivery.preview_url} target="_blank" rel="noreferrer">Önizlemeyi aç ↗</a>}<small className="delivery-path">{message.delivery.workspace_path}</small><button className="delivery-files-button" onClick={() => void toggleFiles(message.delivery!.project_id)}>{fileViews[message.delivery.project_id] ? "Dosyaları gizle" : "Dosyaları göster"}</button>{fileViews[message.delivery.project_id]?.map(file => <details key={file.path} className="delivery-file"><summary>{file.path}</summary><pre>{file.content}</pre></details>)}{message.delivery.test_results.checks?.map(check => <small className="delivery-check" key={check.name}>{check.passed ? "✓" : "!"} {check.name}</small>)}</div>}</div>)}{busy && <div className="typing"><i/><i/><i/> {activity || "Orkestra çalışıyor"}</div>}</div><form className="composer" onSubmit={sendMessage}><textarea value={input} onChange={e => setInput(e.target.value)} placeholder="Bir görev yazın..." rows={2} aria-label="Görev mesajı"/><div className="composer-bottom"><span>{taskId ? <button type="button" className="cancel-task" onClick={cancelTask}>Görevi iptal et</button> : "Yanıtlar yerel modelde işlenir"}</span><button type="submit" className="send-button" aria-label="Görevi gönder" disabled={busy || !input.trim()}><Icon name="send"/></button></div></form></div><div className="privacy-note"><span>◇</span><p>Verileriniz cihazınızda kalır.<br/><b>Yerel ve gizli.</b></p><span className="privacy-lock">⌑</span></div></aside>
    </div>
    {dialog && <div className="modal-backdrop" onMouseDown={() => setDialog(false)}><form className="modal" onSubmit={createAgent} onMouseDown={e => e.stopPropagation()}><button type="button" className="modal-close" onClick={() => setDialog(false)}>×</button><Robot/><span className="section-kicker">EKİBE YENİ BİR ÜYE</span><h2>Ajan oluştur</h2><p>Ajanın uzmanlığını tanımlayın; model ve yetenekler API üzerinden kaydedilir.</p><label>Ajan adı<input required value={agentName} onChange={e => setAgentName(e.target.value)} placeholder="örn. Araştırma ajanı"/></label><label>Açıklama<input value={agentDescription} onChange={e => setAgentDescription(e.target.value)} placeholder="Uzmanlık alanı"/></label><label>System prompt<textarea required value={agentPrompt} onChange={e => setAgentPrompt(e.target.value)} placeholder="Ajanın rolünü ve çalışma şeklini yazın" rows={4}/></label>{error && <p className="form-error">{error}</p>}<button className="primary-button modal-submit" type="submit"><Icon name="plus"/> Ajanı kaydet</button></form></div>}
  </main>
}
