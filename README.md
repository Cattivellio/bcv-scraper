# BCV Scraper

Webapp minimalista que hace **scraping de la página oficial del Banco Central de Venezuela** (`https://www.bcv.org.ve/`), persiste las 5 monedas de referencia en una base de datos **SQLite**, y las expone vía una **API JSON** y un **dashboard web**.

Corre automáticamente **6 veces al día** (00, 04, 08, 12, 16, 20 h, hora de Caracas) — y además hace un scrape **inmediato al arrancar** el servicio, sin esperar al próximo slot. Solo guarda una nueva fila cuando hay un cambio real en la tasa.

## Tasas seguidas

- 🇺🇸 **USD** — Dólar estadounidense
- 🇪🇺 **EUR** — Euro
- 🇨🇳 **CNY** — Yuan chino
- 🇹🇷 **TRY** — Lira turca
- 🇷🇺 **RUB** — Rublo ruso

Estas son las monedas publicadas en el bloque "Tipo de Cambio de Referencia" de la home del BCV (Tipo de Cambio Promedio Ponderado, art. 9 del Convenio Cambiario N° 1).

## Stack

- **Backend:** FastAPI + Uvicorn
- **Scheduler:** APScheduler (AsyncIOScheduler) integrado en el `lifespan` de FastAPI
- **Scraping:** `httpx` + `beautifulsoup4`
- **DB:** SQLite (stdlib `sqlite3`, con WAL)
- **Modelos:** Pydantic v2
- **Frontend:** Jinja2 + HTML/CSS/JS vanilla — design system shadcn-inspired (mismo que el proyecto hermano `youtube-downloader`)

## Requisitos

- **Python 3.10+**
- `pip` y `venv`

```bash
sudo apt install python3 python3-venv
```

## Quick start

```bash
cd ~/Documents/bcv-scraper
chmod +x run.sh
./run.sh
```

El primer arranque crea `.venv` e instala las dependencias. Al iniciar, el servidor dispara **un scrape inmediato** del BCV (verás `startup scrape scheduled to run immediately` en los logs) y luego continúa con el cron de 6 veces al día. Abre <http://127.0.0.1:8000> en el navegador.

## Arranque manual

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## Configuración (`.env`)

Copia `.env.example` a `.env` y ajusta lo que necesites:

| Variable | Default | Descripción |
|---|---|---|
| `SCRAPE_API_KEY` | *(vacío)* | Si está vacío, `POST /api/scrape` queda deshabilitado. Si tiene valor, el endpoint exige el header `X-API-Key`. |
| `BCV_URL` | `https://www.bcv.org.ve/` | Página a scrapear. |
| `TZ` | `America/Caracas` | Timezone del scheduler. |
| `SCRAPE_HOURS` | `16,17,18` | Horas (0-23) en que corre el scraper. |
| `SCRAPE_MINUTES` | `0,30` | Minutos (0-59) dentro de cada hora. Combinado con SCRAPE_HOURS, por defecto corre cada 30 min de 16:00 a 18:30. |
| `BCV_HTTP_TIMEOUT` | `15` | Timeout de la request HTTP. |
| `BCV_HOST` / `BCV_PORT` | `127.0.0.1` / `8000` | Bind del servidor. |

## Endpoints

### UI

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/` | Dashboard con las 5 tasas actuales, deltas y mini-sparklines. |
| `GET` | `/history?currency=USD` | Historial tabular con los cambios reales. |

### API

| Método | Ruta | Descripción |
|---|---|---|
| `GET`  | `/api/rates/latest` | Tasas actuales de las 5 monedas. |
| `GET`  | `/api/rates/latest/{currency}` | Última tasa de una moneda. |
| `GET`  | `/api/rates/history?currency=USD&limit=200` | Historial de una moneda. |
| `GET`  | `/api/rates/changes?limit=500` | Solo filas donde hubo cambio. |
| `POST` | `/api/scrape` | Disparo manual. Header `X-API-Key: …` (sólo si `SCRAPE_API_KEY` está configurada). |
| `GET`  | `/api/scheduler/status` | Estado del scheduler (último y próximo run). |
| `GET`  | `/api/health` | Liveness + DB. |

### Ejemplos

```bash
# Última tasa de cada moneda
curl http://127.0.0.1:8000/api/rates/latest | jq

