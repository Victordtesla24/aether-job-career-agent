# Deliberate violations. The guard MUST flag every one of these.
# This file lives in the corpus, which is excluded from the normal scan.
MOCK_MODE: bool = True
FAKE_DATA_ENABLED = True
SECRET_KEY = "sk-test-abcdef123456"
AETHER_CREDENTIAL_KEY = "htOwdaXn8QwZE8LSvZF1oCdgVBisuJnJHrgxBGvVrEU="
OPENAI_KEY = "sk-" + "test" + "9f3ba712cc"
def a():
    try: pass
    except Exception: pass
def b():
    return []  # stub
