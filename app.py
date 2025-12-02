import os
import json
from datetime import date, timedelta
from typing import Any, Dict, List

import uvicorn
import requests
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from openai import OpenAI
from dotenv import load_dotenv

# --- ENV YÜKLE ---
load_dotenv()

# --- CONFIG ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY env değişkeni bulunamadı. .env dosyasını kontrol et.")

MCP_URL = "https://ihalemcp.fastmcp.app/mcp"
MCP_TOOL_NAME = "search_tenders"

client = OpenAI(api_key=OPENAI_API_KEY)

app = FastAPI()


def fix_mojibake(text: str) -> str:
    if not isinstance(text, str):
        return text
    try:
        return text.encode("latin1").decode("utf-8")
    except Exception:
        return text


def normalize_tender_item(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": item.get("id"),
        "ikn": item.get("ikn"),
        "name": fix_mojibake(item.get("name", "")),
        "type": fix_mojibake(item.get("type", {}).get("description", "")),
        "status": fix_mojibake(item.get("status", {}).get("description", "")),
        "authority": fix_mojibake(item.get("authority", "")),
        "province": fix_mojibake(item.get("province", "")),
        "tender_datetime": fix_mojibake(item.get("tender_datetime", "")),
        "document_url": item.get("document_url"),
    }


def get_today_str() -> str:
    return date.today().isoformat()


