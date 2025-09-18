from langgraph.checkpoint.memory import InMemorySaver

def build_checkpointer():
    # Facile à remplacer par Redis/SQLite plus tard
    return InMemorySaver()
