"""
ElevenLabs Batch TTS — turn a JSON file of scripts into MP3 voiceovers.

The API key is entered in the app at runtime and is never stored on disk.
"""

import json
import os
import re
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk
import requests

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

API_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"   # "Rachel", a public ElevenLabs premade voice
DEFAULT_MODEL_ID = "eleven_multilingual_v2"
MAX_ATTEMPTS = 3
REQUEST_TIMEOUT = 120


def extract_items(data):
    """Accepts a list, or a dict holding a "scripts"/"items" list, or a single object."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("scripts") or data.get("items") or [data]
    return [data]


def item_text_and_id(item, index):
    if isinstance(item, dict):
        text = item.get("text") or item.get("script") or ""
        return str(text), item.get("id", index)
    return str(item), index


def safe_filename(value):
    return re.sub(r"[^A-Za-z0-9_-]+", "_", str(value)).strip("_") or "item"


class ElevenLabsBatchApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("ElevenLabs Batch Audio Generator")
        self.geometry("700x580")
        self.resizable(False, False)

        ctk.CTkLabel(self, text="ElevenLabs Batch Audio Generator",
                     font=ctk.CTkFont(size=20, weight="bold")).pack(pady=(20, 10))

        main = ctk.CTkFrame(self, corner_radius=10)
        main.pack(padx=20, pady=10, fill="both", expand=True)

        # API key
        ctk.CTkLabel(main, text="ElevenLabs API Key:", font=ctk.CTkFont(size=12)).pack(
            anchor="w", padx=20, pady=(15, 0))
        self.api_entry = ctk.CTkEntry(main, placeholder_text="Enter your ElevenLabs API key", show="*")
        self.api_entry.pack(fill="x", padx=20, pady=(5, 10))

        # Voice ID
        ctk.CTkLabel(main, text="Voice ID:", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=20, pady=(5, 0))
        self.voice_entry = ctk.CTkEntry(main)
        self.voice_entry.insert(0, DEFAULT_VOICE_ID)
        self.voice_entry.pack(fill="x", padx=20, pady=(5, 10))

        # Model ID
        ctk.CTkLabel(main, text="Model ID:", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=20, pady=(5, 0))
        self.model_entry = ctk.CTkEntry(main)
        self.model_entry.insert(0, DEFAULT_MODEL_ID)
        self.model_entry.pack(fill="x", padx=20, pady=(5, 10))

        # JSON file
        ctk.CTkLabel(main, text="Select JSON File:", font=ctk.CTkFont(size=12)).pack(anchor="w", padx=20, pady=(5, 0))
        json_row = ctk.CTkFrame(main, fg_color="transparent")
        json_row.pack(fill="x", padx=20, pady=(5, 10))
        self.json_entry = ctk.CTkEntry(json_row, placeholder_text="No JSON file selected")
        self.json_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        ctk.CTkButton(json_row, text="Browse...", width=100, command=self.browse_json).pack(side="right")

        # Output folder
        ctk.CTkLabel(main, text="Select Output Directory:", font=ctk.CTkFont(size=12)).pack(
            anchor="w", padx=20, pady=(5, 0))
        out_row = ctk.CTkFrame(main, fg_color="transparent")
        out_row.pack(fill="x", padx=20, pady=(5, 10))
        self.out_entry = ctk.CTkEntry(out_row, placeholder_text="No folder selected")
        self.out_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        ctk.CTkButton(out_row, text="Browse...", width=100, command=self.browse_output).pack(side="right")

        # Progress
        self.status_label = ctk.CTkLabel(main, text="Status: Ready", font=ctk.CTkFont(size=12, weight="bold"))
        self.status_label.pack(anchor="w", padx=20, pady=(10, 0))
        self.progress_bar = ctk.CTkProgressBar(main)
        self.progress_bar.set(0)
        self.progress_bar.pack(fill="x", padx=20, pady=(5, 15))

        self.start_btn = ctk.CTkButton(self, text="START BATCH GENERATION",
                                       font=ctk.CTkFont(size=14, weight="bold"), height=40,
                                       command=self.start_processing_thread)
        self.start_btn.pack(padx=20, pady=(0, 20), fill="x")

    # ---- thread-safe UI helpers (Tk must only be touched from the main thread) ----
    def ui(self, fn, *args, **kwargs):
        self.after(0, lambda: fn(*args, **kwargs))

    def set_status(self, text, progress=None):
        def _apply():
            self.status_label.configure(text=text)
            if progress is not None:
                self.progress_bar.set(progress)
        self.after(0, _apply)

    def browse_json(self):
        filename = filedialog.askopenfilename(filetypes=[("JSON Files", "*.json")])
        if filename:
            self.json_entry.delete(0, tk.END)
            self.json_entry.insert(0, filename)

    def browse_output(self):
        folder = filedialog.askdirectory()
        if folder:
            self.out_entry.delete(0, tk.END)
            self.out_entry.insert(0, folder)

    def start_processing_thread(self):
        api_key = self.api_entry.get().strip()
        voice_id = self.voice_entry.get().strip() or DEFAULT_VOICE_ID
        model_id = self.model_entry.get().strip() or DEFAULT_MODEL_ID
        json_path = self.json_entry.get().strip()
        out_dir = self.out_entry.get().strip()

        if not api_key or not json_path or not out_dir:
            messagebox.showerror("Error", "Please fill in all required fields!")
            return

        self.start_btn.configure(state="disabled")
        self.progress_bar.set(0)
        threading.Thread(target=self.process_batch,
                         args=(api_key, voice_id, model_id, json_path, out_dir),
                         daemon=True).start()

    def process_batch(self, api_key, voice_id, model_id, json_path, out_dir):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                items = extract_items(json.load(f))

            total = len(items)
            if total == 0:
                self.ui(messagebox.showwarning, "Warning", "No scripts found in the JSON file.")
                return

            os.makedirs(out_dir, exist_ok=True)
            url = API_URL.format(voice_id=voice_id)
            headers = {"Accept": "audio/mpeg", "Content-Type": "application/json", "xi-api-key": api_key}
            failed = []

            for idx, item in enumerate(items, 1):
                text, item_id = item_text_and_id(item, idx)
                self.set_status(f"Processing {idx}/{total} (ID: {item_id})...", (idx - 1) / total)

                if not text.strip():
                    failed.append((item_id, "empty text"))
                    continue

                payload = {
                    "text": text,
                    "model_id": model_id,
                    "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
                }
                output_path = os.path.join(out_dir, f"audio_{safe_filename(item_id)}.mp3")
                error = self._synthesize(url, headers, payload, output_path)
                if error:
                    failed.append((item_id, error))
                    if error.startswith("HTTP 401"):
                        break   # invalid key — no point continuing

            done = total - len(failed)
            self.set_status(f"Completed: {done}/{total} files exported.", 1.0)
            if failed:
                details = "\n".join(f"• {i}: {e}" for i, e in failed[:10])
                self.ui(messagebox.showwarning, "Finished with errors",
                        f"{done}/{total} files saved to:\n{out_dir}\n\nFailed:\n{details}")
            else:
                self.ui(messagebox.showinfo, "Success", f"All {total} audio files saved to:\n{out_dir}")

        except Exception as e:
            self.set_status("Status: Error")
            self.ui(messagebox.showerror, "Error", f"An error occurred: {e}")
        finally:
            self.ui(self.start_btn.configure, state="normal")

    @staticmethod
    def _synthesize(url, headers, payload, output_path):
        """Returns None on success, or an error description."""
        error = "unknown error"
        for attempt in range(MAX_ATTEMPTS):
            try:
                response = requests.post(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
            except requests.RequestException as e:
                error = f"network error: {e}"
                time.sleep(2 ** attempt)
                continue

            if response.status_code == 200:
                with open(output_path, "wb") as audio_file:
                    audio_file.write(response.content)
                return None

            error = f"HTTP {response.status_code}: {response.text[:200]}"
            if response.status_code in (401, 403, 422):
                return error                   # not retryable
            time.sleep(2 ** attempt)           # 429 / 5xx: back off and retry
        return error


if __name__ == "__main__":
    ElevenLabsBatchApp().mainloop()
