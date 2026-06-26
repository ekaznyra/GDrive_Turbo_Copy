"""Authentication and Drive service-factory construction.

Google imports are done lazily inside the functions so that importing the
package (e.g. for unit tests) never requires ``google.colab`` or network access.

No secrets are stored in code: authentication relies on Colab's user auth,
Application Default Credentials, or a service-account file path supplied at
runtime via an environment variable.
"""

from __future__ import annotations

import os
from typing import Callable

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]


def _build(credentials=None):
    from googleapiclient.discovery import build

    if credentials is None:
        return build("drive", "v3", cache_discovery=False)
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def make_service_factory(
    *,
    prefer_colab: bool = True,
    scopes: list[str] | None = None,
    service_account_file: str | None = None,
) -> Callable[[], object]:
    """Return a thread-safe factory that builds a fresh Drive ``service``.

    Resolution order:

    1. Colab user auth (when ``prefer_colab`` and running in Colab).
    2. A service-account file (arg or ``GOOGLE_APPLICATION_CREDENTIALS`` /
       ``GDRIVE_SERVICE_ACCOUNT_FILE``).
    3. Application Default Credentials.
    """
    scopes = scopes or DRIVE_SCOPES

    if prefer_colab:
        try:
            from google.colab import auth as colab_auth  # type: ignore

            colab_auth.authenticate_user()

            def colab_factory() -> object:
                return _build()

            return colab_factory
        except Exception:
            pass

    sa_file = (
        service_account_file
        or os.environ.get("GDRIVE_SERVICE_ACCOUNT_FILE")
        or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    )
    if sa_file:
        from google.oauth2 import service_account  # type: ignore

        creds = service_account.Credentials.from_service_account_file(sa_file, scopes=scopes)

        def sa_factory() -> object:
            return _build(creds)

        return sa_factory

    import google.auth  # type: ignore

    creds, _ = google.auth.default(scopes=scopes)

    def adc_factory() -> object:
        return _build(creds)

    return adc_factory


def fetch_account_identifier(client) -> str | None:
    """Best-effort account identifier (email, else ``root-<id>``)."""
    try:
        about = client.about_user()
        email = (about.get("user") or {}).get("emailAddress")
        if email:
            return email
    except Exception:
        pass
    try:
        root = client.get_metadata("root", fields="id")
        return f"root-{root.get('id')}"
    except Exception:
        return None
