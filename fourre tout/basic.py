import os
import ollama

model = os.getenv("OLLAMA_MODEL", "llama3")
messages = [
    {"role": "system", "content": "You're a helpful assistant."},
    {"role": "user", "content": "Write a limerick about the Python programming language."},
]

response = ollama.chat(model=model, messages=messages)
print(response['message']['content'])