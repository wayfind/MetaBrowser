# Synthetic codec fixtures

These files contain generated test patterns only, no downloaded media or user
recordings. `gpu_media_runner.py` serves them on loopback in an SDK-free browser.

Reproduce with FFmpeg:

```sh
ffmpeg -f lavfi -i 'testsrc2=size=160x96:rate=10:duration=1' -an \
  -c:v libx264 -pix_fmt yuv420p -profile:v baseline -level 3.0 \
  -movflags +frag_keyframe+empty_moov+default_base_moof media-avc-fragmented.mp4
ffmpeg -f lavfi -i 'sine=frequency=440:sample_rate=48000:duration=1' \
  -c:a aac -b:a 64k media-aac.m4a
ffmpeg -f lavfi -i 'testsrc2=size=160x96:rate=10:duration=1' -an \
  -c:v libx264 -pix_fmt yuv420p -profile:v baseline -level 3.0 -g 1 \
  -encryption_scheme cenc-aes-ctr \
  -encryption_key 00112233445566778899aabbccddeeff \
  -encryption_kid 112233445566778899aabbccddeeff00 \
  -movflags +faststart media-avc-clearkey-source.mp4
python3 fragment_cenc.py media-avc-clearkey-source.mp4 media-avc-clearkey.mp4
```

The fragmented AVC sample exercises MSE append, frame presentation, time
advancement and actual VideoFrame readback. AAC acceptance actually decodes the
M4A and checks sample rate, channel count, duration and nonzero finite PCM.
Support strings alone cannot pass either acceptance case.

The CENC sample uses a public test-only key. The narrow fragment converter moves
the sample encryption data into a movie fragment for Chromium's MSE MP4 parser;
the encrypted samples remain unchanged. FFmpeg can independently decrypt and
decode the resulting fragment. Extended acceptance uses a temporary ClearKey
EME session with identifiers and persistence forbidden, then requires MSE frame
presentation and playback time progression. It makes no license server requests
and does not establish Widevine/FairPlay compatibility.
