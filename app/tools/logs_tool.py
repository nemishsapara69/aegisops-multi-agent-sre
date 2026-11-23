from app.tools.mock_data import LOGS


def search_logs(service, keyword="", limit=10):
    if service not in LOGS:
        raise ValueError("Unknown service '" + str(service) + "'. Available: " + ", ".join(LOGS))
    try:
        limit = max(1, min(int(limit), 15))
    except (TypeError, ValueError):
        limit = 10
    kw = str(keyword).lower()
    lines = [line for line in LOGS[service] if kw in line.lower()]
    if not lines:
        return "No matching log lines."
    return "\n".join(lines[:limit])