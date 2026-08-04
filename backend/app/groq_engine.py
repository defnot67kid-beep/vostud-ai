import os
from groq import Groq
from typing import List, Dict
from app.rag_engine import RAGEngine

class ChatEngine:
    def __init__(self):
        self.client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        self.rag = RAGEngine()
        self.system_prompt = "You are Vostud AI, a study assistant. Be helpful and clear."

    def generate_response(self, user_message: str, history=None, use_rag=True):
        context = ""
        if use_rag:
            docs = self.rag.search(user_message)
            if docs:
                context = "\n\n".join([d['text'] for d in docs[:3]])

        messages = [
            {"role": "system", "content": self.system_prompt}
        ]
        
        if context:
            messages.append({"role": "system", "content": f"Context: {context}"})
        
        if history:
            messages.extend(history)
        
        messages.append({"role": "user", "content": user_message})

        response = self.client.chat.completions.create(
            model="mixtral-8x7b-32768",  # Free model
            messages=messages,
            temperature=0.7
        )
        return response.choices[0].message.content