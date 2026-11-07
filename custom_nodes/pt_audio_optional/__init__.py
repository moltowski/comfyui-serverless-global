"""
PT_LoadAudioOptional - loader audio "by path" tolerant au vide.

- chemin vide/absent -> None (pas de ref audio ; H3 genere la voix depuis le prompt)
- chemin present -> AUDIO {waveform:[1,1,T] mono, sample_rate}
Chargement fiable via soundfile (WAV/FLAC/OGG). torchaudio est evite (backend
torchcodec casse dans ce venv). Fallback PyAV (deinterleave correct) pour MP4/M4A.
Downmix mono : une reference de timbre de voix n'a pas besoin de stereo.
"""
import os

def _to_audio(wav, sr):
    import torch
    if wav.dim() == 1:
        wav = wav.unsqueeze(0)          # [T] -> [1, T]
    if wav.dim() == 2 and wav.shape[0] > 1:
        wav = wav.mean(0, keepdim=True)  # downmix -> mono [1, T]
    return {"waveform": wav.unsqueeze(0).contiguous().float(), "sample_rate": int(sr)}  # [1,1,T]

def _load_soundfile(path):
    import soundfile as sf, torch
    data, sr = sf.read(path, dtype="float32", always_2d=True)  # [T, C]
    return _to_audio(torch.from_numpy(data.T), sr)              # [C, T]

def _load_pyav(path):
    import av, numpy as np, torch
    c = av.open(path)
    s = next(x for x in c.streams if x.type == "audio")
    ch = s.channels or 1
    chunks = []
    for fr in c.decode(s):
        chunks.append(fr.to_ndarray())   # packed: [1, C*n] ; planar: [C, n]
    c.close()
    raw = np.concatenate(chunks, axis=1)
    if raw.shape[0] == 1 and ch > 1:     # packed interleaved -> deinterleave
        raw = raw.reshape(-1, ch).T      # [C, n]
    wav = torch.from_numpy(np.ascontiguousarray(raw)).float()
    if wav.abs().max() > 1.5:            # PCM int -> normalise
        wav = wav / 32768.0
    sr = int(s.codec_context.sample_rate or s.rate or 16000)
    return _to_audio(wav, sr)

class PT_LoadAudioOptional:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"audio_path": ("STRING", {"default": ""})}}

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "load"
    CATEGORY = "project_types"

    def load(self, audio_path):
        p = (audio_path or "").strip()
        if not p or not os.path.isfile(p):
            print("[PT_LoadAudioOptional] chemin vide/absent -> None:", repr(p))
            return (None,)
        try:
            a = _load_soundfile(p)
        except Exception as e:
            print("[PT_LoadAudioOptional] soundfile echoue (%s), fallback PyAV" % e)
            a = _load_pyav(p)
        print("[PT_LoadAudioOptional] loaded %s -> waveform %s sr=%s" % (
            os.path.basename(p), tuple(a["waveform"].shape), a["sample_rate"]))
        return (a,)

    @classmethod
    def IS_CHANGED(cls, audio_path):
        p = (audio_path or "").strip()
        try:
            return str(os.path.getmtime(p)) if p and os.path.isfile(p) else "empty"
        except Exception:
            return "empty"

NODE_CLASS_MAPPINGS = {"PT_LoadAudioOptional": PT_LoadAudioOptional}
NODE_DISPLAY_NAME_MAPPINGS = {"PT_LoadAudioOptional": "PT Load Audio (optional / hub)"}
