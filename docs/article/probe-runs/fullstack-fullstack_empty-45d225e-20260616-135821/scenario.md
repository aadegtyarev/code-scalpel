# API Key Management Service

Собери микросервис управления API-ключами: FastAPI + PostgreSQL + Redis, Docker Compose.

## Компоненты
- **POST /keys** — выпустить ключ (scope, rate_limit), вернуть `{id, key, scope, rate_limit}`
- **GET /keys** — список активных ключей
- **DELETE /keys/{id}** — отозвать ключ
- **POST /verify** — валидация: `{key: "sk-..."}` → `{valid: bool, scope?, remaining?}`
- Rate limiting: sliding window на Redis (1 minute window)
- Миграция SQLAlchemy для таблицы keys

## Архитектурные требования
- Ключи хранятся как SHA-256 хеш (не plaintext)
- Верификация — быстрый путь (Redis first, PG fallback)
- Docker Compose: app на 8000, Redis 6379, PG 5432
- Корректные HTTP статусы: 201/200/204/401/429
