"""ECDSA P-256 verification for the Galileo public key directory."""

import hashlib

__all__ = [
    "decompress_public_key",
    "verify_ecdsa_p256",
]

P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
A = P - 3
B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
GX = 0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296
GY = 0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5


class InvalidSignature(ValueError):
    """The signature values are not a valid P-256 signature pair."""


def _inverse(value: int) -> int:
    return pow(value, P - 2, P)


def _point_add(
    left: tuple[int, int] | None, right: tuple[int, int] | None
) -> tuple[int, int] | None:
    if left is None:
        return right
    if right is None:
        return left
    x1, y1 = left
    x2, y2 = right
    if x1 == x2 and (y1 + y2) % P == 0:
        return None
    if left == right:
        slope = (3 * x1 * x1 + A) * _inverse(2 * y1) % P
    else:
        slope = (y2 - y1) * _inverse((x2 - x1) % P) % P
    x3 = (slope * slope - x1 - x2) % P
    y3 = (slope * (x1 - x3) - y1) % P
    return x3, y3


def _point_multiply(scalar: int, point: tuple[int, int]) -> tuple[int, int] | None:
    result: tuple[int, int] | None = None
    addend: tuple[int, int] | None = point
    while scalar:
        if scalar & 1:
            result = _point_add(result, addend)
        addend = _point_add(addend, addend)
        scalar >>= 1
    return result


def decompress_public_key(compressed: bytes) -> tuple[int, int]:
    """Return the P-256 point of a compressed public key.

    ``compressed`` is the 33-byte SEC1 form with the leading sign byte.
    Raises :class:`InvalidSignature` for values not on the curve.
    """
    if len(compressed) != 33 or compressed[0] not in (2, 3):
        raise InvalidSignature("Compressed P-256 keys are 33 bytes with sign 2 or 3")
    x = int.from_bytes(compressed[1:], "big")
    y_squared = (pow(x, 3, P) + A * x + B) % P
    y = pow(y_squared, (P + 1) // 4, P)
    if pow(y, 2, P) != y_squared:
        raise InvalidSignature("Compressed key does not encode a curve point")
    if y & 1 != compressed[0] & 1:
        y = P - y
    return x, y


def verify_ecdsa_p256(
    message: bytes, signature: bytes, public_key: bytes
) -> bool:
    """Verify an ECDSA P-256/SHA-256 ``signature`` over ``message``.

    ``public_key`` is the 65-byte uncompressed SEC1 form or the 33-byte
    compressed form. The signature is the raw ``r || s`` pair with
    fixed-width coordinates, as used by the Galileo authentication
    messages.
    """
    if len(signature) != 64:
        raise InvalidSignature("P-256 signatures are the 64 byte raw r and s pair")
    r = int.from_bytes(signature[:32], "big")
    s = int.from_bytes(signature[32:], "big")
    if not (0 < r < N and 0 < s < N):
        return False
    if len(public_key) == 33:
        public_point = decompress_public_key(public_key)
    elif len(public_key) == 65 and public_key[0] == 4:
        public_point = (
            int.from_bytes(public_key[1:33], "big"),
            int.from_bytes(public_key[33:], "big"),
        )
    else:
        raise InvalidSignature("Public key must be the 33 or 65 byte SEC1 form")
    digest = hashlib.sha256(message).digest()
    z = int.from_bytes(digest, "big")
    w = pow(s, N - 2, N)
    u1 = z * w % N
    u2 = r * w % N
    product = _point_add(
        _point_multiply(u1, (GX, GY)), _point_multiply(u2, public_point)
    )
    return product is not None and product[0] % N == r
