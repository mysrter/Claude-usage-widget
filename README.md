# Claude usage widget

Claude Code'un yerel token kullanimini ekranin kosesinde gosteren kucuk masaustu
widget.

## Kullanim

- Baslat: `start.bat` (veya `pythonw widget.pyw`).
- Kapat: sag ustteki x  -  Yenile: dairesel ok (20 sn'de bir otomatik)  -  Tasi: basligi surukle.
- Claude Code ile otomatik acilis -> `~/.claude/settings.json`:

      "hooks": {
        "SessionStart": [
          { "hooks": [ { "type": "command",
            "command": "wscript.exe \"C:\\YOL\\Claude-usage-widget\\launch.vbs\"" } ] }
        ]
      }

  (Yolu kendi konumuna gore duzelt.)

## Kalibrasyon (yuzdeler)

Resmi 5 saatlik / haftalik limit yuzdeleri sunucu tarafindadir ve yerelde yoktur;
bu yuzden widget yuzdeyi senin verdigin gercek degerlere gore (yerel maliyet
uzerinden) hesaplar:

1. Claude Desktop > Settings > Usage'i ac; "Current session" ve "Weekly" yuzdelerine bak.
2. Widget basligindaki dis carki dugmesine bas, bu iki yuzdeyi yaz, Kaydet.
   (Ayni islem terminalden: `calibrate.bat` veya `python calibrate.py 10 8`.)
3. Cubuklar o yuzdelere oturur. Zamanla kayarsa carkla birkac saniyede yeniden kalibre et.

Ayarlar `limits.json`'da tutulur (`limits.example.json`'a bak): pencere suresi,
haftalik sifirlanma gunu/saati ve kalibrasyon tavanlari oradadir.
