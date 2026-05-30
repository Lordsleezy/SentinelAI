"""
Wake Word Detection — "Hey Sentinel"
Uses openWakeWord for always-listening wake word detection
"""
import os
import sys
import time
import threading
import logging
from datetime import datetime
from typing import Optional, Callable

logger = logging.getLogger(__name__)

# Check for dependencies
try:
    import openwakeword
    from openwakeword.model import Model
    OPENWAKEWORD_AVAILABLE = True
except ImportError:
    OPENWAKEWORD_AVAILABLE = False
    logger.warning("openwakeword not installed - wake word detection disabled")

try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False
    logger.warning("pyaudio not installed - wake word detection disabled")

try:
    import speech_recognition as sr
    SR_AVAILABLE = True
except ImportError:
    SR_AVAILABLE = False
    logger.warning("speech_recognition not installed - STT disabled")

# Try to import whisper for local STT
try:
    import whisper
    WHISPER_AVAILABLE = True
    logger.info("Whisper available for local STT")
except ImportError:
    WHISPER_AVAILABLE = False
    logger.info("Whisper not available - will use Google STT fallback")


class WakeWordDetector:
    """Always-listening wake word detector for 'hey sentinel'"""

    def __init__(self, callback: Optional[Callable] = None):
        self.callback = callback
        self.running = False
        self.muted = False
        self.thread = None
        self.model = None
        self.audio = None
        self.stream = None

        # Audio settings
        self.chunk_size = 1280  # openwakeword default
        self.sample_rate = 16000
        self.channels = 1

        # STT settings
        self.listening_window_seconds = 6
        self.whisper_model = None

    def initialize(self) -> bool:
        """Initialize wake word model and audio stream"""
        if not OPENWAKEWORD_AVAILABLE or not PYAUDIO_AVAILABLE:
            logger.error("Cannot initialize wake word detector - missing dependencies")
            return False

        try:
            # Initialize openWakeWord model
            self.model = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
            logger.info("Wake word model loaded (using 'hey_jarvis' as proxy for 'hey sentinel')")

            # Initialize PyAudio
            self.audio = pyaudio.PyAudio()

            # Initialize Whisper if available
            if WHISPER_AVAILABLE:
                try:
                    self.whisper_model = whisper.load_model("base.en")
                    logger.info("Whisper model loaded for local STT")
                except Exception as e:
                    logger.warning(f"Failed to load Whisper model: {e}")
                    self.whisper_model = None

            return True

        except Exception as e:
            logger.exception(f"Failed to initialize wake word detector: {e}")
            return False

    def start(self):
        """Start the wake word detection thread"""
        if not OPENWAKEWORD_AVAILABLE or not PYAUDIO_AVAILABLE:
            logger.warning("Wake word detector not available - skipping")
            return

        if self.running:
            logger.warning("Wake word detector already running")
            return

        if not self.initialize():
            logger.error("Failed to initialize wake word detector")
            return

        self.running = True
        self.thread = threading.Thread(target=self._detection_loop, daemon=True)
        self.thread.start()
        logger.info("Wake word detector started")

    def stop(self):
        """Stop the wake word detection thread"""
        self.running = False

        if self.stream:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except:
                pass

        if self.audio:
            try:
                self.audio.terminate()
            except:
                pass

        if self.thread:
            self.thread.join(timeout=2.0)

        logger.info("Wake word detector stopped")

    def mute(self):
        """Mute wake word detection"""
        self.muted = True
        logger.info("Wake word detector muted")

    def unmute(self):
        """Unmute wake word detection"""
        self.muted = False
        logger.info("Wake word detector unmuted")

    def _detection_loop(self):
        """Main detection loop - runs in background thread"""
        try:
            # Open audio stream
            self.stream = self.audio.open(
                format=pyaudio.paInt16,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                frames_per_buffer=self.chunk_size
            )

            logger.info("Listening for wake word 'hey sentinel'...")

            while self.running:
                if self.muted:
                    time.sleep(0.1)
                    continue

                try:
                    # Read audio chunk
                    audio_data = self.stream.read(self.chunk_size, exception_on_overflow=False)

                    # Run prediction
                    prediction = self.model.predict(audio_data)

                    # Check if wake word detected (threshold 0.5)
                    for mdl in self.model.prediction_buffer.keys():
                        score = prediction[mdl]
                        if score > 0.5:
                            logger.info(f"Wake word detected! (confidence: {score:.2f})")
                            self._on_wake_word_detected()
                            # Brief pause to avoid double-triggering
                            time.sleep(1.0)
                            break

                except Exception as e:
                    logger.error(f"Error in detection loop: {e}")
                    time.sleep(0.1)

        except Exception as e:
            logger.exception(f"Fatal error in wake word detection loop: {e}")
        finally:
            if self.stream:
                self.stream.stop_stream()
                self.stream.close()

    def _on_wake_word_detected(self):
        """Handle wake word detection"""
        timestamp = datetime.now().isoformat()

        # Fire callback if provided
        if self.callback:
            try:
                self.callback({"detected": True, "timestamp": timestamp})
            except Exception as e:
                logger.error(f"Error in wake word callback: {e}")

        # Start listening for speech
        self._listen_for_speech()

    def _listen_for_speech(self):
        """Listen for speech after wake word detected"""
        if not SR_AVAILABLE:
            logger.warning("speech_recognition not available - cannot transcribe")
            return

        recognizer = sr.Recognizer()

        try:
            with sr.Microphone(sample_rate=self.sample_rate) as source:
                logger.info("Listening for speech...")

                # Adjust for ambient noise briefly
                recognizer.adjust_for_ambient_noise(source, duration=0.5)

                # Listen with timeout
                audio = recognizer.listen(source, timeout=self.listening_window_seconds)

                # Transcribe using Whisper if available, otherwise Google STT
                text = None

                if WHISPER_AVAILABLE and self.whisper_model:
                    try:
                        # Save audio to temp file for Whisper
                        import tempfile
                        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                            temp_path = f.name
                            with open(temp_path, "wb") as audio_file:
                                audio_file.write(audio.get_wav_data())

                        # Transcribe with Whisper
                        result = self.whisper_model.transcribe(temp_path)
                        text = result["text"].strip()

                        # Clean up temp file
                        os.unlink(temp_path)

                        logger.info(f"Transcribed (Whisper): {text}")

                    except Exception as e:
                        logger.error(f"Whisper transcription failed: {e}")

                # Fallback to Google STT
                if not text:
                    try:
                        text = recognizer.recognize_google(audio)
                        logger.info(f"Transcribed (Google): {text}")
                    except sr.UnknownValueError:
                        logger.info("No speech detected")
                        return
                    except sr.RequestError as e:
                        logger.error(f"STT request failed: {e}")
                        return

                # Send transcribed text to chat API
                if text and self.callback:
                    self.callback({
                        "detected": True,
                        "timestamp": datetime.now().isoformat(),
                        "transcription": text
                    })

        except sr.WaitTimeoutError:
            logger.info("No speech detected within timeout window")
        except Exception as e:
            logger.exception(f"Error during speech recognition: {e}")


# Global detector instance
_detector: Optional[WakeWordDetector] = None


def get_detector() -> Optional[WakeWordDetector]:
    """Get the global wake word detector instance"""
    return _detector


def start_detector(callback: Optional[Callable] = None):
    """Start the global wake word detector"""
    global _detector

    if _detector is None:
        _detector = WakeWordDetector(callback=callback)

    _detector.start()


def stop_detector():
    """Stop the global wake word detector"""
    global _detector

    if _detector:
        _detector.stop()


def mute_detector():
    """Mute the wake word detector"""
    global _detector

    if _detector:
        _detector.mute()


def unmute_detector():
    """Unmute the wake word detector"""
    global _detector

    if _detector:
        _detector.unmute()


def get_status() -> dict:
    """Get wake word detector status"""
    if _detector is None:
        return {"listening": False, "muted": False, "available": False}

    return {
        "listening": _detector.running,
        "muted": _detector.muted,
        "available": OPENWAKEWORD_AVAILABLE and PYAUDIO_AVAILABLE
    }
