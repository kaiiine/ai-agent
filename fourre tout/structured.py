import json
import os

from pydantic_core import ValidationError
import ollama
from pydantic import BaseModel

ollama_model="qwen2.5-coder:7b"

# --------------------------------------------------------------
# Step 1: Define the response format in a Pydantic model
# --------------------------------------------------------------


class CalendarEvent(BaseModel):
    name: str
    date: str
    participants: list[str]
    class Config:
        extra="ignore"


# --------------------------------------------------------------
# Step 2: Call the model
# --------------------------------------------------------------

completion = ollama.chat(model=ollama_model, messages=[
    {"role": "system", "content": ("Extract the event information and response ONLY in this exact JSON format: \n"  
                                   '{"name: "...", "date": "...", "participants": ["...", "..."]}')},
    {
        "role": "user",
        "content": "Alice and Bob are going to a science fair on Friday.",
    },
])

# --------------------------------------------------------------
# Step 3: Parse the response
# --------------------------------------------------------------

json_data = completion['message']['content']
data = json.loads(json_data)
event = CalendarEvent(**data)
print(event.name)