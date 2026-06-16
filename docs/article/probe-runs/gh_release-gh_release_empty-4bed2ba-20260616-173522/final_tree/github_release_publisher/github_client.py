"""GitHub REST API client для управления релизами."""

import os
from pathlib import Path
from typing import Optional

import requests


class GitHubClient:
    """Клиент для GitHub Releases API.

    Аутентификация — Bearer-токен из GITHUB_TOKEN.
    """

    BASE_URL = "https://api.github.com"

    def __init__(self, token: Optional[str] = None):
        self.token = token or os.environ.get("GITHUB_TOKEN")
        if not self.token:
            raise ValueError(
                "Токен не указан. Передайте token= или установите GITHUB_TOKEN"
            )
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    @staticmethod
    def _parse_repo(repo: str) -> tuple[str, str]:
        parts = repo.split("/")
        if len(parts) != 2 or not all(parts):
            raise ValueError(
                "Репозиторий должен быть в формате owner/repo"
            )
        return parts[0], parts[1]

    def create_release(
        self,
        repo: str,
        tag: str,
        name: str = "",
        body: str = "",
        dry_run: bool = False,
    ) -> Optional[dict]:
        """Создаёт GitHub Release.

        При dry_run возвращает словарь с данными, но не вызывает API.
        """
        owner, repo_name = self._parse_repo(repo)
        payload = {
            "tag_name": tag,
            "name": name or tag,
            "body": body,
        }

        if dry_run:
            return {"tag_name": tag, "name": name or tag, "body": body, "dry_run": True}

        url = f"{self.BASE_URL}/repos/{owner}/{repo_name}/releases"
        resp = self._session.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()

    def upload_asset(self, release_data: dict, file_path: str | Path) -> dict:
        """Загружает бинарный файл как asset к релизу.

        release_data — ответ от create_release (содержит upload_url).
        file_path — путь к файлу на диске.
        """
        upload_url = release_data["upload_url"]
        filename = Path(file_path).name
        # upload_url содержит шаблон {?name,label} — заменяем на ?name=<filename>
        url = upload_url.replace("{?name,label}", f"?name={filename}")

        with open(file_path, "rb") as f:
            data = f.read()

        resp = self._session.post(
            url,
            data=data,
            headers={"Content-Type": "application/octet-stream"},
        )
        resp.raise_for_status()
        return resp.json()

    def list_releases(self, repo: str) -> list[dict]:
        """Возвращает список релизов репозитория."""
        owner, repo_name = self._parse_repo(repo)
        url = f"{self.BASE_URL}/repos/{owner}/{repo_name}/releases"
        resp = self._session.get(url)
        resp.raise_for_status()
        return resp.json()
