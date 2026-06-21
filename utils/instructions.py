import re

SENTENCE_BOUNDARY_PATTERN = re.compile(r"(?<=[.!?])\s+")
BULLET_PREFIX_PATTERN = re.compile(r"^\s*(?:[-*]|\d+[.)])\s*")
STEP_PREFIX_PATTERN = re.compile(r"^\s*step\s*\d+\s*[:.)-]\s*", re.IGNORECASE)
STEP_BOUNDARY_PATTERN = re.compile(
    r"(?:^|(?<=[.!?]))\s*step\s*\d+\s*[:.)-]\s*",
    re.IGNORECASE,
)
LEADING_SEQUENCE_PATTERN = re.compile(
    r"^(?:and|first|next|then|now|meanwhile|finally|lastly|afterward|afterwards|subsequently)\s+",
    re.IGNORECASE,
)
SEQUENCE_MARKER_PATTERN = re.compile(
    r"\s+(?=(?:next|then|now|meanwhile|finally|lastly|afterward|afterwards|subsequently)\b)",
    re.IGNORECASE,
)
ACTION_BOUNDARY_PATTERN = re.compile(
    r"(?<!\bto)\s+(?=(?:wash|rinse|soak|drain|heat\s+(?:oil|coconut|mustard|water|milk|ghee)|add|put|place|cook|simmer|stir|mix|grind|pour|steam\s+for|cover|remove|serve|turn off|allow|beat|whisk|saute|fry|garnish)\b)",
    re.IGNORECASE,
)
TRAILING_CONNECTOR_PATTERN = re.compile(r"\s+(?:and|then)\s*$", re.IGNORECASE)
SHORT_FOLLOW_UP_PATTERN = re.compile(r"^(?:mix|stir|whisk|beat|keep|set|allow|let)\b", re.IGNORECASE)
CONNECTOR_ACTION_PATTERN = re.compile(
    r"\s+(?:and\s+)?(?=(?:add|cook|stir|mix|grind|pour|cover|remove|serve|turn off|garnish)\b)",
    re.IGNORECASE,
)


def clean_instruction_fragment(value):
    text = BULLET_PREFIX_PATTERN.sub("", str(value or "").strip())
    text = STEP_PREFIX_PATTERN.sub("", text)
    text = LEADING_SEQUENCE_PATTERN.sub("", text)
    text = re.sub(r"\s+", " ", text).strip(" ,;:")
    return TRAILING_CONNECTOR_PATTERN.sub("", text).strip(" ,;:")


def finalize_instruction_step(text):
    cleaned = clean_instruction_fragment(text)
    if not cleaned:
        return ""

    normalized = cleaned[0].upper() + cleaned[1:] if len(cleaned) > 1 else cleaned.upper()
    if normalized[-1] not in ".!?":
        normalized = f"{normalized}."
    return normalized


def split_on_action_boundaries(text):
    parts = [clean_instruction_fragment(part) for part in ACTION_BOUNDARY_PATTERN.split(text) if part.strip()]
    if len(parts) <= 1:
        parts = [clean_instruction_fragment(part) for part in CONNECTOR_ACTION_PATTERN.split(text) if part.strip()]

    if len(parts) <= 1:
        return [text]

    merged = []
    for part in parts:
        if merged and SHORT_FOLLOW_UP_PATTERN.match(part) and len(part.split()) <= 4:
            merged[-1] = f"{merged[-1]} {part}".strip()
            continue

        merged.append(part)

    return merged


def split_instruction_block(text):
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []

    if STEP_BOUNDARY_PATTERN.search(normalized):
        explicit_steps = [
            clean_instruction_fragment(part)
            for part in STEP_BOUNDARY_PATTERN.split(normalized)
            if part.strip()
        ]
        return [finalize_instruction_step(step) for step in explicit_steps if step]

    lines = [clean_instruction_fragment(line) for line in normalized.split("\n") if line.strip()]
    if len(lines) > 1:
        steps = []
        for line in lines:
            steps.extend(split_instruction_block(line))
        return [step for step in steps if step]

    sentence_steps = [clean_instruction_fragment(part) for part in SENTENCE_BOUNDARY_PATTERN.split(normalized) if part.strip()]
    if len(sentence_steps) > 1:
        return [finalize_instruction_step(step) for step in expand_long_steps(sentence_steps) if step]

    sequence_steps = [clean_instruction_fragment(part) for part in SEQUENCE_MARKER_PATTERN.split(normalized) if part.strip()]
    if len(sequence_steps) > 1:
        return [finalize_instruction_step(step) for step in expand_long_steps(sequence_steps) if step]

    return [finalize_instruction_step(step) for step in expand_long_steps([clean_instruction_fragment(normalized)]) if step]


def expand_long_steps(steps):
    expanded = []
    for step in steps:
        if len(step) <= 70:
            expanded.append(step)
            continue

        secondary_steps = [clean_instruction_fragment(part) for part in split_on_action_boundaries(step) if part.strip()]
        if len(secondary_steps) > 1:
            expanded.extend(secondary_steps)
        else:
            expanded.append(step)

    return expanded
