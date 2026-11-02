# AI Orchestra

Yerel Ollama modellerini kullanan React + FastAPI ajan çalışma alanı.

## Özellikler ve sınırlar

- Ajan CRUD ve kalıcı SQLite kayıtları; model listesi ve Ollama health.
- Tekli chat token streaming'i; çoklu ajan akışında yerel supervisor göreve göre en fazla dört ajan seçer (hatalı router çıktısında yerel anahtar kelime fallback'i). LangGraph worker ajanlarını paralel çalıştırır, sonuçları reducer ile toplar ve seçildiyse synthesis ajanına verir.
- Chat endpoint'leri `?stream=true` ile task, step, token, done ve error SSE olayları verir.
- Görev iptali sonraki stream/workflow adımında uygulanır. Bekleyen Ollama HTTP çağrısı hemen kesilmeyebilir.
- Sohbet mesajları ve ayarlar kalıcıdır. SSE kuyrukları süreç belleğinde tutulur; backend restart sonrası geçmiş görevler okunabilir ancak eski event stream replay edilmez.
- Statik web proje oluşturma/değiştirme için LangGraph planla→üret→yaz→runtime→QA→onar→teslim akışı, güvenli proje dizini ve ZIP teslimi.
- Çoklu dosya yükleme, CSV/JSON/kod/HTML/CSS/TXT/Markdown, DOCX/XLSX XML ve PDF (pypdf kuruluysa) metin çıkarımı; ZIP içeriğini çıkarmadan güvenli metin üyelerini okuma; checksum duplicate kontrolü ve 20 MB sınırı.
- SQLite FTS5 kaynaklı chunk araması; upload/source kayıtları konuşma ve isteğe bağlı projeye bağlanır. URL alımı HTML/plain text/PDF içindir; loopback/private IP ve redirect reddedilir.
- Proje memory CRUD API'si, sürümlü artifact kopyaları, artifact indirme/karşılaştırma ve projeyi ZIP olarak paketleme.
- Tekli ajanda allowlist tool calling: kaynak bağlamı ara, proje dosyalarını listele ve izlenen dosyayı oku. Dosya yazımı, silme ve terminal komutları model tool'larına açık değildir.
- Mevcut proje dosyalarını değiştirme öncesi chat içinde approval request oluşturulur; reddedilince yazım başlamaz.
- SSE kuyrukları ve approval bekleyicileri süreç belleğindedir; backend restart sonrası event replay/approval devam ettirme yoktur. Yerel uygulamada kullanıcı kimlik doğrulaması bulunmaz.
- Görsel vision analizi yapılandırılmış model gerektirir; yoksa dosya kaydedilir ve analiz yapılmadığı bildirilir. GitHub repository ağacı incelemesi/kimlik doğrulaması ve tam proje dashboard henüz yoktur.
- Dışa aktarılmış Figma tasarım dosyası bulunamadı; mevcut React ekranının koyu neon görsel dili korunmuştur.

## Mimari

```text
src/                         React 19 + Vite + TypeScript dashboard
backend/app/api/routes/      FastAPI API uçları
backend/app/llm/             Ollama HTTP ve streaming provider
backend/app/orchestration/   LangGraph state workflow
backend/app/services/        Arka plan task runner ve SSE olayları
backend/app/database/        SQLAlchemy modelleri ve SQLite
backend/app/schemas/         Pydantic istek/yanıt şemaları
```

## Kurulum

Python 3.11+ ve Node.js gerekir:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

`.env` içindeki temel ayarlar:

```dotenv
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:3b
DATABASE_URL=sqlite:///./ai_orchestra.db
FRONTEND_ORIGIN=http://localhost:8443
```

## Ollama

Ollama'yı Windows'ta çalıştırıp bir model indirin:

```powershell
ollama pull qwen2.5:3b
ollama list
```

Modeli `.env` içindeki `OLLAMA_MODEL` ile değiştirin. Backend Ollama `/api/tags` ve `/api/chat` uçlarını kullanır.

