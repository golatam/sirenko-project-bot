"""Настройка OAuth-авторизации через Claude CLI.

Использование:
    python3.12 -m src.auth_setup

Flow:
1. Проверяет наличие claude CLI и статус авторизации
2. Если не авторизован — предлагает запустить claude auth login
3. Извлекает OAuth токен из macOS Keychain
4. Сохраняет в .env как ANTHROPIC_AUTH_TOKEN
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ENV_PATH = Path(__file__).parent.parent / ".env"
KEYCHAIN_SERVICE = "Claude Code-credentials"


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def check_claude_cli() -> bool:
    """Проверить наличие claude CLI."""
    result = _run(["which", "claude"])
    if result.returncode != 0:
        print("✗ Claude CLI не найден. Установите: npm install -g @anthropic-ai/claude-code")
        return False
    print(f"✓ Claude CLI: {result.stdout.strip()}")
    return True


def check_auth_status() -> dict | None:
    """Проверить статус авторизации Claude CLI."""
    result = _run(["claude", "auth", "status"])
    if result.returncode != 0:
        print("✗ Не удалось проверить статус авторизации")
        return None

    try:
        status = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"✗ Неожиданный ответ: {result.stdout}")
        return None

    if not status.get("loggedIn"):
        print("✗ Не авторизован в Claude")
        return None

    print(f"✓ Авторизован: {status.get('email')} ({status.get('subscriptionType', 'unknown')})")
    return status


def extract_token() -> dict | None:
    """Извлечь OAuth токен из macOS Keychain."""
    result = _run([
        "security", "find-generic-password",
        "-s", KEYCHAIN_SERVICE, "-w",
    ])
    if result.returncode != 0:
        print("✗ Токен не найден в Keychain")
        print("  Убедитесь что вы авторизованы: claude auth login")
        return None

    try:
        creds = json.loads(result.stdout.strip())
        oauth = creds.get("claudeAiOauth", {})
    except (json.JSONDecodeError, AttributeError):
        print("✗ Не удалось разобрать credentials из Keychain")
        return None

    access_token = oauth.get("accessToken", "")
    if not access_token:
        print("✗ accessToken пуст в credentials")
        return None

    expires_at = oauth.get("expiresAt")
    if expires_at:
        from datetime import datetime, timezone
        exp = datetime.fromtimestamp(expires_at / 1000, tz=timezone.utc)
        print(f"✓ Токен получен (истекает: {exp.strftime('%Y-%m-%d %H:%M UTC')})")
    else:
        print("✓ Токен получен")

    return {
        "access_token": access_token,
        "refresh_token": oauth.get("refreshToken", ""),
        "expires_at": expires_at,
    }


def save_to_env(token: str) -> None:
    """Сохранить токен в .env файл."""
    lines: list[str] = []
    token_saved = False

    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            if line.startswith("ANTHROPIC_AUTH_TOKEN="):
                lines.append(f"ANTHROPIC_AUTH_TOKEN={token}")
                token_saved = True
            else:
                lines.append(line)

    if not token_saved:
        lines.append(f"ANTHROPIC_AUTH_TOKEN={token}")

    ENV_PATH.write_text("\n".join(lines) + "\n")
    print(f"✓ Токен сохранён в {ENV_PATH}")


def main() -> None:
    print("=== Настройка OAuth авторизации Claude ===\n")

    if not check_claude_cli():
        sys.exit(1)

    status = check_auth_status()
    if not status:
        print("\nЗапустите авторизацию:")
        print("  claude auth login")
        print("\nПосле авторизации запустите эту команду снова.")
        sys.exit(1)

    token_data = extract_token()
    if not token_data:
        sys.exit(1)

    save_to_env(token_data["access_token"])

    print(f"\n=== Готово ===")
    print(f"Убедитесь что в config/projects.yaml установлено:")
    print(f"  auth_method: oauth")
    print(f"\nДля обновления токена запустите эту команду снова.")


if __name__ == "__main__":
    main()
