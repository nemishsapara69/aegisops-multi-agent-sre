KNOWN_ROLES = ["sre", "dba", "developer", "support", "security", "guest"]


def normalize_role(role):
    """Unknown or missing roles become 'guest' (least privilege)."""
    cleaned = str(role or "").strip().lower()
    return cleaned if cleaned in KNOWN_ROLES else "guest"


def can_access(role, allowed_roles):
    allowed = [a.lower() for a in allowed_roles]
    return "all" in allowed or normalize_role(role) in allowed


def filter_chunks(chunks, role):
    """Applied BEFORE search, so restricted text never reaches scoring or any LLM."""
    return [c for c in chunks if can_access(role, c.allowed_roles)]