import speech_recognition as sr
import openai
import time

# Set your OpenAI API key
openai.api_key = "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"

# Wake word
WAKE_WORD = "hey pi"

def transcribe_with_openai(audio_file_path):
    print("🧠 Transcribing with OpenAI...")
    with open(audio_file_path, "rb") as audio_file:
        result = openai.Audio.transcribe("whisper-1", audio_file)
    return result["text"]

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
        print(f"API Error: {e}")
        return False

def listen_and_save(recognizer, mic, filename="command.wav"):
    print("🎤 Listening for your command (speak now)...")
    with mic as source:
        audio = recognizer.listen(source, timeout=5, phrase_time_limit=15)
    with open(filename, "wb") as f:
        f.write(audio.get_wav_data())
    return filename

def main():
    recognizer = sr.Recognizer()
    mic = sr.Microphone(device_index=1)  # change index if needed

    while True:
        try:
            if listen_for_wake_word(recognizer, mic):
                print("🎉 Wake word detected!")
                audio_path = listen_and_save(recognizer, mic)
                text = transcribe_with_openai(audio_path)
                print(f"✅ You said: {text}")
                print("-" * 50)
            else:
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("👋 Exiting.")
            break

if __name__ == "__main__":
    main()
