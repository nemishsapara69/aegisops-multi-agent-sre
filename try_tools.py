from app.llm import get_llm, BIG_MODEL, FAST_MODEL, BACKUP_MODEL
from app.schemas.remediation import FixProposal
from app.tools.fix_schema import SUBMIT_FIX_SCHEMA
from app.tools.sandbox import validate_fix

RUNS = 3
PROMPT = (
    "payments-api v2.14.0 leaks database connections. Propose a rollback of payments-api "
    "from v2.14.0 to v2.13.4 by calling submit_fix. For a rollback, content must be "
    '{"service": "payments-api", "from_version": "v2.14.0", "to_version": "v2.13.4"}.'
)

for model in [BIG_MODEL, FAST_MODEL, BACKUP_MODEL]:
    ok = 0
    problems = []
    for _ in range(RUNS):
        try:
            llm = get_llm(model, fallbacks=[]).bind_tools([SUBMIT_FIX_SCHEMA])
            reply = llm.invoke(PROMPT)
            call = reply.tool_calls[0]
            proposal = FixProposal(**call["args"])
            sandbox = validate_fix(proposal)
            if call["name"] == "submit_fix" and sandbox.passed:
                ok += 1
            else:
                bad = [c.name for c in sandbox.checks if not c.passed]
                problems.append("sandbox failed: " + ", ".join(bad))
        except Exception as e:
            problems.append(type(e).__name__ + ": " + str(e)[:90])
    print("%-24s valid fixes: %d of %d" % (model, ok, RUNS))
    if problems:
        print("    first problem:", problems[0])