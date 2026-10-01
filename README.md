# YouTube Loop CMS v2.0.0 — Vercel + Windows/RDP

Satu live/video tetap berjalan. Judul berputar mengikuti antrean sampai Pause/Stop. CMS di Vercel mengatur antrean, interval dan perintah; RDP menjalankan YouTube API serta jadwal lokal. Antrean/perintah/status disimpan dalam Supabase. Token YouTube tidak dikirim ke Vercel/Supabase.

Paket ini **siap di-import ke GitHub/Vercel**, belum dipublikasikan ke akun pengguna. Akun Supabase/Vercel, environment variables dan OAuth Google perlu dipasang sendiri melalui akun pengguna. Buka `MULAI_DI_SINI.html` untuk urutan pemasangan.

## Isi

- `cms/`: project Vercel Node.js 22, dashboard responsive tanpa dependency npm tambahan, password login, session cookie, REST API, schema Supabase.
- `rdp/`: agent Windows Python 3.10+, OAuth YouTube, scheduler, journal perintah, sync outbound setiap 15 detik.
- `GENERATE_KEYS.bat`: membuat password/secret acak pada mesin pengguna. Hasilnya jangan di-upload/di-chat.
- `test_integration.py`: pengujian developer HTTP CMS↔RDP, memakai database dan YouTube simulasi.

## Pemasangan singkat

1. Buat project Supabase khusus tool ini. SQL Editor → jalankan seluruh `cms/supabase.sql` sekali. Bisa diulang tanpa menghapus data.
2. Salin Project URL dan **secret key** `sb_secret_...` dari Supabase Settings → API Keys. Simpan hanya sebagai environment variable backend.
3. Upload isi folder `cms` ke root repository GitHub baru. Atau upload seluruh paket lalu gunakan **Root Directory = cms** di Vercel.
4. Vercel → Import repository → Framework **Other**, Node.js **22.x**. Output Directory **public** (juga sudah ada di vercel.json); tidak perlu build command.
5. Isi 6 Environment Variables untuk Production, lalu deploy/redeploy:

| Nama | Isi |
|---|---|
| `SUPABASE_URL` | Project URL Supabase |
| `SUPABASE_SECRET_KEY` | Secret key `sb_secret_...`; backend saja |
| `CMS_PASSWORD` | Password pribadi minimal 12 karakter |
| `SESSION_SECRET` | Secret acak minimal 32 karakter |
| `AGENT_KEY` | Secret acak berbeda, minimal 32 karakter |
| `CMS_PUBLIC_URL` | Origin production final, misalnya `https://nama.vercel.app` |

Gunakan `GENERATE_KEYS.bat` jika ingin membuat 3 nilai acak. Saat deployment pertama URL final belum ada, tentukan nama project/production URL dari Vercel; sesudah deploy periksa URL tersebut dan perbarui `CMS_PUBLIC_URL` lalu redeploy bila berbeda. Login ditolak jika domain yang dibuka tidak cocok.

Backend juga menerima `SUPABASE_SERVICE_ROLE_KEY` legacy sebagai fallback, tetapi secret key baru direkomendasikan. Key baru dikirim melalui header `apikey`; legacy JWT menggunakan `apikey` + Bearer. Anon/publishable key tidak cocok untuk backend ini. **Jangan memakai prefix NEXT_PUBLIC untuk secret.**

6. Tutup versi RDP v1 lewat Pengaturan → Tutup program. Extract `rdp` v2 ke folder tetap di Windows RDP, lalu `START.bat`. Jangan menjalankan v1 dan v2 bersamaan.
7. Di dashboard lokal RDP: Pengaturan → import OAuth JSON **Desktop app** → Hubungkan YouTube → buka link consent Google di browser RDP. Pilih channel yang benar. Token v1 dapat digunakan lagi jika memakai user Windows yang sama karena data berada di `%LOCALAPPDATA%\YouTubeTitleLoop`.
8. Pengaturan RDP → Hubungkan CMS: masukkan URL production yang sama dan `AGENT_KEY` yang sama dengan Vercel. Klik Hubungkan CMS. Pairing menjeda loop; antrean selanjutnya dikontrol dari CMS.
9. Buka CMS dari HP/PC, login memakai `CMS_PASSWORD`, tunggu **RDP ONLINE**, lalu Refresh live. Pilih live → isi judul/interval → Simpan antrean → tunggu **Selesai** → Start Loop.

Tidak perlu mengatur Cron Vercel atau membuka port RDP. Pola hybrid menghindari kebutuhan cron beberapa kali sehari; tetap tunduk pada kuota/biaya penggunaan Vercel, Supabase dan YouTube. Tidak menjamin seluruh layanan gratis selamanya.

## YouTube / RDP

Google Cloud: aktifkan YouTube Data API v3; Google Auth Platform → Branding/Audience, tambah Gmail sebagai Test user saat Testing; Data Access scope `https://www.googleapis.com/auth/youtube.force-ssl`; Clients → **Desktop app** → download JSON. API key atau Web application tidak dipakai. Login hanya di browser Windows RDP.

External Testing dengan scope YouTube mengeluarkan refresh token yang umumnya kedaluwarsa setelah 7 hari. Untuk pemakaian lama, periksa opsi In production dan persyaratan verifikasi Google; tetap tangani token yang dicabut/kedaluwarsa dengan Hubungkan ulang. Jangan menjanjikan koneksi abadi tanpa reauth.

Jalankan video melalui encoder seperti biasa. Tool tidak menyalakan OBS/FFmpeg, tidak mengganti file video dan tidak mengirim RTMP. **Stop Live mengakhiri sesi YouTube**, tidak menutup encoder. Sesi yang selesai tidak bisa dipakai lagi sebagai live yang sama.