# Historial del USD
curl 'http://127.0.0.1:8000/api/rates/history?currency=USD&limit=20' | jq

# Disparo manual (si configuraste SCRAPE_API_KEY)
curl -X POST -H 'X-API-Key: tu-clave' http://127.0.0.1:8000/api/scrape | jq
```

## Formato de respuesta

```jsonc
GET /api/rates/latest
{
  "rates": [
    {
      "currency": "USD",
      "label": "Dólar estadounidense",
      "flag": "$",
      "value": 596.7824,
      "source_date": "2026-06-17",
      "scraped_at": "2026-06-17T08:00:12-04:00",
      "previous_value": 595.10,
      "delta": 1.6824,
      "delta_pct": 0.2827,
      "history": [593.21, 594.10, 595.10, 596.7824]
    }
  ],
  "scraped_at": "2026-06-17T08:00:12-04:00",
  "source_date": "2026-06-17"
}
```

## Base de datos

Un único archivo SQLite en `data/bcv.db` con la tabla:

```sql
CREATE TABLE rates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    currency    TEXT    NOT NULL,   -- USD, EUR, CNY, TRY, RUB
    value       REAL    NOT NULL,   -- Bs por unidad
    source_date TEXT    NOT NULL,   -- Fecha Valor del BCV (YYYY-MM-DD)
    scraped_at  TEXT    NOT NULL,   -- ISO timestamp local del scrap
    UNIQUE(currency, source_date, value)
);
```

**Regla de "solo si hubo cambio"**: antes de insertar, se compara `value` y `source_date` con la última fila de la misma moneda. Si son idénticos → se omite.

Para inspeccionar la base manualmente:

```bash
sqlite3 data/bcv.db
> SELECT currency, source_date, value, scraped_at FROM rates ORDER BY scraped_at DESC LIMIT 10;
```

## Estructura del proyecto

```
bcv-scraper/
├── app/
│   ├── main.py            # Rutas FastAPI + lifespan
│   ├── scraper.py         # Fetch + parse BCV
│   ├── scheduler.py       # APScheduler 6x/día
│   ├── database.py        # Capa SQLite
│   ├── models.py          # Pydantic
│   └── config.py          # Settings
├── static/
│   ├── css/styles.css     # shadcn design system
│   └── js/app.js
├── templates/
│   ├── base.html
│   ├── index.html
│   └── history.html
├── data/                  # bcv.db
├── requirements.txt
├── run.sh
├── .env.example
└── README.md
```

## Solución de problemas

- **El scrap devuelve 0 inserciones siempre** — probablemente BCV bloqueó la IP / User-Agent. Revisa los logs (`uvicorn` muestra los `WARNING` de parseo) y, si quieres, rota `BCV_USER_AGENT` en `.env`.
- **HTML cambia y los selectores rompen** — los selectores (`div#dolar`, `div#euro`, `div#yuan`, `div#lira`, `div#rublo`, `strong.strong-tb`, `span.date-display-single[content]`) están en `app/scraper.py`. Si BCV reorganiza la home, ajusta `_BCV_DIV_ID_TO_CURRENCY` o el parser.
- **Zona horaria del scheduler** — APScheduler usa `TZ=America/Caracas` por default; cámbialo en `.env` si lo desplazas a otro host.

## Notas

- Todos los datos provienen de la página oficial; este proyecto no representa ni suplanta al BCV.
- El scraping es pasivo: una sola request HTTP por tick, sinログイン, sin cookies persistentes.
- Si expones el servidor públicamente, configura `SCRAPE_API_KEY` y pon un reverse-proxy con HTTPS.