## Başlatma

Backend:

```powershell
$env:PYTHONPATH = (Resolve-Path .\backend).Path
uvicorn app.main:app --app-dir backend --reload --port 8000
```

Frontend:

```powershell
pnpm install
$env:VITE_API_URL = "http://localhost:8000/api"
pnpm dev
```

Figma Make preview varsayılan portu `8443`'tür. API dokümantasyonu `http://localhost:8000/docs` adresindedir.

## API

| Method | Endpoint | İşlev |
|---|---|---|
| GET | `/api/health` | Ollama bağlantısı ve kullanılabilir modeller |
| GET, POST | `/api/agents` | Ajan listeleme ve oluşturma |
| GET, PUT, DELETE | `/api/agents/{agent_id}` | Ajan okuma, düzenleme, silme |
| GET | `/api/models` | Ollama modelleri |
| POST | `/api/chat` | Tek ajan yanıtı; `?stream=true` ile SSE |
| POST | `/api/orchestrate` | LangGraph çoklu ajan; `?stream=true` ile SSE |
| GET | `/api/tasks` | Son görevler |
| GET | `/api/tasks/{task_id}` | Görev ve adımları |
| GET | `/api/tasks/{task_id}/events` | Görev SSE akışı/snapshot |
| POST | `/api/tasks/{task_id}/cancel` | Aktif görevi iptal etme isteği |
| POST, GET | `/api/uploads` | Dosya yükleme/listeleme |
| DELETE | `/api/uploads/{file_id}` | Yüklenen dosya ve bağlamını silme |
| POST, GET, DELETE | `/api/sources` | Web kaynağı ekleme/listeleme/silme |
| GET | `/api/artifacts` | Artifact sürümlerini listeleme |
| GET | `/api/artifacts/{artifact_id}/download` | Artifact indirme |
| GET | `/api/artifacts/{artifact_id}/versions` | Sürümleri listeleme |
| GET | `/api/artifacts/{artifact_id}/compare/{version}` | Metin sürümlerini karşılaştırma |
| POST | `/api/projects/{project_id}/package` | Projeyi ZIP olarak paketleme |
| GET, POST, PATCH, DELETE | `/api/projects/{project_id}/memory` | Proje hafızası kayıtlarını yönetme |
| POST | `/api/approvals/{approval_id}/resolve` | Bekleyen değişikliği onaylama/reddetme |
| GET, POST | `/api/conversations` | Sohbetleri listeleme/oluşturma |
| GET | `/api/conversations/{id}` | Mesaj geçmişini okuma |
| GET, PUT | `/api/settings` | Ollama ve varsayılan ajan ayarları |

Örnek istek:

```json
{
  "message": "Bu fonksiyonu açıkla",
  "agent_id": "ajan-uuid",
  "execution_mode": "single",
  "conversation_id": "opsiyonel-konuşma-id"
}
```

Çoklu ajan modu için en az bir aktif ajan gerekir. Synthesis ajanı adı içinde `synthesis` taşımalıdır.

## Doğrulama

Frontend build:

```powershell
pnpm build
```

Yerel Ollama gerektiren canlı smoke suite (geçici SQLite DB ile):

```powershell
$env:PYTHONPATH = (Resolve-Path .\backend).Path
python backend/tests/smoke_orchestrator.py
```

Suite model listesi/doğrudan chat, FastAPI health, ajan CRUD, single-agent, supervisor/LangGraph multi-agent, kalıcı task steps ve SSE token/done olaylarını kontrol eder. Workspace ingestion/context smoke kontrolleri ayrıca CSV çıkarımı, checksum dedupe, FTS5 retrieval ve private-IP URL reddini doğrular.

Backend health:

```powershell
Invoke-RestMethod http://localhost:8000/api/health
```

`requirements.txt` backend ve test çalıştırma bağımlılıklarını bildirir.
