# Suppress Gemini warnings
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

# Then in smart_engine.py, add this before importing google.generativeai