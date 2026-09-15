# PCE VGM trim

Python script to trim PC Engine / TG16 VGM and VGZ files down to a specified length given in seconds.

Mainly written to get vgms playing using UzeC6280 on Uzeboxes with limited SPI RAM.

It attempts to retain the GD3 track metadata if present in the source file.

I don't plan to add any other features or support any other APUs but feel free to fork it.

Dan

## Show a PCE VGM or VGZ files duration

 python3 vgm_trim.py Dungeon.vgm

## Trim a VGM or VGZ file

 python3 vgm_trim.py -t 77 Dungeon.vgm

This will trim **Dungeon.vgm** to 77 seconds and output a .vgm file with a **_trimmed.vgm** suffix in the same directory.

## UzeC6280 forum topic

https://uzebox.org/forums/viewtopic.php?t=11877
