#!/usr/bin/env python
"""
Quick test to verify Ollama setup before running the full voice agent.
Run: python test_ollama.py
"""

import os
import sys
import requests
from dotenv import load_dotenv
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

OLLAMA_API_URL = os.getenv("OLLAMA_API_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL")
OLLAMA_TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0.7"))

def test_ollama_connection():
    """Test if Ollama server is accessible."""
    print("=" * 60)
    print("🔍 Testing Ollama Connection")
    print("=" * 60)
    print(f"\n🌐 Ollama URL: {OLLAMA_API_URL}")
    print(f"🤖 Model: {OLLAMA_MODEL}")
    print(f"🌡️  Temperature: {OLLAMA_TEMPERATURE}\n")
    
    try:
        # Test basic connectivity
        print("📡 Testing connection to Ollama...")
        response = requests.get(f"{OLLAMA_API_URL}/api/tags", timeout=5)
        
        if response.status_code == 200:
            print("✅ Ollama is running!\n")
            
            # Get available models
            models = response.json().get("models", [])
            print(f"📦 Available models ({len(models)}):")
            for model in models:
                model_name = model.get("name", "Unknown")
                size = model.get("size", 0)
                size_gb = size / (1024**3)
                print(f"   • {model_name} ({size_gb:.1f} GB)")
            
            print()
            
            # Check if specified model exists
            model_names = [m["name"] for m in models]
            if OLLAMA_MODEL in model_names:
                print(f"✅ Model '{OLLAMA_MODEL}' is installed")
            else:
                print(f"⚠️  Model '{OLLAMA_MODEL}' NOT FOUND")
                print(f"   Pull it with: ollama pull {OLLAMA_MODEL}")
                return False
        else:
            print(f"❌ Ollama returned status code {response.status_code}")
            return False
    
    except requests.exceptions.ConnectionError:
        print("❌ Could not connect to Ollama")
        print(f"   Make sure Ollama is running: ollama serve")
        print(f"   Check the URL is correct: {OLLAMA_API_URL}")
        return False
    
    except Exception as e:
        print(f"❌ Error: {e}")
        return False
    
    return True

def test_ollama_response():
    """Test if Ollama can generate a response."""
    print("\n" + "=" * 60)
    print("🧠 Testing LLM Response")
    print("=" * 60 + "\n")
    
    try:
        print(f"📨 Sending test message to {OLLAMA_MODEL}...")
        
        response = requests.post(
            f"{OLLAMA_API_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": "You are a helpful assistant. Keep responses brief (1-2 sentences)."},
                    {"role": "user", "content": "What is 2+2?"}
                ],
                "temperature": OLLAMA_TEMPERATURE,
                "stream": False
            },
            timeout=60
        )
        
        if response.status_code == 200:
            result = response.json()
            message = result.get("message", {}).get("content", "").strip()
            
            if message:
                print(f"✅ LLM Response received:\n")
                print(f"   💬 \"{message}\"\n")
                return True
            else:
                print("❌ Empty response from LLM")
                return False
        else:
            print(f"❌ API returned status code {response.status_code}")
            print(f"   Response: {response.text}")
            return False
    
    except requests.exceptions.Timeout:
        print("❌ Request timed out (60 seconds)")
        print("   This usually means the model is very large or your system is slow")
        return False
    
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def test_voice_components():
    """Test voice components if available."""
    print("\n" + "=" * 60)
    print("🎤 Checking Voice Components")
    print("=" * 60 + "\n")
    
    all_ok = True
    
    # Test faster-whisper
    try:
        from faster_whisper import WhisperModel
        print("✅ faster-whisper is installed")
    except ImportError:
        print("❌ faster-whisper not installed: pip install faster-whisper")
        all_ok = False
    
    # Test openwakeword
    try:
        from openwakeword import Model
        print("✅ openwakeword is installed")
    except ImportError:
        print("❌ openwakeword not installed: pip install openwakeword")
        all_ok = False
    
    # Test pyttsx3
    try:
        import pyttsx3
        print("✅ pyttsx3 is installed")
    except ImportError:
        print("❌ pyttsx3 not installed: pip install pyttsx3")
        all_ok = False
    
    # Test sounddevice
    try:
        import sounddevice
        print("✅ sounddevice is installed")
    except ImportError:
        print("❌ sounddevice not installed: pip install sounddevice")
        all_ok = False
    
    # Test requests
    try:
        import requests
        print("✅ requests is installed")
    except ImportError:
        print("❌ requests not installed: pip install requests")
        all_ok = False
    
    # Test python-dotenv
    try:
        from dotenv import load_dotenv
        print("✅ python-dotenv is installed")
    except ImportError:
        print("❌ python-dotenv not installed: pip install python-dotenv")
        all_ok = False
    
    return all_ok

def main():
    """Run all tests."""
    print("\n")
    
    # Test voice components first
    voice_ok = test_voice_components()
    
    # Test Ollama connection
    ollama_connected = test_ollama_connection()
    
    if not ollama_connected:
        print("\n" + "=" * 60)
        print("❌ OLLAMA NOT READY")
        print("=" * 60)
        print("\nTo fix:")
        print("1. Start Ollama server: ollama serve")
        print("2. In another terminal, pull a model:")
        print(f"   ollama pull {OLLAMA_MODEL}")
        print("3. Then run this test again")
        return False
    
    # Test LLM response
    response_ok = test_ollama_response()
    
    # Summary
    print("\n" + "=" * 60)
    print("📋 Summary")
    print("=" * 60)
    
    if voice_ok and ollama_connected and response_ok:
        print("\n✅ All systems ready! You can now run:")
        print("   python main.py\n")
        return True
    else:
        print("\n⚠️  Some issues detected. Please fix above and try again.\n")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
