# test.py
import sys
print(f"Python: {sys.version}")

try:
    import openai
    print("✅ OpenAI")
except Exception as e:
    print(f"❌ OpenAI: {e}")

try:
    import fastapi
    print("✅ FastAPI")
except Exception as e:
    print(f"❌ FastAPI: {e}")

try:
    import pypdf
    print("✅ PyPDF")
except Exception as e:
    print(f"❌ PyPDF: {e}")

try:
    import chromadb
    print("✅ ChromaDB")
except Exception as e:
    print(f"⚠️ ChromaDB: {e} (try FAISS instead)")

try:
    import faiss
    print("✅ FAISS")
except Exception as e:
    print(f"⚠️ FAISS: {e}")# test.py
import sys
print(f"Python: {sys.version}")

try:
    import openai
    print("✅ OpenAI")
except Exception as e:
    print(f"❌ OpenAI: {e}")

try:
    import fastapi
    print("✅ FastAPI")
except Exception as e:
    print(f"❌ FastAPI: {e}")

try:
    import pypdf
    print("✅ PyPDF")
except Exception as e:
    print(f"❌ PyPDF: {e}")

try:
    import chromadb
    print("✅ ChromaDB")
except Exception as e:
    print(f"⚠️ ChromaDB: {e} (try FAISS instead)")

try:
    import faiss
    print("✅ FAISS")
except Exception as e:
    print(f"⚠️ FAISS: {e}")