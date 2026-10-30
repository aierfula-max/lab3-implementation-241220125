"""口令哈希。

REQ-021 要求 bcrypt(cost≥10) 或 Argon2id。桌面版不引第三方依赖，
这里用标准库的 PBKDF2-HMAC-SHA256（20 万轮、16 字节随机盐）替代，
存储格式 ``pbkdf2_sha256$轮数$盐$摘要``，校验用常量时间比较。

这是一个**有意的偏离**，不是“等价实现”。报告 7.2 节把它列进了不足：
PBKDF2 对 GPU 的抵抗力弱于 Argon2id，真上线要换成 argon2-cffi，
并且把 ``hash_password``/``verify_password`` 保持成同一个接口。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 200_000


def hash_password(password: str, *, iterations: int = ITERATIONS) -> str:
    """生成可存库的口令摘要。"""
    if len(password) < 8:
        raise ValueError("密码至少 8 位")
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("ascii"), iterations
    ).hex()
    return f"{ALGORITHM}${iterations}${salt}${digest}"


def verify_password(password: str, encoded: str) -> bool:
    """常量时间校验，格式错误一律返回 False。"""
    try:
        algorithm, rounds, salt, expected = encoded.split("$")
        if algorithm != ALGORITHM:
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("ascii"), int(rounds)
        ).hex()
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, expected)
