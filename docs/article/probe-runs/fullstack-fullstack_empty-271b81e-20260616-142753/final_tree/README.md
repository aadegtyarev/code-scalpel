# API Key Management Microservice

Микросервис для управления API-ключами на **FastAPI** + **PostgreSQL** + **Redis**.
Ключи хранятся в виде SHA-256 хешей. Rate limiting реализован через скользящее окно
(sliding window) в Redis.

---

## Архитектура

```
┌──────────────┐      HTTP      ┌──────────────────┐
│   Client     │ ──────────────►│  FastAPI (app)    │
│   (curl /    │ ◄──────────────│  :8000            │
│    httpx)    │                └────────┬─────────┘
└──────────────┘                         │
                         ┌───────────────┼─────────────┐
                         ▼               ▼             ▼
                  ┌──────────┐    ┌──────────┐  ┌──────────┐
                  │PostgreSQL│    │  Redis   │  │  Redis   │
                  │ :5432    │    │ :6379    │  │ (rate    │
                  │(ключи)   │    │(кэш/RL)  │  │  limiter)│
                  └──────────┘    └──────────┘  └──────────┘
```

- **PostgreSQL** — основное хранилище API-ключей. Ключи хранятся как SHA-256 хеши.
- **Redis** — два назначения:
  1. Rate limiter (алгоритм sliding window через sorted sets).
  2. Кэш для ускорения проверки ключей.

---

## Эндпоинты

### `POST /keys`
Создать новый API-ключ.

```bash
curl -X POST http://localhost:8000/keys -H "Content-Type: application/json" -d '{}'
```

**Ответ:** `201 Created`
```json
{
  "id": 1,
  "key": "ak_abc123...",
  "created_at": "2026-01-01T00:00:00Z"
}
```

**Примечание:** `key` возвращается в открытом виде **только один раз** — при создании.
В базе хранится его SHA-256 хеш.

---

### `GET /keys`
Получить список всех ключей (хеши).

```bash
curl http://localhost:8000/keys
```

**Ответ:** `200 OK`
```json
[
  {
    "id": 1,
    "key_hash": "a665a45920422f9d417e4867efdc4fb8a04a1f3fff1fa07e998e86f7f7a27ae3",
    "created_at": "2026-01-01T00:00:00Z",
    "is_active": true
  }
]
```

---

### `DELETE /keys/{id}`
Удалить ключ по ID.

```bash
curl -X DELETE http://localhost:8000/keys/1
```

- **`204 No Content`** — ключ удалён.
- **`404 Not Found`** — ключ с таким ID не существует.

---

### `POST /verify`
Проверить, существует ли ключ (по его SHA-256 хешу).

```bash
curl -X POST http://localhost:8000/verify \
  -H "Content-Type: application/json" \
  -d '{"key": "ak_abc123..."}'
```

**Ответ:** `200 OK`
```json
{
  "valid": true
}
```

Если ключ не найден:
```json
{
  "valid": false
}
```

---

## Хранение ключей

- При создании ключа микросервис генерирует случайный ключ (префикс `ak_`).
- Ключ хешируется алгоритмом **SHA-256** и сохраняется в PostgreSQL.
- Открытый ключ возвращается клиенту ровно один раз при `POST /keys`.
- При `POST /verify` сервер хеширует переданный ключ и ищет совпадение в БД.

---

## Rate Limiting (Sliding Window)

Для защиты эндпоинтов `POST /keys` и `POST /verify` используется алгоритм
**скользящего окна** (sliding window log) на Redis sorted sets.

- **Окно:** 60 секунд.
- **Лимит:** 10 запросов на окно (настраивается через переменную окружения).
- **Идентификатор:** IP-адрес клиента (`X-Forwarded-For` или `remote_addr`).

При превышении лимита сервер возвращает:

```
429 Too Many Requests
Retry-After: 42
```

```json
{
  "detail": "Rate limit exceeded. Try again in 42 seconds."
}
```

---

## Быстрый старт (Docker Compose)

### Требования

- [Docker](https://docs.docker.com/get-docker/)
- [Docker Compose](https://docs.docker.com/compose/install/)

### Запуск

```bash
docker compose up --build
```

Сервис будет доступен по адресу `http://localhost:8000`.

Документация OpenAPI: `http://localhost:8000/docs`.

### Остановка

```bash
docker compose down
```

Чтобы удалить также тома (БД и Redis):
```bash
docker compose down -v
```

---

## Переменные окружения

| Переменная | Значение по умолчанию | Описание |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg2://app:secret@postgres:5432/apikeys` | DSN PostgreSQL |
| `REDIS_URL` | `redis://redis:6379/0` | DSN Redis |
| `RATE_LIMIT_REQUESTS` | `10` | Максимум запросов в окно |
| `RATE_LIMIT_WINDOW` | `60` | Размер окна в секундах |

---

## Локальный запуск (без Docker)

```bash
pip install -e .
uvicorn app.main:app --reload
```

Требуется запущенный PostgreSQL и Redis; укажите их адреса через переменные окружения.

---

## Тестирование

```bash
pip install -e ".[test]"
pytest tests/
```