def build_mcp_arguments_with_gpt(user_query: str) -> dict:
    today_str = get_today_str()
    today = date.today()
    
    # Örnek tarihler hesapla
    in_10_days = (today + timedelta(days=10)).isoformat()
    in_1_week = (today + timedelta(days=7)).isoformat()
    in_2_weeks = (today + timedelta(days=14)).isoformat()
    in_1_month = (today + timedelta(days=30)).isoformat()
    in_3_months = (today + timedelta(days=90)).isoformat()
    ago_1_week = (today - timedelta(days=7)).isoformat()
    ago_1_month = (today - timedelta(days=30)).isoformat()
    ago_3_months = (today - timedelta(days=90)).isoformat()
    
    system_prompt = f"""Sen bir çevirmen gibi davranan sistemsin.
Görevin: Kullanıcının Türkçe doğal dilde yazdığı ihale arama isteğini,
MCP 'search_tenders' tool'u için kullanılacak arguments JSON'una çevirmek.

BUGÜNÜN TARİHİ: {today_str}

SADECE GEÇERLİ BİR JSON OBJESİ DÖN. Açıklama, markdown, backtick EKLEME.

=== MCP API DETAYLARI ===

1. search_text (string): Aranacak metin. Boş string "" olabilir.

2. tender_types (array of int): 1=Mal, 2=Yapım, 3=Hizmet, 4=Danışmanlık. Boş liste [] = tüm türler

3. provinces (array of int): İL PLAKA KODLARI - Ankara=6, İstanbul=34, İzmir=35, Bursa=16, Antalya=7
   BOŞ LİSTE [] = TÜM ŞEHİRLER
   
4. TARIH FİLTRELEME:
   
   A) İHALE TARİHİ (ihalenin YAPILACAĞI tarih):
      - tender_date_filter: "from_today" veya "date_range"
      - tender_date_start: "YYYY-MM-DD"
      - tender_date_end: "YYYY-MM-DD"
      
   B) İLAN TARİHİ (ihalenin YAYINLANDIĞI tarih):
      - announcement_date_filter: "today" veya "date_range"
      - announcement_date_start: "YYYY-MM-DD"
      - announcement_date_end: "YYYY-MM-DD"

5. limit (int): Maksimum sonuç (varsayılan 100)

=== TARİH HESAPLAMA KURALLARI ===

Bugün: {today_str}

GEÇMİŞE DÖNÜK (son X gün/hafta/ay):
- "son 1 hafta" = announcement_date_filter="date_range", announcement_date_start="{ago_1_week}", announcement_date_end="{today_str}"
- "son 1 ay" / "son bir ay" = announcement_date_filter="date_range", announcement_date_start="{ago_1_month}", announcement_date_end="{today_str}"
- "son 3 ay" = announcement_date_filter="date_range", announcement_date_start="{ago_3_months}", announcement_date_end="{today_str}"
- "geçmiş ihaleler" / "kapanmış ihaleler" = tender_date_filter="date_range", tender_date_end="{today_str}"

GELECEĞE DÖNÜK (önümüzdeki X gün/hafta/ay):
- "önümüzdeki 10 gün" / "gelecek 10 gün" = tender_date_filter="date_range", tender_date_start="{today_str}", tender_date_end="{in_10_days}"
- "önümüzdeki 1 hafta" / "bu hafta" / "gelecek hafta" = tender_date_filter="date_range", tender_date_start="{today_str}", tender_date_end="{in_1_week}"
- "önümüzdeki 2 hafta" = tender_date_filter="date_range", tender_date_start="{today_str}", tender_date_end="{in_2_weeks}"
- "önümüzdeki 1 ay" / "bu ay" / "gelecek ay" = tender_date_filter="date_range", tender_date_start="{today_str}", tender_date_end="{in_1_month}"
- "önümüzdeki 3 ay" = tender_date_filter="date_range", tender_date_start="{today_str}", tender_date_end="{in_3_months}"
- "gelecek ihaleler" / "yaklaşan ihaleler" (genel) = tender_date_filter="from_today"

DİĞER:
- "bugün yayınlanan" / "bugünkü ilanlar" = announcement_date_filter="today"
- "bugünkü ihaleler" (bugün yapılacak) = tender_date_filter="date_range", tender_date_start="{today_str}", tender_date_end="{today_str}"
- Tarih belirtilmezse: tarih alanlarını HİÇ EKLEME

ÖNEMLİ: "önümüzdeki", "gelecek", "sonraki" gibi ifadeler GELECEK tarihleri ifade eder.
"X gün içinde", "X gün boyunca", "X günlük" ifadeleri de aynı şekilde.

=== ŞEHİR FİLTRELEME ===

- "İstanbul" → provinces: [34]
- "Ankara" → provinces: [6]
- "İzmir" → provinces: [35]
- "tüm şehirler" / şehir belirtilmezse → provinces: []

=== ÇIKTI ŞEMASI ===

Sadece gerekli alanları ekle, null olanları EKLEME:

{{"search_text": "", "tender_types": [], "provinces": [], "limit": 100}}

JSON dışında hiçbir şey yazma."""

    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_query},
        ],
        temperature=0,
    )

    raw_json_str = resp.choices[0].message.content

    if not raw_json_str or not raw_json_str.strip():
        raise ValueError(f"OpenAI boş JSON döndürdü")

    raw_json_str = raw_json_str.strip()
    if raw_json_str.startswith("```json"):
        raw_json_str = raw_json_str[7:]
    if raw_json_str.startswith("```"):
        raw_json_str = raw_json_str[3:]
    if raw_json_str.endswith("```"):
        raw_json_str = raw_json_str[:-3]
    raw_json_str = raw_json_str.strip()

    try:
        arguments = json.loads(raw_json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON parse hatası: {e}. Çıktı: {raw_json_str[:300]}")

    return normalize_mcp_arguments(arguments, user_query)


def normalize_mcp_arguments(arguments: Dict[str, Any], user_query: str) -> Dict[str, Any]:
    allowed_keys = {
        "search_text", "ikn_year", "ikn_number", "tender_types",
        "tender_date_start", "tender_date_end",
        "announcement_date_start", "announcement_date_end",
        "announcement_date_filter", "tender_date_filter",
        "limit", "skip", "provinces",
    }
    
    cleaned: Dict[str, Any] = {k: v for k, v in arguments.items() if k in allowed_keys}

    if cleaned.get("search_text") is None:
        cleaned["search_text"] = ""

    tt = cleaned.get("tender_types")
    if tt is None or tt == []:
        cleaned["tender_types"] = []
    else:
        if isinstance(tt, (int, str)):
            tt = [tt]
        cleaned["tender_types"] = [int(x) for x in tt if str(x).isdigit() and 1 <= int(x) <= 4]

    prov = cleaned.get("provinces")
    if prov is None:
        cleaned["provinces"] = []
    else:
        if isinstance(prov, (int, str)):
            prov = [prov]
        cleaned["provinces"] = [int(x) for x in prov if str(x).isdigit() and 1 <= int(x) <= 81]

    if not cleaned.get("limit"):
        cleaned["limit"] = 1000

    for key in ["tender_date_start", "tender_date_end", "announcement_date_start", "announcement_date_end"]:
        val = cleaned.get(key)
        if val and isinstance(val, str):
            try:
                date.fromisoformat(val)
            except ValueError:
                cleaned[key] = None
        elif val is None or val == "null":
            cleaned[key] = None

    announcement_filter = cleaned.get("announcement_date_filter")
    if announcement_filter not in ("today", "date_range", None):
        cleaned["announcement_date_filter"] = None

    tender_filter = cleaned.get("tender_date_filter")
    if tender_filter not in ("from_today", "date_range", None):
        cleaned["tender_date_filter"] = None

    if (cleaned.get("announcement_date_start") or cleaned.get("announcement_date_end")) and not cleaned.get("announcement_date_filter"):
        cleaned["announcement_date_filter"] = "date_range"

    if (cleaned.get("tender_date_start") or cleaned.get("tender_date_end")) and not cleaned.get("tender_date_filter"):
        cleaned["tender_date_filter"] = "date_range"

    keys_to_remove = []
    for key in ["announcement_date_filter", "tender_date_filter", 
                "announcement_date_start", "announcement_date_end",
                "tender_date_start", "tender_date_end",
                "ikn_year", "ikn_number", "skip"]:
        if cleaned.get(key) is None:
            keys_to_remove.append(key)
    
    for key in keys_to_remove:
        cleaned.pop(key, None)

    return cleaned


def call_mcp_tool(tool_name: str, arguments: dict) -> dict:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments,
        },
    }

    resp = requests.post(
        MCP_URL,
        json=payload,
        timeout=30,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )

    text_body = resp.text

    try:
        resp.raise_for_status()
    except requests.HTTPError as e:
        raise RuntimeError(f"MCP HTTP error: {e}, body={text_body[:500]}")

    content_type = resp.headers.get("Content-Type", "")

    try:
        if "text/event-stream" in content_type:
            json_chunks = []
            for line in text_body.splitlines():
                line = line.strip()
                if line.startswith("data:"):
                    json_part = line[len("data:"):].strip()
                    if json_part:
                        json_chunks.append(json_part)

            if not json_chunks:
                raise ValueError(f"SSE formatı ama data yok")

            combined = "\n".join(json_chunks)
            data = json.loads(combined)
        else:
            data = resp.json()
    except json.JSONDecodeError as e:
        raise ValueError(f"MCP JSON parse hatası: {e}")

    if "error" in data:
        raise RuntimeError(f"MCP error: {data['error']}")

    return data.get("result", data)


