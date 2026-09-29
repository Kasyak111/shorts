"""
Video Processor for Shorts, TikTok, and Reels.
Transforms widescreen movie clips into vertical 9:16 (1080x1920) videos
with dynamic blurred background, centered crisp original video, normalized audio,
and overlays official moving/animated video banners (FunPay / PlayerOk) with native alpha.
"""

import os
import sys
import subprocess
import shutil
from typing import Optional, Union

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

def parse_time_to_seconds(time_val: Union[str, int, float]) -> float:
    """Parses 'HH:MM:SS', 'MM:SS', or seconds into float seconds."""
    if isinstance(time_val, (int, float)):
        return float(time_val)
    parts = str(time_val).strip().replace(",", ".").split(":")
    if len(parts) == 1:
        return float(parts[0])
    elif len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    elif len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    raise ValueError(f"Invalid time format: {time_val}")

class VideoProcessor:
    def __init__(self, ffmpeg_bin: str = "ffmpeg"):
        self.ffmpeg_bin = ffmpeg_bin
        if not shutil.which(ffmpeg_bin):
            raise FileNotFoundError(f"FFmpeg binary '{ffmpeg_bin}' was not found in PATH.")

    def get_video_dimensions(self, video_path: str) -> tuple[int, int]:
        """Returns (width, height) of the video using ffprobe."""
        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=s=x:p=0",
                video_path
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            parts = res.stdout.strip().split("x")
            return int(parts[0]), int(parts[1])
        except Exception:
            return 1920, 1080

    def render_vertical_clip(
        self,
        input_video: str,
        output_video: str,
        overlay_video: Optional[str] = None,
        overlay_png: Optional[str] = None,
        start_time: Optional[Union[str, float]] = None,
        end_time: Optional[Union[str, float]] = None,
        duration: Optional[Union[str, float]] = None,
        subtitles_ass_path: Optional[str] = None,
        normalize_audio: bool = True,
        use_hardware_accel: bool = False,
    ) -> bool:
        """
        Renders a movie clip into vertical 9:16 format with blurred background,
        clean single-line subtitles, and animated moving sponsor banner.
        """
        if not os.path.exists(input_video):
            raise FileNotFoundError(f"Input video not found: {input_video}")

        os.makedirs(os.path.dirname(os.path.abspath(output_video)), exist_ok=True)

        cmd = [self.ffmpeg_bin, "-y"]

        # Fast seek before input
        if start_time is not None:
            s_sec = parse_time_to_seconds(start_time)
            cmd.extend(["-ss", f"{s_sec:.3f}"])

        if duration is not None:
            d_sec = parse_time_to_seconds(duration)
            cmd.extend(["-t", f"{d_sec:.3f}"])
        elif end_time is not None and start_time is not None:
            s_sec = parse_time_to_seconds(start_time)
            e_sec = parse_time_to_seconds(end_time)
            d_sec = max(0.1, e_sec - s_sec)
            cmd.extend(["-t", f"{d_sec:.3f}"])

        # Input 0: movie video
        cmd.extend(["-i", input_video])

        has_overlay_vid = overlay_video is not None and os.path.exists(overlay_video)
        has_overlay_png = overlay_png is not None and os.path.exists(overlay_png) and not has_overlay_vid

        # Input 1: Moving Video Banner (looped)
        if has_overlay_vid:
            cmd.extend(["-stream_loop", "-1", "-i", overlay_video])
        elif has_overlay_png:
            cmd.extend(["-i", overlay_png])

        # Filter Graph:
        # 1. If input is vertical (competitor short), crop the central 16:9 movie area to remove competitor titles/banners!
        # 2. Split video into background (vbg) and foreground (vmain)
        # 3. Scale & crop background to 1080x1920, apply boxblur and slight darkening
        # 4. Scale main video to 1080 width with even height (scale=1080:-2)
        # 5. Center main video over blurred background
        in_w, in_h = self.get_video_dimensions(input_video)
        is_vertical_input = in_h > in_w

        if is_vertical_input:
            crop_h = int(in_w * 9 / 16)
            crop_y = int((in_h - crop_h) / 2)
            filter_parts = [
                f"[0:v]crop={in_w}:{crop_h}:0:{crop_y},split=2[vbg][vmain]",
                "[vbg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=26:3,eq=brightness=-0.16:contrast=0.92[bg]",
                "[vmain]scale=1080:-2[fg]",
                "[bg][fg]overlay=(W-w)/2:(H-h)/2[composite]"
            ]
        else:
            filter_parts = [
                "[0:v]split=2[vbg][vmain]",
                "[vbg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=26:3,eq=brightness=-0.16:contrast=0.92[bg]",
                "[vmain]scale=1080:-2[fg]",
                "[bg][fg]overlay=(W-w)/2:(H-h)/2[composite]"
            ]

        curr_label = "[composite]"
        if subtitles_ass_path and os.path.exists(subtitles_ass_path):
            clean_sub_path = subtitles_ass_path.replace("\\", "/").replace(":", "\\:")
            filter_parts.append(f"{curr_label}ass='{clean_sub_path}'[with_subs]")
            curr_label = "[with_subs]"

        if has_overlay_vid:
            # Scale banner appropriately for mobile safe zone, lifted directly below the movie frame
            banner_low = overlay_video.lower()
            if "instagram" in banner_low:
                # Instagram Reels comic splash banner: crop top/bottom empty padding and scale neatly
                filter_parts.append("[1:v]crop=2000:1200:0:320,scale=720:-1[bscale]")
                b_y = 1270
            elif "tiktok" in banner_low:
                filter_parts.append("[1:v]scale=920:-1[bscale]")
                b_y = 1270
            elif "funpay" in banner_low:
                filter_parts.append("[1:v]scale=920:-1[bscale]")
                b_y = 1270
            else:
                filter_parts.append("[1:v]scale=920:-1[bscale]")
                b_y = 1270

            filter_parts.append(f"{curr_label}[bscale]overlay=(W-w)/2:{b_y}:shortest=1[vfinal]")
            final_v_label = "[vfinal]"
        elif has_overlay_png:
            filter_parts.append(f"{curr_label}[1:v]overlay=0:0[vfinal]")
            final_v_label = "[vfinal]"
        else:
            final_v_label = curr_label

        filter_complex = ";".join(filter_parts)
        cmd.extend(["-filter_complex", filter_complex])
        cmd.extend(["-map", final_v_label])

        # Audio processing
        if normalize_audio:
            cmd.extend(["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"])
        
        cmd.extend(["-map", "0:a?"])

        cmd_base = list(cmd)
        effective_hw_accel = use_hardware_accel and (sys.platform == "win32")
        if use_hardware_accel and sys.platform != "win32":
            print("ℹ️ Hardware acceleration 'h264_mf' is Windows-only; falling back to CPU 'libx264'.")

        def _assemble_cmd(hw: bool) -> list:
            c = list(cmd_base)
            if hw:
                c.extend(["-c:v", "h264_mf", "-b:v", "4500k"])
            else:
                c.extend([
                    "-c:v", "libx264",
                    "-preset", "ultrafast",
                    "-crf", "21",
                    "-maxrate", "5000k",
                    "-bufsize", "10000k",
                    "-pix_fmt", "yuv420p"
                ])
            c.extend([
                "-c:a", "aac",
                "-b:a", "192k",
                "-ar", "44100",
                "-movflags", "+faststart",
                output_video
            ])
            return c

        print(f"🎬 Processing vertical clip: {os.path.basename(output_video)}...")
        exec_cmd = _assemble_cmd(effective_hw_accel)
        res = subprocess.run(exec_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0 and effective_hw_accel:
            print(f"⚠️ Hardware encoder h264_mf failed; retrying with libx264 fallback...")
            fallback_cmd = _assemble_cmd(False)
            res = subprocess.run(fallback_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        if res.returncode != 0:
            print(f"FFmpeg error:\n{res.stderr}")
            return False

        print(f"✅ Rendered successfully: {output_video}")
        return True
