# Full-size files supplied in the GitHub Release

To keep the Git history quick to clone, files at or above 10 MiB are included in the complete Release ZIP but omitted from the browseable Git source view. The full package manifest and checksums in `delivery/` apply to the Release ZIP.

- `results/phase10_confirmation_event_timeline.json` — 43,176,040 bytes; SHA-256 `84cda0b43af637c83c4caa15d20be23047d185cf0e39ec6f86f4a9c55634751a`
- `results/phase10_confirmation_progress.jsonl` — 70,913,639 bytes; SHA-256 `1c13a0c0ac9f96f46bf41b9f78ea00480f17b6e70a447a53e9bb8971e9755f94`
- `results/phase10_confirmation_raw.json` — 152,084,576 bytes; SHA-256 `6c90e943b4e702652337da110837ca7942d598998a91c77464431fdd061f6e2d`
- `results/phase10_development_progress.jsonl` — 10,650,683 bytes; SHA-256 `215c1cfa0d9109b959b0341efd12ba205d7474bece13d739ac4ed074ecb3fb27`
- `results/phase10_development_raw.json` — 22,811,864 bytes; SHA-256 `40c5aff69ce75ddbb65432db7742f44b75ce52ff116dea7803caa1d58fdd1612`
- `results/phase11_confirmation_progress.jsonl` — 174,355,200 bytes; SHA-256 `f71e74b9de1f30ba7c22f24396366af3f2adf299d01f4967a961daf0190c8847`
- `results/phase11_confirmation_raw.json` — 350,308,579 bytes; SHA-256 `1d59d67be873e5a2f63bbf7ff2ff459f88e370237dc41752d0055ef8a4a11b4c`
- `results/phase11_development_progress.jsonl` — 26,305,647 bytes; SHA-256 `72a84304c7d6ff61948bbec3825a0990e68815d65b8cd09fd6b25a2d4dc88eae`
- `results/phase11_development_raw.json` — 52,794,746 bytes; SHA-256 `32c5c19119807bb794e8450bceeba4873dc74f4d2e4c72e23bf280b7900f3fe1`
- `results/phase14_confirmation_raw.json` — 84,454,812 bytes; SHA-256 `954c903d595e1acab4a351fefd63393be37f81ba2df7ab7cbc6ad2767904d211`
- `results/phase14_development_raw.json` — 12,636,025 bytes; SHA-256 `4275cf00d723de0d0fffcae67d6171bae6b5c9b94e12143137df7265f65ad8a4`
- `results/phase8_development_raw.json` — 70,138,040 bytes; SHA-256 `84dbf85df3280f8a5dcf19eacc19cc625fd97e8a997ff5796d2960e2967f2cba`
- `results/phase8_replication_raw.json` — 182,754,761 bytes; SHA-256 `1c8311e81bca28fcc7662037df489bf448d031103f9a25d3f0c4ed7de58ebf62`
- `results/phase8_sensitivity_validation_raw.json` — 317,779,704 bytes; SHA-256 `0ec158db99b78d00843a5d11685349470535fd9bbbc93e4eed70b725b1549888`
- `results/phase8_validation_raw.json` — 90,927,045 bytes; SHA-256 `dad10ed7d68fa6a70199c1e740701de8e42c2d2d39ad804cea59e7fa5588adfc`
- `results/phase9_confirmation_raw.json` — 44,847,901 bytes; SHA-256 `7f30ae206eb016fb0ec0ae50f152df07b39745b9a026a3170218ba7e786e89fd`
- `results/phase9_corrected_confirmation_raw.json` — 53,485,358 bytes; SHA-256 `3ba7bd11dc8303f3efb20a1a220220b6c988f5d8aa9b0437aae651bcd946b4c6`
- `results/phase9_corrected_energy_sensitivity_raw.json` — 50,685,599 bytes; SHA-256 `a0517c92cfb719ffc8f2790a4266b66b320408188511e40436f28e8b9fbbb02a`
- `results/phase9_development_iteration1_raw.json` — 15,924,519 bytes; SHA-256 `a757ab9e5a79c23853f3969df9222271c7ec37f279c36dc9467356a822f86f87`
- `results/phase9_development_pre_route_fix_raw.json` — 15,766,298 bytes; SHA-256 `617f6d23ed721e329cc33cf210bfdea1976bd551a3aa08a2c1defe626d2f04d5`
- `results/phase9_development_raw.json` — 23,760,282 bytes; SHA-256 `f9abac0c99080062878ae053cf95033dba5df01e4dc3eac8979293b0ea6c5fba`

The complete review archive is available from the repository Releases page. No experiment record is removed from the Release package.

## Restoring the complete review archive

Release `v2026.10.22-review` provides the complete `6G-RESCUE-review-package-2026-10-22.zip` as eleven 20 MB-or-smaller parts to support reliable downloads. Download all assets named `6G-RESCUE-review-package-2026-10-22.zip.001` through `.011`, together with `PARTS-MANIFEST.json`, `PARTS-SHA256SUMS.txt`, and `REASSEMBLE.ps1`, into one folder. From that folder run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\REASSEMBLE.ps1
```

The script checks each part and the reconstructed archive before creating the ZIP. Expected archive size: `219738845` bytes. Expected SHA-256: `05f22ea02d4af148febde7c7eafcae9f5658cbbe04678b91f73762396ec2bdb3`.
