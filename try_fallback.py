from app.llm import get_llm, BACKUP_MODEL
from app.resilience import llm_events
from app.tools.fix_schema import SUBMIT_FIX_SCHEMA


def show_events():
    for e in llm_events.EVENTS:
        print("   %-28s attempt %d  %-10s %s" % (e["model"], e["attempt"], e["outcome"], e["error"][:60]))
    llm_events.EVENTS.clear()


print("CHECK 1: primary model does not exist, so it must fall back")
llm = get_llm("openai/not-a-real-model")
print("  reply:", llm.invoke("Say hello in one line").content)
print("  answered by:", llm.last_model)
show_events()

print("\nCHECK 2: backup model alone")
backup = get_llm(BACKUP_MODEL, fallbacks=[])
print("  reply:", backup.invoke("Say hello in one line").content)
print("  answered by:", backup.last_model)
show_events()

print("\nCHECK 3: does the backup model support native tool calls?")
tool_llm = get_llm(BACKUP_MODEL, fallbacks=[]).bind_tools([SUBMIT_FIX_SCHEMA])
reply = tool_llm.invoke("Propose a rollback of payments-api from v2.14.0 to v2.13.4 by calling submit_fix.")
print("  tool calls:", [c["name"] for c in reply.tool_calls])
print("  answered by:", tool_llm.last_model)
show_events()