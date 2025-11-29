import os
import json
from datetime import date, timedelta
from typing import Any, Dict, List

import uvicorn
import requests  # pip install requests
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


# --- Yardımcı fonksiyonlar ---

def fix_mojibake(text: str) -> str:
    """
    MCP'den gelen 'Ä°' vs. gibi bozulmuş Türkçe karakterleri
    olabildiğince düzeltmeye çalışır.
    """
    if not isinstance(text, str):
        return text
    try:
        return text.encode("latin1").decode("utf-8")
    except Exception:
        return text


def normalize_tender_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    structuredContent.tenders içindeki bir kaydı
    daha okunabilir, sade bir dict'e çevir.
    """
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


# 1) Doğal dili al -> GPT ile MCP argüman JSON'una çevir
def build_mcp_arguments_with_gpt(user_query: str) -> dict:
    system_prompt = """
Sen bir çevirmen gibi davranan sistemsin.
Görevin: Kullanıcının Türkçe doğal dilde yazdığı ihale arama isteğini,
MCP 'search_tenders' tool'u için kullanılacak **arguments** JSON'una çevirmek.

SADECE GEÇERLİ BİR JSON OBJESİ DÖN.
Kesinlikle açıklama, yazı, markdown, backtick, yorum ekleme.

Tool açıklaması:
- Search Turkish government tenders from EKAP v2 portal.
- Tender types: 1=Mal, 2=Yapım, 3=Hizmet, 4=Danışık
- Provinces: plate numbers (6=Ankara, 34=İstanbul, 35=İzmir)
- IKN format: YEAR/NUMBER, dates: YYYY-MM-DD

KULLANACAĞIN ŞEMA:

{
  "search_text": "string",                // ihale başlığı / açıklama / şartname içinde aranacak serbest metin
  "ikn_year": 2025 veya null,             // IKN yılı, yoksa null
  "ikn_number": 123456 veya null,         // IKN numarası, yoksa null
  "tender_types": [1, 3],                 // 1=Mal, 2=Yapım, 3=Hizmet, 4=Danışık; belirsizse boş liste []
  "tender_date_start": "YYYY-MM-DD" veya null,
  "tender_date_end": "YYYY-MM-DD" veya null,
  "announcement_date_start": "YYYY-MM-DD" veya null,
  "announcement_date_end": "YYYY-MM-DD" veya null,
  "announcement_date_filter": "today" | "date_range" | null,
  "tender_date_filter": "from_today" | "date_range" | null
}

Kurallar:
- Kullanıcı tarih aralığı verirse:
  - Eğer ihale tarihi ile ilgiliyse -> tender_date_start / tender_date_end doldur, tender_date_filter = "date_range"
  - Eğer ilan tarihi ile ilgiliyse -> announcement_date_start / announcement_date_end doldur, announcement_date_filter = "date_range"
- Kullanıcı "bugün yayınlanan ihaleler" gibi derse -> announcement_date_filter = "today"
- Kullanıcı "bugünden itibaren" derse -> tender_date_filter = "from_today"
- Kullanıcı tarih bilgisi vermezse tarih alanları ve filter alanları null olsun.
- Kullanıcı ihale türü belirtirse (mal, hizmet, yapım, danışmanlık):
  - "mal" -> 1
  - "yapım" -> 2
  - "hizmet" -> 3
  - "danışmanlık" / "danışık" -> 4
- Kullanıcı IKN verirse (örn: 2025/123456):
  - ikn_year = 2025
  - ikn_number = 123456
- Kullanıcı IKN vermezse ikn_year ve ikn_number null olsun.
- search_text her zaman dolu olsun; kullanıcı sorgusunu buraya koy.
- Eğer tender_types belirsizse boş liste kullan ([]).