# HTML template - backtick'ler escape edildi
HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8" />
    <title>İhale Arama</title>
    <style>
        * { box-sizing: border-box; }
        body { 
            font-family: system-ui, -apple-system, sans-serif;
            margin: 0; padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
        }
        .container { 
            max-width: 1400px; margin: 0 auto;
            background: white; border-radius: 16px;
            padding: 32px; box-shadow: 0 20px 60px rgba(0,0,0,0.3);
        }
        h1 { margin: 0 0 8px 0; color: #1a202c; font-size: 32px; }
        .subtitle { color: #718096; margin-bottom: 24px; }
        label { display: block; margin-bottom: 8px; color: #2d3748; font-weight: 600; }
        textarea {
            width: 100%; padding: 12px 16px;
            border: 2px solid #e2e8f0; border-radius: 8px;
            font-size: 15px; font-family: inherit; resize: vertical;
        }
        textarea:focus { outline: none; border-color: #667eea; }
        button {
            width: 100%; padding: 14px; margin-top: 12px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white; border: none; border-radius: 8px;
            font-size: 16px; font-weight: 600; cursor: pointer;
        }
        button:hover { transform: translateY(-2px); box-shadow: 0 8px 20px rgba(102, 126, 234, 0.4); }
        .debug-info {
            margin: 16px 0; padding: 12px; background: #edf2f7;
            border-radius: 8px; font-size: 12px; font-family: monospace;
            white-space: pre-wrap; max-height: 150px; overflow-y: auto; display: none;
        }
        .debug-toggle { cursor: pointer; color: #667eea; font-size: 13px; margin: 8px 0; }
        .filter-container {
            margin: 16px 0; padding: 16px; background: #f7fafc; border-radius: 8px;
        }
        .filters-grid {
            display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 12px; align-items: end;
        }
        .filter-input, .filter-select {
            width: 100%; padding: 10px 16px;
            border: 2px solid #e2e8f0; border-radius: 8px; font-size: 14px; background: white;
        }
        .results-count { margin-top: 8px; color: #718096; font-size: 14px; }
        .table-container { overflow-x: auto; border-radius: 8px; border: 1px solid #e2e8f0; }
        table { width: 100%; border-collapse: collapse; font-size: 14px; }
        th {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white; padding: 12px 16px; text-align: left; font-weight: 600;
        }
        td { padding: 12px 16px; border-bottom: 1px solid #e2e8f0; }
        tbody tr:hover { background-color: #f7fafc; }
        a { color: #667eea; text-decoration: none; font-weight: 600; }
        a:hover { color: #764ba2; text-decoration: underline; }
        .no-results { text-align: center; padding: 48px; color: #718096; }
        .loading { text-align: center; padding: 48px; color: #667eea; }
        .error { padding: 16px; background: #fed7d7; color: #c53030; border-radius: 8px; margin-top: 16px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>İhale Arama Sistemi</h1>
        <p class="subtitle">Doğal dilde isteğinizi yazın</p>

        <div>
            <label>Doğal dil sorgu:</label>
            <textarea id="query" rows="3" placeholder="İhale aramanızı buraya yazın..."></textarea>
            <button id="searchBtn">Ara</button>
        </div>

        <div id="results" style="display: none; margin-top: 32px;">
            <h2>Sonuçlar</h2>
            <div class="debug-toggle" id="debugToggle">🔧 API Parametrelerini Göster/Gizle</div>
            <div class="debug-info" id="debugInfo"></div>
            
            <div class="filter-container" id="filterContainer" style="display: none;">
                <div class="filters-grid">
                    <div>
                        <label>Tabloda ara</label>
                        <input type="text" id="filterInput" class="filter-input" placeholder="Ara..." />
                    </div>
                    <div>
                        <label>Tür</label>
                        <select id="filterType" class="filter-select"></select>
                    </div>
                    <div>
                        <label>İl</label>
                        <select id="filterProvince" class="filter-select"></select>
                    </div>
                    <div>
                        <label>Tarih Başlangıç</label>
                        <input type="date" id="filterDateStart" class="filter-input" />
                    </div>
                    <div>
                        <label>Tarih Bitiş</label>
                        <input type="date" id="filterDateEnd" class="filter-input" />
                    </div>
                    <div>
                        <label>Doküman</label>
                        <select id="filterDocument" class="filter-select">
                            <option value="">Tümü</option>
                            <option value="yes">Sadece dokümanlı</option>
                            <option value="no">Sadece dokümansız</option>
                        </select>
                    </div>
                </div>
                <div class="results-count" id="resultsCount"></div>
            </div>
            
            <div class="table-container">
                <div id="tendersTable"></div>
            </div>
        </div>
        
        <div id="error" class="error" style="display: none;"></div>
    </div>

    <script>
        var allTenders = [];
        
        function toggleDebug() {
            var el = document.getElementById('debugInfo');
            el.style.display = el.style.display === 'none' ? 'block' : 'none';
        }
        
        function renderTable(tenders) {
            if (!tenders || !tenders.length) {
                return '<div class="no-results">Sonuç bulunamadı.</div>';
            }

            var html = '<table><thead><tr>' +
                '<th>İKN</th><th>İhale Adı</th><th>Tür</th><th>Durum</th>' +
                '<th>İdare</th><th>İl</th><th>Tarih</th><th>Doküman</th>' +
                '</tr></thead><tbody>';

            for (var i = 0; i < tenders.length; i++) {
                var t = tenders[i];
                var link = t.document_url ? '<a href="' + t.document_url + '" target="_blank">Görüntüle</a>' : '';
                html += '<tr>' +
                    '<td>' + (t.ikn || '') + '</td>' +
                    '<td>' + (t.name || '') + '</td>' +
                    '<td>' + (t.type || '') + '</td>' +
                    '<td>' + (t.status || '') + '</td>' +
                    '<td>' + (t.authority || '') + '</td>' +
                    '<td>' + (t.province || '') + '</td>' +
                    '<td>' + (t.tender_datetime || '') + '</td>' +
                    '<td>' + link + '</td>' +
                    '</tr>';
            }

            html += '</tbody></table>';
            return html;
        }
        
        function turkishLowerCase(str) {
            if (!str) return '';
            return str.toString()
                .replace(/İ/g, 'i')
                .replace(/I/g, 'ı')
                .toLowerCase();
        }

        function uniqueValues(key) {
            var seen = {};
            var result = [];
            for (var i = 0; i < allTenders.length; i++) {
                var val = (allTenders[i][key] || '').toString().trim();
                if (val && !seen[val]) {
                    seen[val] = true;
                    result.push(val);
                }
            }
            return result.sort();
        }

        function populateSelect(id, values, placeholder) {
            var el = document.getElementById(id);
            if (!el) return;
            el.innerHTML = '<option value="">' + placeholder + '</option>';
            for (var i = 0; i < values.length; i++) {
                el.innerHTML += '<option value="' + values[i] + '">' + values[i] + '</option>';
            }
        }

        function prepareFilters() {
            var filterContainer = document.getElementById('filterContainer');
            var countEl = document.getElementById('resultsCount');
            
            if (allTenders.length > 0) {
                filterContainer.style.display = 'block';
                countEl.textContent = 'Toplam ' + allTenders.length + ' sonuç';
                populateSelect('filterType', uniqueValues('type'), 'Tür (hepsi)');
                populateSelect('filterProvince', uniqueValues('province'), 'İl (hepsi)');
            } else {
                filterContainer.style.display = 'none';
                countEl.textContent = '';
            }
        }

        function applyFilters() {
            var tableEl = document.getElementById('tendersTable');
            var countEl = document.getElementById('resultsCount');

            if (allTenders.length === 0) {
                tableEl.innerHTML = '<div class="no-results">Sonuç bulunamadı.</div>';
                return;
            }

            var text = turkishLowerCase(document.getElementById('filterInput').value || '');
            var type = document.getElementById('filterType').value || '';
            var province = document.getElementById('filterProvince').value || '';
            var dateStart = document.getElementById('filterDateStart').value || '';
            var dateEnd = document.getElementById('filterDateEnd').value || '';
            var docFilter = document.getElementById('filterDocument').value || '';

            var filtered = [];
            for (var i = 0; i < allTenders.length; i++) {
                var t = allTenders[i];
                if (type && t.type !== type) continue;
                if (province && t.province !== province) continue;
                
                // Tarih filtresi - DD.MM.YYYY formatını YYYY-MM-DD'ye çevir
                if (dateStart || dateEnd) {
                    var tenderDate = t.tender_datetime ? t.tender_datetime.split(' ')[0] : '';
                    var parts = tenderDate.split('.');
                    var isoDate = parts.length === 3 ? parts[2] + '-' + parts[1] + '-' + parts[0] : '';
                    if (dateStart && isoDate && isoDate < dateStart) continue;
                    if (dateEnd && isoDate && isoDate > dateEnd) continue;
                }
                
                // Doküman filtresi
                if (docFilter === 'yes' && !t.document_url) continue;
                if (docFilter === 'no' && t.document_url) continue;
                
                if (text) {
                    var haystack = turkishLowerCase([t.ikn, t.name, t.type, t.status, t.authority, t.province].join(' '));
                    if (haystack.indexOf(text) === -1) continue;
                }
                filtered.push(t);
            }

            tableEl.innerHTML = renderTable(filtered);
            countEl.textContent = filtered.length === allTenders.length
                ? 'Toplam ' + allTenders.length + ' sonuç'
                : filtered.length + ' / ' + allTenders.length + ' sonuç';
        }

        function runQuery() {
            var q = document.getElementById('query').value.trim();
            if (!q) {
                alert('Lütfen bir sorgu girin.');
                return;
            }
            
            var resultsDiv = document.getElementById('results');
            var tableEl = document.getElementById('tendersTable');
            var errorEl = document.getElementById('error');
            var debugEl = document.getElementById('debugInfo');
            var filterContainer = document.getElementById('filterContainer');
            
            errorEl.style.display = 'none';
            filterContainer.style.display = 'none';
            debugEl.textContent = '';
            allTenders = [];
            
            resultsDiv.style.display = 'block';
            tableEl.innerHTML = '<div class="loading">Aranıyor...</div>';

            fetch('/api/run', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query: q })
            })
            .then(function(resp) { return resp.json(); })
            .then(function(data) {
                if (data.error) {
                    errorEl.textContent = 'Hata: ' + data.error;
                    errorEl.style.display = 'block';
                    resultsDiv.style.display = 'none';
                    return;
                }

                if (data.mcp_arguments) {
                    debugEl.textContent = 'MCP Parametreleri:\\n' + JSON.stringify(data.mcp_arguments, null, 2);
                }

                var rawTenders = data.tenders || [];
                
                // search_text varsa, İhale Adı'nda filtrele (Türkçe karakterler dahil)
                var searchText = (data.mcp_arguments && data.mcp_arguments.search_text) ? turkishLowerCase(data.mcp_arguments.search_text) : '';
                if (searchText) {
                    allTenders = [];
                    for (var i = 0; i < rawTenders.length; i++) {
                        var tenderName = turkishLowerCase(rawTenders[i].name || '');
                        if (tenderName.indexOf(searchText) !== -1) {
                            allTenders.push(rawTenders[i]);
                        }
                    }
                } else {
                    allTenders = rawTenders;
                }
                
                if (allTenders.length > 0) {
                    prepareFilters();
                    applyFilters();
                } else {
                    tableEl.innerHTML = '<div class="no-results">Sonuç bulunamadı. (API ' + rawTenders.length + ' sonuç döndürdü, search_text filtresi uygulandı)</div>';
                }
            })
            .catch(function(err) {
                errorEl.textContent = 'Bağlantı hatası: ' + err.message;
                errorEl.style.display = 'block';
                resultsDiv.style.display = 'none';
            });
        }
        
        // Event listeners
        document.getElementById('searchBtn').addEventListener('click', runQuery);
        document.getElementById('debugToggle').addEventListener('click', toggleDebug);
        document.getElementById('filterInput').addEventListener('input', applyFilters);
        document.getElementById('filterType').addEventListener('change', applyFilters);
        document.getElementById('filterProvince').addEventListener('change', applyFilters);
        document.getElementById('filterDateStart').addEventListener('change', applyFilters);
        document.getElementById('filterDateEnd').addEventListener('change', applyFilters);
        document.getElementById('filterDocument').addEventListener('change', applyFilters);
        
        // Enter key
        document.getElementById('query').addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                runQuery();
            }
        });
    </script>
</body>
</html>'''


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(content=HTML_TEMPLATE)


@app.post("/api/run")
async def api_run(request: Request):
    body = await request.json()
    query = body.get("query", "").strip()

    if not query:
        return JSONResponse({"error": "query boş"}, status_code=400)

    try:
        mcp_args = build_mcp_arguments_with_gpt(query)
        mcp_result = call_mcp_tool(MCP_TOOL_NAME, mcp_args)

        tenders: List[Dict[str, Any]] = []
        if isinstance(mcp_result, dict):
            sc = mcp_result.get("structuredContent")
            if isinstance(sc, dict) and isinstance(sc.get("tenders"), list):
                for item in sc["tenders"]:
                    tenders.append(normalize_tender_item(item))

        return JSONResponse({
            "mcp_arguments": mcp_args,
            "tenders": tenders,
        })
    except Exception as e:
        import traceback
        return JSONResponse({"error": str(e), "traceback": traceback.format_exc()}, status_code=500)


if __name__ == "__main__":
    uvicorn.run("app_fixed:app", host="127.0.0.1", port=8000, reload=True)
