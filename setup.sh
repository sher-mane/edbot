#!/bin/bash

sudo apt install portaudio19-dev
pip install pyaudio
pip install openai
pip install pyttsx3

# for whisper via OPENAI Cloud
#pip install requests

#
pip install git+https://github.com/openai/whisper.git
pip install torch  # Requires compatible PyTorch version for your Pi (may need manual install)
