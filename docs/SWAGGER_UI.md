# Swagger UI – API docs for UI / frontend developers

Use these URLs in the browser to explore and test the API.

---

## URLs

| Purpose | URL |
|--------|-----|
| **Swagger UI (interactive docs)** | **`/docs`** |
| **OpenAPI schema (JSON)** | **`/openapi.json`** |

---

## How to open (by environment)

- **Local (same machine):**
  - Swagger: [http://localhost:8000/docs](http://localhost:8000/docs)
  - Schema: [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)

- **Local (other device on network):**  
  Replace `localhost` with your machine’s IP, e.g. `http://192.168.1.10:8000/docs`

- **Staging / production:**  
  Use your deployed base URL, e.g. `https://api.yourdomain.com/docs`

---

## Using Swagger UI

1. Open **`/docs`** in the browser (e.g. `http://localhost:8000/docs`).
2. You’ll see all endpoints: **Auth**, **Profile**, **Censor**.
3. Click an endpoint → **Try it out** → fill body/params → **Execute**.
4. For **Profile** endpoints, get a token from **POST /auth/login**, then click **Authorize** (top right), enter `Bearer <your_token>`, and call the endpoints.
5. For realtime chat/notification docs, open the **Realtime** tag and call **GET `/api/realtime/docs/`**. Swagger cannot open a WebSocket, but it lists the socket URLs, auth options, and JSON event shapes.

---

## Quick reference for UI devs

| What | Value |
|------|--------|
| Base URL (Ninja API) | Same as where you opened `/docs` (e.g. `http://localhost:8000`) |
| Auth | Bearer token from `POST /auth/login` or `POST /auth/register` |
| Auth header | `Authorization: Bearer <token>` |
| Censor (no auth) | `POST /censor/text` (JSON body), `POST /censor/image` (multipart file) |
| Realtime docs | `GET /api/realtime/docs/` in Swagger |
| Chat WebSocket | `ws://host/ws/chat/{request_id}/?format=json` |
| Notification WebSocket | `ws://host/ws/notifications/?token=<token>` |
| OpenAPI spec | Fetch `/openapi.json` for codegen or API clients |

---

## CORS

If the frontend runs on a different origin (e.g. `http://localhost:3000`), the backend must allow CORS. If requests to `/docs` or the API fail from the browser, ask the backend to allow your origin or enable CORS for dev (e.g. `django-cors-headers`).
