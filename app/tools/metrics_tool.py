import json

from app.tools.mock_data import METRICS


def get_metrics(service, metric):
    if service not in METRICS:
        raise ValueError("Unknown service '" + str(service) + "'. Available: " + ", ".join(METRICS))
    if metric not in METRICS[service]:
        raise ValueError(
            "Unknown metric '" + str(metric) + "' for " + service + ". Available: "
            + ", ".join(METRICS[service])
        )
    return json.dumps(METRICS[service][metric])