from app.llm import get_llm, BIG_MODEL
from app.agents.investigator import SYSTEM_PROMPT

llm = get_llm(BIG_MODEL)
messages = [
    ("system", SYSTEM_PROMPT),
    ("user", "Incident priority: P1\nCategory: database\nAffected service: payments-db\n"
             "Alert text (sanitized):\n<<<\nPayments failing for all users, connection pool exhausted\n>>>"),
]
reply = llm.invoke(messages)

print("CONTENT :", repr(reply.content))
print("METADATA:", reply.response_metadata)
print("EXTRA   :", reply.additional_kwargs)