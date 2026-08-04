import os
from typing import List, Dict, Any
from openai import OpenAI
from app.rag_engine import RAGEngine

class ChatEngine:
    def __init__(self):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.rag = RAGEngine()
        self.system_prompt = """You are Vostud AI, a friendly and knowledgeable study assistant.

Your purpose is to help students learn effectively. Follow these guidelines:

1. Always be encouraging and supportive
2. Explain concepts step-by-step with clear examples
3. Use simple language - avoid jargon when possible
4. When explaining, break down complex topics
5. If asked about a specific topic, use the provided context
6. If you don't know something, be honest
7. Offer to create quizzes, flashcards, or study plans
8. Use bullet points and formatting for clarity

Remember: You're helping someone learn, so be patient and thorough."""
    
    def generate_response(self, 
                          user_message: str, 
                          conversation_history: List[Dict] = None,
                          use_rag: bool = True) -> str:
        """Generate a response using RAG and conversation history"""
        
        # Step 1: Get relevant context from RAG
        context = ""
        if use_rag:
            documents = self.rag.search(user_message, n_results=3)
            if documents:
                context_parts = [doc['text'] for doc in documents]
                context = "\n\n".join(context_parts[:3])
        
        # Step 2: Build messages
        messages = [
            {"role": "system", "content": self.system_prompt}
        ]
        
        # Add conversation history
        if conversation_history:
            messages.extend(conversation_history)
        
        # Add context and user message
        if context:
            context_message = f"""
Relevant context from your study materials:
{context}

Based on this context and your knowledge, answer the user's question.
If the context doesn't contain the answer, use your general knowledge.
"""
            messages.append({"role": "system", "content": context_message})
        
        messages.append({"role": "user", "content": user_message})
        
        # Step 3: Generate response
        response = self.client.chat.completions.create(
            model="gpt-3.5-turbo",  # or "gpt-4" if you have access
            messages=messages,
            temperature=0.7,
            max_tokens=1000
        )
        
        return response.choices[0].message.content
    
    def generate_quiz(self, topic: str, num_questions: int = 5) -> str:
        """Generate a quiz on a specific topic"""
        prompt = f"""
Create a quiz with {num_questions} multiple-choice questions about "{topic}".

Format:
1. Question text
   A. Option
   B. Option
   C. Option
   D. Option
   Answer: [Correct letter]

Make the questions challenging but fair. Include a mix of easy and hard questions.
"""
        
        # Use RAG to get context
        documents = self.rag.search(topic, n_results=5)
        context = "\n\n".join([doc['text'] for doc in documents]) if documents else ""
        
        if context:
            prompt = f"""
Using this context from your study materials:
{context}

Create a quiz with {num_questions} multiple-choice questions about "{topic}".

Format:
1. Question text
   A. Option
   B. Option
   C. Option
   D. Option
   Answer: [Correct letter]

Make the questions challenging but fair.
"""
        
        response = self.client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are Vostud AI, a quiz generator."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.8,
            max_tokens=1500
        )
        
        return response.choices[0].message.content