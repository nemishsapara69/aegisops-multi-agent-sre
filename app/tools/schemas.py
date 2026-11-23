def _fn(name, description, properties, required):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


SERVICES = ["payments-api", "payments-db", "orders-api"]

ALL_SCHEMAS = [
    _fn(
        "query_db",
        "Run ONE read-only SQL SELECT. Tables: "
        "connections(service, minute, active, max_allowed), "
        "deployments(id, service, version, deployed_at, status), "
        "payment_errors(minute, service, error_code, error_count).",
        {"sql": {"type": "string"}},
        ["sql"],
    ),
    _fn(
        "get_metrics",
        "Get a metric time series. payments-db: cpu_percent, connections_active, p95_latency_ms. "
        "payments-api: error_rate_percent, p95_latency_ms. orders-api: error_rate_percent, p95_latency_ms.",
        {"service": {"type": "string", "enum": SERVICES}, "metric": {"type": "string"}},
        ["service", "metric"],
    ),
    _fn(
        "search_logs",
        "Search recent log lines of a service with a case-insensitive keyword filter.",
        {
            "service": {"type": "string", "enum": SERVICES},
            "keyword": {"type": "string"},
            "limit": {"type": "integer"},
        },
        ["service"],
    ),
    _fn(
        "submit_report",
        "Submit the final root-cause report. Call this once, when you know the root cause "
        "or when you must escalate.",
        {
            "root_cause": {"type": "string"},
            "confidence": {"type": "number", "description": "between 0 and 1"},
            "evidence": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"source": {"type": "string"}, "detail": {"type": "string"}},
                    "required": ["source", "detail"],
                },
            },
            "suggested_fix_area": {"type": "string"},
            "needs_human": {"type": "boolean"},
        },
        ["root_cause", "confidence", "evidence", "suggested_fix_area", "needs_human"],
    ),
]