#!/usr/bin/env python
"""
Test suite for OpenWakeWord-based WakeWordDetector.
Run: python tests/test_openwakeword.py
"""

import os
import sys
import time
import logging
from dotenv import load_dotenv

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

WAKE_WORD = os.getenv("WAKE_WORD", "alexa")
WAKE_WORD_THRESHOLD = float(os.getenv("WAKE_WORD_THRESHOLD", "0.5"))
WAKE_WORD_TIMEOUT = int(os.getenv("WAKE_WORD_TIMEOUT", "30"))


def print_header(title):
    """Print a formatted header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_section(title):
    """Print a section separator."""
    print(f"\n{'─' * 70}")
    print(f"  {title}")
    print(f"{'─' * 70}\n")


def test_dependencies():
    """Test if all required dependencies are installed."""
    print_header("📦 Testing Dependencies")
    
    all_ok = True
    
    # Test openwakeword
    try:
        import openwakeword
        print("✅ openwakeword is installed")
    except ImportError:
        print("❌ openwakeword not installed: pip install openwakeword")
        all_ok = False
    
    # Test sounddevice
    try:
        import sounddevice
        print("✅ sounddevice is installed")
    except ImportError:
        print("❌ sounddevice not installed: pip install sounddevice")
        all_ok = False
    
    # Test numpy
    try:
        import numpy
        print("✅ numpy is installed")
    except ImportError:
        print("❌ numpy not installed: pip install numpy")
        all_ok = False
    
    return all_ok


def test_available_models():
    """List all available OpenWakeWord models."""
    print_header("🎯 Available OpenWakeWord Models")
    
    try:
        from openwakeword import get_pretrained_model_paths
        
        paths = get_pretrained_model_paths()
        print(f"\nFound {len(paths)} pretrained models:\n")
        
        for i, path in enumerate(paths, 1):
            model_name = os.path.basename(path).replace('.tflite', '').replace('.onnx', '')
            print(f"  {i}. {model_name}")
        
        print(f"\n💡 To use a model, set WAKE_WORD to match the model name")
        print(f"   Example: WAKE_WORD=hey_jarvis\n")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Failed to list models: {e}\n")
        return False


def test_wakeword_init():
    """Test WakeWordDetector initialization."""
    print_header("🔧 Testing WakeWordDetector Initialization")
    
    try:
        from src.wpa.voice.wakeword import WakeWordDetector
        
        print(f"\n📝 Creating detector with wake_word='{WAKE_WORD}'...")
        print("   (Loading OpenWakeWord model, this may take a few seconds...)\n")
        
        start = time.time()
        detector = WakeWordDetector(
            wake_word=WAKE_WORD,
            threshold=WAKE_WORD_THRESHOLD
        )
        init_time = time.time() - start
        
        print(f"✅ Detector initialized in {init_time:.2f}s\n")
        print(f"📋 Configuration:")
        print(f"   • Wake word: '{detector.wake_word}'")
        print(f"   • Threshold: {detector.threshold:.4f}")
        print(f"   • Detection method: OpenWakeWord")
        print(f"   • Model key: {detector._key}\n")
        
        return detector
        
    except Exception as e:
        print(f"\n❌ Initialization failed: {e}\n")
        import traceback
        traceback.print_exc()
        return None


def test_single_listen(detector, timeout=10):
    """Run a single listen test."""
    print_section("🎤 Testing Wake Word Detection")
    
    print(f"Configuration:")
    print(f"  • Timeout: {timeout} seconds")
    print(f"  • Threshold: {detector.threshold:.4f}\n")
    
    print("Instructions:")
    print(f"  1. Say '{detector.wake_word}' clearly")
    print(f"  2. Speak naturally, not too fast or slow")
    print(f"  3. Wait for detection or timeout\n")
    
    print("─" * 70)
    print("Starting in 2 seconds...\n")
    time.sleep(2)
    
    start = time.time()
    detected = detector.listen(timeout=timeout, verbose=True)
    elapsed = time.time() - start
    
    print("─" * 70)
    
    if detected:
        print(f"\n✅ SUCCESS!")
        print(f"   Wake word detected in {elapsed:.2f} seconds\n")
        return True
    else:
        print(f"\n⏰ TIMEOUT")
        print(f"   No wake word detected in {elapsed:.2f} seconds")
        print(f"   Make sure you said: '{detector.wake_word}'\n")
        return False


def test_threshold_tuning(detector):
    """Let user test different threshold levels."""
    print_section("📊 Threshold Tuning")
    
    print("Test different threshold levels to find optimal sensitivity.")
    print("Lower values = more sensitive (easier to trigger, more false positives)")
    print("Higher values = stricter (harder to trigger, fewer false positives)\n")
    
    print(f"Current threshold: {detector.threshold:.4f}\n")
    
    # Suggest thresholds based on current value
    base = detector.threshold
    thresholds = [
        base * 0.5,   # More sensitive
        base,         # Current
        base * 1.5,   # Less sensitive
        base * 2.0    # Much less sensitive
    ]
    
    results = {}
    
    for i, sensitivity in enumerate(thresholds, 1):
        print(f"\n[{i}/{len(thresholds)}] Testing threshold: {sensitivity:.4f}")
        
        if i == 2:
            print("      (This is your current threshold)")
        elif i == 1:
            print("      (More sensitive)")
        else:
            print("      (Less sensitive)")
        
        print("─" * 70)
        
        detector.threshold = sensitivity
        print(f"🎤 Say '{detector.wake_word}' (timeout=10s)...\n")
        time.sleep(1)
        
        detected = detector.listen(timeout=10, verbose=True)
        results[sensitivity] = detected
        
        print("─" * 70)
        
        if detected:
            print(f"✅ Detected at threshold {sensitivity:.4f}\n")
        else:
            print(f"❌ Not detected at threshold {sensitivity:.4f}\n")
        
        if i < len(thresholds):
            response = input("Continue to next threshold? (y/n): ").strip().lower()
            if response != 'y':
                break
    
    # Reset to original
    detector.threshold = WAKE_WORD_THRESHOLD
    
    print("\n📊 Results Summary:")
    for threshold, result in results.items():
        status = "✅ Detected" if result else "❌ Not detected"
        marker = " ← Current" if abs(threshold - WAKE_WORD_THRESHOLD) < 0.0001 else ""
        print(f"   {threshold:.4f}: {status}{marker}")
    
    print("\n💡 Recommendation:")
    detected_thresholds = [t for t, r in results.items() if r]
    if detected_thresholds:
        recommended = max(detected_thresholds)
        print(f"   Use threshold: {recommended:.4f}")
        print(f"   Update .env: WAKE_WORD_THRESHOLD={recommended:.4f}")
    else:
        print(f"   No detections. Try lowering threshold below {min(results.keys()):.4f}")
    
    return results


def test_multiple_attempts(detector, num_tests=3):
    """Run multiple listen tests."""
    print_section(f"🔁 Testing {num_tests} Consecutive Attempts")
    
    results = []
    detected_count = 0
    timeout_count = 0
    times = []
    
    for i in range(1, num_tests + 1):
        print(f"\n[Attempt {i}/{num_tests}]")
        print("─" * 70)
        
        start = time.time()
        detected = detector.listen(timeout=15, verbose=True)
        elapsed = time.time() - start
        
        results.append(detected)
        
        if detected:
            detected_count += 1
            times.append(elapsed)
            print(f"✅ Detected in {elapsed:.2f}s!\n")
        else:
            timeout_count += 1
            print("⏰ Timeout\n")
        
        if i < num_tests:
            response = input("Continue to next attempt? (y/n): ").strip().lower()
            if response != 'y':
                break
    
    # Summary
    print("\n" + "=" * 70)
    print("  📋 Test Summary")
    print("=" * 70)
    
    total = len(results)
    print(f"\nTotal attempts: {total}")
    print(f"Detected: {detected_count} ({detected_count*100//total if total > 0 else 0}%)")
    print(f"Timeout: {timeout_count} ({timeout_count*100//total if total > 0 else 0}%)")
    
    if times:
        avg_time = sum(times) / len(times)
        min_time = min(times)
        max_time = max(times)
        print(f"\nDetection times:")
        print(f"  • Average: {avg_time:.2f}s")
        print(f"  • Fastest: {min_time:.2f}s")
        print(f"  • Slowest: {max_time:.2f}s")
    
    if detected_count > 0:
        print("\n✅ Wake word detector is working!")
        if detected_count == total:
            print("   Perfect score! 🎉")
        elif detected_count >= total * 0.8:
            print("   Good reliability!")
        else:
            print("   Consider adjusting threshold for better consistency.")
    else:
        print("\n⚠️  No detections. Troubleshooting tips:")
        print("   • Speak louder and clearer")
        print("   • Reduce background noise")
        print("   • Lower threshold (try 0.3 or 0.2)")
        print("   • Check microphone is working")
        print("   • Ensure correct wake word model is loaded")
    
    print()
    return results


def test_noise_floor(detector, duration=5):
    """Test background noise levels."""
    print_section(f"🔊 Testing Noise Floor ({duration}s)")
    
    print("This test measures background noise when you're SILENT.")
    print("Stay quiet and don't move during the test.\n")
    
    input("Press Enter to start...")
    
    import sounddevice as sd
    import numpy as np
    
    scores = []
    start = time.time()
    
    print("\n📊 Measuring... (stay silent)")
    
    try:
        with sd.InputStream(channels=1, samplerate=16000,
                            blocksize=1280, dtype='int16') as stream:
            while time.time() - start < duration:
                chunk, _ = stream.read(1280)
                score = detector._model.predict(chunk.flatten())[detector._key]
                scores.append(score)
                print(f"  Score: {score:.6f}", end="\r")
        
        print()
        
        avg_noise = sum(scores) / len(scores)
        max_noise = max(scores)
        min_noise = min(scores)
        
        print(f"\n📊 Noise Analysis:")
        print(f"   • Average: {avg_noise:.6f}")
        print(f"   • Maximum: {max_noise:.6f}")
        print(f"   • Minimum: {min_noise:.6f}")
        print(f"   • Current threshold: {detector.threshold:.6f}")
        
        if max_noise > detector.threshold:
            print(f"\n⚠️  WARNING: Noise exceeds threshold!")
            print(f"   Recommended threshold: {max_noise * 1.5:.6f}")
        else:
            margin = detector.threshold / max_noise if max_noise > 0 else float('inf')
            print(f"\n✅ Good separation: {margin:.1f}x margin")
            if margin < 2:
                print(f"   Consider increasing threshold to: {max_noise * 2:.6f}")
        
        return avg_noise, max_noise
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return None, None


def show_menu():
    """Display main menu."""
    print_header("🧪 OpenWakeWord Detector Test Suite")
    
    print("\nChoose a test:\n")
    print("  1️⃣  Single Listen Test (quick check)")
    print("  2️⃣  Threshold Tuning (find optimal sensitivity)")
    print("  3️⃣  Multiple Attempts (test reliability)")
    print("  4️⃣  Noise Floor Test (measure background noise)")
    print("  5️⃣  List Available Models")
    print("  6️⃣  Full Test Suite (all tests)")
    print("  7️⃣  Exit\n")


def main():
    """Main test menu."""
    
    # Check dependencies
    if not test_dependencies():
        print("\n❌ Missing dependencies. Install them first.\n")
        return
    
    # List available models
    test_available_models()
    
    # Initialize detector
    detector = test_wakeword_init()
    
    if detector is None:
        print("\n❌ Cannot proceed without detector.\n")
        return
    
    while True:
        show_menu()
        
        choice = input("Enter choice (1-7): ").strip()
        
        if choice == "1":
            test_single_listen(detector, timeout=15)
        
        elif choice == "2":
            test_threshold_tuning(detector)
        
        elif choice == "3":
            num = input("\nHow many attempts? (default 3): ").strip()
            num = int(num) if num.isdigit() else 3
            test_multiple_attempts(detector, num_tests=num)
        
        elif choice == "4":
            duration = input("\nTest duration in seconds? (default 5): ").strip()
            duration = int(duration) if duration.isdigit() else 5
            test_noise_floor(detector, duration=duration)
        
        elif choice == "5":
            test_available_models()
        
        elif choice == "6":
            print_section("🚀 Running Full Test Suite")
            
            # Part 1: Single test
            print("\nPart 1: Single Listen Test")
            test_single_listen(detector, timeout=10)
            input("\nPress Enter to continue...")
            
            # Part 2: Noise floor
            print("\nPart 2: Noise Floor Test")
            test_noise_floor(detector, duration=5)
            input("\nPress Enter to continue...")
            
            # Part 3: Multiple attempts
            print("\nPart 3: Multiple Attempts (3 tries)")
            test_multiple_attempts(detector, num_tests=3)
            input("\nPress Enter to continue...")
            
            # Part 4: Threshold tuning
            print("\nPart 4: Threshold Tuning")
            test_threshold_tuning(detector)
            
            print_section("✅ Full Test Suite Complete")
        
        elif choice == "7":
            print("\n👋 Exiting...\n")
            break
        
        else:
            print("❌ Invalid choice. Please enter 1-7.\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Test interrupted by user.\n")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)
