# Validasi build v2.0.0

- 43 tes Python lulus: scheduler/wrap, retry/permanent error, pause/resume, recovery, metadata, OAuth PKCE/state/cancel, local API; ditambah remote receipt/replay, crash setelah update sebelum ack, single-title queue, binding validation, secret stripping, mismatch live dan emergency unpair.
- 9 tes Node lulus: session signature/expiry/password rotation, config/title validation, status whitelist, command delivery/ack/cancel/TTL, pairing conflict, HTTP login/CSRF/agent auth/rate limit.
- 1 tes integrasi HTTP lulus: CMS nyata pada local Node → Bridge RDP nyata → YouTube simulasi; pairing/heartbeat, configure, start, next/wrap, duplikat request, pause/cancel, restart/replay, stop/ack. Supabase diganti DemoStore dalam tes ini.
- JavaScript syntax dan Python compile checks dijalankan; kontrak HTML/JS memeriksa elemen yang dirujuk ada dan ID tidak duplikat.

Belum diverifikasi: deployment akun Vercel pengguna, SQL migration pada PostgreSQL/Supabase live, OAuth/YouTube live asli, launcher/autostart/DPAPI Windows, tampilan/interaksi browser. Chromium lokal tidak tersedia; cloud browser menolak akses localhost (`ERR_BLOCKED_BY_CLIENT`). Tidak diklaim sebagai pengujian visual lulus.

Tes mock tidak membuktikan migration SQL sukses atau quota/token pengguna valid. Pasang database dan lakukan test pada live pribadi/unlisted pengguna setelah setup sesuai panduan.

Paket tidak memuat token YouTube, database key, password, atau Agent key production. Nilai demo hanya ada pada dev server/demo docs dan tidak digunakan oleh production handler.
