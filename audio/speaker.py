import pyttsx3
import threading

engine = pyttsx3.init()
_SPEAKING_EVENT = threading.Event()


def is_speaking():

    return _SPEAKING_EVENT.is_set()

def speak(text):

    _SPEAKING_EVENT.set()

    try:
        engine.say(text)
        engine.runAndWait()
    finally:
        _SPEAKING_EVENT.clear()