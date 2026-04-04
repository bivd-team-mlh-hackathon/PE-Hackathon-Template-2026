"""
URL shortening utilities.

Short code generation follows the Base 62 conversion approach described in the
system design plan: encode the URL's auto-increment primary key in base 62,
producing a collision-free, compact code that grows naturally with the dataset.

Character set: 0-9 (0-9), a-z (10-35), A-Z (36-61)  →  62 possible chars
  n=7 supports 62^7 ≈ 3.5 trillion unique codes (sufficient for 365B over 10yr)
"""

CHARSET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"

# Paths that must never be usable as short codes
RESERVED = {"urls", "users", "api", "health", "static", "favicon.ico", "robots.txt"}


def to_base62(n: int) -> str:
    """Convert a positive integer to a base-62 string."""
    if n <= 0:
        return CHARSET[0]
    digits = []
    while n:
        digits.append(CHARSET[n % 62])
        n //= 62
    return "".join(reversed(digits))


def is_valid_custom_code(code: str) -> tuple[bool, str]:
    """Validate a user-supplied custom short code. Returns (ok, error_message)."""
    if not code:
        return False, "Code cannot be empty"
    if len(code) > 20:
        return False, "Code must be 20 characters or fewer"
    if code.lower() in RESERVED:
        return False, f'"{code}" is a reserved path'
    allowed = set(CHARSET + "-_")
    if not all(c in allowed for c in code):
        return False, "Code may only contain letters, numbers, hyphens, and underscores"
    return True, ""
