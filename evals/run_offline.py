import itertools
import tempfile

from app.agents.governance_gate import needs_human, score_risk
from app.agents.institutional_memory import retrieve
from app.rag.ingest import load_documents
from app.rag.rbac import KNOWN_ROLES, can_access
from app.rag.sample_docs import write_sample_docs
from app.schemas.remediation import FixProposal
from app.security.pii_redactor import redact
from app.tools.sandbox import validate_fix
from evals import data, judge


def suite_redaction():
    failures, leaked = [], 0
    for case in data.REDACTION_CASES:
        clean, _counts = redact(case["text"])
        problems = []
        for secret in case["remove"]:
            if secret in clean:
                problems.append("leaked: " + secret)
                leaked += 1
        for keep in case["keep"]:
            if keep not in clean:
                problems.append("over-redacted: " + keep)
        if problems:
            failures.append({"case": case["name"], "problems": problems})
    n = len(data.REDACTION_CASES)
    return {"cases": n, "passed": n - len(failures), "secrets_leaked": leaked, "failures": failures}


def suite_sandbox():
    failures, false_accepts, false_rejects = [], 0, 0
    for case in data.SANDBOX_CASES:
        proposal = FixProposal(fix_type=case["fix_type"], target_service=case["target"], summary="s",
                               rationale="r", content=case["content"], rollback_plan="undo")
        result = validate_fix(proposal)
        if result.passed != case["expect_pass"]:
            if result.passed:
                false_accepts += 1
            else:
                false_rejects += 1
            failed = [c.name for c in result.checks if not c.passed]
            failures.append({"case": case["name"], "expected_pass": case["expect_pass"], "failed_checks": failed})
    n = len(data.SANDBOX_CASES)
    return {"cases": n, "passed": n - len(failures), "false_accepts": false_accepts,
            "false_rejects": false_rejects, "failures": failures}


def _decide(priority, env, fix_type, reversible=True, restart=False, confidence=0.9, docs=True):
    proposal = FixProposal(fix_type=fix_type, target_service="svc", summary="s", rationale="r",
                           content={"x": 1}, rollback_plan="undo", reversible=reversible,
                           requires_restart=restart, supporting_docs=["RB-1"] if docs else [])
    state = {"triage": {"priority": priority}, "raw_alert": {"environment": env},
             "investigation": {"confidence": confidence}}
    risk = score_risk(state, proposal)
    return risk, bool(needs_human(priority, risk.score))


def suite_governance():
    mismatches = []
    for case in data.GOVERNANCE_CASES:
        risk, human = _decide(**case["args"])
        if human != case["expect_human"]:
            mismatches.append({"args": case["args"], "score": risk.score, "needs_human": human,
                               "expected": case["expect_human"]})
    counts = {"hi": [0, 0], "lo": [0, 0]}          # [combinations, auto-executed]
    for p, env, ft, rev, rs, conf, docs in itertools.product(
            ["P1", "P2", "P3", "P4"], ["production", "staging", "dev", "moon"],
            ["rollback", "config_change", "sql_patch", "code_diff"],
            [True, False], [True, False], [0.9, 0.4], [True, False]):
        _risk, human = _decide(p, env, ft, rev, rs, conf, docs)
        bucket = counts["hi"] if p in ("P1", "P2") else counts["lo"]
        bucket[0] += 1
        if not human:
            bucket[1] += 1
    return {"cases": len(data.GOVERNANCE_CASES), "case_mismatches": len(mismatches), "mismatches": mismatches,
            "p1_p2_combos": counts["hi"][0], "p1_p2_auto_executed": counts["hi"][1],
            "p3_p4_combos": counts["lo"][0], "p3_p4_auto_pct": judge.pct(counts["lo"][1], counts["lo"][0])}


def suite_retrieval():
    with tempfile.TemporaryDirectory() as tmp:
        write_sample_docs(tmp)
        chunks = load_documents(tmp)
    access = {c.doc_id: c.allowed_roles for c in chunks}

    leaks, checks = 0, 0
    for role in KNOWN_ROLES + ["admin"]:                 # "admin" is unknown, so it must act as guest
        for query in data.RETRIEVAL_QUERIES:
            ctx = retrieve(query, role, chunks)
            checks += 1
            for r in ctx.results:
                if not can_access(role, access[r.doc_id]):
                    leaks += 1

    failures = []
    for case in data.RETRIEVAL_CASES:
        ids = {r.doc_id for r in retrieve(case["query"], case["role"], chunks).results}
        if case["kind"] == "negative":
            ok = not ids
        else:
            ok = all(e in ids for e in case["expect"]) and not any(f in ids for f in case["forbid"])
        if not ok:
            failures.append({"case": case["name"], "returned": sorted(ids)})
    n = len(data.RETRIEVAL_CASES)
    return {"cases": n, "passed": n - len(failures), "failures": failures,
            "leak_checks": checks, "leaks": leaks}


def run_all():
    return {"redaction": suite_redaction(), "sandbox": suite_sandbox(),
            "governance": suite_governance(), "retrieval": suite_retrieval()}


def main():
    r = run_all()
    red, sb, gov, ret = r["redaction"], r["sandbox"], r["governance"], r["retrieval"]
    print("REDACTION  : %d/%d cases passed | secrets leaked: %d" % (red["passed"], red["cases"], red["secrets_leaked"]))
    for f in red["failures"]:
        print("   FAIL", f["case"], "->", "; ".join(f["problems"]))
    print("SANDBOX    : %d/%d cases passed | false accepts: %d | false rejects: %d" % (
        sb["passed"], sb["cases"], sb["false_accepts"], sb["false_rejects"]))
    for f in sb["failures"]:
        print("   FAIL", f["case"], "| expected pass:", f["expected_pass"], "| failed checks:", f["failed_checks"])
    print("GOVERNANCE : %d/%d policy cases agree | P1/P2 combinations auto-executed: %d of %d" % (
        gov["cases"] - gov["case_mismatches"], gov["cases"], gov["p1_p2_auto_executed"], gov["p1_p2_combos"]))
    for m in gov["mismatches"]:
        print("   FAIL", m)
    print("RETRIEVAL  : %d/%d cases passed | RBAC leaks: %d in %d checks" % (
        ret["passed"], ret["cases"], ret["leaks"], ret["leak_checks"]))
    for f in ret["failures"]:
        print("   FAIL", f["case"], "-> returned", f["returned"])
    print("saved:", judge.save_summary("offline", r))


if __name__ == "__main__":
    main()