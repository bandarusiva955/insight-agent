import os

from dotenv import load_dotenv
from google import genai

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

if not api_key:
    raise ValueError("GEMINI_API_KEY is missing from .env")

client = genai.Client(api_key=api_key)

response = client.interactions.create(
    model=model,
    input="Explain what SQL is in two simple sentences."
)

print("Gemini connected successfully!")
print("\nGemini response:")
print(response.output_text)