"""
Banner Template Generator for Movie Shorts/TikTok/Reels
Generates high-resolution 1080x1920 transparent PNG overlays with platform-specific
banners, hooks, movie codes, and custom sponsors:
- FUNPAY for YouTube Shorts
- PLAYEROK for TikTok and Instagram Reels
Adhering to mobile safe zones.
"""

import os
from typing import Dict, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont

# Default Windows fonts with fallbacks
FONT_BOLD = r"C:\Windows\Fonts\arialbd.ttf"
FONT_REGULAR = r"C:\Windows\Fonts\arial.ttf"
FONT_IMPACT = r"C:\Windows\Fonts\impact.ttf"

class BannerGenerator:
    def __init__(self, width: int = 1080, height: int = 1920):
        self.width = width
        self.height = height

    def _get_font(self, font_path: str, size: int) -> ImageFont.FreeTypeFont:
        try:
            return ImageFont.truetype(font_path, size)
        except Exception:
            return ImageFont.load_default()

    def _wrap_text(self, text: str, font: ImageFont.FreeTypeFont, max_width: int, draw: ImageDraw.ImageDraw) -> list[str]:
        words = text.split()
        if not words:
            return []
        
        lines = []
        current_line = []
        for word in words:
            test_line = " ".join(current_line + [word])
            bbox = draw.textbbox((0, 0), test_line, font=font)
            line_w = bbox[2] - bbox[0]
            if line_w <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(" ".join(current_line))
                    current_line = [word]
                else:
                    lines.append(word)
                    current_line = []
        if current_line:
            lines.append(" ".join(current_line))
        return lines

    def create_banner_overlay(
        self,
        platform: str,
        hook_title: str = "",
        movie_code: str = "",
        cta_text: Optional[str] = None,
        watermark: str = "",
        sponsor_brand: Optional[str] = None, # 'funpay', 'playerok', or None
        custom_banner_img: Optional[str] = None,
    ) -> Image.Image:
        """
        Creates a 1080x1920 RGBA image containing the complete overlay for a platform.
        Supports dedicated FunPay and PlayerOk sponsor branding.
        """
        overlay = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # Auto-assign sponsor only if explicitly specified
        plat_lower = platform.lower()
        if sponsor_brand:
            sponsor_brand = sponsor_brand.lower()
        if sponsor_brand not in ["funpay", "playerok"]:
            sponsor_brand = None

        # Platform-specific presets
        platform_presets = {
            "shorts": {
                "name": "YouTube Shorts",
                "accent_color": (0, 122, 255, 255) if sponsor_brand == "funpay" else (229, 9, 20, 255),
                "badge_bg": (12, 20, 36, 240) if sponsor_brand == "funpay" else (20, 20, 20, 230),
                "badge_border": (0, 170, 255, 245) if sponsor_brand == "funpay" else (229, 9, 20, 240),
                "default_cta": "🎮 FUNPAY: биржа игровых ценностей №1! Ссылка в закрепе 👇" if sponsor_brand == "funpay" else "🎬 ПОДПИШИСЬ НА КАНАЛ  |  ЛУЧШИЕ ФИЛЬМЫ",
                "cta_y": 1420,
                "cta_max_w": 960,
                "tag_badge": "💰 FUNPAY | ПРОВЕРЕНО" if sponsor_brand == "funpay" else "🎬 КИНО",
                "brand": sponsor_brand or "cinema",
            },
            "tiktok": {
                "name": "TikTok",
                "accent_color": (168, 85, 247, 255) if sponsor_brand == "playerok" else (0, 242, 254, 255),
                "badge_bg": (22, 12, 38, 242) if sponsor_brand == "playerok" else (15, 15, 18, 235),
                "badge_border": (236, 72, 153, 240) if sponsor_brand == "playerok" else (254, 44, 85, 240),
                "default_cta": "⚡ PLAYEROK: донат, гемы и робуксы! Ссылка в био 👆" if sponsor_brand == "playerok" else "🎬 ПОДПИШИСЬ  |  СМОТРИ ЛУЧШИЕ МОМЕНТЫ",
                "cta_y": 1390,
                "cta_max_w": 820,
                "tag_badge": "⚡ PLAYEROK | ДОНАТ" if sponsor_brand == "playerok" else "🎬 КИНО",
                "brand": sponsor_brand or "cinema",
            },
            "reels": {
                "name": "Instagram Reels",
                "accent_color": (168, 85, 247, 255) if sponsor_brand == "playerok" else (225, 48, 108, 255),
                "badge_bg": (22, 12, 38, 242) if sponsor_brand == "playerok" else (18, 18, 22, 235),
                "badge_border": (236, 72, 153, 240) if sponsor_brand == "playerok" else (245, 133, 41, 240),
                "default_cta": "⚡ PLAYEROK: донат и скины по скидке! Ссылка в шапке 👆" if sponsor_brand == "playerok" else "🎬 ПОДПИСЫВАЙСЯ  |  КИНО НА ВЕЧЕР",
                "cta_y": 1400,
                "cta_max_w": 840,
                "tag_badge": "⚡ PLAYEROK | ИГРЫ" if sponsor_brand == "playerok" else "🎬 КИНО",
                "brand": sponsor_brand or "cinema",
            },
        }

        conf = platform_presets.get(plat_lower, platform_presets["shorts"])
        active_cta = cta_text if cta_text is not None else conf["default_cta"]

        # 1. DRAW WATERMARK (Top right safe zone)
        if watermark:
            wm_font = self._get_font(FONT_REGULAR, 32)
            wm_text = watermark if watermark.startswith("@") else f"@{watermark}"
            wm_bbox = draw.textbbox((0, 0), wm_text, font=wm_font)
            wm_w = wm_bbox[2] - wm_bbox[0]
            wm_x = self.width - wm_w - 60
            wm_y = 140
            
            pad_x, pad_y = 16, 8
            draw.rounded_rectangle(
                [wm_x - pad_x, wm_y - pad_y, wm_x + wm_w + pad_x, wm_y + (wm_bbox[3] - wm_bbox[1]) + pad_y],
                radius=12,
                fill=(0, 0, 0, 140),
            )
            draw.text((wm_x, wm_y), wm_text, font=wm_font, fill=(255, 255, 255, 200))

        # 2. DRAW TOP HOOK / TITLE BANNER (Y ~ 220 to 460)
        if hook_title:
            font_size = 46 if len(hook_title) > 60 else (52 if len(hook_title) > 30 else 58)
            title_font = self._get_font(FONT_BOLD, font_size)
            max_text_w = 920
            lines = self._wrap_text(hook_title.upper(), title_font, max_text_w, draw)
            
            line_height = int(font_size * 1.25)
            total_text_h = len(lines) * line_height
            
            box_pad_x = 36
            box_pad_y = 28
            box_w = max_text_w + box_pad_x * 2
            box_h = total_text_h + box_pad_y * 2
            
            box_x0 = (self.width - box_w) // 2
            box_y0 = 240
            box_x1 = box_x0 + box_w
            box_y1 = box_y0 + box_h
            
            # Semi-transparent sleek dark background with rounded corners
            draw.rounded_rectangle(
                [box_x0, box_y0, box_x1, box_y1],
                radius=24,
                fill=(12, 12, 16, 225),
                outline=conf["accent_color"],
                width=3,
            )
            
            # Platform / Sponsor tag badge on top border
            tag_font = self._get_font(FONT_BOLD, 22)
            tag_text = conf["tag_badge"]
            tag_bbox = draw.textbbox((0, 0), tag_text, font=tag_font)
            tag_w = tag_bbox[2] - tag_bbox[0]
            tag_h = tag_bbox[3] - tag_bbox[1]
            tag_x0 = box_x0 + 30
            tag_y0 = box_y0 - (tag_h // 2) - 10
            draw.rounded_rectangle(
                [tag_x0 - 14, tag_y0 - 4, tag_x0 + tag_w + 14, tag_y0 + tag_h + 8],
                radius=10,
                fill=conf["accent_color"],
            )
            draw.text((tag_x0, tag_y0), tag_text, font=tag_font, fill=(255, 255, 255, 255))
            
            # Draw hook text
            curr_y = box_y0 + box_pad_y
            for line in lines:
                l_bbox = draw.textbbox((0, 0), line, font=title_font)
                l_w = l_bbox[2] - l_bbox[0]
                l_x = (self.width - l_w) // 2
                draw.text((l_x + 2, curr_y + 2), line, font=title_font, fill=(0, 0, 0, 180))
                draw.text((l_x, curr_y), line, font=title_font, fill=(255, 255, 255, 255))
                curr_y += line_height

        # 3. DRAW MOVIE CODE / TITLE PILL (Y ~ 550 - 610)
        if movie_code:
            code_font = self._get_font(FONT_BOLD, 36)
            code_text = f"🍿 КОД ФИЛЬМА:  {movie_code}"
            c_bbox = draw.textbbox((0, 0), code_text, font=code_font)
            c_w = c_bbox[2] - c_bbox[0]
            c_h = c_bbox[3] - c_bbox[1]
            
            pill_pad_x, pill_pad_y = 28, 14
            pill_w = c_w + pill_pad_x * 2
            pill_h = c_h + pill_pad_y * 2
            pill_x0 = (self.width - pill_w) // 2
            pill_y0 = 550
            
            draw.rounded_rectangle(
                [pill_x0, pill_y0, pill_x0 + pill_w, pill_y0 + pill_h],
                radius=18,
                fill=(255, 180, 0, 240),
                outline=(255, 255, 255, 200),
                width=2,
            )
            draw.text(
                (pill_x0 + pill_pad_x, pill_y0 + pill_pad_y - 2),
                code_text,
                font=code_font,
                fill=(10, 10, 10, 255),
            )

        # 4. DRAW SPONSOR CTA BANNER (FUNPAY / PLAYEROK) IN SAFE ZONE
        # First check if user provided a custom PNG banner in assets/banners/
        user_banner_path = custom_banner_img
        if not user_banner_path or not os.path.exists(user_banner_path):
            banner_candidates = [
                os.path.join("assets", "banners", f"{plat_lower}_{conf['brand']}.png"),
                os.path.join("assets", "banners", f"{conf['brand']}_{plat_lower}.png"),
                os.path.join("assets", "banners", f"{plat_lower}.png"),
                os.path.join("assets", "banners", f"{conf['brand']}.png"),
            ]
            for cand in banner_candidates:
                if os.path.exists(cand):
                    user_banner_path = cand
                    break

        if user_banner_path and os.path.exists(user_banner_path):
            try:
                b_img = Image.open(user_banner_path).convert("RGBA")
                max_w = conf["cta_max_w"]
                if b_img.width > max_w:
                    ratio = max_w / b_img.width
                    b_img = b_img.resize((max_w, int(b_img.height * ratio)), Image.Resampling.LANCZOS)
                
                if plat_lower == "tiktok":
                    b_center_x = 490
                elif plat_lower == "reels":
                    b_center_x = 510
                else:
                    b_center_x = self.width // 2
                    
                b_x0 = b_center_x - (b_img.width // 2)
                b_y0 = conf["cta_y"]
                overlay.paste(b_img, (b_x0, b_y0), b_img)
                print(f"🖼️ Использован пользовательский баннер: {user_banner_path}")
            except Exception as e:
                print(f"Warning: Failed to load custom banner {user_banner_path}: {e}")
        elif active_cta:
            cta_font = self._get_font(FONT_BOLD, 36)
            cta_lines = self._wrap_text(active_cta, cta_font, conf["cta_max_w"] - 60, draw)
            
            c_line_h = 46
            c_total_h = len(cta_lines) * c_line_h
            
            b_pad_x = 34
            b_pad_y = 24
            actual_w = min(
                conf["cta_max_w"],
                max(draw.textbbox((0, 0), l, font=cta_font)[2] - draw.textbbox((0, 0), l, font=cta_font)[0] for l in cta_lines) + b_pad_x * 2
            )
            
            if plat_lower == "tiktok":
                b_center_x = 490
            elif plat_lower == "reels":
                b_center_x = 510
            else:
                b_center_x = self.width // 2
                
            b_x0 = b_center_x - (actual_w // 2)
            b_y0 = conf["cta_y"]
            b_x1 = b_x0 + actual_w
            b_y1 = b_y0 + c_total_h + b_pad_y * 2
            
            # Outer Glow / Double border for sponsor cards
            draw.rounded_rectangle(
                [b_x0 - 2, b_y0 - 2, b_x1 + 2, b_y1 + 2],
                radius=28,
                outline=conf["accent_color"],
                width=2,
            )
            draw.rounded_rectangle(
                [b_x0, b_y0, b_x1, b_y1],
                radius=26,
                fill=conf["badge_bg"],
                outline=conf["badge_border"],
                width=3,
            )

            # Draw small branded sub-badge atop the banner
            sponsor_tag = "💎 FUNPAY.COM" if conf["brand"] == "funpay" else "⚡ PLAYEROK.COM"
            stag_font = self._get_font(FONT_BOLD, 20)
            st_box = draw.textbbox((0, 0), sponsor_tag, font=stag_font)
            st_w = st_box[2] - st_box[0]
            st_h = st_box[3] - st_box[1]
            st_x0 = b_x0 + 26
            st_y0 = b_y0 - (st_h // 2) - 8
            draw.rounded_rectangle(
                [st_x0 - 10, st_y0 - 3, st_x0 + st_w + 10, st_y0 + st_h + 7],
                radius=8,
                fill=conf["accent_color"],
            )
            draw.text((st_x0, st_y0), sponsor_tag, font=stag_font, fill=(255, 255, 255, 255))
            
            # Draw CTA text lines
            c_curr_y = b_y0 + b_pad_y
            for line in cta_lines:
                l_bbox = draw.textbbox((0, 0), line, font=cta_font)
                l_w = l_bbox[2] - l_bbox[0]
                l_x = b_center_x - (l_w // 2)
                draw.text((l_x + 1, c_curr_y + 1), line, font=cta_font, fill=(0, 0, 0, 220))
                draw.text((l_x, c_curr_y), line, font=cta_font, fill=(255, 255, 255, 255))
                c_curr_y += c_line_h

        # 5. CUSTOM PNG BANNER (Optional)
        if custom_banner_img and os.path.exists(custom_banner_img):
            try:
                c_img = Image.open(custom_banner_img).convert("RGBA")
                if c_img.width > 980:
                    ratio = 980 / c_img.width
                    c_img = c_img.resize((980, int(c_img.height * ratio)), Image.Resampling.LANCZOS)
                paste_x = (self.width - c_img.width) // 2
                paste_y = 1620
                overlay.paste(c_img, (paste_x, paste_y), c_img)
            except Exception as e:
                print(f"Warning: Could not overlay custom image {custom_banner_img}: {e}")

        return overlay

    def save_banner_overlay(self, output_path: str, **kwargs) -> str:
        overlay = self.create_banner_overlay(**kwargs)
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        overlay.save(output_path, "PNG")
        return output_path

if __name__ == "__main__":
    generator = BannerGenerator()
    # Test FunPay for Shorts
    generator.save_banner_overlay(
        output_path="test_funpay_shorts.png",
        platform="shorts",
        sponsor_brand="funpay",
        hook_title="Этот парень обманул всё казино за 3 минуты!",
        movie_code="392",
        watermark="movie_pulse",
    )
    # Test PlayerOk for TikTok & Reels
    generator.save_banner_overlay(
        output_path="test_playerok_tiktok.png",
        platform="tiktok",
        sponsor_brand="playerok",
        hook_title="Этот парень обманул всё казино за 3 минуты!",
        movie_code="392",
        watermark="movie_pulse",
    )
    print("Generated test sponsor banners: FunPay (Shorts) and PlayerOk (TikTok)")
