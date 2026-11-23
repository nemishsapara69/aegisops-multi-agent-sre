from app.llm import get_llm, FAST_MODEL

print(get_llm().invoke("Say hello in one line").content)
print(get_llm(FAST_MODEL).invoke("Say hello in one line").content)