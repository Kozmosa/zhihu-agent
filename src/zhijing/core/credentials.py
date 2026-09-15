"""Machine-local model profiles encrypted for the current Windows account.

Only ciphertext reaches the filesystem. No network, registry, environment or
credential-store mutation is performed. Legacy migration never makes a plaintext backup.
"""

import base64
import ctypes
import json
import os
import tempfile
from pathlib import Path
from typing import Protocol

PROFILE_FILE = "model-config.dpapi.json"
LEGACY_FILE = "model-config.json"
ALLOWED_FIELDS = {"ZHIJING_MODEL_PROVIDER"} | {
    "ZHIJING_" + provider + "_" + field
    for provider, fields in {
        "OPENAI": (
            "URL",
            "MODEL",
            "API_KEY",
            "TIMEOUT",
            "FORMAT",
            "MAX_TOKENS",
            "CONTEXT_WINDOW",
            "MAX_INPUT_CHARS",
            "THINKING",
        ),
        "OLLAMA": (
            "URL",
            "MODEL",
            "API_KEY",
            "TIMEOUT",
            "FORMAT",
            "NUM_PREDICT",
            "NUM_CTX",
            "MAX_INPUT_CHARS",
        ),
    }.items()
    for field in fields
}


class CredentialStorageError(ValueError):
    """Safe, content-free error suitable for the configuration API."""


class Protector(Protocol):
    def protect(self, value: bytes) -> bytes: ...
    def unprotect(self, value: bytes) -> bytes: ...


class WindowsDPAPI:
    """DPAPI CurrentUser with UI disabled; never uses machine-wide encryption."""

    def _convert(self, value: bytes, *, decrypt: bool) -> bytes:
        if os.name != "nt":
            raise CredentialStorageError("加密保存 API 配置需要 Windows 当前用户保护。")
        from ctypes import wintypes

        class Blob(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

        buffer = ctypes.create_string_buffer(value)
        incoming = Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
        outgoing = Blob()
        crypt = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
        fn.argtypes = [
            ctypes.POINTER(Blob),
            ctypes.c_void_p,
            ctypes.POINTER(Blob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(Blob),
        ]
        fn.restype = wintypes.BOOL
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        # CRYPTPROTECT_UI_FORBIDDEN = 1, no CRYPTPROTECT_LOCAL_MACHINE.
        if not fn(ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing)):
            raise CredentialStorageError(
                "无法保护或解密本机 API 配置，请使用保存它的 Windows 账户。"
            )
        try:
            return ctypes.string_at(outgoing.data, outgoing.size)
        finally:
            if outgoing.data:
                ctypes.memset(outgoing.data, 0, outgoing.size)
                kernel.LocalFree(outgoing.data)

    def protect(self, value: bytes) -> bytes:
        return self._convert(value, decrypt=False)

    def unprotect(self, value: bytes) -> bytes:
        return self._convert(value, decrypt=True)


def persistence_supported() -> bool:
    return os.name == "nt"


def default_protector() -> Protector:
    return WindowsDPAPI()


def _validate(value) -> dict[str, str]:
    if not isinstance(value, dict) or any(
        key not in ALLOWED_FIELDS or not isinstance(item, str) for key, item in value.items()
    ):
        raise CredentialStorageError("Local model-config.json 配置字段无效。")
    if len(json.dumps(value).encode("utf-8")) > 16384:
        raise CredentialStorageError("本机 API 配置内容过大。")
    return value


def _read(path: Path, limit: int):
    try:
        if path.stat().st_size > limit:
            raise ValueError()
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raise CredentialStorageError("Local model-config.json 配置无效或无法读取。") from None


def load_protected_profile(data_dir: Path, *, protector: Protector | None = None) -> dict[str, str]:
    protector = protector or default_protector()
    try:
        envelope = _read(data_dir / PROFILE_FILE, 65536)
        if set(envelope) != {"version", "protection", "ciphertext"}:
            raise ValueError()
        if envelope["version"] != 1 or envelope["protection"] != "windows-dpapi-current-user":
            raise ValueError()
        encrypted = base64.b64decode(envelope["ciphertext"], validate=True)
        return _validate(json.loads(protector.unprotect(encrypted).decode("utf-8")))
    except CredentialStorageError:
        raise
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise CredentialStorageError("本机加密 API 配置无效，请重新保存配置。") from None


def save_model_profile(
    data_dir: Path, profile: dict[str, str], *, protector: Protector | None = None
) -> None:
    protector = protector or default_protector()
    profile = _validate(profile)
    encrypted = protector.protect(json.dumps(profile, ensure_ascii=False).encode("utf-8"))
    # Verify decryptability before replacing an existing file or deleting legacy data.
    if _validate(json.loads(protector.unprotect(encrypted).decode("utf-8"))) != profile:
        raise CredentialStorageError("本机 API 配置加密校验失败。")
    payload = json.dumps(
        {
            "version": 1,
            "protection": "windows-dpapi-current-user",
            "ciphertext": base64.b64encode(encrypted).decode("ascii"),
        }
    )
    temporary = None
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=data_dir,
            prefix=".model-config-",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, data_dir / PROFILE_FILE)
    except OSError:
        raise CredentialStorageError("无法写入本机加密 API 配置。") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def migrate_legacy_model_profile(data_dir: Path, *, protector: Protector | None = None) -> bool:
    """Encrypt legacy fields, verify persisted bytes, then remove the old file.

    An existing protected profile must match; conflicting files are never silently
    overwritten or removed. Failure leaves the original available for recovery.
    """
    legacy = data_dir / LEGACY_FILE
    if not legacy.exists():
        return False
    profile = _validate(_read(legacy, 16384))
    if (data_dir / PROFILE_FILE).exists():
        if load_protected_profile(data_dir, protector=protector) != profile:
            raise CredentialStorageError("明文与加密 API 配置不一致，请先确认要保留的配置。")
    else:
        save_model_profile(data_dir, profile, protector=protector)
    if load_protected_profile(data_dir, protector=protector) != profile:
        raise CredentialStorageError("本机 API 配置迁移校验失败。")
    try:
        legacy.unlink()
    except OSError:
        raise CredentialStorageError(
            "加密已完成，但旧明文配置无法删除，请关闭占用它的程序。"
        ) from None
    return True


def load_model_profile(data_dir: Path) -> dict[str, str]:
    if (data_dir / LEGACY_FILE).exists():
        migrate_legacy_model_profile(data_dir)
    return load_protected_profile(data_dir) if (data_dir / PROFILE_FILE).exists() else {}
