# API Key Management — микросервис

Управление API-ключами с хранением в PostgreSQL, rate limiting через Redis (sliding window), развёртывание через Docker Compose.

## Стек

- **FastAPI** (асинхронные эндпоинты)
- **PostgreSQL 15** (хранение ключей)
- **Redis 7** (sliding window rate limiter)
- **SQLAlchemy** (asyncpg) + Alembic (миграции)
- **Docker Compose** (оркестрация)

## Эндпоинты

### `POST /keys` — создать ключ

Генерирует случайный API-ключ и сохраняет его SHA-256 хеш в БД.

**Ответ `201`**:
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "key": "ak_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
}
```

**Пример**:
```bash
curl -s -X POST http://localhost:8000/keys | jq .
```

---

### `GET /keys` — список активных ключей

Возвращает все активные ключи (хеш не раскрывается).

**Ответ `200`**:
```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "created_at": "2026-05-11T12:00:00Z"
  }
]
```

**Пример**:
```bash
curl -s http://localhost:8000/keys | jq .
```

---

### `DELETE /keys/{id}` — деактивировать ключ

Помечает ключ как неактивный (soft delete, `is_active = false`).

**Ответ `204`** — без тела.

**Пример**:
```bash
curl -s -X DELETE http://localhost:8000/keys/550e8400-e29b-41d4-a716-446655440000
```

**Ошибка `404`**, если ключ с таким ID не найден.

---

### `POST /verify` — проверить ключ

Принимает ключ в теле, хеширует его SHA-256 и ищет в БД. Дополнительно применяется rate limiting (10 запросов в минуту с одного IP, sliding window).

**Запрос**:
```json
{
  "key": "ak_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
}
```

**Ответ `200`** — ключ валиден и активен:
```json
{
  "valid": true
}
```

**Ответ `403`** — ключ не найден, неактивен или превышен rate limit:
```json
{
  "detail": "Invalid or inactive key"
}
```

**Rate limit заголовки** (всегда присутствуют в ответе):
```
X-RateLimit-Limit: 10
X-RateLimit-Remaining: 7
X-RateLimit-Reset: 1715400000
```

**Пример**:
```bash
curl -s -X POST http://localhost:8000/verify \
  -H "Content-Type: application/json" \
  -d '{"key": "ak_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"}' | jq .
```

---

## Хранение ключей

| Поле         | Тип      | Описание                            |
|--------------|----------|-------------------------------------|
| `id`         | UUID     | Первичный ключ                      |
| `key_hash`   | TEXT     | SHA-256 хеш ключа (hex)             |
| `created_at` | TIMESTAMP| Дата создания                       |
| `is_active`  | BOOLEAN  | Активен ли ключ (default true)      |

Сам ключ (`ak_...`) возвращается клиенту **только один раз** при создании. В БД хранится исключительно хеш, поэтому утечка базы данных не скомпрометирует ключи.

## Rate limiting (sliding window)

Алгоритм на Redis sorted set:

1. Каждый запрос добавляет `ZADD window:<ip> <timestamp> <unique_id>`.
2. Перед проверкой очищает устаревшие записи: `ZREMRANGEBYSCORE window:<ip> 0 <now - window_size>`.
3. Считает количество запросов в окне: `ZCARD window:<ip>`.
4. Если `count >= limit` — запрос отклоняется (403).
5. TTL на ключ окна — `EXPIRE window:<ip> <window_size>` для автоочистки.

По умолчанию: **10 запросов в минуту** на IP. Настраивается через переменные окружения `RATE_LIMIT_REQUESTS` и `RATE_LIMIT_WINDOW_SECONDS`.

## Переменные окружения

| Переменная                 | По умолчанию          | Описание                        |
|----------------------------|-----------------------|---------------------------------|
| `DATABASE_URL`             | `postgresql+asyncpg://postgres:postgres@localhost:5432/keys` | Строка подключения к БД |
| `REDIS_URL`                | `redis://localhost:6379/0` | Строка подключения к Redis |
| `RATE_LIMIT_REQUESTS`      | `10`                  | Макс. запросов в окне           |
| `RATE_LIMIT_WINDOW_SECONDS`| `60`                  | Размер окна в секундах          |

## Запуск

```bash
# Docker Compose (все сервисы)
docker compose up --build

# Или локально (нужны свои postgres + redis)
python -m uvicorn app.main:app --reload
```

Сервис будет доступен на `http://localhost:8000`. OpenAPI-документация — `http://localhost:8000/docs`.
