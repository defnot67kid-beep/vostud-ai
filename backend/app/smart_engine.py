import os
import time
import requests
from typing import List, Dict, Any
from dotenv import load_dotenv
from app.coding_prompts import CODING_SYSTEM_PROMPT
from app.model_switcher import ModelSwitcher

load_dotenv()

class SmartAIEngine:
    """Vostud AI with automatic API switching - Full Coding Assistant"""
    
    def __init__(self):
        self.rag = None
        self.current_api = None
        self.api_priority = []
        self.apis = {}
        self.model_switcher = None
        
        # Initialize RAG
        try:
            from app.rag_engine import RAGEngine
            self.rag = RAGEngine()
            print(f"✅ RAG Engine loaded in SmartEngine")
        except Exception as e:
            print(f"⚠️ RAG Engine not available: {e}")
            self.rag = None
        
        # Setup API clients
        self._setup_apis()
        
        # Initialize model switcher
        if self.apis:
            self.model_switcher = ModelSwitcher(self)
            print(f"✅ Model Switcher initialized with {len(self.model_switcher.available_models)} models")
        
        # Use specialized coding system prompt
        self.system_prompt = CODING_SYSTEM_PROMPT

    def _setup_apis(self):
        """Setup all available API clients"""
        
        # ============================================
        # PRIMARY: Groq (Fastest, free, WORKING)
        # ============================================
        try:
            from groq import Groq
            api_key = os.getenv("GROQ_API_KEY")
            if api_key and api_key != "your_groq_api_key_here" and api_key.startswith("gsk_"):
                self.apis['groq'] = {
                    'client': Groq(api_key=api_key),
                    'type': 'groq',
                    'models': [
                        'llama-3.3-70b-versatile',  # BEST - most capable
                        'llama-3.1-70b-versatile',  # Good alternative
                        'llama-3.1-8b-instant',     # Fastest
                        'gemma2-9b-it'              # Google's model
                    ]
                }
                self.api_priority.append('groq')
                print("✅ Groq API initialized (PRIMARY - Fastest!)")
            else:
                if api_key and not api_key.startswith("gsk_"):
                    print("⚠️ Groq API key format invalid (should start with 'gsk_')")
                else:
                    print("⚠️ Groq API key not set")
        except ImportError:
            print("⚠️ Groq not installed (pip install groq)")
        except Exception as e:
            print(f"⚠️ Groq init error: {e}")
        
        # ============================================
        # BACKUP 1: Google Gemini (Free, native API)
        # ============================================
        try:
            import google.generativeai as genai
            api_key = os.getenv("GEMINI_API_KEY")
            if api_key and api_key != "your_gemini_api_key_here" and api_key.startswith("AIza"):
                genai.configure(api_key=api_key)
                
                # Get available models
                available_models = []
                try:
                    for model in genai.list_models():
                        if 'generateContent' in model.supported_generation_methods:
                            available_models.append(model.name.split('/')[-1])
                except:
                    available_models = ['gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-pro']
                
                # Filter to working models
                working_models = []
                for model in available_models:
                    if model in ['gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-pro', 
                                 'gemini-2.5-flash', 'gemini-2.5-pro']:
                        working_models.append(model)
                
                if not working_models:
                    working_models = ['gemini-2.0-flash', 'gemini-1.5-flash']
                
                if working_models:
                    self.apis['gemini'] = {
                        'client': genai,
                        'type': 'gemini',
                        'models': working_models
                    }
                    self.api_priority.append('gemini')
                    print(f"✅ Google Gemini initialized (BACKUP 1)")
                else:
                    print("⚠️ No working Gemini models found")
            else:
                if api_key and not api_key.startswith("AIza"):
                    print("⚠️ Gemini API key format invalid (should start with 'AIza')")
                    print("   Get a key at: https://makersuite.google.com/app/apikey")
                else:
                    print("⚠️ Gemini API key not set")
        except ImportError:
            print("⚠️ Google Gemini not installed (pip install google-generativeai)")
        except Exception as e:
            print(f"⚠️ Gemini init error: {e}")
        
        # ============================================
        # BACKUP 2: OpenRouter (Free models, proxy)
        # ============================================
        try:
            from openai import OpenAI
            api_key = os.getenv("OPENROUTER_API_KEY")
            if api_key and api_key != "your_openrouter_api_key_here" and api_key.startswith("sk-or-v1"):
                self.apis['openrouter'] = {
                    'client': OpenAI(
                        base_url="https://openrouter.ai/api/v1",
                        api_key=api_key,
                        default_headers={
                            "HTTP-Referer": "http://localhost:8000",
                            "X-Title": "Vostud AI"
                        }
                    ),
                    'type': 'openrouter',
                    'models': [
                        # CONFIRMED WORKING OpenRouter models
                        'google/gemini-flash-1.5',      # Google via OpenRouter
                        'deepseek/deepseek-chat',       # DeepSeek
                        'qwen/qwen-2.5-7b-instruct',    # Qwen
                        'meta-llama/llama-3.1-8b-instruct',  # Llama 3.1
                        'microsoft/phi-3-mini-128k-instruct'  # Phi-3
                    ]
                }
                self.api_priority.append('openrouter')
                print(f"✅ OpenRouter API initialized (BACKUP 2 - {len(self.apis['openrouter']['models'])} models)")
            else:
                if api_key and not api_key.startswith("sk-or-v1"):
                    print("⚠️ OpenRouter API key format invalid (should start with 'sk-or-v1')")
                else:
                    print("⚠️ OpenRouter API key not set")
        except ImportError:
            print("⚠️ OpenAI client not installed (pip install openai)")
        except Exception as e:
            print(f"⚠️ OpenRouter init error: {e}")
        
        # ============================================
        # BACKUP 3: Ollama (Local, free - SLOW)
        # ============================================
        try:
            import ollama
            
            try:
                models_list = ollama.list()
                
                if models_list and hasattr(models_list, 'models'):
                    model_names = []
                    for m in models_list.models:
                        model_names.append(m.model)
                    
                    if model_names:
                        code_models = []
                        for m in model_names:
                            if any(name in m.lower() for name in ['llama2', 'qwen', 'codellama', 'mistral', 'deepseek', 'llama3', 'coder']):
                                code_models.append(m)
                        
                        if not code_models:
                            code_models = model_names
                        
                        if code_models:
                            self.apis['ollama'] = {
                                'client': ollama,
                                'type': 'ollama',
                                'models': code_models
                            }
                            self.api_priority.append('ollama')
                            print(f"✅ Ollama initialized (BACKUP 3 - Slow)")
                        else:
                            print("⚠️ Ollama running but no valid models found")
                    else:
                        print("⚠️ Ollama running but no models found. Run: ollama pull llama2")
                else:
                    print("⚠️ Ollama running but no models found. Run: ollama pull llama2")
                    
            except Exception as e:
                print(f"⚠️ Ollama connection error: {e}. Make sure Ollama is running.")
                
        except ImportError:
            print("⚠️ Ollama not installed (pip install ollama)")
        except Exception as e:
            print(f"⚠️ Ollama init error: {e}")
        
        # ============================================
        # LAST RESORT: OpenAI (Paid)
        # ============================================
        try:
            from openai import OpenAI
            api_key = os.getenv("OPENAI_API_KEY")
            if api_key and api_key != "your_openai_api_key_here" and not api_key.startswith("sk-test"):
                self.apis['openai'] = {
                    'client': OpenAI(api_key=api_key),
                    'type': 'openai',
                    'models': ['gpt-3.5-turbo', 'gpt-4']
                }
                self.api_priority.append('openai')
                print("✅ OpenAI initialized (LAST RESORT - Paid)")
            else:
                if api_key and api_key.startswith("sk-test"):
                    print("⚠️ OpenAI test key detected (not valid for API calls)")
                else:
                    print("⚠️ OpenAI API key not set or invalid")
        except ImportError:
            print("⚠️ OpenAI not installed (pip install openai)")
        except Exception as e:
            print(f"⚠️ OpenAI init error: {e}")
        
        # ============================================
        # FINAL STATUS
        # ============================================
        if not self.api_priority:
            print("❌ No APIs available! Please set up at least one API.")
            print("   - Groq: https://console.groq.com (FREE, FAST)")
            print("   - Gemini: https://makersuite.google.com/app/apikey (FREE)")
            print("   - OpenRouter: https://openrouter.ai/ (FREE)")
            print("   - Ollama: https://ollama.ai/ (LOCAL, FREE)")
        else:
            print(f"✅ {len(self.api_priority)} API(s) available: {', '.join(self.api_priority)}")

    def generate_response(self, 
                         user_message: str, 
                         conversation_history: List[Dict] = None,
                         use_rag: bool = True,
                         model_override: str = None) -> str:
        """Generate response with model switching support"""
        
        # Get context from RAG if available
        context = ""
        if use_rag and self.rag:
            try:
                documents = self.rag.search(user_message, n_results=3)
                if documents:
                    context_parts = [doc['text'] for doc in documents]
                    context = "\n\n".join(context_parts[:3])
            except Exception as e:
                print(f"⚠️ RAG search error: {e}")
        
        # Build messages
        messages = [
            {"role": "system", "content": self.system_prompt}
        ]
        
        if conversation_history:
            messages.extend(conversation_history)
        
        if context:
            context_message = f"""
Relevant context from your study materials:
{context}

Based on this context and your knowledge, answer the user's question.
If the context doesn't contain the answer, use your general knowledge.
"""
            messages.append({"role": "system", "content": context_message})
        
        messages.append({"role": "user", "content": user_message})
        
        # Check for model override
        if model_override and self.model_switcher:
            try:
                print(f"🎯 Using manually selected model: {model_override}")
                response = self._call_specific_model(model_override, messages)
                if response:
                    self.current_api = model_override.split('/')[0]
                    return response
            except Exception as e:
                print(f"❌ Manual model selection failed: {e}")
                print("Falling back to auto-selection...")
        
        # Auto-select best model if enabled
        if self.model_switcher and self.model_switcher.auto_mode:
            best_model = self.model_switcher.get_best_model()
            if best_model:
                try:
                    print(f"🤖 Auto-selected model: {best_model}")
                    response = self._call_specific_model(best_model, messages)
                    if response:
                        self.current_api = best_model.split('/')[0]
                        return response
                except Exception as e:
                    print(f"❌ Auto-selected model failed: {e}")
        
        # Fallback to priority-based API switching
        for api_name in self.api_priority:
            try:
                print(f"🔄 Trying {api_name}...")
                response = self._call_api(api_name, messages)
                if response:
                    self.current_api = api_name
                    print(f"✅ Using {api_name}")
                    return response
            except Exception as e:
                error_msg = str(e)
                print(f"❌ {api_name} failed: {error_msg[:200]}")
                continue
        
        if context:
            return f"""I found relevant information in your study materials, but I'm having trouble connecting to my AI services.

Here's what I found:
{context[:500]}...

💡 To enable AI responses, set up an API:
- Groq (Fastest, Free): https://console.groq.com
- Gemini (Free): https://makersuite.google.com/app/apikey
- OpenRouter (Free): https://openrouter.ai/"""
        
        return "❌ All APIs are currently unavailable. Please check your API keys or try again later."

    def _call_specific_model(self, model_key: str, messages: List[Dict]) -> str:
        """Call a specific model by its key (api/model)"""
        if not self.model_switcher or model_key not in self.model_switcher.available_models:
            return None
        
        model_info = self.model_switcher.available_models[model_key]
        api_name = model_info['api']
        model = model_info['model']
        
        if api_name in self.apis:
            try:
                api_config = self.apis[api_name]
                if api_name == 'groq':
                    result = self._call_groq_specific(api_config, messages, model)
                elif api_name == 'gemini':
                    result = self._call_gemini_specific(api_config, messages, model)
                elif api_name == 'openrouter':
                    result = self._call_openrouter_specific(api_config, messages, model)
                elif api_name == 'ollama':
                    result = self._call_ollama_specific(api_config, messages, model)
                elif api_name == 'openai':
                    result = self._call_openai_specific(api_config, messages, model)
                else:
                    return None
                
                if result:
                    self.model_switcher.mark_model_status(model_key, 'working')
                    return result
            except Exception as e:
                self.model_switcher.mark_model_status(model_key, 'failed')
                raise e
        
        return None

    def _call_groq_specific(self, config, messages, model):
        client = config['client']
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.7,
                max_tokens=1000
            )
            return response.choices[0].message.content
        except Exception as e:
            raise e

    def _call_gemini_specific(self, config, messages, model):
        prompt = ""
        system_prompt = ""
        
        for msg in messages:
            role = msg['role']
            content = msg['content']
            if role == 'system':
                system_prompt += content + "\n\n"
            elif role == 'user':
                prompt += f"User: {content}\n"
            elif role == 'assistant':
                prompt += f"Assistant: {content}\n"
        
        if system_prompt:
            prompt = f"System: {system_prompt}\n\n{prompt}"
        prompt += "Assistant: "
        
        try:
            model_obj = config['client'].GenerativeModel(model)
            response = model_obj.generate_content(prompt)
            if response and response.text:
                return response.text
        except Exception as e:
            raise e
        
        return None

    def _call_openrouter_specific(self, config, messages, model):
        client = config['client']
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.7,
                max_tokens=1000
            )
            if response and response.choices:
                return response.choices[0].message.content
        except Exception as e:
            raise e
        return None

    def _call_ollama_specific(self, config, messages, model):
        import requests
        
        ollama_messages = []
        system_content = ""
        
        for msg in messages:
            role = msg['role']
            content = msg['content']
            if role == 'system':
                system_content += content + "\n\n"
            else:
                if system_content and role == 'user' and not ollama_messages:
                    content = f"{system_content}\n\n{content}"
                    system_content = ""
                ollama_messages.append({
                    'role': role,
                    'content': content
                })
        
        if system_content:
            ollama_messages.insert(0, {'role': 'user', 'content': system_content})
        
        try:
            response = requests.post(
                "http://localhost:11434/api/chat",
                json={
                    "model": model,
                    "messages": ollama_messages,
                    "stream": False,
                    "options": {
                        "temperature": 0.7,
                        "num_predict": 1000
                    }
                },
                timeout=120
            )
            
            if response.status_code == 200:
                result = response.json()
                if result and result.get('message'):
                    return result['message']['content']
        except Exception as e:
            raise e
        
        return None

    def _call_openai_specific(self, config, messages, model):
        client = config['client']
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.7,
                max_tokens=1000
            )
            return response.choices[0].message.content
        except Exception as e:
            raise e

    def _call_api(self, api_name: str, messages: List[Dict]) -> str:
        """Call specific API"""
        
        api_config = self.apis.get(api_name)
        if not api_config:
            return None
        
        try:
            if api_name == 'groq':
                return self._call_groq(api_config, messages)
            elif api_name == 'gemini':
                return self._call_gemini(api_config, messages)
            elif api_name == 'openrouter':
                return self._call_openrouter(api_config, messages)
            elif api_name == 'ollama':
                return self._call_ollama(api_config, messages)
            elif api_name == 'openai':
                return self._call_openai(api_config, messages)
        except Exception as e:
            raise Exception(f"{api_name} API error: {e}")
        
        return None

    def _call_groq(self, config, messages):
        client = config['client']
        for model in config['models']:
            try:
                print(f"   Trying Groq model: {model}")
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.7,
                    max_tokens=1000
                )
                return response.choices[0].message.content
            except Exception as e:
                error_str = str(e)
                if "decommissioned" in error_str.lower() or "not supported" in error_str.lower():
                    print(f"   ⚠️ Model {model} is deprecated, trying next...")
                    continue
                elif "model" in error_str.lower() and "not found" in error_str.lower():
                    print(f"   ⚠️ Model {model} not available, trying next...")
                    continue
                else:
                    print(f"   ⚠️ Groq error with {model}: {error_str[:100]}")
                    continue
        raise Exception("No Groq models available")

    def _call_gemini(self, config, messages):
        prompt = ""
        system_prompt = ""
        
        for msg in messages:
            role = msg['role']
            content = msg['content']
            if role == 'system':
                system_prompt += content + "\n\n"
            elif role == 'user':
                prompt += f"User: {content}\n"
            elif role == 'assistant':
                prompt += f"Assistant: {content}\n"
        
        if system_prompt:
            prompt = f"System: {system_prompt}\n\n{prompt}"
        prompt += "Assistant: "
        
        for model_name in config['models']:
            try:
                print(f"   Trying Gemini model: {model_name}")
                model = config['client'].GenerativeModel(model_name)
                response = model.generate_content(prompt)
                if response and response.text:
                    return response.text
            except Exception as e:
                error_str = str(e)
                if "not found" in error_str or "not supported" in error_str or "404" in error_str:
                    print(f"   ⚠️ Model {model_name} not available, trying next...")
                    continue
                else:
                    print(f"   ⚠️ Gemini error with {model_name}: {error_str[:100]}")
                    continue
        
        raise Exception("No Gemini models available")

    def _call_openrouter(self, config, messages):
        client = config['client']
        
        # Try auto-select first
        try:
            print(f"   Trying OpenRouter auto-select...")
            response = client.chat.completions.create(
                model="",
                messages=messages,
                temperature=0.7,
                max_tokens=1000,
                extra_body={
                    "models": config['models'][:5]
                }
            )
            if response and response.choices:
                return response.choices[0].message.content
        except Exception as e:
            print(f"   ⚠️ Auto-select failed: {str(e)[:50]}")
        
        # Fallback: try specific models
        for model in config['models']:
            try:
                print(f"   Trying OpenRouter model: {model}")
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.7,
                    max_tokens=1000
                )
                if response and response.choices:
                    return response.choices[0].message.content
            except Exception as e:
                error_str = str(e)
                if "rate limit" in error_str.lower() or "429" in error_str:
                    print(f"   ⚠️ Rate limit on {model}, trying next...")
                    continue
                elif "not found" in error_str.lower() or "404" in error_str:
                    print(f"   ⚠️ Model {model} not available, trying next...")
                    continue
                elif "free" in error_str.lower() or "unavailable" in error_str.lower():
                    print(f"   ⚠️ {model} not free, trying next...")
                    continue
                else:
                    print(f"   ⚠️ OpenRouter error with {model}: {error_str[:100]}")
                    continue
        
        raise Exception("No OpenRouter models available")

    def _call_ollama(self, config, messages):
        ollama_messages = []
        system_content = ""
        
        for msg in messages:
            role = msg['role']
            content = msg['content']
            if role == 'system':
                system_content += content + "\n\n"
            else:
                if system_content and role == 'user' and not ollama_messages:
                    content = f"{system_content}\n\n{content}"
                    system_content = ""
                ollama_messages.append({
                    'role': role,
                    'content': content
                })
        
        if system_content:
            ollama_messages.insert(0, {'role': 'user', 'content': system_content})
        
        for model_name in config['models']:
            try:
                print(f"   Trying Ollama model: {model_name}")
                response = requests.post(
                    "http://localhost:11434/api/chat",
                    json={
                        "model": model_name,
                        "messages": ollama_messages,
                        "stream": False,
                        "options": {
                            "temperature": 0.7,
                            "num_predict": 1000
                        }
                    },
                    timeout=120
                )
                if response.status_code == 200:
                    result = response.json()
                    if result and result.get('message'):
                        return result['message']['content']
                else:
                    error_msg = response.text[:100] if response.text else "Unknown error"
                    if "model" in error_msg.lower() and "not found" in error_msg.lower():
                        print(f"   ⚠️ Model {model_name} not found, trying next...")
                        continue
                    else:
                        print(f"   ⚠️ Ollama returned {response.status_code}: {error_msg}")
                        continue
            except requests.exceptions.ConnectionError:
                print(f"   ❌ Cannot connect to Ollama. Make sure it's running.")
                raise Exception("Ollama not running")
            except requests.exceptions.Timeout:
                print(f"   ⚠️ Ollama timeout with {model_name}, trying next...")
                continue
            except Exception as e:
                error_str = str(e)
                if "not found" in error_str.lower():
                    print(f"   ⚠️ Model {model_name} not available, trying next...")
                    continue
                else:
                    print(f"   ⚠️ Ollama error with {model_name}: {error_str[:100]}")
                    continue
        
        raise Exception("No Ollama models available")

    def _call_openai(self, config, messages):
        client = config['client']
        for model in config['models']:
            try:
                print(f"   Trying OpenAI model: {model}")
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.7,
                    max_tokens=1000
                )
                return response.choices[0].message.content
            except Exception as e:
                error_str = str(e)
                if "model" in error_str.lower() and "not found" in error_str.lower():
                    print(f"   ⚠️ Model {model} not available, trying next...")
                    continue
                elif "429" in error_str:
                    raise Exception(f"OpenAI: No credits remaining or rate limited")
                elif "401" in error_str:
                    raise Exception(f"OpenAI: Invalid API key")
                else:
                    print(f"   ⚠️ OpenAI error with {model}: {error_str[:100]}")
                    continue
        
        raise Exception("No OpenAI models available")

    def generate_quiz(self, topic: str, num_questions: int = 5) -> str:
        """Generate a quiz using available API"""
        
        context = ""
        if self.rag:
            try:
                documents = self.rag.search(topic, n_results=5)
                if documents:
                    context = "\n\n".join([doc['text'] for doc in documents[:5]])
            except:
                pass
        
        prompt = f"""
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
        
        if context:
            prompt = f"""
Using this context from study materials:
{context}

{prompt}
"""
        
        messages = [
            {"role": "system", "content": "You are Vostud AI, a quiz generator."},
            {"role": "user", "content": prompt}
        ]
        
        for api_name in self.api_priority:
            try:
                print(f"🔄 Generating quiz with {api_name}...")
                response = self._call_api(api_name, messages)
                if response:
                    return response
            except Exception as e:
                print(f"❌ {api_name} quiz generation failed: {e}")
                continue
        
        return "❌ Could not generate quiz. Please check API availability."