# src/app.py
import argparse
from dotenv import load_dotenv
from langchain_core.messages import AIMessageChunk, AIMessage, ToolMessage
from src.orchestrator.graph import build_orchestrator
import os

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


def cli_vscode(user_input: str, thread_id: str = "1"):
    load_dotenv()
    app = build_orchestrator()
    file_path = os.getenv("CLI_AGENT_FILE", "")
    dir_path=os.getenv("CLI_AGENT_DIR","")
    ws_path=os.getenv("CLI_AGENT_WS","")
    selection = os.getenv("CLI_AGENT_SELECTION", "")


    context=[]
    if(file_path):
        context.append(f"file: {file_path}")
    if(dir_path):
        context.append(f"dir: {dir_path}")
    if(ws_path):
        context.append(f"workspace: {ws_path}")
    
    text = " ".join(context)
    if(text):
        user_input += f"\n\n[VSCodeContext: {text}]"
    if selection:
        user_input += f"\n\n[Selection]\n{selection}"



    state = {"messages": [{"role": "user", "content": user_input}]}

    for msg, meta in app.stream(
        state,
        stream_mode="messages",
        config={"configurable": {"thread_id": thread_id}},
    ):
        if isinstance(msg, ToolMessage):
            continue
        if isinstance(msg, AIMessageChunk):
            print(msg.content, end="", flush=True)
        elif isinstance(msg, AIMessage):
            print(msg.content, end="", flush=True)
    print()


def main():
    """
    Point d'entrée avec choix de mode.
    
    Exemples :
        python -m src.app                                    # Mode interactif (défaut)
        python -m src.app --once "Ton message"               # Mode one-shot
        python -m src.app --once "Corrige bug" --thread-id "vscode-workspace"
    """
    parser = argparse.ArgumentParser(description="AI Agent CLI")
    parser.add_argument(
        "--once",
        "--message",
        "-m",
        type=str,
        help="Mode one-shot : exécute une seule commande",
        dest="message"
    )
    parser.add_argument(
        "--thread-id",
        "-t",
        type=str,
        default="1",
        help="ID du thread (défaut: '1')"
    )
    
    args = parser.parse_args()
    
    if args.message:
        # Mode one-shot (cli_vscode)
        cli_vscode(user_input=args.message, thread_id=args.thread_id)
    else:
        # Mode interactif (stream_cli)
        stream_cli(thread_id=args.thread_id)


if __name__ == "__main__":
    main()
