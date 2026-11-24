# Media Downloader Malaysia

Aplikasi Windows 64-bit untuk memuat turun video daripada pautan yang disokong. Fail `Media Downloader Malaysia.exe` tersedia di bahagian **Releases**.

Tampal pautan, klik **Semak pautan**, pilih pilihan video dan klik **Muat turun**. **Original** pada kadar bingkai mengekalkan masa bingkai video sumber. Pilihan kadar tetap ialah 24, 30, 60 dan 120 fps. Resolusi dan sari kata yang tersedia bergantung pada sumber. Tab **Sejarah** memaparkan hasil muat turun dan tab **Tetapan** menyimpan pilihan lalai.

## Jalankan kod sumber

Keperluan ialah Python 3.12 dengan Tk, Pillow serta `yt-dlp.exe`, `ffmpeg.exe`, `ffprobe.exe` dan `node.exe` dalam PATH. Gunakan binaan rasmi `yt-dlp.exe` kendiri dan letakkan FFmpeg dan FFprobe dalam folder yang sama. FFmpeg perlu menyokong penapis `subtitles` melalui libass.

```powershell
python -m pip install Pillow PyInstaller
python media_downloader.py
python qa_media_downloader.py
.\build.ps1
```

Ujian menggunakan pelayan HTTP setempat. Skrip bina menghasilkan `dist/Media Downloader Malaysia.exe` dengan alat luaran dibundel bersama aplikasi.

## Komponen dibundel

- [yt-dlp 2026.11.23](https://github.com/yt-dlp/yt-dlp/releases/tag/2026.11.23)
- [FFmpeg dan FFprobe 9.0.2 full build untuk Windows](https://www.gyan.dev/ffmpeg/builds/) · [Kod sumber FFmpeg](https://github.com/FFmpeg/FFmpeg/tree/n9.0.2)
- [Node.js v26.13.1](https://github.com/nodejs/node/tree/v26.13.1) · [Lesen](https://github.com/nodejs/node/blob/v26.13.1/LICENSE)
