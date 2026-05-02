from dotenv import load_dotenv
from functools import lru_cache
import os
from langbly import Langbly
load_dotenv()

@lru_cache(maxsize=1)
def get_translator():
    return Langbly(os.getenv("LANGBLY_API_KEY"))