`RUN_BACKGROUND.vbs` menjalankan agent tanpa CMD. Dashboard lokal/CMS boleh ditutup. Autostart di dashboard lokal berlaku saat user Windows login, bukan sebelum login. RDP disconnect boleh jika provider membiarkan sesi berjalan; Sign out, reboot, sleep, maintenance atau session timeout dapat menghentikan agent dan video. Tool tidak memulai encoder sesudah reboot.

## Perilaku dan status

- Antrean baru: Start Loop langsung memakai judul pertama. Setelah interval, judul berikutnya; setelah terakhir kembali awal.
- Pause: pergantian judul berhenti, video tetap live. Resume mempertahankan judul saat itu dan menghitung ulang satu interval.
- Ganti sekarang: maju satu judul; tetap pada mode running/paused semula.
- Reset: hanya saat pause; Start berikutnya memakai judul pertama.
- Perintah CMS: **Menunggu RDP → Dikirim ke RDP → Selesai / Gagal**. "Tersimpan" berarti belum tentu sudah dieksekusi. Sync normal 15 detik; API/koneksi yang lambat bisa menambah waktu.
- Heartbeat dianggap online jika diterima dalam 60 detik. Offline bukan bukti video mati; status CMS adalah snapshot terakhir.
- Saat CMS/internet sync terputus, loop RDP tetap memakai jadwal terakhir jika YouTube masih terjangkau. Pause CMS baru berlaku saat diterima RDP. Untuk darurat di RDP: Pengaturan → **Putus CMS + pause**.
- Start/Next/Reset/Stop memerlukan heartbeat fresh. Start/Next/Reset kedaluwarsa jika belum diterima selama 15 menit; Stop setelah 2 menit. Configure/Pause tidak kedaluwarsa. Perintah yang sudah diterima dipulihkan dari journal, bukan dibuang hanya karena TTL lewat.
- Pause/Stop membatalkan Start/Next/Reset yang masih pending; perintah yang sedang dikerjakan dapat selesai dulu lalu pause diproses.
- Retry koneksi API YouTube: 30/60/120 detik lalu pause. Antrean tidak maju ketika update gagal. Intent dan receipt disimpan bersama state; replay perintah yang telah selesai tidak memajukan judul lagi.
- Judul/deskripsi/tag/kategori/bahasa dibaca sebelum update. Privacy/status/thumbnail tidak ditulis. Jangan mengedit snippet di Studio tepat bersamaan dengan tool. Localizations judul bahasa lain tidak diubah.

## Login, pairing dan perlindungan

- CMS memakai password owner tunggal; session HttpOnly + SameSite Strict + Secure pada HTTPS, expiry 12 jam. POST memakai pemeriksaan Origin dan CSRF token. Ganti password/session secret di Vercel + redeploy untuk membatalkan sesi lama.
- Login dibatasi 8 percobaan per IP per 15 menit, disimpan di database. Fitur ini bukan pengganti perlindungan jaringan/provider bila serangan berskala besar.
- Agent memakai key berbeda dari password. API database memakai server-only secret, RLS aktif dan anon/authenticated tidak punya akses tabel/RPC.
- Windows menyimpan OAuth dan agent key memakai DPAPI untuk user Windows yang menjalankannya. Jangan upload folder data Windows atau file credentials.
- Satu agent installation ID dipasangkan ke CMS; agent lain ditolak. Tidak ada takeover otomatis saat heartbeat hilang, supaya RDP yang sekadar kehilangan koneksi tidak bentrok dengan mesin baru.
- Pindah RDP: pause/putus agent lama terlebih dahulu, lalu reset `agent_id` di Supabase (lihat instruksi di panduan HTML), baru pair mesin baru. Jangan mereset pairing saat mesin lama masih streaming loop tanpa kontrol.
- Bila Production dilindungi Vercel Authentication sehingga agent menerima 401/redirect, sesuaikan metode akses machine resmi yang diizinkan akun Vercel. Jangan menaruh bypass secret di URL/chat. Paket default mengasumsikan domain production bisa mencapai API dengan auth aplikasi; tidak otomatis mengubah proteksi Vercel.

## Demo dan test developer

Untuk demo lokal tanpa akun/DB: Node.js 22 → dari `cms`, `node dev.mjs --demo`; buka http://127.0.0.1:3000. Password **demo-title-loop**. Jalankan `rdp/DEMO.bat`, lalu pair ke URL demo itu dengan key **demo-agent-key-012345678901234567890**. HTTP localhost hanya diizinkan dalam mode demo. Nilai demo jangan dipakai untuk production. DemoStore berada pada dev server saja; API production selalu menggunakan Supabase.

Tes:

```sh
# Dari cms
npm test
# Dari rdp
python -m unittest discover -s tests -v
# Dari root paket, memerlukan Node dan Python
python test_integration.py
```

Saat build: 43 tes Python + 9 tes Node + 1 pengujian integrasi HTTP lulus. Integrasi memakai YouTube/DB simulasi. **Belum diuji pada akun Vercel/Supabase/YouTube pengguna**, SQL migration belum dijalankan pada PostgreSQL live, dan DPAPI/launcher/autostart Windows perlu diuji di RDP. Browser visual test terhalang akses localhost dari browser build; layout belum diverifikasi secara visual. Detail tersedia di VALIDASI.md.

## Sumber resmi

- https://vercel.com/docs/functions/runtimes/node-js
- https://supabase.com/docs/guides/getting-started/api-keys
- https://supabase.com/docs/guides/database/functions
- https://developers.google.com/youtube/v3/docs/videos/update
- https://developers.google.com/identity/protocols/oauth2/native-app
- https://developers.google.com/identity/protocols/oauth2#expiration
