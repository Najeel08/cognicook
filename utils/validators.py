import re
from urllib.parse import unquote

EMAIL_PATTERN = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z]{2,63}$"
)
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,30}$")
UPPERCASE_PATTERN = re.compile(r"[A-Z]")
LOWERCASE_PATTERN = re.compile(r"[a-z]")
DIGIT_PATTERN = re.compile(r"\d")
REPEATED_CHARACTER_PATTERN = re.compile(r"(.)\1{3,}", re.IGNORECASE)
CONTROL_CHARACTER_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
TRAVERSAL_SEGMENT_PATTERN = re.compile(r"(^|[\\/,&;=\s])\.\.($|[\\/,&;=\s])")

COMMON_WEAK_PASSWORDS = {
    "12345678",
    "123456789",
    "1234567890",
    "password",
    "password1",
    "password123",
    "admin123",
    "qwerty123",
    "welcome123",
    "letmein123",
    "abc12345",
    "cognicook",
    "cognicook123",
}

SEQUENTIAL_PATTERNS = {
    "qwer",
    "asdf",
    "zxcv",
}

SEQUENTIAL_RUN_SOURCES = ("0123456789", "abcdefghijklmnopqrstuvwxyz")


def get_positive_int(value, default, minimum=1, maximum=None):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default

    if parsed < minimum:
        return default

    if maximum is not None and parsed > maximum:
        return maximum

    return parsed


def decode_repeatedly(value, max_rounds=3):
    decoded = str(value or "")
    for _ in range(max_rounds):
        next_value = unquote(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    return decoded


def contains_control_characters(value):
    return bool(CONTROL_CHARACTER_PATTERN.search(str(value or "")))


def contains_path_traversal(value):
    normalized = decode_repeatedly(value).replace("\\", "/")
    parts = [part for part in normalized.split("/") if part]
    return "\x00" in normalized or any(part == ".." for part in parts) or bool(TRAVERSAL_SEGMENT_PATTERN.search(normalized))


def is_safe_input(value, max_length=1000, allow_path_separators=True):
    text = str(value or "")
    if len(text) > max_length or contains_control_characters(text):
        return False
    if not allow_path_separators and ("/" in text or "\\" in text):
        return False
    return not contains_path_traversal(text)


def sanitize_choice(value, allowed_values):
    if not value:
        return ""

    normalized = value.strip().lower()
    return normalized if normalized in allowed_values else ""


def is_valid_email(value):
    email = (value or "").strip()
    if len(email) > 254 or ".." in email:
        return False
    local_part = email.split("@", 1)[0]
    if local_part.startswith(".") or local_part.endswith("."):
        return False
    return bool(EMAIL_PATTERN.fullmatch(email))


def is_valid_username(value):
    return bool(USERNAME_PATTERN.match((value or "").strip()))


def has_sequential_run(value, run_length=4):
    lowered = (value or "").lower()
    if any(pattern in lowered for pattern in SEQUENTIAL_PATTERNS):
        return True

    for source in SEQUENTIAL_RUN_SOURCES:
        for index in range(len(source) - run_length + 1):
            sequence = source[index : index + run_length]
            if sequence in lowered or sequence[::-1] in lowered:
                return True

    return False


def validate_password(password):
    value = password or ""
    lowered = value.lower()
    errors = []

    if len(value) < 8:
        errors.append("Password must be at least 8 characters long.")
    if not UPPERCASE_PATTERN.search(value):
        errors.append("Password must include at least one uppercase letter.")
    if not LOWERCASE_PATTERN.search(value):
        errors.append("Password must include at least one lowercase letter.")
    if not DIGIT_PATTERN.search(value):
        errors.append("Password must include at least one number.")
    if REPEATED_CHARACTER_PATTERN.search(value):
        errors.append("Password cannot contain simple repeated sequences like 1111 or aaaa.")
    if has_sequential_run(lowered):
        errors.append("Password cannot contain obvious sequential patterns like 1234 or abcd.")
    if lowered in COMMON_WEAK_PASSWORDS:
        errors.append("Password is too common. Please choose a stronger password.")

    return errors
