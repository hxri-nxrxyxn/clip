FROM nvidia/cuda:12.3.2-cudnn9-runtime-ubuntu22.04
WORKDIR /app
RUN apt-get update -y && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*
RUN pip3 install --no-cache-dir \
    faster-whisper==1.2.1 \
    ctranslate2==4.9.0 \
    numpy==2.2.6
COPY whisper_common.py ./whisper_common.py
COPY transcribe.py ./transcribe.py
CMD ["python3", "transcribe.py"]