JSON dışında hiçbir şey yazma. Sadece tek bir JSON object döndür.
"""

    resp = client.responses.create(
        model="gpt-5.1",
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_query},
        ],
    )

    raw_json_str = resp.output[0].content[0].text

    if not raw_json_str or not raw_json_str.strip():
        raise ValueError(f"OpenAI boş veya geçersiz JSON döndürdü. raw={repr(raw_json_str)}")

    try:
        arguments = json.loads(raw_json_str)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"OpenAI JSON parse hatası: {e}. "
            f"Model çıktısı (ilk 300 char): {raw_json_str[:300]!r}"
        )

    if not isinstance(arguments, dict):
        raise ValueError(
            f"Beklenen dict, gelen: {type(arguments)} | raw={raw_json_str[:300]!r}"
        )

    allowed_keys = {
        "search_text",
        "ikn_year",
        "ikn_number",
        "tender_types",
        "tender_date_start",
        "tender_date_end",
        "announcement_date_start",
        "announcement_date_end",
        "announcement_date_filter",
        "tender_date_filter",
    }
    cleaned: Dict[str, Any] = {k: v for k, v in arguments.items() if k in allowed_keys}

    # --- DEFAULT / NORMALİZASYON ---

    # search_text: boş ise "" olsun
    if not cleaned.get("search_text"):
        cleaned["search_text"] = user_query  # fallback: tüm sorguyu koy
    # ikn_year / ikn_number: yoksa null bırak (schema anyOf int/null)
    cleaned.setdefault("ikn_year", None)
    cleaned.setdefault("ikn_number", None)

    # tender_types: array olmalı, null olamaz; boşsa []
    tt = cleaned.get("tender_types")
    if tt is None:
        cleaned["tender_types"] = []
    else:
        if isinstance(tt, (int, str)):
            tt_list = [tt]
        else:
            tt_list = list(tt)
        fixed_list: List[int] = []
        for item in tt_list:
            if isinstance(item, int):
                fixed_list.append(item)
            else:
                try:
                    fixed_list.append(int(item))
                except Exception:
                    continue
        cleaned["tender_types"] = fixed_list

    # tarih alanları: yoksa null (schema anyOf string/null)
    for key in [
        "tender_date_start",
        "tender_date_end",
        "announcement_date_start",
        "announcement_date_end",
    ]:
        cleaned.setdefault(key, None)

    # --- EK: Python tarafında 'son 1 ay' heuristiği ---

    qlower = user_query.lower()

    # bugünün tarihi
    today = date.today()
    one_month_ago = today - timedelta(days=30)

    # "son 1 ay" / "son bir ay" / "last month"
    if any(phrase in qlower for phrase in ["son 1 ay", "son bir ay", "last month"]):
        # Default: ilan tarihi üzerinden filtreleyelim
        cleaned["announcement_date_start"] = one_month_ago.isoformat()
        cleaned["announcement_date_end"] = today.isoformat()
        cleaned["announcement_date_filter"] = "date_range"

    # Eğer tarih aralığı dolu ama filter alanı boşsa -> date_range
    if (cleaned.get("announcement_date_start") or cleaned.get("announcement_date_end")) and not cleaned.get("announcement_date_filter"):
        cleaned["announcement_date_filter"] = "date_range"

    if (cleaned.get("tender_date_start") or cleaned.get("tender_date_end")) and not cleaned.get("tender_date_filter"):
        cleaned["tender_date_filter"] = "date_range"

    # filter alanları: NULL ise field'ı HİÇ GÖNDERME
    for filter_key in ["announcement_date_filter", "tender_date_filter"]:
        value = cleaned.get(filter_key, None)
        if value is None:
            cleaned.pop(filter_key, None)
        else:
            if filter_key == "announcement_date_filter":
                if value not in ("today", "date_range"):
                    cleaned.pop(filter_key, None)
            elif filter_key == "tender_date_filter":
                if value not in ("from_today", "date_range"):
                    cleaned.pop(filter_key, None)

    return cleaned


# 2) MCP'ye HTTP POST ile tool çağrısı
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
                raise ValueError(
                    f"SSE formatı ama data satırı yok. raw={text_body[:500]!r}"
                )

            combined = "\n".join(json_chunks)
            data = json.loads(combined)
        else:
            data = resp.json()
    except json.JSONDecodeError as e:
        raise ValueError(
            f"MCP JSON parse hatası: {e}. "
            f"Content-Type={content_type}, body(ilk 500 char)={text_body[:500]!r}"
        )

    if "error" in data:
        raise RuntimeError(f"MCP error: {data['error']}")

    return data.get("result", data)


# 3) HTML UI
@app.get("/", response_class=HTMLResponse)
async def index():
    html = """
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8" />
        <title>OpenAI + MCP Arama UI</title>
        <style>
            body { font-family: system-ui, -apple-system, BlinkMacSystemFont, sans-serif; margin: 40px; }
            .container { max-width: 1100px; margin: 0 auto; }
            textarea, button { width: 100%; padding: 8px; margin-top: 8px; box-sizing: border-box; }
            button { cursor: pointer; }
            pre { background: #f5f5f5; padding: 12px; border-radius: 8px; white-space: pre-wrap; }
            .row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 24px; }
            h1 { margin-bottom: 8px; }
            small { font-size: 0.6em; opacity: 0.7; }
            table { border-collapse: collapse; width: 100%; font-size: 13px; }
            th, td { border: 1px solid #ddd; padding: 6px 8px; text-align: left; }
            th { background: #f0f0f0; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>OpenAI GPT-5.1 → MCP <small>ihale arama</small></h1>
            <p>Doğal dilde isteğini yaz. Örn: <em>\"Son 1 ay içindeki Ankara'daki yazılım ihalelerini bul\"</em></p>

            <label>Doğal dil sorgu:</label>
            <textarea id="query" rows="3"></textarea>
            <button onclick="runQuery()">Çalıştır</button>

            <h2>Sonuçlar</h2>
            <div id="tendersTable"></div>

            <div class="row">
                <div>
                    <h3>GPT → MCP arguments</h3>
                    <pre id="argsResult"></pre>
                </div>
                <div>
                    <h3>Ham MCP JSON</h3>
                    <pre id="mcpResult"></pre>
                </div>
            </div>
        </div>

        <script>
            function renderTable(tenders) {
                if (!tenders || !tenders.length) {
                    return "<p>Sonuç bulunamadı.</p>";
                }

                let html = "<table><thead><tr>" +
                    "<th>İKN</th>" +
                    "<th>Adı</th>" +
                    "<th>Tür</th>" +
                    "<th>Durum</th>" +
                    "<th>İdare</th>" +
                    "<th>Tarih/Saat</th>" +
                    "<th>Doküman</th>" +
                    "</tr></thead><tbody>";

                for (const t of tenders) {
                    const link = t.document_url
                        ? `<a href="${t.document_url}" target="_blank">Link</a>`
                        : "";
                    html += "<tr>" +
                        `<td>${t.ikn || ""}</td>` +
                        `<td>${t.name || ""}</td>` +
                        `<td>${t.type || ""}</td>` +
                        `<td>${t.status || ""}</td>` +
                        `<td>${t.authority || ""}</td>` +
                        `<td>${t.tender_datetime || ""}</td>` +
                        `<td>${link}</td>` +
                        "</tr>";
                }

                html += "</tbody></table>";
                return html;
            }

            async function runQuery() {
                const q = document.getElementById('query').value;
                const argsEl = document.getElementById('argsResult');
                const mcpEl = document.getElementById('mcpResult');
                const tableEl = document.getElementById('tendersTable');

                argsEl.textContent = 'Çalışıyor...';
                mcpEl.textContent = '';
                tableEl.innerHTML = '';

                try {
                    const resp = await fetch('/api/run', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ query: q })
                    });
                    const data = await resp.json();
                    if (data.error) {
                        argsEl.textContent = 'Hata: ' + data.error;
                        return;
                    }

                    argsEl.textContent = JSON.stringify(data.mcp_arguments, null, 2);
                    mcpEl.textContent = JSON.stringify(data.raw_mcp_result, null, 2);

                    if (data.tenders) {
                        tableEl.innerHTML = renderTable(data.tenders);
                    } else {
                        tableEl.innerHTML = "<p>Structured sonuç gelmedi.</p>";
                    }
                } catch (err) {
                    argsEl.textContent = 'Request error: ' + err;
                }
            }
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


# 4) API endpoint
@app.post("/api/run")
async def api_run(request: Request):
    body = await request.json()
    query = body.get("query", "").strip()

    if not query:
        return JSONResponse({"error": "query boş"}, status_code=400)

    try:
        mcp_args = build_mcp_arguments_with_gpt(query)
        mcp_result = call_mcp_tool(MCP_TOOL_NAME, mcp_args)

        # structuredContent.tenders varsa, onu sadeleştir
        tenders: List[Dict[str, Any]] = []
        if isinstance(mcp_result, dict):
            sc = mcp_result.get("structuredContent")
            if isinstance(sc, dict) and isinstance(sc.get("tenders"), list):
                for item in sc["tenders"]:
                    tenders.append(normalize_tender_item(item))

        return JSONResponse(
            {
                "mcp_arguments": mcp_args,
                "raw_mcp_result": mcp_result,
                "tenders": tenders,
            }
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


if __name__ == "__main__":
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
