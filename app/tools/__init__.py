from app.tools.sql_tool import query_db
from app.tools.metrics_tool import get_metrics
from app.tools.logs_tool import search_logs

TOOLS = {
    "query_db": query_db,
    "get_metrics": get_metrics,
    "search_logs": search_logs,
}

TOOL_DESCRIPTIONS = (
    "- query_db(sql): run ONE read-only SELECT. Tables: "
    "connections(service, minute, active, max_allowed), "
    "deployments(id, service, version, deployed_at, status), "
    "payment_errors(minute, service, error_code, error_count)\n"
    "- get_metrics(service, metric): payments-db -> cpu_percent, connections_active, p95_latency_ms; "
    "payments-api -> error_rate_percent, p95_latency_ms; "
    "orders-api -> error_rate_percent, p95_latency_ms\n"
    "- search_logs(service, keyword, limit): case-insensitive keyword filter; "
    "services: payments-api, payments-db, orders-api"
)