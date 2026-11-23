SUBMIT_FIX_SCHEMA = {
    "type": "function",
    "function": {
        "name": "submit_fix",
        "description": "Submit exactly one proposed fix. It is validated in a sandbox.",
        "parameters": {
            "type": "object",
            "properties": {
                "fix_type": {"type": "string", "enum": ["rollback", "config_change", "sql_patch", "code_diff"]},
                "target_service": {"type": "string"},
                "summary": {"type": "string"},
                "rationale": {"type": "string"},
                "content": {"type": "object", "description": "Format depends on fix_type, see instructions."},
                "rollback_plan": {"type": "string"},
                "reversible": {"type": "boolean"},
                "requires_restart": {"type": "boolean"},
                "supporting_docs": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["fix_type", "target_service", "summary", "rationale", "content", "rollback_plan"],
        },
    },
}