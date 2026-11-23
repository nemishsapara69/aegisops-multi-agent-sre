from app.schemas.governance import ExecutionResult
from app.schemas.remediation import FixProposal
from app.tools.sandbox import validate_fix

# Records every "applied" fix so tests and the audit phase can see it.
EXECUTION_LOG = []


def execute_fix(proposal: FixProposal) -> ExecutionResult:
    """MOCK executor. A real one would call your CI/CD or database tooling.
    It re-validates in the sandbox first, so a fix can never change between approval and execution."""
    check = validate_fix(proposal)
    if not check.passed:
        failed = ", ".join(c.name for c in check.checks if not c.passed)
        return ExecutionResult(
            executed=False, mode="mock", checks_rerun_passed=False,
            message="Blocked: sandbox re-check failed (" + failed + ")"[:500],
        )
    EXECUTION_LOG.append({
        "fix_type": proposal.fix_type.value,
        "target_service": proposal.target_service,
        "summary": proposal.summary,
        "content": proposal.content,
    })
    return ExecutionResult(
        executed=True, mode="mock", checks_rerun_passed=True,
        message=("[MOCK] Applied " + proposal.fix_type.value + " to " + proposal.target_service
                 + ": " + proposal.summary)[:500],
    )