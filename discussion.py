#!/usr/bin/env python3

import openai
import speech_recognition as sr
import pyttsx3
import time
import os
import subprocess

# Your OpenAI key
openai.api_key = "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"
client = openai.OpenAI(api_key="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")

# Wake word
WAKE_WORD = "hello"

# Speaker device (replace with your actual USB speaker device string from `aplay -L`)
USB_SPEAKER_DEVICE = "plughw:CARD=UACDemoV10,DEV=0"


# Use pyttsx3 with espeak engine and USB speaker via ALSA
def speak(text):
    print(f"🗣️ Speaking: {text}")
    command = f'espeak "{text}" --stdout | aplay -D {USB_SPEAKER_DEVICE}'
    subprocess.run(command, shell=True)

#def transcribe_audio(filename):
#    print("🧠 Transcribing...")
#    with open(filename, 'rb') as audio_file:
#        result = openai.Audio.transcribe("whisper-1", audio_file)
#    return result["text"]

def transcribe_audio(filename):
    with open(filename, "rb") as f:
        transcription = client.audio.transcriptions.create(
            model="whisper-1",
            file=f
        )
    return transcription.text

def chat_with_gpt(prompt):
    print("🤖 ChatGPT responding...")
    response = client.chat.completions.create(
        model="gpt-4",  # Or gpt-3.5-turbo
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content.strip()

def listen_for_wake_word(recognizer, mic):
    print("👂 Listening for wake word...")
    with mic as source:
        recognizer.adjust_for_ambient_noise(source)
        audio = recognizer.listen(source, phrase_time_limit=5)
    try:
        text = recognizer.recognize_google(audio).lower()
        print(f"🗣 Heard: {text}")
        return WAKE_WORD in text
    except sr.UnknownValueError:
        return False
    except sr.RequestError as e:
        print(f"Error with recognition: {e}")
        return False

def record_command(recognizer, mic, filename="command.wav"):
    print("🎧 Listening for your command...")
    with mic as source:
        audio = recognizer.listen(source, timeout=5, phrase_time_limit=15)
    with open(filename, "wb") as f:
        f.write(audio.get_wav_data())
    return filename

def main():
    recognizer = sr.Recognizer()
    mic = sr.Microphone(device_index=1)  # Replace with your mic index

    while True:
        try:
            if listen_for_wake_word(recognizer, mic):
                speak("I'm listening.")
                audio_path = record_command(recognizer, mic)
                user_text = transcribe_audio(audio_path)
                print(f"📜 You said: {user_text}")
                response = chat_with_gpt(user_text)
                print(f"💬 ChatGPT: {response}")
                speak(response)
            time.sleep(0.5)
        except KeyboardInterrupt:
            print("\n👋 Exiting.")
            break
        except Exception as e:
            print(f"❌ Error: {e}")
            speak("Sorry, something went wrong.")

if __name__ == "__main__":
    main()
