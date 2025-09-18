# src/app.py
from dotenv import load_dotenv
from langchain_core.messages import AIMessageChunk, AIMessage, ToolMessage
from src.orchestrator.graph import build_orchestrator

def stream_cli(thread_id: str = "1"):
    load_dotenv()
    app = build_orchestrator()

    while True:
        try:
            user_input = input("User: ")
        except EOFError:
            break

        if user_input.lower() in {"quit","exit","q"}:
            print("Goodbye!")
            break

        state = {"messages": [{"role": "user", "content": user_input}]}

        for msg, meta in app.stream(
            state,
            stream_mode="messages",
            config={"configurable": {"thread_id": thread_id}},
        ):
            if isinstance(msg, ToolMessage):
                # (optionnel) print("🔧 tool call…")
                continue
            if isinstance(msg, AIMessageChunk):
                print(msg.content, end="", flush=True)
            elif isinstance(msg, AIMessage):
                print(msg.content, end="", flush=True)
        print()

if __name__ == "__main__":
    stream_cli(thread_id="1")
